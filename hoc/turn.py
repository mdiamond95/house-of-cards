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
