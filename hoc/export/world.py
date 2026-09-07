"""The live world as one JSON file, so the browser can pick the game up.

Phase 10-2. `outputs/site/play.html` runs the JavaScript engine
(`web/engine/`) against the committed game, and to do that it needs the world
the Python engine left behind — not a summary of it, but every value the engine
reads. This module writes that state, and reads it back.

**What is here is what the engine reads, and nothing else.** Three things the
database holds are deliberately left out, because `web/engine/sim.js` never
looks at them and carrying them would multiply the file's size at exactly the
point (a phone, on mobile data) where size matters most:

* **Released holdings.** Every query in both engines filters on
  `released_event_id IS NULL`; a released holding is history, and the site's
  timeline already carries history.
* **Dead people.** `holder()` and `heirs()` both filter on `alive = 1`.
* **Per-season history** — `stat_snapshots` and `house_actions`. That is what
  `outputs/site/data/timeline.json` is for.

Events are kept, but projected down to the four fields the engine reads:
`firedEvents` needs a societal event's title and houses, `seasonsSinceLoss` and
`relationSeason` need its season, and `debtCheck` needs to spot "debt" in a
transfer's title. Narrative prose and the full mechanical delta are dropped.

The id counters are carried across even though the rows they counted are not,
because a resumed world must keep issuing ids where the Python engine stopped —
`ORDER BY id DESC` is how "the most recently acquired riding" is found, and two
engines that number their rows differently would pick different ridings.

`tests/test_world_snapshot.py` is what holds this honest: it snapshots a world
at season 60 and proves that thirty more seasons played from the snapshot — in
either engine — are byte-identical to thirty more played from the database.
"""

import hashlib
import json
from pathlib import Path

from hoc import scenario
from hoc.sim import RULES_VERSION

__all__ = [
    "SNAPSHOT_VERSION",
    "WORLD_FILENAME",
    "world_snapshot",
    "write_world",
    "load_snapshot",
]

SNAPSHOT_VERSION = 1
WORLD_FILENAME = "world.json"


def _rows(conn, sql, params=()):
    return [dict(row) for row in conn.execute(sql, params)]


def _last_season_sha(conn, season):
    """The SHA-256 of the last committed season file.

    The browser uses it to tell whether the world it has in IndexedDB was
    resumed from the same commit it is now looking at: a snapshot whose sha no
    longer matches the site's is stale, and offering to resume it would silently
    fork the game.
    """
    if season is None:
        return None
    row = conn.execute(
        "SELECT json_path FROM seasons WHERE season_no = ?", (season,)
    ).fetchone()
    if row is None or not row["json_path"]:
        return None
    path = scenario.REPO_ROOT / row["json_path"]
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def world_snapshot(conn):
    """The world as a plain dict, in the shape `web/engine/state.js` loads."""
    season_row = conn.execute("SELECT MAX(season_no) AS n FROM seasons").fetchone()
    season = None if season_row is None else season_row["n"]
    seed_row = conn.execute(
        "SELECT seed FROM seasons ORDER BY season_no DESC LIMIT 1"
    ).fetchone()

    houses = [
        {
            "house": row["house"],
            "peerage": row["peerage"],
            "rank": row["rank"],
            "status": row["status"],
            "primaryHex": row["primary_hex"],
            "secondaryHex": row["secondary_hex"],
            "notes": row["notes"],
        }
        for row in conn.execute("SELECT * FROM houses ORDER BY house")
    ]

    stats = [
        {
            "house": row["house"],
            "capital": row["capital"],
            "influence": row["influence"],
            "cohesion": row["cohesion"],
            "ambition": row["ambition"],
            "enclosed": row["enclosed"],
            "enclosedSince": row["enclosed_since"],
            "community": row["community"],
            "region": row["region"],
            "tradition": row["tradition"],
            "tag": row["tag"],
            "province": row["province"],
            "seatPlace": row["seat_place"],
            "foundedSeason": row["founded_season"],
            "removedSeason": row["removed_season"],
            "forcedAction": row["forced_action"],
        }
        for row in conn.execute("SELECT * FROM house_stats ORDER BY house")
    ]

    holdings = [
        {
            "id": row["id"],
            "house": row["house"],
            "fedId": row["fed_id"],
            "seatOrder": row["seat_order"],
            "hex": row["hex"],
            "acquiredEventId": row["acquired_event_id"],
        }
        for row in conn.execute(
            "SELECT * FROM holdings WHERE released_event_id IS NULL ORDER BY id"
        )
    ]

    persons = [
        {
            "id": row["id"],
            "house": row["house"],
            "name": row["name"],
            "gender": row["gender"],
            "age": row["age"],
            "role": row["role"],
            "married": row["married"],
            "bornSeason": row["born_season"],
        }
        for row in conn.execute("SELECT * FROM persons WHERE alive = 1 ORDER BY id")
    ]

    clocks = [
        {"house": row["house"], "personalYear": row["personal_year"], "basis": row["basis"]}
        for row in conn.execute("SELECT * FROM clocks ORDER BY house")
    ]

    objectives = [
        {
            "id": row["id"],
            "house": row["house"],
            "objective": row["objective"],
            "acquiredSeason": row["acquired_season"],
            "satisfiedSeason": row["satisfied_season"],
        }
        for row in conn.execute("SELECT * FROM objectives ORDER BY id")
    ]

    relations = [
        {
            "id": row["id"],
            "houseA": row["house_a"],
            "houseB": row["house_b"],
            "marker": row["marker"],
            "eventId": row["event_id"],
            "eventText": row["event_text"],
            "source": row["source"],
        }
        for row in conn.execute("SELECT * FROM relations ORDER BY id")
    ]

    # Events, projected to what the engine reads, and pruned to the events it
    # reads at all. `sim.js` asks four questions of this table and no others:
    #
    #   firedEvents        which societal events a house has already met
    #   seasonsSinceLoss   the season of a house's latest transfer
    #   debtCheck          whether a house has a transfer whose title says debt
    #   relationSeason     the season of the event a current relation hangs off
    #
    # So a societal event, a transfer, or an event some standing relation points
    # at, is kept; everything else — foundings, successions, expansions,
    # elevations, challenges, and the relational events whose relation has since
    # been overwritten — is history the browser never consults, and at three
    # hundred seasons that is three fifths of the table. `season` comes out of
    # the mechanical delta, where sim.py stamps it because the table has no
    # season column of its own.
    # A current holding's acquiring event is kept too, and not for reading:
    # §7's contested expansion releases a holding *to its own acquiring event*
    # (`released_event_id = acquired_event_id`), so that number has to still
    # mean something. Drop the event and Python's foreign key refuses the
    # holding; null the reference instead and a contested release would write
    # NULL, which reads as "not released" — the holding would come back to life.
    events = []
    for row in conn.execute(
        "SELECT e.id, e.kind, e.title, e.mechanical_delta FROM events e"
        " WHERE e.kind IN ('societal', 'transfer')"
        "    OR e.id IN (SELECT event_id FROM relations WHERE event_id IS NOT NULL)"
        "    OR e.id IN (SELECT acquired_event_id FROM holdings"
        "                WHERE released_event_id IS NULL AND acquired_event_id IS NOT NULL)"
        " ORDER BY e.id"
    ):
        try:
            delta = json.loads(row["mechanical_delta"] or "{}")
        except ValueError:
            delta = {}
        events.append({
            "id": row["id"],
            "kind": row["kind"],
            "title": row["title"],
            "season": delta.get("season"),
            "houses": [
                r["house"]
                for r in conn.execute(
                    "SELECT house FROM event_houses WHERE event_id = ? ORDER BY house",
                    (row["id"],),
                )
            ],
        })

    climate = [
        {
            "id": row["id"],
            "eraCohort": row["era_cohort"],
            "seq": row["seq"],
            "event": row["event"],
            "magnitude": row["magnitude"],
            "tag": row["tag"],
            "cumulativeAfter": row["cumulative_after"],
            "source": row["source"],
        }
        for row in conn.execute("SELECT * FROM climate ORDER BY era_cohort, seq")
    ]

    friction = [
        {"houseA": row["house_a"], "houseB": row["house_b"], "value": row["value"]}
        for row in conn.execute("SELECT * FROM friction ORDER BY house_a, house_b")
    ]

    seasons = [
        {
            "seasonNo": row["season_no"],
            "seed": row["seed"],
            "housesAfter": row["houses_after"],
            "ridingsAfter": row["ridings_after"],
            "rulesVersion": row["rules_version"],
        }
        for row in conn.execute("SELECT * FROM seasons ORDER BY season_no")
    ]

    # Where each table's ids stand. MAX over the whole table, released and dead
    # rows included, because that is where SQLite's own counter stands.
    def next_id(table):
        row = conn.execute(f"SELECT COALESCE(MAX(id), 0) + 1 AS n FROM {table}").fetchone()
        return row["n"]

    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "rules_version": RULES_VERSION,
        "scenario": scenario.current_name(),
        "world_seed": None if seed_row is None else seed_row["seed"],
        "season": season,
        "last_season_sha256": _last_season_sha(conn, season),
        "nextId": {
            "holdings": next_id("holdings"),
            "persons": next_id("persons"),
            "objectives": next_id("objectives"),
            "relations": next_id("relations"),
            "events": next_id("events"),
            "climate": next_id("climate"),
            "houseActions": next_id("house_actions"),
        },
        "houses": houses,
        "houseStats": stats,
        "holdings": holdings,
        "persons": persons,
        "clocks": clocks,
        "objectives": objectives,
        "relations": relations,
        "events": events,
        "climate": climate,
        "friction": friction,
        "seasons": seasons,
    }


def write_world(conn, out_dir):
    """Write `world.json`. Returns (path, byte count)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / WORLD_FILENAME
    # Compact separators: this file is fetched on a phone, and the whitespace of
    # an indented dump is a third of its size. Sorted keys so two exports of the
    # same world are byte-identical (hoc/export/workbook.py has the same rule
    # and the same reason).
    text = json.dumps(
        world_snapshot(conn), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    path.write_text(text + "\n", encoding="utf-8")
    return path, len(text.encode("utf-8")) + 1


def load_snapshot(conn, snapshot):
    """Write a snapshot into an empty database (reference data already loaded).

    The mirror of `world_snapshot`, and the reason it exists is the test: a
    world that round-trips through JSON and then plays on identically is a world
    whose snapshot is complete. Anything the snapshot silently dropped would
    show up as a diverging season within a handful of turns.

    Events are re-created carrying only the season in their delta, which is all
    the engine reads back out of one.
    """
    if snapshot.get("snapshot_version") != SNAPSHOT_VERSION:
        raise ValueError(
            f"snapshot version {snapshot.get('snapshot_version')!r} is not"
            f" {SNAPSHOT_VERSION}: this loader cannot read it"
        )

    for row in snapshot["houses"]:
        conn.execute(
            "INSERT INTO houses (house, peerage, rank, status, primary_hex, secondary_hex, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (row["house"], row["peerage"], row["rank"], row["status"],
             row["primaryHex"], row["secondaryHex"], row["notes"]),
        )
    for row in snapshot["houseStats"]:
        conn.execute(
            "INSERT INTO house_stats (house, capital, influence, cohesion, ambition, enclosed,"
            " enclosed_since, community, region, tradition, tag, province, seat_place,"
            " founded_season, removed_season, forced_action)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row["house"], row["capital"], row["influence"], row["cohesion"], row["ambition"],
             row["enclosed"], row["enclosedSince"], row["community"], row["region"],
             row["tradition"], row["tag"], row["province"], row["seatPlace"],
             row["foundedSeason"], row["removedSeason"], row["forcedAction"]),
        )

    # Events first: holdings and relations reference them.
    for row in snapshot["events"]:
        conn.execute(
            "INSERT INTO events (id, kind, title, mechanical_delta, source, created_at)"
            " VALUES (?, ?, ?, ?, 'engine', '1970-01-01T00:00:00+00:00')",
            (row["id"], row["kind"], row["title"],
             json.dumps({"season": row["season"]}) if row["season"] is not None else None),
        )
        for house in row["houses"]:
            conn.execute(
                "INSERT INTO event_houses (event_id, house, role) VALUES (?, ?, 'participant')",
                (row["id"], house),
            )

    for row in snapshot["holdings"]:
        conn.execute(
            "INSERT INTO holdings (id, house, fed_id, seat_order, hex, acquired_event_id)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (row["id"], row["house"], row["fedId"], row["seatOrder"], row["hex"],
             row["acquiredEventId"]),
        )
    for row in snapshot["persons"]:
        conn.execute(
            "INSERT INTO persons (id, house, name, gender, age, role, alive, married, born_season)"
            " VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (row["id"], row["house"], row["name"], row["gender"], row["age"], row["role"],
             row["married"], row["bornSeason"]),
        )
    for row in snapshot["clocks"]:
        conn.execute(
            "INSERT INTO clocks (house, personal_year, basis) VALUES (?, ?, ?)",
            (row["house"], row["personalYear"], row["basis"]),
        )
    for row in snapshot["objectives"]:
        conn.execute(
            "INSERT INTO objectives (id, house, objective, acquired_season, satisfied_season)"
            " VALUES (?, ?, ?, ?, ?)",
            (row["id"], row["house"], row["objective"], row["acquiredSeason"],
             row["satisfiedSeason"]),
        )
    for row in snapshot["relations"]:
        conn.execute(
            "INSERT INTO relations (id, house_a, house_b, marker, event_id, event_text, source)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (row["id"], row["houseA"], row["houseB"], row["marker"], row["eventId"],
             row["eventText"], row["source"]),
        )
    for row in snapshot["climate"]:
        conn.execute(
            "INSERT INTO climate (id, era_cohort, seq, event, magnitude, tag,"
            " cumulative_after, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (row["id"], row["eraCohort"], row["seq"], row["event"], row["magnitude"],
             row["tag"], row["cumulativeAfter"], row["source"]),
        )
    for row in snapshot["friction"]:
        conn.execute(
            "INSERT INTO friction (house_a, house_b, value) VALUES (?, ?, ?)",
            (row["houseA"], row["houseB"], row["value"]),
        )
    for row in snapshot["seasons"]:
        conn.execute(
            "INSERT INTO seasons (season_no, seed, houses_after, ridings_after,"
            " rules_version, created_at) VALUES (?, ?, ?, ?, ?, '1970-01-01T00:00:00+00:00')",
            (row["seasonNo"], row["seed"], row["housesAfter"], row["ridingsAfter"],
             row["rulesVersion"]),
        )

    # Park each table's id counter where the snapshot says it stands, so a
    # resumed world numbers its next row exactly as the original would have.
    # SQLite takes the next rowid from MAX(id) + 1, so one sentinel row at the
    # right id — inserted, then deleted — moves the counter and leaves nothing
    # behind. Each sentinel uses real foreign keys and dodges the partial unique
    # indexes (a released holding, a dead non-holder), because the database
    # enforces both and a loader that had to switch them off would be a loader
    # nobody could trust.
    _park_counters(conn, snapshot)
    return conn


def _park_counters(conn, snapshot):
    any_house = snapshot["houses"][0]["house"] if snapshot["houses"] else None
    any_event = snapshot["events"][-1]["id"] if snapshot["events"] else None
    any_riding = conn.execute("SELECT fed_id FROM ridings LIMIT 1").fetchone()["fed_id"]

    def park(table, at_id, insert, params):
        highest = conn.execute(
            f"SELECT COALESCE(MAX(id), 0) AS n FROM {table}"
        ).fetchone()["n"]
        if at_id <= highest:
            return
        conn.execute(insert, params)
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (at_id,))

    nxt = snapshot["nextId"]

    park(
        "events", nxt["events"] - 1,
        "INSERT INTO events (id, kind, title, source, created_at)"
        " VALUES (?, 'other', 'id placeholder', 'engine', '1970-01-01T00:00:00+00:00')",
        (nxt["events"] - 1,),
    )
    if any_house is not None:
        park(
            "persons", nxt["persons"] - 1,
            "INSERT INTO persons (id, house, name, gender, age, role, alive)"
            " VALUES (?, ?, 'id placeholder', 'm', 0, 'other', 0)",
            (nxt["persons"] - 1, any_house),
        )
        park(
            "objectives", nxt["objectives"] - 1,
            "INSERT INTO objectives (id, house, objective, acquired_season)"
            " VALUES (?, ?, 'id placeholder', 0)",
            (nxt["objectives"] - 1, any_house),
        )
        # A released holding: released_event_id is what both partial unique
        # indexes key off, so a released row collides with nothing.
        park(
            "holdings", nxt["holdings"] - 1,
            "INSERT INTO holdings (id, house, fed_id, seat_order, hex, released_event_id)"
            " VALUES (?, ?, ?, 9999, '#000000', ?)",
            (nxt["holdings"] - 1, any_house, any_riding, any_event),
        )
    if len(snapshot["houses"]) >= 2:
        park(
            "relations", nxt["relations"] - 1,
            "INSERT INTO relations (id, house_a, house_b, marker, source)"
            " VALUES (?, ?, ?, '~', 'engine')",
            (nxt["relations"] - 1, snapshot["houses"][0]["house"],
             snapshot["houses"][1]["house"]),
        )
    park(
        "climate", nxt["climate"] - 1,
        "INSERT INTO climate (id, era_cohort, seq, event, cumulative_after, source)"
        " VALUES (?, '__placeholder__', 999999, 'id placeholder', '0', 'engine')",
        (nxt["climate"] - 1,),
    )
