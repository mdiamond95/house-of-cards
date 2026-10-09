"""Typed beats for the story layer (docs/STORY_DESIGN.md §3.1), from hoc.db.

    data/beats/index.json      the game, its baseline board, its houses, its chunks
    data/beats/chunk-NNN.json  {"turns": {"<turn>": [beat, ...]}}, each under CHUNK_BUDGET

The story layer itself is JavaScript (web/story/): it weighs beats, picks each
turn's headline and keeps the standings, in the browser. What it is handed is
built here, from the structured record and never from prose:

* an event's `kind`, its houses in the order `event_houses` recorded them (the
  acting house first), and its `mechanical_delta`;
* the holdings the event moved (`holdings.acquired_event_id` and
  `released_event_id`), which say exactly which ridings changed hands;
* the acting house's own row in `house_actions` that season — the only thing
  that tells a letter between kin from a marriage, or a letter between
  compacted houses from a compact, since all of them write a bare marker;
* the founding rank of each house founded that turn.

`turn_input` assembles that per turn and `type_turn` types it, by the same rules
as web/story/beats.js `typeTurn`; tests/test_story.py runs the JavaScript over
the same inputs and requires the two to agree beat for beat. Change one, change
both.

A turn is a season for an engine-played game (the season in each event's
delta) and a director's turn for the reconstructed one (`events.turn_id`).
Events that belong to no turn — the reconstructed game's history before its
first turn, and a director's intervention wrapper, whose effects carry their
own season — are not beats; what they did to the board is the baseline.
"""

import json
from collections import defaultdict
from pathlib import Path

from hoc import places, rules as mechanics

__all__ = [
    "build_story", "write_beats", "turn_inputs", "type_turn", "BEAT_KINDS", "CHUNK_BUDGET",
    "seat_history", "jurisdiction_spans", "write_atlas",
]

CHUNK_BUDGET = 500_000  # bytes per fetch (Phase A, task 3)

GRIEVANCE = "Sig−"

BEAT_KINDS = (
    "removed", "riding_passes", "partition", "elevation", "succession_disorderly",
    "quarrel", "marriage", "dispute_won", "reconciled", "founding", "succession_clean",
    "major_response", "compact", "expansion", "failed", "correspondence",
    "invest", "cultivate", "consolidate", "name_heir",
    "riding_lost", "endowment", "era_response", "other",
    "heir_wanted", "heir_of_age", "bide",
    "scheme_begun", "scheme_step", "scheme_answered", "scheme_abandoned", "scheme_resolved",
    "ally_joins", "ally_declines", "contest_won", "contest_lost", "fallen",
    "crisis", "accession", "event_continues", "reckoning",
)

# Rules 1.0 `world_calendar`: the world's own events, by their delta's `world`.
WORLD_KINDS = {
    "accession": "accession", "extension": "accession",
    "continues": "event_continues", "reckoning": "reckoning",
}

SCHEME_PHASES = {
    "begun": "scheme_begun",
    "step": "scheme_step",
    "answered": "scheme_answered",
    "abandoned": "scheme_abandoned",
    "resolved": "scheme_resolved",
}

SILENT_FAILURES = (
    "Cede / swap", "Expand", "Marriage alliance", "Petition elevation",
    "Propose compact", "Purchase riding", "Reconcile",
)

BOOKKEEPING_ACTIONS = {
    "Invest": "invest",
    "Cultivate influence": "cultivate",
    "Consolidate (rest)": "consolidate",
    "Bide": "bide",
}


def rank_index(rank):
    return mechanics.RANK_LEVEL.get(rank, 0)


# ------------------------------------------------------------------ typing --


def type_event(event, action_of):
    """(kind, outcome) for one event: web/story/beats.js typeEvent."""
    d = event["delta"] or {}
    houses = event["houses"]
    kind = event["kind"]
    if kind == "founding":
        return ("partition", None) if d.get("nature") == "partition" else ("founding", None)
    if kind == "succession":
        nature = d.get("nature")
        if nature == "extinction" and "taken_by" in d:
            return "fallen", d["taken_by"]
        if nature == "extinction":
            return "removed", d.get("reason")
        if nature == "disorderly":
            return "succession_disorderly", d.get("cause")
        if nature == "clean":
            return "succession_clean", d.get("cause")
        return "other", None
    if kind == "transfer":
        if d.get("nature") == "absorption":
            return "riding_passes", "absorption"
        if len(houses) >= 2:
            if "under_claim" in d:
                return "riding_passes", "cession under claim"
            return "riding_passes", "purchase" if "price" in d else d.get("reason")
        return "riding_lost", d.get("reason")
    if kind == "challenge":
        if "contest" in d:
            if d["contest"] == "held":
                return "contest_lost", "held"
            return "contest_won", d["contest"]
        if d.get("outcome") == "won":
            return "riding_passes", "challenge"
        return "failed", "Challenge (11b)"
    if kind == "elevation":
        return "elevation", d.get("to")
    if kind == "expansion":
        return "expansion", None
    if kind == "societal":
        # Rules 1.0 `crises`: one event for the whole crisis, both camps in it.
        if isinstance(d.get("crisis"), dict):
            return "crisis", d["crisis"].get("carried")
        if d.get("magnitude") == "Major":
            return "major_response", d.get("response")
        return "era_response", d.get("response")
    if kind == "relational":
        if d.get("outcome") == "won":
            return "dispute_won", d.get("marker")
        if d.get("outcome") == "lost":
            return "failed", "Dispute"
        if "cause" in d and d.get("marker") == GRIEVANCE:
            return "quarrel", d["cause"]
        if "ceded" in d:
            return "reconciled", "cession"
        if "peace" in d:
            return "reconciled", "peace"
        if d.get("letter"):
            return "correspondence", d.get("marker")
        action = action_of(houses[0]) if houses else None
        return {
            "Correspond": ("correspondence", d.get("marker")),
            "Propose compact": ("compact", None),
            "Reconcile": ("reconciled", None),
            "Marriage alliance": ("marriage", None),
            "Absorb": ("failed", "Absorb"),
        }.get(action, ("other", None))
    if kind == "other":
        if d.get("world") in WORLD_KINDS:
            return WORLD_KINDS[d["world"]], d.get("event", d["world"])
        scheme = d.get("scheme")
        if isinstance(scheme, dict) and scheme.get("phase") in SCHEME_PHASES:
            return SCHEME_PHASES[scheme["phase"]], scheme.get("name")
        ally = d.get("ally")
        if isinstance(ally, dict):
            return ("ally_joins" if ally.get("joins") else "ally_declines"), ally.get("side")
        if d.get("watch") == "no_heir":
            return "heir_wanted", None
        if d.get("watch") == "heir_of_age":
            return "heir_of_age", None
        action = action_of(houses[0]) if houses else None
        if action == "Name heir":
            return "name_heir", d.get("role")
        if action == "Endow":
            return "endowment", None
        return "other", None
    return "other", None


def _beat(turn, seq, kind, houses, ridings, outcome, line, owners, ranks, removed,
          scheme=None, ran=None, world=None, part=None):
    """The canonical shape: empty fields left out (web/story/beats.js makeBeat)."""
    beat = {"turn": turn, "seq": seq, "kind": kind, "houses": houses}
    if ridings:
        beat["ridings"] = ridings
    if outcome is not None:
        beat["outcome"] = outcome
    if line is not None:
        beat["line"] = line
    if owners:
        beat["owners"] = owners
    if ranks:
        beat["ranks"] = ranks
    if removed:
        beat["removed"] = removed
    if scheme is not None:
        beat["scheme"] = scheme
    if ran is not None:
        beat["ran"] = ran
    if world is not None:
        beat["world"] = world
    if part is not None:
        beat["part"] = part
    return beat


def _world_facts(kind, d, title=None):
    """Rules 1.0 `world_calendar` and `crises`: what a world beat carries for
    its sentence and the pages (web/story/beats.js worldFacts). A house's
    response to an ordinary event carries the event's name (Phase V3), which
    the engine records as the event's title."""
    if kind in ("era_response", "major_response"):
        return {"event": title} if title else None
    if kind == "crisis":
        c = d["crisis"]
        facts = {"event": d.get("event"), "lead": c["lead"], "resist": c["resist"],
                 "carried": c["carried"]}
        if "years" in d:
            facts["years"] = d["years"]
        return facts
    if kind == "event_continues":
        return {"event": d["event"], "year_of": d["year_of"], "years": d["years"]}
    if kind == "accession":
        return {"jurisdiction": d["jurisdiction"], "status": d["status"], "change": d["world"]}
    return None


def type_turn(data):
    """One turn's beats: web/story/beats.js typeTurn."""
    actions = {row["house"]: row["action"] for row in data["actions"]}

    def action_of(house):
        return actions.get(house)

    moves = defaultdict(list)
    for row in data["holdings"]:
        moves[row["event"]].append(row)

    beats = []
    offended = set()
    for event in data["events"]:
        kind, outcome = type_event(event, action_of)
        houses = list(event["houses"])
        d = event["delta"] or {}
        if kind == "quarrel" and d.get("cause") == "correspondence" and houses:
            offended.add(houses[0])

        owners = {}
        rows = moves.get(event["id"], [])
        for row in rows:
            if row["change"] == "released":
                owners[row["fed"]] = None
        for row in rows:
            if row["change"] == "acquired":
                owners[row["fed"]] = row["house"]
        ridings = sorted(owners)

        ranks = {}
        if kind in ("founding", "partition"):
            index = 0 if kind == "founding" else 1
            if len(houses) > index and houses[index] in data["ranks"]:
                ranks[houses[index]] = rank_index(data["ranks"][houses[index]])
        if kind == "elevation" and houses and "to" in d:
            ranks[houses[0]] = rank_index(d["to"])

        removed = []
        if kind in ("removed", "fallen") and houses:
            removed.append(houses[0])

        scheme = ran = None
        if isinstance(d.get("scheme"), dict):
            scheme = d["scheme"].get("id")
            if kind == "scheme_resolved":
                ran = d["scheme"].get("ran")
        elif isinstance(d.get("scheme"), int) and not isinstance(d.get("scheme"), bool):
            scheme = d["scheme"]
        elif isinstance(d.get("ally"), dict):
            # Phase D1: an ally answers the call of one contest, told with it.
            scheme = d["ally"].get("scheme")
        if kind == "riding_passes" and outcome == "absorption" and len(houses) > 1:
            removed.append(houses[1])
        world = _world_facts(kind, d, event.get("title"))
        if kind == "accession":
            # The land it opens, for the map to show.
            ridings = sorted(d.get("fed_ids") or [])

        beats.append(_beat(data["turn"], len(beats), kind, houses, ridings, outcome,
                           event["line"], owners, ranks, removed, scheme, ran, world,
                           d.get("part")))

    # Rules 1.0 `round_record`: an action is written in its house's own turn,
    # so where the turn's playing order is known an action beat is that
    # house's part of the round.
    round_known = data.get("order") is not None
    for row in data["actions"]:
        kind = None
        outcome = "success" if row["success"] else "failed"
        if row["action"] in BOOKKEEPING_ACTIONS:
            kind = BOOKKEEPING_ACTIONS[row["action"]]
        elif not row["success"] and row["action"] in SILENT_FAILURES:
            kind, outcome = "failed", row["action"]
        elif not row["success"] and row["action"] == "Correspond" and row["house"] not in offended:
            kind = "correspondence"
        if kind is None:
            continue
        beats.append(_beat(data["turn"], len(beats), kind, [row["house"]], [], outcome,
                           None, {}, {}, [], part=row["house"] if round_known else None))
    return beats


# ------------------------------------------------------------------- input --


def _is_engine_game(conn):
    return conn.execute("SELECT COUNT(*) AS n FROM seasons").fetchone()["n"] > 0


def _founding_ranks(conn):
    """Each house's rank when it was founded: its first elevation's `from`, or
    its rank now if it was never elevated."""
    first_from = {}
    for row in conn.execute(
        "SELECT e.id, e.mechanical_delta, eh.house FROM events e"
        " JOIN event_houses eh ON eh.event_id = e.id"
        " WHERE e.kind = 'elevation' ORDER BY e.id, eh.rowid"
    ):
        delta = json.loads(row["mechanical_delta"] or "{}")
        if row["house"] not in first_from and "from" in delta:
            first_from[row["house"]] = delta["from"]
    ranks = {}
    for row in conn.execute("SELECT house, rank FROM houses ORDER BY house"):
        ranks[row["house"]] = first_from.get(row["house"], row["rank"])
    return ranks


def turn_inputs(conn, orders=None):
    """Every turn's input, as (turns, baseline): turns is [(turn, input)] for
    turns 1..last, baseline the board before turn 1 (web/story/standings.js).

    `orders` ({turn: [house, ...]}) is each season record's `order` (rules 1.0
    `round_record`), which the database does not keep; a turn given one
    carries it as its input's `order`."""
    engine = _is_engine_game(conn)
    houses_of = defaultdict(list)
    for row in conn.execute("SELECT event_id, house FROM event_houses ORDER BY event_id, rowid"):
        houses_of[row["event_id"]].append(row["house"])

    turn_of = {}
    by_turn = defaultdict(list)
    for row in conn.execute(
        "SELECT id, turn_id, kind, title, narrative, mechanical_delta FROM events ORDER BY id"
    ):
        delta = json.loads(row["mechanical_delta"]) if row["mechanical_delta"] else None
        if engine:
            turn = delta.get("season") if isinstance(delta, dict) else None
        else:
            turn = row["turn_id"]
        if not isinstance(turn, int):
            continue
        turn_of[row["id"]] = turn
        by_turn[turn].append({
            "id": row["id"],
            "kind": row["kind"],
            "houses": houses_of.get(row["id"], []),
            "delta": delta,
            "line": row["narrative"] if row["narrative"] is not None else row["title"],
            "title": row["title"],
        })

    actions = defaultdict(list)
    for row in conn.execute(
        "SELECT season_no, house, action, success FROM house_actions ORDER BY id"
    ):
        actions[row["season_no"]].append(
            {"house": row["house"], "action": row["action"], "success": 1 if row["success"] else 0}
        )

    holdings = defaultdict(list)
    baseline_owners = {}
    for row in conn.execute(
        "SELECT id, house, fed_id, acquired_event_id, released_event_id FROM holdings ORDER BY id"
    ):
        acquired = turn_of.get(row["acquired_event_id"])
        released = turn_of.get(row["released_event_id"]) if row["released_event_id"] else None
        if acquired is not None:
            holdings[acquired].append({"event": row["acquired_event_id"], "fed": row["fed_id"],
                                       "house": row["house"], "change": "acquired"})
        if released is not None:
            holdings[released].append({"event": row["released_event_id"], "fed": row["fed_id"],
                                       "house": row["house"], "change": "released"})
        # Held before the first turn: acquired outside any turn, and still held
        # then — released by nothing, or by something a turn did.
        if acquired is None and (row["released_event_id"] is None or released is not None):
            baseline_owners[row["fed_id"]] = row["house"]

    founding = _founding_ranks(conn)
    founded_in = {}
    for turn, events in by_turn.items():
        for event in events:
            if event["kind"] != "founding":
                continue
            delta = event["delta"] or {}
            index = 1 if delta.get("nature") == "partition" else 0
            if len(event["houses"]) > index:
                founded_in[event["houses"][index]] = turn

    baseline_ranks = {}
    baseline_removed = []
    removed_in_turn = set()
    for events in by_turn.values():
        for event in events:
            delta = event["delta"] or {}
            if event["kind"] == "succession" and delta.get("nature") == "extinction":
                removed_in_turn.update(event["houses"][:1])
            if event["kind"] == "transfer" and delta.get("nature") == "absorption":
                removed_in_turn.update(event["houses"][1:2])
    for row in conn.execute("SELECT house, status FROM houses ORDER BY house"):
        if row["house"] in founded_in:
            continue
        baseline_ranks[row["house"]] = rank_index(founding.get(row["house"]))
        if row["status"] != "active" and row["house"] not in removed_in_turn:
            baseline_removed.append(row["house"])

    if engine:
        last = conn.execute("SELECT MAX(season_no) AS n FROM seasons").fetchone()["n"] or 0
    else:
        last = conn.execute("SELECT MAX(turn_id) AS n FROM turns").fetchone()["n"] or 0

    turns = []
    for turn in range(1, last + 1):
        events = by_turn.get(turn, [])
        ranks = {}
        for event in events:
            if event["kind"] != "founding":
                continue
            index = 1 if (event["delta"] or {}).get("nature") == "partition" else 0
            if len(event["houses"]) > index:
                house = event["houses"][index]
                if founding.get(house):
                    ranks[house] = founding[house]
        moved = sorted(holdings.get(turn, []), key=lambda row: row["event"])
        data = {
            "turn": turn,
            "events": events,
            "actions": actions.get(turn, []) if engine else [],
            "holdings": moved,
            "ranks": ranks,
        }
        if orders is not None and turn in orders:
            data["order"] = list(orders[turn])
        turns.append((turn, data))
    baseline = {"owners": baseline_owners, "ranks": baseline_ranks,
                "removed": sorted(baseline_removed)}
    return turns, baseline


# ------------------------------------------------------------------ output --


def build_story(conn, orders=None):
    """(index, {turn: beats}) for the whole game."""
    turns, baseline = turn_inputs(conn, orders)
    beats = {turn: type_turn(data) for turn, data in turns}
    # What the story layer names a house by (web/story/text.js houseStyle): its
    # peerage as last written, the rank word in it, and its seat's place where
    # the engine recorded one. The story layer derives styles and designations
    # from these; nothing here parses them.
    houses = {}
    for row in conn.execute(
        "SELECT h.house, h.peerage, h.rank, c.primary_hex, s.seat_place FROM houses h"
        " JOIN v_house_colours c ON c.house = h.house"
        " LEFT JOIN house_stats s ON s.house = h.house ORDER BY h.house"
    ):
        houses[row["house"]] = {
            "peerage": row["peerage"], "rank": row["rank"], "place": row["seat_place"],
            "colour": row["primary_hex"],
        }
    ridings = {row["fed_id"]: row["name_en"]
               for row in conn.execute("SELECT fed_id, name_en FROM ridings ORDER BY fed_id")}
    index = {
        "unit": "season" if _is_engine_game(conn) else "turn",
        "turns": len(turns),
        "baseline": baseline,
        "houses": houses,
        "ridings": ridings,
        # Whether the record carries rules 1.0's succession watch: the story
        # layer then opens and closes succession questions on its events.
        "succession_watch": _record_has(conn, "succession_watch"),
        # Whether it carries rules 1.0's schemes: the pages then show Plans afoot.
        "schemes": _record_has(conn, "schemes"),
    }
    # Rules 1.0 `world_calendar`: the calendar a turn is a year of, and the
    # reckoning the engine wrote after the last turn, for a record with them.
    calendar = calendar_of(conn)
    if calendar is not None:
        index["calendar"] = calendar
    reckoning = reckoning_of(conn)
    if reckoning is not None:
        index["reckoning"] = reckoning
    return index, beats


def calendar_of(conn):
    """game.json's calendar for a game played with `world_calendar`: its start
    year, its turns and its chapters. None for any other game."""
    from hoc import rules_data

    for (version,) in conn.execute(
        "SELECT DISTINCT rules_version FROM seasons WHERE rules_version IS NOT NULL"
        " ORDER BY rules_version"
    ):
        try:
            if not rules_data.load_features(version).get("world_calendar"):
                continue
            game = rules_data.load_rules(version=version).game
        except rules_data.RulesDataError:
            continue
        return {
            "start_year": game["start_year"],
            "turns": game["turns"],
            "chapters": [
                {key: chapter[key] for key in ("id", "name", "numeral", "start_year", "end_year")}
                for chapter in game["chapters"]
            ],
        }
    return None


def reckoning_of(conn):
    """The reckoning record the engine wrote after a calendar game's last turn,
    or None."""
    for (delta,) in conn.execute(
        "SELECT mechanical_delta FROM events WHERE kind = 'other'"
        " AND mechanical_delta LIKE '%\"reckoning\"%' ORDER BY id DESC"
    ):
        facts = json.loads(delta).get("reckoning")
        if isinstance(facts, dict):
            return facts
    return None


def _record_has(conn, flag):
    """Whether any season of the game was played under a version with `flag` on."""
    from hoc import rules_data

    versions = [row["rules_version"] for row in conn.execute(
        "SELECT DISTINCT rules_version FROM seasons WHERE rules_version IS NOT NULL"
        " ORDER BY rules_version")]
    for version in versions:
        try:
            if rules_data.load_features(version).get(flag):
                return True
        except rules_data.RulesDataError:
            continue
    return False


def prestige_by_turn(conn):
    """Rules 1.0 `prestige`: each house's prestige at the end of each season, for
    a game whose record carries it ({turn: {house: value}}); empty otherwise."""
    out = defaultdict(dict)
    for row in conn.execute(
        "SELECT season_no, house, value FROM prestige_history ORDER BY season_no, house"
    ):
        out[row["season_no"]][row["house"]] = row["value"]
    return dict(out)


def plans_by_turn(conn):
    """Rules 1.0 `schemes`: every public scheme at the end of each season
    ({turn: [plan, ...]}), in the shape the engine writes as a season record's
    `plans`, rebuilt from the scheme events — each step records its turns
    remaining, so the latest event at or before a season is the scheme as that
    season left it. Empty for a game whose record carries no schemes."""
    if not _record_has(conn, "schemes"):
        return {}
    history = defaultdict(list)
    for row in conn.execute(
        "SELECT e.id, e.mechanical_delta FROM events e"
        " WHERE e.kind = 'other' AND e.mechanical_delta LIKE '%\"scheme\": {%' ORDER BY e.id"
    ):
        delta = json.loads(row["mechanical_delta"])
        payload = delta.get("scheme")
        if not isinstance(payload, dict) or "phase" not in payload:
            continue
        house = conn.execute(
            "SELECT house FROM event_houses WHERE event_id = ? ORDER BY rowid LIMIT 1", (row["id"],)
        ).fetchone()["house"]
        history[payload["id"]].append((delta["season"], payload, house))
    last = conn.execute("SELECT MAX(season_no) AS n FROM seasons").fetchone()["n"] or 0
    # A house leaving play ends its schemes with no event of their own: its
    # removal is theirs.
    removed = {
        row["house"]: row["removed_season"] for row in conn.execute(
            "SELECT house, removed_season FROM house_stats WHERE removed_season IS NOT NULL")
    }
    out = {}
    for turn in range(1, last + 1):
        plans = []
        for scheme_id in sorted(history):
            seen = [entry for entry in history[scheme_id] if entry[0] <= turn]
            if not seen:
                continue
            _, payload, house = seen[-1]
            if payload["phase"] in ("abandoned", "resolved"):
                continue
            if house in removed and removed[house] <= turn:
                continue
            plans.append({
                "id": scheme_id,
                "house": house,
                "scheme": payload["name"],
                "target_house": payload.get("target_house"),
                "riding": payload.get("riding"),
                "turns_remaining": payload["turns_remaining"],
                "begun": seen[0][0],
                "committed": payload["committed"],
            })
        out[turn] = plans
    return out


def orders_from_records(records):
    """{turn: order} from season records that carry rules 1.0's `order`; None
    when none does (a game without `round_record`)."""
    out = {record["season"]: record["order"] for record in records if "order" in record}
    return out or None


def orders_from_dir(seasons_dir):
    """{turn: order} from a directory of season files, as orders_from_records."""
    records = []
    for path in sorted(Path(seasons_dir).glob("[0-9][0-9][0-9][0-9].json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return orders_from_records(records)


def deck_by_turn(conn):
    """Rules 1.0 `round_record` with `world_calendar`: the events of each
    year's deck, by name, for the world's turn to announce ({turn: [{name,
    magnitude, crisis, years}]}), in deck order. Turn 1 is the first founding
    alone, so its year's events are not announced. Empty for any other game."""
    from hoc import rules_data

    out = {}
    for row in conn.execute(
        "SELECT season_no, rules_version FROM seasons WHERE rules_version IS NOT NULL ORDER BY season_no"
    ):
        try:
            rules = rules_data.load_rules(version=row["rules_version"])
        except rules_data.RulesDataError:
            continue
        if not (rules.feature("world_calendar") and rules.feature("round_record")) or row["season_no"] < 2:
            continue
        year = rules.game["start_year"] + row["season_no"] - 1
        out[row["season_no"]] = [
            {
                "name": event.name,
                "magnitude": event.magnitude,
                "crisis": bool(rules.feature("crises") and event.magnitude == "Major"),
                "years": (event.through_year - event.personal_year + 1) if event.through_year else 1,
            }
            for event in rules.events if event.personal_year == year
        ]
    return out


def people_of(conn):
    """Each house's holders and heirs over the game, for the map view's house
    sheet (Phase V2): {house: [[name, gender, role, entered, died, age, from],
    ...]} in id order. `role` is the person's role now; `entered` the season
    the person entered the record; `died` the season they died, or None;
    `age` their age at death, or now; `from` the season they became holder,
    or None for one who never held. A house's first holder holds from its
    founding; each later one from the season the holder before died, since a
    succession is decided in the season of the death (§9). Only holders and
    named heirs are listed."""
    founded = {row["house"]: row["founded_season"] for row in conn.execute(
        "SELECT house, founded_season FROM house_stats")}
    rows = defaultdict(list)
    for row in conn.execute(
        "SELECT id, house, name, gender, role, born_season, died_season, age FROM persons"
        " WHERE role IN ('holder', 'heir', 'heir2') ORDER BY id"
    ):
        rows[row["house"]].append(row)
    out = {}
    for house in sorted(rows):
        holders = sorted(
            (r for r in rows[house] if r["role"] == "holder"),
            key=lambda r: (r["died_season"] is None, r["died_season"] or 0, r["id"]),
        )
        held_from = {}
        previous = None
        for r in holders:
            held_from[r["id"]] = founded.get(house) if previous is None else previous["died_season"]
            previous = r
        out[house] = [
            [r["name"], r["gender"], r["role"], r["born_season"], r["died_season"], r["age"],
             held_from.get(r["id"])]
            for r in rows[house]
        ]
    return out


def seat_history(conn):
    """Each house's principal seat over the game, for the map view (Phase V):
    {house: [[turn, fed_id or None], ...]}, a row each time it changes, turn 0
    the board before the first turn.

    The seat is the first of a house's ridings in canonical row order (hard
    rule 4). The engine appends every holding it grants at the end of the
    house's order and closes the gaps a departure leaves without reordering,
    so for an engine-played game the seat at any turn is the riding held then
    with the lowest holding id. The reconstructed game's order was written by
    hand, so there the seat the record holds now comes first while it is held.
    """
    engine = _is_engine_game(conn)
    turn_of = {}
    for row in conn.execute("SELECT id, turn_id, mechanical_delta FROM events ORDER BY id"):
        if engine:
            delta = json.loads(row["mechanical_delta"]) if row["mechanical_delta"] else None
            turn = delta.get("season") if isinstance(delta, dict) else None
        else:
            turn = row["turn_id"]
        if isinstance(turn, int):
            turn_of[row["id"]] = turn
    rows = defaultdict(list)
    for row in conn.execute(
        "SELECT id, house, fed_id, seat_order, acquired_event_id, released_event_id"
        " FROM holdings ORDER BY id"
    ):
        acquired = turn_of.get(row["acquired_event_id"], 0)
        if row["released_event_id"] is None:
            released = None
        else:
            released = turn_of.get(row["released_event_id"])
            if released is None:
                continue  # released before the first turn: never on the board told
        current = row["released_event_id"] is None and row["seat_order"] == 1
        rows[row["house"]].append((acquired, released, current, row["id"], row["fed_id"]))
    if engine:
        last = conn.execute("SELECT MAX(season_no) AS n FROM seasons").fetchone()["n"] or 0
    else:
        last = conn.execute("SELECT MAX(turn_id) AS n FROM turns").fetchone()["n"] or 0
    out = {}
    for house in sorted(rows):
        changes = []
        seat = None
        for turn in range(0, last + 1):
            held = [r for r in rows[house] if r[0] <= turn and (r[1] is None or r[1] > turn)]
            if held:
                key = (lambda r: r[3]) if engine else (lambda r: (0 if r[2] else 1, r[3]))
                now = min(held, key=key)[4]
            else:
                now = None
            if now != seat:
                changes.append([turn, now])
                seat = now
        if changes:
            out[house] = changes
    return out


def jurisdiction_spans(conn):
    """The jurisdictions every riding lay under, by year, for a game played on
    a world calendar on a set that has them ({fed_id: [[from, to, name, status,
    sovereign], ...]}, `to` None for the span in force today), else None. The
    map view draws land not under Canada in the year shown as closed, and names
    a riding's jurisdiction that year when it is tapped. Display only."""
    if calendar_of(conn) is None:
        return None
    from hoc import places

    spans = places.riding_jurisdictions(places.reference_dir_for(conn))
    if not spans:
        return None
    return {
        fed: [[s["from_year"], s["to_year"], s["name"], s["status"], s["sovereign"]] for s in rows]
        for fed, rows in sorted(spans.items())
    }


def write_atlas(conn, data_dir, people=False):
    """data/beats/atlas.json: what only the map view reads — each house's seat
    over the game, for a calendar game the jurisdictions by year, and for a
    game told round by round (`people`) its holders and heirs."""
    atlas = {"seats": seat_history(conn)}
    if people:
        atlas["people"] = people_of(conn)
    spans = jurisdiction_spans(conn)
    if spans is not None:
        atlas["jurisdictions"] = spans
    path = Path(data_dir) / "beats" / "atlas.json"
    path.write_text(_dumps(atlas) + "\n", encoding="utf-8")
    return path


def _dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def write_beats(conn, data_dir, title=None, orders=None):
    """Write data/beats/. Returns the paths written.

    `orders` is each season record's `order` ({turn: [house, ...]}), for a
    game played with rules 1.0's `round_record`: the database does not keep
    it, so the caller hands it over from the records. A game given orders is
    told round by round (index `round`): each turn's chunk carries its
    `order`, and for a calendar game its `deck`, the year's events by name."""
    out = Path(data_dir) / "beats"
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.json"):
        stale.unlink()
    told_by_round = bool(orders) and _record_has(conn, "round_record")
    if not told_by_round:
        orders = None
    index, beats = build_story(conn, orders)
    index["title"] = title
    # What a unit of the map is called, where the set names it (the hex
    # trial's "holding"); a riding set's index has no key and reads "riding".
    unit_word = places.set_info(places.reference_dir_for(conn)).get("unit_word")
    if unit_word:
        index["unit_word"] = unit_word
    if told_by_round:
        index["round"] = True
    prestige = prestige_by_turn(conn)
    plans = plans_by_turn(conn)
    deck = deck_by_turn(conn) if told_by_round else {}

    chunks = []
    current = {}
    size = 0
    for turn in sorted(beats):
        piece = len(_dumps({str(turn): beats[turn]}).encode("utf-8"))
        if turn in prestige:
            piece += len(_dumps({str(turn): prestige[turn]}).encode("utf-8"))
        if turn in plans:
            piece += len(_dumps({str(turn): plans[turn]}).encode("utf-8"))
        if orders is not None:
            piece += len(_dumps({str(turn): orders.get(turn, [])}).encode("utf-8"))
            piece += len(_dumps({str(turn): deck.get(turn, [])}).encode("utf-8"))
        if current and size + piece > CHUNK_BUDGET - 64:
            chunks.append(current)
            current, size = {}, 0
        current[str(turn)] = beats[turn]
        size += piece
    if current or not chunks:
        chunks.append(current)

    written = []
    index["chunks"] = []
    for number, chunk in enumerate(chunks, start=1):
        name = f"chunk-{number:03d}.json"
        body = {"turns": chunk}
        held = {t: prestige[int(t)] for t in chunk if int(t) in prestige}
        if held:
            # Rules 1.0 `prestige`: the standings the story layer shows.
            body["prestige"] = held
        if plans:
            # Rules 1.0 `schemes`: what the Plans afoot panel shows.
            body["plans"] = {t: plans.get(int(t), []) for t in chunk}
        if orders is not None:
            # Rules 1.0 `round_record`: the playing order of each turn, and
            # the deck events its world's turn announces.
            body["order"] = {t: orders.get(int(t), []) for t in chunk}
            body["deck"] = {t: deck.get(int(t), []) for t in chunk}
        text = _dumps(body) + "\n"
        if len(text.encode("utf-8")) > CHUNK_BUDGET:
            raise ValueError(f"{name} is over the {CHUNK_BUDGET:,}-byte budget; one turn is too large")
        (out / name).write_text(text, encoding="utf-8")
        written.append(out / name)
        turns = sorted(int(t) for t in chunk)
        index["chunks"].append({
            "file": name,
            "first": turns[0] if turns else 0,
            "last": turns[-1] if turns else 0,
        })
    (out / "index.json").write_text(_dumps(index) + "\n", encoding="utf-8")
    written.append(out / "index.json")
    written.append(write_atlas(conn, data_dir, people=told_by_round))
    return written
