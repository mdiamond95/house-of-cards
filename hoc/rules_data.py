"""Loader and validator for the Phase 9 rules tables under rules/.

This module only parses and validates; it does not run anything. The season
engine that reads a RulesBundle to actually play seasons is Phase 9c. Nothing
here is imported by the current (v1) turn runner or rules engine.
"""

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "RulesDataError",
    "Action",
    "Objective",
    "MortalityBand",
    "EraBand",
    "EventEffect",
    "Event",
    "Community",
    "Place",
    "GivenName",
    "Surname",
    "RulesBundle",
    "load_rules",
    "probability_for_age",
]

VALID_TARGET_RANGE = range(2, 13)  # 2..12 inclusive

# The scope vocabulary for events.direct_effect (§8), recorded in rules/README.md.
REGIONS = {"maritime", "quebec", "ontario", "prairie", "bc", "north", "newfoundland"}
TAGS = {"Conservative", "Progressive", "Mixed", "Outside"}
COMMUNITY_GROUPS = {"asian", "francophone", "metis", "female_line"}
VALID_SCOPES = {"all"} | REGIONS | TAGS | COMMUNITY_GROUPS


class RulesDataError(Exception):
    """A rules table failed to load or validate."""


@dataclass
class Action:
    action: str
    preconditions: str
    base_weight: str
    modifiers: str
    target: "int | str"  # an int 2-12, or the literal string "auto"
    success: str
    failure: str
    enclosure_bonus: str


@dataclass
class Objective:
    objective: str
    favoured_by: str
    satisfied_when: str
    action_weight_bonus: list = field(default_factory=list)


@dataclass
class MortalityBand:
    age_min: int
    age_max: int
    annual_probability: float
    note: str


@dataclass
class EraBand:
    name: str
    start_year: int
    end_year: "int | None"


@dataclass
class EventEffect:
    stat: str
    delta: "int | str"  # an int for capital/influence/cohesion, or "extra" for mortality
    scope: str


@dataclass
class Event:
    personal_year: int
    band: str
    name: str
    magnitude: str
    tag: str
    direct_effect: list
    note: str


@dataclass
class Community:
    region: str
    community: str
    weight: float
    naming_tradition: str
    note: str


@dataclass
class Place:
    province: str
    place: str


@dataclass
class GivenName:
    tradition: str
    gender: str
    name: str


@dataclass
class Surname:
    community: str
    surname: str


@dataclass
class RulesBundle:
    actions: list
    objectives: list
    mortality: list
    eras: list
    founding: dict
    succession: dict
    responses: dict
    events: list
    communities: list
    places: list
    given_names: list
    surnames: list


def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _parse_target(raw, action_name):
    if raw == "auto":
        return "auto"
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise RulesDataError(
            f"action {action_name!r}: target {raw!r} is neither an integer 2-12 nor 'auto'"
        )
    if value not in VALID_TARGET_RANGE:
        raise RulesDataError(
            f"action {action_name!r}: target {value} is out of range 2-12"
        )
    return value


def _load_actions(rules_dir):
    rows = _read_csv(rules_dir / "actions.csv")
    actions = []
    for row in rows:
        target = _parse_target(row["target"], row["action"])
        actions.append(
            Action(
                action=row["action"],
                preconditions=row["preconditions"],
                base_weight=row["base_weight"],
                modifiers=row["modifiers"],
                target=target,
                success=row["success"],
                failure=row["failure"],
                enclosure_bonus=row["enclosure_bonus"],
            )
        )
    return actions


def _load_objectives(rules_dir, action_names):
    rows = _read_csv(rules_dir / "objectives.csv")
    objectives = []
    for row in rows:
        raw = (row["action_weight_bonus"] or "").strip()
        names = [n.strip() for n in raw.split(";") if n.strip()] if raw else []
        for name in names:
            if name not in action_names:
                raise RulesDataError(
                    f"objective {row['objective']!r}: action_weight_bonus names"
                    f" unknown action {name!r}"
                )
        objectives.append(
            Objective(
                objective=row["objective"],
                favoured_by=row["favoured_by"],
                satisfied_when=row["satisfied_when"],
                action_weight_bonus=names,
            )
        )
    return objectives


def _load_mortality(rules_dir):
    rows = _read_csv(rules_dir / "mortality.csv")
    bands = [
        MortalityBand(
            age_min=int(row["age_min"]),
            age_max=int(row["age_max"]),
            annual_probability=float(row["annual_probability"]),
            note=row["note"],
        )
        for row in rows
    ]
    bands.sort(key=lambda b: b.age_min)

    if not bands or bands[0].age_min != 0:
        raise RulesDataError("mortality bands must start at age 0")
    for previous, current in zip(bands, bands[1:]):
        if current.age_min != previous.age_max + 1:
            raise RulesDataError(
                f"mortality bands are not contiguous: {previous.age_min}-{previous.age_max}"
                f" then {current.age_min}-{current.age_max}"
            )
    for band in bands:
        if not 0 <= band.annual_probability <= 1:
            raise RulesDataError(
                f"mortality band {band.age_min}-{band.age_max}: annual_probability"
                f" {band.annual_probability} is not within [0, 1]"
            )
    return bands


def _load_eras(rules_dir):
    data = _read_json(rules_dir / "eras.json")
    bands = [
        EraBand(name=b["name"], start_year=b["start_year"], end_year=b.get("end_year"))
        for b in data["bands"]
    ]
    bands.sort(key=lambda b: b.start_year)

    for previous, current in zip(bands, bands[1:]):
        if previous.end_year is None:
            raise RulesDataError(
                f"era band {previous.name!r} has no end_year but is not the last band"
            )
        if current.start_year != previous.end_year + 1:
            raise RulesDataError(
                f"era bands are not contiguous: {previous.name!r} ends {previous.end_year},"
                f" {current.name!r} starts {current.start_year}"
            )
    if bands[-1].end_year is not None:
        raise RulesDataError(f"the last era band ({bands[-1].name!r}) must be open-ended (end_year null)")
    return bands


def _check_probability(value, label):
    if not 0 <= value <= 1:
        raise RulesDataError(f"{label}: {value} is not a probability within [0, 1]")


def _load_founding(rules_dir):
    data = _read_json(rules_dir / "founding.json")
    _check_probability(data["p_found"]["season_loop_default"]["value"], "founding.p_found.season_loop_default.value")
    for rank, probability in data["rank_probabilities"].items():
        _check_probability(probability, f"founding.rank_probabilities.{rank}")
    return data


def _load_succession(rules_dir):
    data = _read_json(rules_dir / "succession.json")
    _check_probability(
        data["losing_ridings"]["disorderly_succession"]["probability"],
        "succession.losing_ridings.disorderly_succession.probability",
    )
    return data


def _load_responses(rules_dir):
    return _read_json(rules_dir / "responses.json")


def _parse_direct_effect(raw, event_name):
    raw = (raw or "").strip()
    if not raw:
        return []
    effects = []
    for triple in raw.split(";"):
        parts = triple.split(":")
        if len(parts) != 3:
            raise RulesDataError(
                f"event {event_name!r}: direct_effect segment {triple!r} is not"
                " a stat:delta:scope triple"
            )
        stat, delta, scope = parts
        if scope not in VALID_SCOPES:
            raise RulesDataError(
                f"event {event_name!r}: direct_effect scope {scope!r} is not in"
                " the valid vocabulary (all, a region, a tag, or a community group)"
            )
        if stat == "mortality":
            if delta != "extra":
                raise RulesDataError(
                    f"event {event_name!r}: mortality effect delta must be"
                    f" 'extra', got {delta!r}"
                )
        else:
            try:
                delta = int(delta)
            except ValueError:
                raise RulesDataError(
                    f"event {event_name!r}: direct_effect delta {delta!r} for"
                    f" stat {stat!r} is not an integer"
                )
        effects.append(EventEffect(stat=stat, delta=delta, scope=scope))
    return effects


def _load_events(rules_dir):
    rows = _read_csv(rules_dir / "events.csv")
    events = []
    for row in rows:
        events.append(
            Event(
                personal_year=int(row["personal_year"]),
                band=row["band"],
                name=row["name"],
                magnitude=row["magnitude"],
                tag=row["tag"],
                direct_effect=_parse_direct_effect(row["direct_effect"], row["name"]),
                note=row["note"],
            )
        )
    return events


def _load_communities(rules_dir):
    rows = _read_csv(rules_dir / "communities.csv")
    return [
        Community(
            region=row["region"],
            community=row["community"],
            weight=float(row["weight"]),
            naming_tradition=row["naming_tradition"],
            note=row["note"],
        )
        for row in rows
    ]


def _load_places(rules_dir):
    rows = _read_csv(rules_dir / "places.csv")
    return [Place(province=row["province"], place=row["place"]) for row in rows]


def _load_given_names(rules_dir):
    rows = _read_csv(rules_dir / "given_names.csv")
    return [
        GivenName(tradition=row["tradition"], gender=row["gender"], name=row["name"])
        for row in rows
    ]


def _load_surnames(rules_dir):
    rows = _read_csv(rules_dir / "surnames.csv")
    return [Surname(community=row["community"], surname=row["surname"]) for row in rows]


def probability_for_age(mortality, age):
    """The annual death probability for a holder of the given age, from a
    loaded mortality table (RulesBundle.mortality)."""
    for band in mortality:
        if band.age_min <= age <= band.age_max:
            return band.annual_probability
    raise RulesDataError(f"no mortality band covers age {age}")


def load_rules(path="rules"):
    """Load and validate every rules table. Raises RulesDataError on any
    violation, naming the table and the specific problem."""
    rules_dir = Path(path)

    actions = _load_actions(rules_dir)
    action_names = {a.action for a in actions}
    objectives = _load_objectives(rules_dir, action_names)
    mortality = _load_mortality(rules_dir)
    eras = _load_eras(rules_dir)
    founding = _load_founding(rules_dir)
    succession = _load_succession(rules_dir)
    responses = _load_responses(rules_dir)
    events = _load_events(rules_dir)
    communities = _load_communities(rules_dir)
    places = _load_places(rules_dir)
    given_names = _load_given_names(rules_dir)
    surnames = _load_surnames(rules_dir)

    return RulesBundle(
        actions=actions,
        objectives=objectives,
        mortality=mortality,
        eras=eras,
        founding=founding,
        succession=succession,
        responses=responses,
        events=events,
        communities=communities,
        places=places,
        given_names=given_names,
        surnames=surnames,
    )
