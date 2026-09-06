"""Game mechanics, executed against an open hoc.db connection.

Every function here takes a live sqlite3 connection from `hoc.db.connect` and
writes through it. Nothing in this module reads or writes the seed CSVs, and
nothing here exports a workbook — the turn runner owns the transaction and the
exporters.

Transactions: these functions do not commit. The caller wraps a turn in one
transaction so that a rule failure part-way through rolls the whole turn back.

Where a rule was never recovered from the lost workbook, the value is an
explicit parameter rather than a formula invented here (CLAUDE.md hard rule 1).
Those are: the year participants sync to (`sync_clocks`), the per-event climate
delta (`climate_shift`), and the cohort-fit thresholds (`cohort_fit`, a first
encoding). See docs/RECONSTRUCTION.md, "Rules not recovered".
"""

import json
from dataclasses import dataclass

from hoc.names import name_key

__all__ = [
    "RuleError",
    "ExpansionCheck",
    "EVENT_KINDS",
    "RANK_LADDER",
    "validate_expansion",
    "expand",
    "release_holding",
    "transfer_holding",
    "house_colours",
    "succeed",
    "set_clock",
    "advance_clock",
    "sync_clocks",
    "climate_shift",
    "current_climate",
    "cohort_fit",
    "elevate",
    "record_event",
]


class RuleError(Exception):
    """A move that the mechanics forbid."""


# Kinds accepted by the events table (kept in step with hoc/schema.sql).
EVENT_KINDS = (
    "founding",
    "expansion",
    "relational",
    "incursion",
    "challenge",
    "succession",
    "societal",
    "elevation",
    "transfer",
    "other",
)

# Only these kinds are direct shared events between named houses, so only these
# can sync clocks. Global (societal) events never do — CLAUDE.md hard rule 5.
SYNCABLE_KINDS = ("relational", "challenge", "incursion", "transfer")

# Rank ladder, low to high. Each step lists the forms in use; a house keeps
# whichever form its peerage uses.
RANK_LADDER = (
    ("Baron", "Baroness"),
    ("Viscount", "Viscountess"),
    ("Earl", "Countess"),
    ("Marquis", "Marchioness"),
    ("Duke", "Duchess"),
)

RANK_LEVEL = {form: level for level, forms in enumerate(RANK_LADDER) for form in forms}

CLIMATE_MAGNITUDES = ("Minor", "Significant", "Major")
CLIMATE_TAGS = ("Progressive", "Conservative", "Mixed", "Outside", "Global", "regressive")


@dataclass
class ExpansionCheck:
    ok: bool
    fed_id: str | None
    reason: str
    warning: str | None = None


# ------------------------------------------------------------------ helpers --


def _resolve_riding(conn, riding_name):
    row = conn.execute(
        "SELECT fed_id FROM ridings WHERE name_key = ?", (name_key(riding_name),)
    ).fetchone()
    return None if row is None else row["fed_id"]


def _require_house(conn, house):
    row = conn.execute("SELECT * FROM houses WHERE house = ?", (house,)).fetchone()
    if row is None:
        raise RuleError(f"unknown house {house!r}")
    return row


def _current_holding(conn, house, fed_id):
    return conn.execute(
        "SELECT * FROM holdings WHERE house = ? AND fed_id = ? AND released_event_id IS NULL",
        (house, fed_id),
    ).fetchone()


def _holder_of(conn, fed_id):
    """The house currently holding a riding, or None."""
    row = conn.execute(
        "SELECT house FROM holdings WHERE fed_id = ? AND released_event_id IS NULL",
        (fed_id,),
    ).fetchone()
    return None if row is None else row["house"]


def _next_seat_order(conn, house):
    row = conn.execute(
        "SELECT COALESCE(MAX(seat_order), 0) + 1 AS next FROM holdings"
        " WHERE house = ? AND released_event_id IS NULL",
        (house,),
    ).fetchone()
    return row["next"]


def _expansion_hex(conn, house):
    """A newly acquired riding takes the house's secondary colour; a house with
    no secondary recorded uses its primary. The principal seat keeps the primary
    colour (hard rule 4), so this never touches seat_order 1."""
    primary, secondary = house_colours(conn, house)
    return secondary or primary


# ---------------------------------------------------------------- expansion --


def validate_expansion(conn, house, riding_name):
    """Check a proposed expansion before any narrative is written.

    Adjacency is to a *current* holding of the house. Water-only adjacency is
    allowed but flagged, never silently accepted (hard rule 3).
    """
    _require_house(conn, house)

    fed_id = _resolve_riding(conn, riding_name)
    if fed_id is None:
        return ExpansionCheck(ok=False, fed_id=None, reason="unknown riding")

    occupant = _holder_of(conn, fed_id)
    if occupant is not None:
        return ExpansionCheck(ok=False, fed_id=fed_id, reason=f"occupied by {occupant}")

    types = {
        row["adjacency_type"]
        for row in conn.execute(
            "SELECT a.adjacency_type FROM adjacency a"
            " JOIN holdings h ON h.released_event_id IS NULL AND h.house = ?"
            "   AND ((a.fed_id_a = ? AND a.fed_id_b = h.fed_id)"
            "     OR (a.fed_id_b = ? AND a.fed_id_a = h.fed_id))",
            (house, fed_id, fed_id),
        )
    }

    if "land" in types:
        return ExpansionCheck(ok=True, fed_id=fed_id, reason="land adjacency")
    if "water" in types:
        return ExpansionCheck(
            ok=True,
            fed_id=fed_id,
            reason="water adjacency",
            warning="water adjacency only; land preferred",
        )
    return ExpansionCheck(ok=False, fed_id=fed_id, reason="not adjacent")


def expand(conn, house, riding_name, event_id):
    """Add a riding to a house. Returns the new holding id."""
    check = validate_expansion(conn, house, riding_name)
    if not check.ok:
        raise RuleError(f"cannot expand {house} into {riding_name!r}: {check.reason}")

    cursor = conn.execute(
        "INSERT INTO holdings (house, fed_id, seat_order, hex, acquired_event_id)"
        " VALUES (?, ?, ?, ?, ?)",
        (house, check.fed_id, _next_seat_order(conn, house), _expansion_hex(conn, house), event_id),
    )
    return cursor.lastrowid


def release_holding(conn, house, riding_name, event_id):
    """Close a holding, keeping the row as history. Returns the released id."""
    fed_id = _resolve_riding(conn, riding_name)
    if fed_id is None:
        raise RuleError(f"unknown riding {riding_name!r}")

    holding = _current_holding(conn, house, fed_id)
    if holding is None:
        raise RuleError(f"{house} does not currently hold {riding_name!r}")

    conn.execute("UPDATE holdings SET released_event_id = ? WHERE id = ?", (event_id, holding["id"]))
    return holding["id"]


def transfer_holding(conn, from_house, to_house, riding_name, event_id):
    """Move a riding between houses. Returns the new holding id.

    Transfers are not adjacency-bound: Section 12 transfers happened between
    houses that did not border each other.
    """
    _require_house(conn, to_house)
    if from_house == to_house:
        raise RuleError("cannot transfer a riding to the house that already holds it")

    fed_id = _resolve_riding(conn, riding_name)
    if fed_id is None:
        raise RuleError(f"unknown riding {riding_name!r}")

    release_holding(conn, from_house, riding_name, event_id)
    cursor = conn.execute(
        "INSERT INTO holdings (house, fed_id, seat_order, hex, acquired_event_id)"
        " VALUES (?, ?, ?, ?, ?)",
        (to_house, fed_id, _next_seat_order(conn, to_house), _expansion_hex(conn, to_house), event_id),
    )
    return cursor.lastrowid


def house_colours(conn, house):
    """(primary_hex, secondary_hex or None) as the colours view derives them."""
    row = conn.execute(
        "SELECT primary_hex, secondary_hex FROM v_house_colours WHERE house = ?", (house,)
    ).fetchone()
    if row is None:
        raise RuleError(f"unknown house {house!r}")
    return row["primary_hex"], row["secondary_hex"]


# --------------------------------------------------------------- succession --


def _current_holder(conn, house):
    return conn.execute(
        "SELECT * FROM holders WHERE house = ? AND is_current = 1", (house,)
    ).fetchone()


def _next_generation(generation, house):
    """G1 → G2 → G3. An unrecovered generation is not guessed."""
    if not generation or not generation.startswith("G") or not generation[1:].isdigit():
        raise RuleError(
            f"cannot advance generation for {house}: current generation is {generation!r};"
            " set it explicitly before running a succession"
        )
    return f"G{int(generation[1:]) + 1}"


def succeed(conn, house, successor_name, bio_age_at_accession, personal_date, nature, event_id,
            heir_apparent=None):
    """Record a succession. Returns the new holder id.

    The new holder's clock resets to personal 1867 (hard rule 5). Biological
    ages are recorded as given, never reset or recomputed.
    """
    _require_house(conn, house)
    outgoing = _current_holder(conn, house)
    if outgoing is None:
        raise RuleError(f"{house} has no current holder to succeed")

    generation = _next_generation(outgoing["generation"], house)

    # The partial unique index allows only one current holder per house, so the
    # outgoing holder must step down before the successor is inserted.
    conn.execute("UPDATE holders SET is_current = 0 WHERE id = ?", (outgoing["id"],))
    cursor = conn.execute(
        "INSERT INTO holders (house, name, generation, acceded, bio_age_at_accession,"
        " predecessor, heir_apparent, is_current, source, confidence)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'turn', 'high')",
        (
            house,
            successor_name,
            generation,
            personal_date,
            bio_age_at_accession,
            outgoing["name"],
            heir_apparent,
        ),
    )
    holder_id = cursor.lastrowid

    conn.execute(
        "UPDATE clocks SET personal_year = 1867, basis = ? WHERE house = ?",
        (f"reset at accession {personal_date}", house),
    )

    next_seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM successions").fetchone()["next"]
    conn.execute(
        "INSERT INTO successions (seq, house, predecessor, successor, transition,"
        " personal_date, nature, batch, source) VALUES (?, ?, ?, ?, ?, ?, ?, 'turn', 'turn')",
        (
            next_seq,
            house,
            outgoing["name"],
            successor_name,
            f"{outgoing['name']}→{successor_name}",
            personal_date,
            nature,
        ),
    )
    return holder_id


# ------------------------------------------------------------------- clocks --


def set_clock(conn, house, personal_year, basis):
    """Set a house's personal clock outright (the director's call)."""
    _require_house(conn, house)
    conn.execute(
        "UPDATE clocks SET personal_year = ?, basis = ? WHERE house = ?",
        (personal_year, basis, house),
    )


def advance_clock(conn, house, years):
    """Move a house's clock forward. Returns the new personal year."""
    row = conn.execute("SELECT personal_year FROM clocks WHERE house = ?", (house,)).fetchone()
    if row is None:
        raise RuleError(f"unknown house {house!r}")
    if row["personal_year"] is None:
        raise RuleError(
            f"{house} has no personal year recorded; set it explicitly before advancing"
        )
    new_year = row["personal_year"] + years
    conn.execute("UPDATE clocks SET personal_year = ? WHERE house = ?", (new_year, house))
    return new_year


def sync_clocks(conn, event_id, personal_year):
    """Sync the clocks of the houses sharing a direct event.

    Only direct shared events between named houses sync clocks; global events
    never do (hard rule 5). The year the participants meet at was not recovered
    as a formula, so the turn supplies it.
    """
    event = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if event is None:
        raise RuleError(f"unknown event {event_id}")
    if event["kind"] not in SYNCABLE_KINDS:
        raise RuleError(
            f"events of kind {event['kind']!r} never sync clocks;"
            f" syncable kinds are {', '.join(SYNCABLE_KINDS)}"
        )

    houses = [row["house"] for row in conn.execute(
        "SELECT house FROM event_houses WHERE event_id = ? ORDER BY house", (event_id,)
    )]
    if len(houses) < 2:
        raise RuleError(f"event {event_id} has {len(houses)} house(s); a sync needs two or more")

    for house in houses:
        conn.execute(
            "UPDATE clocks SET personal_year = ?, basis = ? WHERE house = ?",
            (personal_year, f"synced to {personal_year} at event {event_id}", house),
        )
    conn.execute(
        "UPDATE event_houses SET personal_year = ? WHERE event_id = ?", (personal_year, event_id)
    )
    return houses


# ------------------------------------------------------------------ climate --


def _format_cumulative(value):
    """Match the ledger's recorded style: '+1', '0', '-2'."""
    return f"+{value}" if value > 0 else str(value)


def current_climate(conn, era_cohort):
    """The latest recorded climate position for one era-cohort, as an integer.

    Never sum or average the cohorts: they are parallel ledgers (hard rule 8).
    """
    row = conn.execute(
        "SELECT cumulative_after FROM v_current_climate WHERE era_cohort = ?", (era_cohort,)
    ).fetchone()
    if row is None:
        raise RuleError(f"no climate ledger for era-cohort {era_cohort!r}")
    if row["cumulative_after"] is None:
        raise RuleError(f"latest {era_cohort} climate row has no recorded cumulative value")
    return int(row["cumulative_after"])


def climate_shift(conn, era_cohort, event, magnitude, tag, delta, event_id=None):
    """Append a societal event to one cohort's ledger. Returns the new cumulative.

    The Section 10 calculator that turned magnitude and tag into a delta was
    never recovered, so `delta` is explicit and is not derived from the other
    arguments.
    """
    if magnitude not in CLIMATE_MAGNITUDES:
        raise RuleError(f"magnitude must be one of {CLIMATE_MAGNITUDES}, got {magnitude!r}")
    if tag not in CLIMATE_TAGS:
        raise RuleError(f"tag must be one of {CLIMATE_TAGS}, got {tag!r}")

    previous = current_climate(conn, era_cohort)
    new_cumulative = previous + delta

    next_seq = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM climate WHERE era_cohort = ?", (era_cohort,)
    ).fetchone()["next"]
    conn.execute(
        "INSERT INTO climate (era_cohort, seq, event, magnitude, tag, cumulative_after, event_id, source)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, 'turn')",
        (era_cohort, next_seq, event, magnitude, tag, _format_cumulative(new_cumulative), event_id),
    )
    return new_cumulative


def cohort_fit(conn, era_cohort, proposed_tag):
    """Whether a proposed founding cohort suits the current climate of a cohort.

    Returns 'fit', 'mismatch' or 'neutral'. Founding grants must be evaluated
    for cohort fit before execution (hard rule 6).

    This is a first encoding, not a recovered rule: the workbook's thresholds
    were lost. It treats any non-zero climate as decisive and a zero climate as
    neutral. The director may refine the thresholds (e.g. requiring a magnitude
    of 2 before a climate counts as decisive) — change it here, in one place.
    """
    climate = current_climate(conn, era_cohort)
    if climate == 0 or proposed_tag not in ("Progressive", "Conservative"):
        return "neutral"
    if proposed_tag == "Progressive":
        return "fit" if climate > 0 else "mismatch"
    return "fit" if climate < 0 else "mismatch"


# ---------------------------------------------------------------- elevation --


def elevate(conn, house, new_rank, event_id):
    """Raise a house's rank and rewrite its peerage. Returns the new peerage.

    Multi-step elevations are allowed: Sinclair-McKay went Baroness → Countess.
    Colours do not change on elevation — the primary colour follows the
    principal seat, not the rank (hard rule 4). The caller records the event.
    """
    row = _require_house(conn, house)

    if new_rank not in RANK_LEVEL:
        raise RuleError(f"unknown rank {new_rank!r}; ladder is {RANK_LADDER}")
    current_rank = row["rank"]
    if current_rank not in RANK_LEVEL:
        raise RuleError(f"{house} has no rank on the ladder recorded (rank={current_rank!r})")
    if RANK_LEVEL[new_rank] <= RANK_LEVEL[current_rank]:
        raise RuleError(f"elevation must move up the ladder: {current_rank} → {new_rank}")

    peerage = row["peerage"]
    if not peerage:
        raise RuleError(f"{house} has no peerage recorded to rewrite")
    head, _, rest = peerage.partition(" ")
    if head not in RANK_LEVEL:
        raise RuleError(f"peerage {peerage!r} does not begin with a rank on the ladder")
    new_peerage = f"{new_rank} {rest}"

    conn.execute(
        "UPDATE houses SET rank = ?, peerage = ? WHERE house = ?", (new_rank, new_peerage, house)
    )
    return new_peerage


# ------------------------------------------------------------------- events --


def record_event(conn, kind, title, houses, era_cohort=None, narrative=None,
                 mechanical_delta=None, turn_id=None, source="turn"):
    """Insert an event and its participating houses. Returns the event id.

    `houses` is a sequence of house names (all recorded as 'participant') or a
    mapping of house name to role. `mechanical_delta` may be a JSON string or
    any JSON-serialisable object.
    """
    if kind not in EVENT_KINDS:
        raise RuleError(f"unknown event kind {kind!r}; valid kinds are {', '.join(EVENT_KINDS)}")

    if isinstance(houses, dict):
        roles = dict(houses)
    else:
        roles = {house: "participant" for house in houses}
    for house in roles:
        _require_house(conn, house)

    if mechanical_delta is not None and not isinstance(mechanical_delta, str):
        mechanical_delta = json.dumps(mechanical_delta)

    cursor = conn.execute(
        "INSERT INTO events (turn_id, kind, era_cohort, title, narrative, mechanical_delta,"
        " source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (turn_id, kind, era_cohort, title, narrative, mechanical_delta, source),
    )
    event_id = cursor.lastrowid

    for house, role in roles.items():
        conn.execute(
            "INSERT INTO event_houses (event_id, house, role) VALUES (?, ?, ?)",
            (event_id, house, role),
        )
    return event_id
