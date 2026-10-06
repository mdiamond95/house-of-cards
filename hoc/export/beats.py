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

from hoc import rules as mechanics

__all__ = [
    "build_story", "write_beats", "turn_inputs", "type_turn", "BEAT_KINDS", "CHUNK_BUDGET",
]

CHUNK_BUDGET = 500_000  # bytes per fetch (Phase A, task 3)

GRIEVANCE = "Sig−"

BEAT_KINDS = (
    "removed", "riding_passes", "partition", "elevation", "succession_disorderly",
    "quarrel", "marriage", "dispute_won", "reconciled", "founding", "succession_clean",
    "major_response", "compact", "expansion", "failed", "correspondence",
    "invest", "cultivate", "consolidate", "name_heir",
    "riding_lost", "endowment", "era_response", "other",
)

SILENT_FAILURES = (
    "Cede / swap", "Expand", "Marriage alliance", "Petition elevation",
    "Propose compact", "Purchase riding", "Reconcile",
)

BOOKKEEPING_ACTIONS = {
    "Invest": "invest",
    "Cultivate influence": "cultivate",
    "Consolidate (rest)": "consolidate",
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
            return "riding_passes", "purchase" if "price" in d else d.get("reason")
        return "riding_lost", d.get("reason")
    if kind == "challenge":
        if d.get("outcome") == "won":
            return "riding_passes", "challenge"
        return "failed", "Challenge (11b)"
    if kind == "elevation":
        return "elevation", d.get("to")
    if kind == "expansion":
        return "expansion", None
    if kind == "societal":
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
        action = action_of(houses[0]) if houses else None
        return {
            "Correspond": ("correspondence", d.get("marker")),
            "Propose compact": ("compact", None),
            "Reconcile": ("reconciled", None),
            "Marriage alliance": ("marriage", None),
            "Absorb": ("failed", "Absorb"),
        }.get(action, ("other", None))
    if kind == "other":
        action = action_of(houses[0]) if houses else None
        if action == "Name heir":
            return "name_heir", d.get("role")
        if action == "Endow":
            return "endowment", None
        return "other", None
    return "other", None


def _beat(turn, seq, kind, houses, ridings, outcome, line, owners, ranks, removed):
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
    return beat


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
        if kind == "removed" and houses:
            removed.append(houses[0])
        if kind == "riding_passes" and outcome == "absorption" and len(houses) > 1:
            removed.append(houses[1])

        beats.append(_beat(data["turn"], len(beats), kind, houses, ridings, outcome,
                           event["line"], owners, ranks, removed))

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
                           None, {}, {}, []))
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


def turn_inputs(conn):
    """Every turn's input, as (turns, baseline): turns is [(turn, input)] for
    turns 1..last, baseline the board before turn 1 (web/story/standings.js)."""
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
        turns.append((turn, {
            "turn": turn,
            "events": events,
            "actions": actions.get(turn, []) if engine else [],
            "holdings": moved,
            "ranks": ranks,
        }))
    baseline = {"owners": baseline_owners, "ranks": baseline_ranks,
                "removed": sorted(baseline_removed)}
    return turns, baseline


# ------------------------------------------------------------------ output --


def build_story(conn):
    """(index, {turn: beats}) for the whole game."""
    turns, baseline = turn_inputs(conn)
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
    }
    return index, beats


def _dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def write_beats(conn, data_dir, title=None):
    """Write data/beats/. Returns the paths written."""
    out = Path(data_dir) / "beats"
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.json"):
        stale.unlink()
    index, beats = build_story(conn)
    index["title"] = title

    chunks = []
    current = {}
    size = 0
    for turn in sorted(beats):
        piece = len(_dumps({str(turn): beats[turn]}).encode("utf-8"))
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
        text = _dumps({"turns": chunk}) + "\n"
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
    return written
