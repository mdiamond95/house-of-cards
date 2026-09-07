"""Loader and validator for the rules tables under rules/versions/<version>/.

This module only parses and validates; it does not run anything.

**Rules are versioned, and a season is always replayed under the rules it was
played with.** `rules/current.txt` names the version a *new* season is played
under; every season file records the version it was played under, and a replay
reads that. Without this, tuning a table would silently rewrite history — the
committed record would stop reproducing the committed database, and the
referee would start refusing seasons that were correct when they were played.

The consequence for anyone changing the rules is in rules/README.md and is
short: never edit a published version's tables. Copy the directory, change the
copy, point current.txt at it. A change in *algorithm* rather than in a number
goes behind a named boolean in that version's features.json, false in every
version that came before it, so the old code path stays reachable for replay.
"""

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "RulesDataError",
    "RULES_ROOT",
    "VERSIONS_DIR",
    "CURRENT_FILE",
    "current_version",
    "available_versions",
    "version_dir",
    "load_features",
    "FEATURE_DEFAULTS",
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


RULES_ROOT = Path(__file__).resolve().parent.parent / "rules"
VERSIONS_DIR = RULES_ROOT / "versions"
CURRENT_FILE = RULES_ROOT / "current.txt"

# Every behaviour flag the engines know about, and what a version that does not
# mention it means. Every default is False: a version's features.json is read as
# "what this version turns on", so a rules directory written before a flag
# existed keeps the behaviour it was played with. A flag added here with a True
# default would change the past, which is the one thing this whole arrangement
# exists to prevent.
FEATURE_DEFAULTS = {
    # rules 0.8. Territorial designations are drawn from places inside the seat
    # riding, then its own name, then its neighbours, before falling back to the
    # province bank. False in 0.7, which drew from the province bank alone.
    "local_designations": False,
    # rules 0.8. A season with no chronicle at all says so, and a house idle for
    # ten seasons is noticed once. False in 0.7, which left both silent.
    "quiet_season_line": False,
}


def current_version(root=None):
    """The version a new season is played under."""
    path = (Path(root) / "current.txt") if root else CURRENT_FILE
    if not path.exists():
        raise RulesDataError(
            f"{path} is missing: it names the rules version new seasons are played"
            " under, and without it the engine does not know which rules are current"
        )
    version = path.read_text(encoding="utf-8").strip()
    if not version:
        raise RulesDataError(f"{path} is empty; it must name a rules version")
    return version


def available_versions(root=None):
    base = (Path(root) / "versions") if root else VERSIONS_DIR
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())


def version_dir(version, root=None):
    """The directory holding one version's tables, checked to exist.

    A season file naming a version this checkout does not have is not something
    to guess about: replaying it under some other version would produce a
    different game and call it the same one.
    """
    base = (Path(root) / "versions") if root else VERSIONS_DIR
    path = base / str(version)
    if not path.is_dir():
        raise RulesDataError(
            f"unknown rules version {version!r}: {path} does not exist."
            f" Available: {', '.join(available_versions(root)) or 'none'}."
            " A season recorded under a version this checkout does not have cannot"
            " be replayed; it must not be replayed under a different one."
        )
    return path


def load_features(version=None, root=None):
    """One version's behaviour flags, defaulted for anything it does not name."""
    directory = version_dir(version or current_version(root), root)
    path = directory / "features.json"
    features = dict(FEATURE_DEFAULTS)
    if not path.exists():
        return features
    with open(path, encoding="utf-8") as f:
        declared = json.load(f)
    if not isinstance(declared, dict):
        raise RulesDataError(f"{path} must hold an object of named booleans")
    unknown = set(declared) - set(FEATURE_DEFAULTS)
    if unknown:
        raise RulesDataError(
            f"{path} names feature(s) the engine does not know: {', '.join(sorted(unknown))}."
            " Add them to rules_data.FEATURE_DEFAULTS (defaulting to False) first."
        )
    for name, value in declared.items():
        if not isinstance(value, bool):
            raise RulesDataError(f"{path}: feature {name!r} must be true or false")
        features[name] = value
    return features


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
    # An integer per cent (rules 0.7). Every probability the engine rolls
    # against is an integer, so both engines roll it the same way: see
    # docs/DETERMINISM.md.
    annual_probability_pct: int
    note: str


@dataclass
class EraBand:
    id: str
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
    # An integer draw weight (rules 0.7), never a float.
    weight: int
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
    friction: dict
    events: list
    communities: list
    places: list
    given_names: list
    surnames: list
    # Which version's tables these are, and which behaviour that version turns
    # on. Carried on the bundle so nothing downstream has to ask a second time
    # and risk asking about a different version than the one it is holding.
    version: str = ""
    features: dict = field(default_factory=dict)

    def feature(self, name):
        """Whether this version turns on a named behaviour."""
        if name not in FEATURE_DEFAULTS:
            raise RulesDataError(f"no such rules feature {name!r}")
        return bool(self.features.get(name, FEATURE_DEFAULTS[name]))


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
            annual_probability_pct=int(row["annual_probability_pct"]),
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
        if not 0 <= band.annual_probability_pct <= 100:
            raise RulesDataError(
                f"mortality band {band.age_min}-{band.age_max}: annual_probability_pct"
                f" {band.annual_probability_pct} is not a per cent within [0, 100]"
            )
    return bands


def _load_eras(rules_dir):
    data = _read_json(rules_dir / "eras.json")
    bands = [
        EraBand(
            id=b["id"],
            name=b["name"],
            start_year=b["start_year"],
            end_year=b.get("end_year"),
        )
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


def _check_percent(value, label):
    """Every probability in rules/ is an integer per cent (rules 0.7)."""
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
        raise RulesDataError(f"{label}: {value!r} is not an integer per cent within [0, 100]")


def _check_weight(value, label):
    """Draw weights are non-negative integers, so the cumulative scan in
    hoc.prng.Prng.weighted_choice never touches a float."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RulesDataError(f"{label}: {value!r} is not a non-negative integer weight")


def _load_founding(rules_dir):
    data = _read_json(rules_dir / "founding.json")
    if "formula" not in data["p_found"]:
        raise RulesDataError("founding.p_found has no formula")
    for rank, weight in data["rank_probabilities"].items():
        _check_weight(weight, f"founding.rank_probabilities.{rank}")
    for region, weight in data["region_weights"]["initial"].items():
        _check_weight(weight, f"founding.region_weights.initial.{region}")
    return data


def _load_succession(rules_dir):
    data = _read_json(rules_dir / "succession.json")
    _check_percent(
        data["losing_ridings"]["disorderly_succession"]["probability_pct"],
        "succession.losing_ridings.disorderly_succession.probability_pct",
    )
    _check_percent(
        data["disorderly_succession"]["sig_minus_probability_pct"],
        "succession.disorderly_succession.sig_minus_probability_pct",
    )
    return data


def _load_responses(rules_dir):
    return _read_json(rules_dir / "responses.json")


def _load_friction(rules_dir):
    """Per-pair friction (rules 0.6). Validated for the one thing that would be
    silently wrong: a threshold outside the stated range."""
    data = _read_json(rules_dir / "friction.json")
    low, high = data["range"]
    threshold = data["flashpoint"]["threshold"]
    if not low <= threshold <= high:
        raise RulesDataError(
            f"friction.flashpoint.threshold {threshold} is outside the range {low}-{high}"
        )
    if not low <= data["flashpoint"]["resets_to"] <= high:
        raise RulesDataError("friction.flashpoint.resets_to is outside the range")
    return data


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
            weight=int(row["weight"]),
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
    """The annual death chance for a holder of the given age, as an integer per
    cent, from a loaded mortality table (RulesBundle.mortality)."""
    for band in mortality:
        if band.age_min <= age <= band.age_max:
            return band.annual_probability_pct
    raise RulesDataError(f"no mortality band covers age {age}")


def load_rules(path=None, version=None, root=None):
    """Load and validate one version's rules tables.

    `version` names the version to load, defaulting to `rules/current.txt`.
    `path` loads a directory of tables directly and is for tests and tools that
    build a rules directory of their own; it bypasses the version machinery, so
    the engine never uses it.

    Raises RulesDataError on any violation, naming the table and the problem.
    """
    if path is not None:
        rules_dir = Path(path)
        features = dict(FEATURE_DEFAULTS)
        features_path = rules_dir / "features.json"
        if features_path.exists():
            with open(features_path, encoding="utf-8") as f:
                features.update(json.load(f))
        version = version or ""
    else:
        version = version or current_version(root)
        rules_dir = version_dir(version, root)
        features = load_features(version, root)

    actions = _load_actions(rules_dir)
    action_names = {a.action for a in actions}
    objectives = _load_objectives(rules_dir, action_names)
    mortality = _load_mortality(rules_dir)
    eras = _load_eras(rules_dir)
    founding = _load_founding(rules_dir)
    succession = _load_succession(rules_dir)
    responses = _load_responses(rules_dir)
    friction = _load_friction(rules_dir)
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
        friction=friction,
        events=events,
        communities=communities,
        places=places,
        given_names=given_names,
        surnames=surnames,
        version=version,
        features=features,
    )
