"""Applying a turn to hoc.db, in one transaction.

A turn either lands whole or not at all: if any operation fails, the events,
holdings, clocks, climate and turns rows written so far are rolled back, so a
half-applied turn can never be committed.
"""

import json

from hoc import rules, turnfile
from hoc.names import name_key
from hoc.rules import RuleError

__all__ = ["TurnError", "apply_turn"]


class TurnError(Exception):
    """A turn that could not be applied. Carries the failing operation index."""

    def __init__(self, reason, operation_index=None):
        self.reason = reason
        self.operation_index = operation_index
        if operation_index is None:
            super().__init__(reason)
        else:
            super().__init__(f"operation {operation_index}: {reason}")


# ------------------------------------------------------------- operations --


def _op_expand(conn, op, event_id, _turn):
    rules.expand(conn, op["house"], op["riding"], event_id)


def _op_transfer(conn, op, event_id, _turn):
    rules.transfer_holding(conn, op["from_house"], op["to_house"], op["riding"], event_id)


def _op_release(conn, op, event_id, _turn):
    rules.release_holding(conn, op["house"], op["riding"], event_id)


def _op_succeed(conn, op, event_id, _turn):
    rules.succeed(
        conn,
        op["house"],
        op["successor_name"],
        op["bio_age_at_accession"],
        op["personal_date"],
        op["nature"],
        event_id,
        heir_apparent=op.get("heir_apparent"),
    )


def _op_elevate(conn, op, event_id, _turn):
    rules.elevate(conn, op["house"], op["new_rank"], event_id)


def _op_set_clock(conn, op, _event_id, _turn):
    rules.set_clock(conn, op["house"], op["personal_year"], op["basis"])


def _op_advance_clock(conn, op, _event_id, _turn):
    rules.advance_clock(conn, op["house"], op["years"])


def _op_sync_clocks(conn, op, event_id, _turn):
    rules.sync_clocks(conn, event_id, op["personal_year"])


def _op_climate_shift(conn, op, event_id, _turn):
    rules.climate_shift(
        conn, op["era_cohort"], op["event"], op["magnitude"], op["tag"], op["delta"], event_id=event_id
    )


def _op_relation(conn, op, event_id, _turn):
    conn.execute(
        "INSERT INTO relations (house_a, house_b, marker, event_id, event_text, source)"
        " VALUES (?, ?, ?, ?, ?, 'turn')",
        (op["house_a"], op["house_b"], op["marker"], event_id, op["text"]),
    )


def _merge_mechanical_delta(conn, event_id, key, value):
    """Append a note to the turn event's mechanical_delta JSON."""
    row = conn.execute("SELECT mechanical_delta FROM events WHERE id = ?", (event_id,)).fetchone()
    delta = json.loads(row["mechanical_delta"]) if row and row["mechanical_delta"] else {}
    delta.setdefault(key, []).append(value)
    conn.execute(
        "UPDATE events SET mechanical_delta = ? WHERE id = ?", (json.dumps(delta), event_id)
    )


def _op_found_house(conn, op, event_id, turn):
    """Create a house with its first riding, holder and clock.

    Founding grants must be evaluated for cohort fit against the current climate
    before execution (hard rule 6). A mismatch blocks the grant unless the
    director has explicitly acknowledged it in the turn file, in which case the
    acknowledgement is recorded on the event.
    """
    era_cohort = turn.get("era_cohort")
    fit = rules.cohort_fit(conn, era_cohort, op["tag"])
    if fit == "mismatch" and not op.get("acknowledge_cohort_mismatch"):
        raise RuleError(
            f"founding {op['house']} with a {op['tag']} cohort mismatches the {era_cohort} climate"
            f" ({rules.current_climate(conn, era_cohort)});"
            " set acknowledge_cohort_mismatch true to proceed anyway"
        )

    fed_id = conn.execute(
        "SELECT fed_id FROM ridings WHERE name_key = ?", (name_key(op["riding"]),)
    ).fetchone()
    if fed_id is None:
        raise RuleError(f"unknown riding {op['riding']!r}")
    fed_id = fed_id["fed_id"]

    occupant = conn.execute(
        "SELECT house FROM holdings WHERE fed_id = ? AND released_event_id IS NULL", (fed_id,)
    ).fetchone()
    if occupant is not None:
        raise RuleError(f"cannot found {op['house']} on {op['riding']!r}: occupied by {occupant['house']}")

    conn.execute(
        "INSERT INTO houses (house, peerage, rank, status, primary_hex, secondary_hex)"
        " VALUES (?, ?, ?, 'active', ?, ?)",
        (op["house"], op["peerage"], op["rank"], op["primary_hex"], op.get("secondary_hex")),
    )
    conn.execute(
        "INSERT INTO holdings (house, fed_id, seat_order, hex, acquired_event_id)"
        " VALUES (?, ?, 1, ?, ?)",
        (op["house"], fed_id, op["primary_hex"], event_id),
    )
    conn.execute(
        "INSERT INTO holders (house, name, generation, acceded, bio_age_at_accession,"
        " heir_apparent, is_current, source, confidence)"
        " VALUES (?, ?, 'G1', 'founding', ?, ?, 1, 'turn', 'high')",
        (op["house"], op["holder_name"], op["bio_age"], op.get("heir_apparent")),
    )
    conn.execute(
        "INSERT INTO clocks (house, personal_year, basis) VALUES (?, 1867, 'founding grant')",
        (op["house"],),
    )
    # The house did not exist when the event was recorded, so it links itself.
    conn.execute(
        "INSERT INTO event_houses (event_id, house, role) VALUES (?, ?, 'founder')",
        (event_id, op["house"]),
    )

    _merge_mechanical_delta(
        conn,
        event_id,
        "founded",
        {"house": op["house"], "riding": op["riding"], "tag": op["tag"], "cohort_fit": fit},
    )
    if fit == "mismatch":
        _merge_mechanical_delta(
            conn,
            event_id,
            "cohort_mismatch_acknowledged",
            {
                "house": op["house"],
                "tag": op["tag"],
                "era_cohort": era_cohort,
                "climate": rules.current_climate(conn, era_cohort),
            },
        )


# ------------------------------------------------- director interventions --
#
# Phase 9e. These four are the console's hands on the game: they change the
# engine's own state rather than the map, so each records what it did and why in
# the event's mechanical delta, and each stamps the season it applies after so
# the next season's log can carry it (hoc/sim.py, _interventions_since).


def _current_season(conn):
    row = conn.execute("SELECT MAX(season_no) AS n FROM seasons").fetchone()
    return 0 if row is None or row["n"] is None else row["n"]


def _require_engine_house(conn, house):
    row = conn.execute("SELECT * FROM house_stats WHERE house = ?", (house,)).fetchone()
    if row is None:
        raise rules.RuleError(
            f"{house} has no engine state; director interventions apply to the"
            " autoplay game, not to the reconstructed one"
        )
    return row


def _op_set_objective(conn, op, event_id, data):
    """Give a house an objective it did not draw (§12)."""
    _require_engine_house(conn, op["house"])
    season = _current_season(conn)

    existing = conn.execute(
        "SELECT 1 FROM objectives WHERE house = ? AND objective = ? AND satisfied_season IS NULL",
        (op["house"], op["objective"]),
    ).fetchone()
    if existing:
        raise rules.RuleError(f"{op['house']} already holds the objective {op['objective']!r}")

    conn.execute(
        "INSERT INTO objectives (house, objective, acquired_season) VALUES (?, ?, ?)",
        (op["house"], op["objective"], season),
    )
    conn.execute(
        "INSERT OR IGNORE INTO event_houses (event_id, house, role)"
        " VALUES (?, ?, 'subject')",
        (event_id, op["house"]),
    )
    _merge_mechanical_delta(
        conn, event_id, "set_objective",
        {"house": op["house"], "objective": op["objective"], "reason": op.get("reason"),
         "after_season": season},
    )


def _op_veto_objective(conn, op, event_id, data):
    """Take an objective away. It is marked satisfied at the current season
    rather than deleted: the house did hold it, and the record should say so."""
    _require_engine_house(conn, op["house"])
    season = _current_season(conn)

    changed = conn.execute(
        "UPDATE objectives SET satisfied_season = ? WHERE house = ? AND objective = ?"
        " AND satisfied_season IS NULL",
        (season, op["house"], op["objective"]),
    ).rowcount
    if not changed:
        raise rules.RuleError(
            f"{op['house']} does not currently hold the objective {op['objective']!r}"
        )
    conn.execute(
        "INSERT OR IGNORE INTO event_houses (event_id, house, role)"
        " VALUES (?, ?, 'subject')",
        (event_id, op["house"]),
    )
    _merge_mechanical_delta(
        conn, event_id, "veto_objective",
        {"house": op["house"], "objective": op["objective"], "reason": op.get("reason"),
         "after_season": season},
    )


def _op_force_action(conn, op, event_id, data):
    """Name the action a house takes next season. Consumed once by the engine."""
    _require_engine_house(conn, op["house"])
    season = _current_season(conn)

    from hoc.rules_data import load_rules

    known = {action.action for action in load_rules().actions}
    if op["action"] not in known:
        raise rules.RuleError(
            f"unknown action {op['action']!r}; valid actions are {', '.join(sorted(known))}"
        )

    conn.execute(
        "UPDATE house_stats SET forced_action = ? WHERE house = ?", (op["action"], op["house"])
    )
    conn.execute(
        "INSERT OR IGNORE INTO event_houses (event_id, house, role)"
        " VALUES (?, ?, 'subject')",
        (event_id, op["house"]),
    )
    _merge_mechanical_delta(
        conn, event_id, "force_action",
        {"house": op["house"], "action": op["action"], "reason": op.get("reason"),
         "after_season": season},
    )


def _op_adjust_stat(conn, op, event_id, data):
    """Move a stat by hand. The reason is required by the turn file schema, not
    merely encouraged: an unexplained adjustment is indistinguishable from a bug
    when someone reads the log a hundred seasons later."""
    row = _require_engine_house(conn, op["house"])
    season = _current_season(conn)

    stat = op["stat"]
    if stat not in STAT_BOUNDS:
        raise rules.RuleError(
            f"unknown stat {stat!r}; adjustable stats are {', '.join(sorted(STAT_BOUNDS))}"
        )

    low, high = STAT_BOUNDS[stat]
    before = row[stat]
    after = max(low, min(high, before + int(op["delta"])))
    conn.execute(f"UPDATE house_stats SET {stat} = ? WHERE house = ?", (after, op["house"]))
    conn.execute(
        "INSERT OR IGNORE INTO event_houses (event_id, house, role)"
        " VALUES (?, ?, 'subject')",
        (event_id, op["house"]),
    )
    _merge_mechanical_delta(
        conn, event_id, "adjust_stat",
        {"house": op["house"], "stat": stat, "delta": int(op["delta"]),
         "before": before, "after": after, "reason": op["reason"], "after_season": season},
    )


def _op_grant_house(conn, op, event_id, data):
    """Grant a house through the engine's founding path (§10, §12).

    The engine's own RNG for the current season does the drawing, so a replay of
    this turn at the same point produces the same house — a granted house is as
    reproducible as a rolled one.
    """
    from hoc import sim

    season = _current_season(conn)
    world = sim.World(conn, world_seed=_world_seed(conn))
    house = world.found_house(
        season,
        seat=op["riding"],
        rng=world.rng_for(season),
        community=op.get("community"),
        tag=op.get("tag"),
        rank=op.get("rank"),
        surname=(op.get("surname") or "").strip() or None,
    )
    if house is None:
        raise rules.RuleError(
            f"could not grant a house at {op['riding']!r};"
            " the riding may be held, or its province's place bank exhausted"
        )

    conn.execute(
        "INSERT OR IGNORE INTO event_houses (event_id, house, role) VALUES (?, ?, 'subject')",
        (event_id, house),
    )
    _merge_mechanical_delta(
        conn, event_id, "grant_house",
        {"house": house, "riding": op["riding"], "community": op.get("community"),
         "rank": op.get("rank"), "tag": op.get("tag"), "reason": op.get("reason"),
         "after_season": season},
    )


def _world_seed(conn):
    row = conn.execute("SELECT seed FROM seasons ORDER BY season_no DESC LIMIT 1").fetchone()
    if row is None:
        raise rules.RuleError(
            "this scenario has no world seed; a grant through the engine needs one"
        )
    return row["seed"]


# The stats a director may move, with the bounds §4 puts them in.
STAT_BOUNDS = {
    "capital": (0, 100),
    "influence": (0, 100),
    "cohesion": (0, 100),
    "ambition": (0, 10),
}


OPERATIONS = {
    "expand": _op_expand,
    "transfer": _op_transfer,
    "release": _op_release,
    "succeed": _op_succeed,
    "elevate": _op_elevate,
    "set_clock": _op_set_clock,
    "advance_clock": _op_advance_clock,
    "sync_clocks": _op_sync_clocks,
    "climate_shift": _op_climate_shift,
    "relation": _op_relation,
    "found_house": _op_found_house,
    "set_objective": _op_set_objective,
    "veto_objective": _op_veto_objective,
    "force_action": _op_force_action,
    "adjust_stat": _op_adjust_stat,
    "grant_house": _op_grant_house,
}


# ------------------------------------------------------------------- turn --


def _apply_watch_and_threads(conn, data):
    watch = data.get("watch") or {}
    for text in watch.get("add", []):
        conn.execute("INSERT INTO watch (text, status) VALUES (?, 'open')", (text,))
    for watch_id in watch.get("discharge", []):
        row = conn.execute("SELECT id FROM watch WHERE id = ?", (watch_id,)).fetchone()
        if row is None:
            raise RuleError(f"cannot discharge watch item {watch_id}: no such item")
        conn.execute("UPDATE watch SET status = 'discharged' WHERE id = ?", (watch_id,))
    for text in data.get("threads") or []:
        conn.execute("INSERT INTO threads (text) VALUES (?)", (text,))


def _summary(conn, event_id, ops_applied):
    holdings = conn.execute(
        "SELECT COUNT(*) FROM holdings WHERE released_event_id IS NULL"
    ).fetchone()[0]
    climate = {
        row["era_cohort"]: int(row["cumulative_after"])
        for row in conn.execute("SELECT era_cohort, cumulative_after FROM v_current_climate")
    }
    return {
        "event_id": event_id,
        "ops_applied": ops_applied,
        "holdings": holdings,
        "climate": climate,
    }


def apply_turn(conn, path):
    """Validate and apply a turn file. Returns a summary dict.

    Raises TurnError on any failure, having rolled the whole turn back — the
    turns table is left exactly as it was.
    """
    try:
        turn_id, data = turnfile.load(path)
        warnings = turnfile.validate(conn, data)
    except turnfile.TurnFileError as exc:
        raise TurnError(str(exc)) from exc

    if conn.execute("SELECT 1 FROM turns WHERE turn_id = ?", (turn_id,)).fetchone():
        raise TurnError(f"turn {turn_id} has already been applied")

    event = data["event"]
    operations = data.get("operations") or []
    index = None
    try:
        conn.execute(
            "INSERT INTO turns (turn_id, directive, created_at, status)"
            " VALUES (?, ?, datetime('now'), 'applied')",
            (turn_id, data["directive"]),
        )
        event_id = rules.record_event(
            conn,
            event["kind"],
            event["title"],
            event.get("houses") or [],
            era_cohort=data.get("era_cohort"),
            narrative=event.get("narrative"),
            turn_id=turn_id,
        )
        for index, op in enumerate(operations):
            OPERATIONS[op["op"]](conn, op, event_id, data)
        index = None
        _apply_watch_and_threads(conn, data)
        summary = _summary(conn, event_id, len(operations))
    except Exception as exc:  # rollback covers RuleError, sqlite errors and bugs alike
        conn.rollback()
        raise TurnError(str(exc), operation_index=index) from exc

    conn.commit()
    summary["turn_id"] = turn_id
    summary["warnings"] = warnings
    return summary
