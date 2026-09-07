"""Turn file loading and validation.

A turn file is the whole of a turn's input: the director's directive, the event
it produces, its narrative, and the mechanical operations to apply. See
docs/TURN_FILE.md for the format.

Validation happens before anything is written, so a malformed turn never opens a
transaction against hoc.db.
"""

import json
import re
from pathlib import Path

from hoc.rules import CLIMATE_MAGNITUDES, CLIMATE_TAGS, EVENT_KINDS, RANK_LEVEL

__all__ = [
    "TurnFileError",
    "OPERATION_FIELDS",
    "NARRATIVE_TARGET_WORDS",
    "NARRATIVE_MAX_WORDS",
    "load",
    "validate",
    "turn_id_from_path",
    "word_count",
]

NARRATIVE_TARGET_WORDS = 500
NARRATIVE_WARN_WORDS = 550
NARRATIVE_MAX_WORDS = 600

# A turn is expected to change something. Housekeeping turns — a policy note, a
# watch item discharged — are the exception and are recorded as kind 'other'.
KIND_ALLOWING_NO_OPERATIONS = "other"

FILENAME_PATTERN = re.compile(r"^(\d{4})_[a-z0-9-]+\.json$")

ERA_COHORTS = ("founding-era", "later-era")

# Required and optional fields per operation type. Each maps to one rules.py call.
OPERATION_FIELDS = {
    "expand": (("house", "riding"), ()),
    "transfer": (("from_house", "to_house", "riding"), ()),
    "release": (("house", "riding"), ()),
    "succeed": (
        ("house", "successor_name", "bio_age_at_accession", "personal_date", "nature"),
        ("heir_apparent",),
    ),
    "elevate": (("house", "new_rank"), ()),
    "set_clock": (("house", "personal_year", "basis"), ()),
    "advance_clock": (("house", "years"), ()),
    "sync_clocks": (("personal_year",), ()),
    "climate_shift": (("era_cohort", "event", "magnitude", "tag", "delta"), ()),
    "relation": (("house_a", "house_b", "marker", "text"), ()),
    "found_house": (
        (
            "house",
            "peerage",
            "rank",
            "riding",
            "primary_hex",
            "holder_name",
            "bio_age",
            "tag",
        ),
        ("secondary_hex", "heir_apparent", "acknowledge_cohort_mismatch"),
    ),
    # Phase 9e director interventions (§12). `reason` is optional on three of
    # them and required on adjust_stat, which is the only one that changes a
    # number with no rule behind it.
    "set_objective": (("house", "objective"), ("reason",)),
    "veto_objective": (("house", "objective"), ("reason",)),
    "force_action": (("house", "action"), ("reason",)),
    "adjust_stat": (("house", "stat", "delta", "reason"), ()),
    # A grant through the engine's own founding path: the director chooses the
    # seat and as much else as they care to, and the banks supply the rest —
    # name, peerage, colours, holder and opening stats. Unlike found_house it
    # does not ask the director to invent a colour or a holder's age.
    "grant_house": (("riding",), ("community", "rank", "tag", "surname", "reason")),
}

# Which fields of an operation name a house that must already exist.
HOUSE_FIELDS = {
    "expand": ("house",),
    "transfer": ("from_house", "to_house"),
    "release": ("house",),
    "succeed": ("house",),
    "elevate": ("house",),
    "set_clock": ("house",),
    "advance_clock": ("house",),
    "relation": ("house_a", "house_b"),
    "set_objective": ("house",),
    "veto_objective": ("house",),
    "force_action": ("house",),
    "adjust_stat": ("house",),
}

# The stats a director may adjust, and the bounds a delta is clamped into.
ADJUSTABLE_STATS = ("capital", "influence", "cohesion", "ambition")

HEX_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


class TurnFileError(Exception):
    """A turn file that cannot be applied as written."""


def word_count(text):
    return len(text.split())


def turn_id_from_path(path):
    """…/turns/0007_slug.json -> 7. The number is the turn id, so it must be
    unique and ordered; the loader refuses anything else."""
    match = FILENAME_PATTERN.match(Path(path).name)
    if match is None:
        raise TurnFileError(
            f"turn file name {Path(path).name!r} must look like NNNN_slug.json"
            " (four digits, underscore, lowercase slug)"
        )
    return int(match.group(1))


def load(path, turn_id=None):
    """Read a turn file. Returns (turn_id, data).

    `turn_id` overrides the one in the filename, which is what an intervention
    recorded as `interventions/NNNN.json` needs: it is keyed by the season it
    follows rather than by a turn number, and its id is allocated from a range
    that cannot collide with a hand-written turn (hoc/turn.py).
    """
    path = Path(path)
    if turn_id is None:
        turn_id = turn_id_from_path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TurnFileError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise TurnFileError(f"{path.name} must contain a JSON object")
    return turn_id, data


def _known_houses(conn):
    return {row["house"] for row in conn.execute("SELECT house FROM houses")}


def _check_event(data, errors):
    event = data.get("event")
    if not isinstance(event, dict):
        errors.append("event: missing or not an object")
        return {}

    for field in ("kind", "title", "narrative"):
        if not event.get(field):
            errors.append(f"event.{field}: missing")
    if event.get("kind") and event["kind"] not in EVENT_KINDS:
        errors.append(f"event.kind: unknown kind {event['kind']!r}; valid kinds are {', '.join(EVENT_KINDS)}")
    if "houses" in event and not isinstance(event["houses"], list):
        errors.append("event.houses: must be a list")
    return event


def _check_operation(conn, index, op, known_houses, errors):
    """Validate one operation. `known_houses` is updated as houses are founded."""
    if not isinstance(op, dict):
        errors.append(f"operations[{index}]: not an object")
        return
    op_type = op.get("op")
    if op_type not in OPERATION_FIELDS:
        errors.append(
            f"operations[{index}]: unknown op {op_type!r};"
            f" valid ops are {', '.join(sorted(OPERATION_FIELDS))}"
        )
        return

    required, optional = OPERATION_FIELDS[op_type]
    for field in required:
        if op.get(field) is None:
            errors.append(f"operations[{index}] ({op_type}): missing required field {field!r}")
    for field in op:
        if field != "op" and field not in required and field not in optional:
            errors.append(f"operations[{index}] ({op_type}): unexpected field {field!r}")

    for field in HOUSE_FIELDS.get(op_type, ()):
        house = op.get(field)
        if house is not None and house not in known_houses:
            errors.append(f"operations[{index}] ({op_type}): unknown house {house!r}")

    if op_type == "elevate" and op.get("new_rank") is not None and op["new_rank"] not in RANK_LEVEL:
        errors.append(f"operations[{index}] (elevate): unknown rank {op['new_rank']!r}")

    if op_type == "climate_shift":
        if op.get("era_cohort") is not None and op["era_cohort"] not in ERA_COHORTS:
            errors.append(f"operations[{index}] (climate_shift): unknown era_cohort {op['era_cohort']!r}")
        if op.get("magnitude") is not None and op["magnitude"] not in CLIMATE_MAGNITUDES:
            errors.append(f"operations[{index}] (climate_shift): magnitude must be one of {CLIMATE_MAGNITUDES}")
        if op.get("tag") is not None and op["tag"] not in CLIMATE_TAGS:
            errors.append(f"operations[{index}] (climate_shift): tag must be one of {CLIMATE_TAGS}")
        if op.get("delta") is not None and not isinstance(op["delta"], int):
            errors.append(f"operations[{index}] (climate_shift): delta must be an integer")

    if op_type == "found_house":
        house = op.get("house")
        if house is not None and house in known_houses:
            errors.append(f"operations[{index}] (found_house): house {house!r} already exists")
        if op.get("rank") is not None and op["rank"] not in RANK_LEVEL:
            errors.append(f"operations[{index}] (found_house): unknown rank {op['rank']!r}")
        if op.get("tag") is not None and op["tag"] not in CLIMATE_TAGS:
            errors.append(f"operations[{index}] (found_house): tag must be one of {CLIMATE_TAGS}")
        for field in ("primary_hex", "secondary_hex"):
            value = op.get(field)
            if value is not None and not HEX_PATTERN.match(str(value)):
                errors.append(f"operations[{index}] (found_house): {field} must look like #RRGGBB")
        if house is not None:
            known_houses.add(house)

    if op_type == "adjust_stat":
        if op.get("stat") is not None and op["stat"] not in ADJUSTABLE_STATS:
            errors.append(
                f"operations[{index}] (adjust_stat): stat must be one of"
                f" {', '.join(ADJUSTABLE_STATS)}"
            )
        if op.get("delta") is not None and not isinstance(op["delta"], int):
            errors.append(f"operations[{index}] (adjust_stat): delta must be an integer")
        reason = op.get("reason")
        if reason is not None and not str(reason).strip():
            # Required-field checking above catches a missing reason; this catches
            # the one that is present and says nothing.
            errors.append(
                f"operations[{index}] (adjust_stat): reason must say why the stat was moved"
            )

    if op_type in ("set_objective", "veto_objective"):
        objective = op.get("objective")
        if objective is not None:
            from hoc.rules_data import load_rules

            known = {row.objective for row in load_rules().objectives}
            if objective not in known:
                errors.append(
                    f"operations[{index}] ({op_type}): unknown objective {objective!r};"
                    f" valid objectives are {', '.join(sorted(known))}"
                )

    if op_type == "force_action":
        action = op.get("action")
        if action is not None:
            from hoc.rules_data import load_rules

            known = {row.action for row in load_rules().actions}
            if action not in known:
                errors.append(
                    f"operations[{index}] (force_action): unknown action {action!r};"
                    f" valid actions are {', '.join(sorted(known))}"
                )

    if op_type == "grant_house":
        from hoc.rules_data import load_rules

        bundle = load_rules()
        community = op.get("community")
        if community is not None:
            known = {row.community for row in bundle.communities}
            if community not in known:
                errors.append(
                    f"operations[{index}] (grant_house): unknown community {community!r}"
                )
        if op.get("rank") is not None and op["rank"] not in RANK_LEVEL:
            errors.append(f"operations[{index}] (grant_house): unknown rank {op['rank']!r}")
        if op.get("tag") is not None and op["tag"] not in CLIMATE_TAGS:
            errors.append(f"operations[{index}] (grant_house): tag must be one of {CLIMATE_TAGS}")

    if op_type in ("expand", "release", "transfer", "found_house", "grant_house"):
        riding = op.get("riding")
        if riding is not None:
            from hoc.names import name_key

            row = conn.execute(
                "SELECT fed_id FROM ridings WHERE name_key = ?", (name_key(riding),)
            ).fetchone()
            if row is None:
                errors.append(f"operations[{index}] ({op_type}): unknown riding {riding!r}")


def validate(conn, data):
    """Check a turn file against the database. Returns a list of warnings and
    raises TurnFileError listing every problem found, rather than the first."""
    errors = []
    warnings = []

    if not data.get("directive"):
        errors.append("directive: missing")

    era_cohort = data.get("era_cohort")
    if era_cohort is not None and era_cohort not in ERA_COHORTS:
        errors.append(f"era_cohort: must be one of {ERA_COHORTS} or null, got {era_cohort!r}")

    event = _check_event(data, errors)

    narrative = event.get("narrative") or ""
    words = word_count(narrative)
    if words > NARRATIVE_MAX_WORDS:
        errors.append(f"event.narrative: {words} words exceeds the {NARRATIVE_MAX_WORDS}-word limit")
    elif words > NARRATIVE_WARN_WORDS:
        warnings.append(
            f"event.narrative: {words} words is over the {NARRATIVE_WARN_WORDS}-word warning"
            f" threshold (target is about {NARRATIVE_TARGET_WORDS})"
        )

    known_houses = _known_houses(conn)
    for house in event.get("houses") or []:
        if house not in known_houses:
            errors.append(
                f"event.houses: unknown house {house!r}."
                " A house created by a found_house operation must not be listed here —"
                " it does not exist when the event is recorded, and found_house links it itself."
            )

    operations = data.get("operations")
    if operations is None:
        operations = []
    if not isinstance(operations, list):
        errors.append("operations: must be a list")
        operations = []

    if not operations and event.get("kind") != KIND_ALLOWING_NO_OPERATIONS:
        errors.append(
            "operations: a turn must do something; only a housekeeping turn"
            f" (event.kind {KIND_ALLOWING_NO_OPERATIONS!r}) may have no operations"
        )

    founding_ops = [op for op in operations if isinstance(op, dict) and op.get("op") == "found_house"]
    if founding_ops and era_cohort is None:
        errors.append(
            "era_cohort: a turn containing found_house must state its era-cohort,"
            " because founding grants are evaluated for cohort fit against it (hard rule 6)"
        )

    for index, op in enumerate(operations):
        _check_operation(conn, index, op, known_houses, errors)

    watch = data.get("watch") or {}
    if not isinstance(watch, dict):
        errors.append("watch: must be an object with 'add' and/or 'discharge'")
    else:
        for field in watch:
            if field not in ("add", "discharge"):
                errors.append(f"watch: unexpected field {field!r}")
        if not isinstance(watch.get("add", []), list) or not isinstance(watch.get("discharge", []), list):
            errors.append("watch.add and watch.discharge must be lists")

    if not isinstance(data.get("threads") or [], list):
        errors.append("threads: must be a list")

    for field in data:
        if field not in ("directive", "era_cohort", "event", "operations", "watch", "threads"):
            errors.append(f"unexpected top-level field {field!r}")

    if errors:
        raise TurnFileError("turn file is not valid:\n  - " + "\n  - ".join(errors))
    return warnings
