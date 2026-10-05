"""Which game `hoc.db` currently holds.

A scenario is a directory under `scenarios/` with its own seed CSVs and its own
record of what has happened since — `turns/` for a director-written game,
`seasons/` for an engine-played one. `scenarios/current.txt` names the one the
database is built from, and every loader, rebuild and export reads it rather
than hard-coding a path.

    scenarios/
      current.txt          the active scenario's name, one line
      legacy/              the reconstructed 2026 playthrough, frozen
        scenario.json      name, title, status, reference_data, seed, started_season
        seed/*.csv         the audited reconstruction (CLAUDE.md hard rule: never edited outside a reconstruction commit)
        turns/NNNN_*.json  director-written turns
        RECONSTRUCTION.md  where the seed came from
      new/                 The First Dominion: an autoplay game, frozen at season 150
        scenario.json
        seed/*.csv         header rows only: the engine generates everything
        seasons/NNNN.json  one file per played season

`current.txt` says which scenario `hoc.db` holds. Whether a scenario may still be
written to is a different question, answered by its manifest's `status`: "live"
or "frozen" (a missing status reads as frozen). At most one scenario is live.
Every writer — the engine workflow, the play page, the console, `hoc sim` — asks
`live_name()` rather than naming a scenario, and `require_live` refuses a frozen
one.

Nothing here reads or writes the database; it only resolves paths and the small
scenario.json manifest.
"""

import json
from pathlib import Path

__all__ = [
    "ScenarioError",
    "SCENARIOS_DIR",
    "CURRENT_FILE",
    "current_name",
    "set_current",
    "scenario_names",
    "scenario_dir",
    "seed_dir",
    "turns_dir",
    "seasons_dir",
    "read_manifest",
    "write_manifest",
    "FrozenScenarioError",
    "STATUS_LIVE",
    "STATUS_FROZEN",
    "status",
    "title",
    "reference_data",
    "reference_dir",
    "reference_path",
    "reference_set_dir",
    "REFERENCE_SETS",
    "DEFAULT_REFERENCE_DATA",
    "is_live",
    "live_name",
    "frozen_names",
    "require_live",
    "blank_seed_dir",
    "frozen_paths",
]

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent
SCENARIOS_DIR = REPO_ROOT / "scenarios"
CURRENT_FILE = SCENARIOS_DIR / "current.txt"

DEFAULT_SCENARIO = "legacy"

STATUS_LIVE = "live"
STATUS_FROZEN = "frozen"

# The reference-data sets: the ground a game is played on. A scenario names the
# set its seed was built against in its manifest's `reference_data`, and every
# reader — the database loader, the engine's designation tables, the site map,
# the play page's assets — goes through reference_dir() rather than naming a
# directory.
#
#   ne-2026          the 2023 Representation Order tables built from Elections
#                    Canada's boundary file and Natural Earth (data/reference/).
#                    Both frozen games were played on it.
#   meridian-v1.0.3  the same 343 ridings and 894 land pairs, built from
#                    Meridian's riding unit table at tag v1.0.3, with census
#                    places, riding statistics and jurisdictions by year
#                    (scripts/build_world_meridian.py; CLAUDE.md, "World data").
#
# A set is never edited once a game has been played on it: moving to newer data
# is a new key and a new directory.
REFERENCE_SETS = {
    "ne-2026": Path("data") / "reference",
    "meridian-v1.0.3": Path("data") / "reference" / "meridian" / "v1.0.3",
}

# What a manifest with no `reference_data` was built against: the one set that
# existed before the key did.
DEFAULT_REFERENCE_DATA = "ne-2026"


class ScenarioError(Exception):
    """A scenario was named that does not exist, or is missing its parts."""


class FrozenScenarioError(ScenarioError):
    """A write was attempted on a scenario that is not live."""


def _scenarios_root(root=None):
    return SCENARIOS_DIR if root is None else Path(root)


def scenario_names(root=None):
    """Every scenario directory name, sorted."""
    base = _scenarios_root(root)
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())


def current_name(root=None):
    """The active scenario's name. Falls back to 'legacy' if current.txt is absent,
    so a checkout without the file still builds the reconstructed game."""
    base = _scenarios_root(root)
    path = base / "current.txt"
    if not path.exists():
        return DEFAULT_SCENARIO
    name = path.read_text(encoding="utf-8").strip()
    return name or DEFAULT_SCENARIO


def set_current(name, root=None):
    """Point current.txt at a scenario. Raises if it does not exist."""
    base = _scenarios_root(root)
    if not (base / name).is_dir():
        raise ScenarioError(
            f"unknown scenario {name!r}; available: {', '.join(scenario_names(root)) or 'none'}"
        )
    (base / "current.txt").write_text(f"{name}\n", encoding="utf-8")
    return name


def scenario_dir(name=None, root=None):
    base = _scenarios_root(root)
    name = name or current_name(root)
    path = base / name
    if not path.is_dir():
        raise ScenarioError(
            f"unknown scenario {name!r}; available: {', '.join(scenario_names(root)) or 'none'}"
        )
    return path


def seed_dir(name=None, root=None):
    return scenario_dir(name, root) / "seed"


def turns_dir(name=None, root=None):
    return scenario_dir(name, root) / "turns"


def seasons_dir(name=None, root=None):
    return scenario_dir(name, root) / "seasons"


def interventions_dir(name=None, root=None):
    """Where a director's intervention into an autoplay game is recorded.

    One file per season it follows — `interventions/0042.json` is applied after
    season 42 — carrying the same turn-file schema `hoc/turn.py` accepts. This
    is the single place an intervention lives for an engine-played game,
    whichever engine played it: the console writes here, and so does the browser
    when it saves (Phase 10-3). `turns/` remains the director-written game's
    record, and the reconstructed game's.
    """
    return scenario_dir(name, root) / "interventions"


def read_manifest(name=None, root=None):
    """The scenario.json manifest: {name, seed, started_season}. Missing file
    yields a manifest with the directory's name and nothing else recorded —
    an unstarted scenario has no seed yet, and that is not an error."""
    path = scenario_dir(name, root) / "scenario.json"
    if not path.exists():
        return {"name": name or current_name(root), "seed": None, "started_season": None}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_manifest(manifest, name=None, root=None):
    path = scenario_dir(name, root) / "scenario.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# ------------------------------------------------------------------ status --


def status(name=None, root=None):
    """"live" or "frozen". A manifest with no status reads as frozen: a game
    must be declared live to be written to, never the other way round."""
    value = read_manifest(name, root).get("status", STATUS_FROZEN)
    if value not in (STATUS_LIVE, STATUS_FROZEN):
        raise ScenarioError(
            f"scenario {name or current_name(root)!r} has status {value!r};"
            f" expected {STATUS_LIVE!r} or {STATUS_FROZEN!r}"
        )
    return value


def title(name=None, root=None):
    """The scenario's display title, or its directory name if it has none."""
    manifest = read_manifest(name, root)
    return manifest.get("title") or manifest.get("name") or name or current_name(root)


def reference_data(name=None, root=None):
    """The scenario's reference-data key. A manifest without one was built
    before the key existed, on the one set there was then."""
    return read_manifest(name, root).get("reference_data") or DEFAULT_REFERENCE_DATA


def reference_set_dir(key):
    """Where a reference-data set's tables are, relative to the repository."""
    if key not in REFERENCE_SETS:
        raise ScenarioError(
            f"unknown reference data {key!r}; known: {', '.join(sorted(REFERENCE_SETS))}"
        )
    return REFERENCE_SETS[key]


def reference_dir(name=None, root=None):
    """Where the scenario's reference tables are, relative to the repository."""
    key = reference_data(name, root)
    if key not in REFERENCE_SETS:
        raise ScenarioError(
            f"scenario {name or current_name(root)!r} names reference data {key!r};"
            f" known: {', '.join(sorted(REFERENCE_SETS))}"
        )
    return REFERENCE_SETS[key]


def reference_path(name=None, root=None):
    """reference_dir(), as an absolute path in this checkout."""
    return REPO_ROOT / reference_dir(name, root)


def is_live(name=None, root=None):
    return status(name, root) == STATUS_LIVE


def live_name(root=None):
    """The scenario that may be played, or None when every game is frozen.
    More than one live scenario is a configuration error: two games cannot both
    own the console, the play page and the referee."""
    live = [n for n in scenario_names(root) if is_live(n, root)]
    if len(live) > 1:
        raise ScenarioError(f"more than one live scenario: {', '.join(live)}")
    return live[0] if live else None


def frozen_names(root=None):
    return [n for n in scenario_names(root) if not is_live(n, root)]


def require_live(name=None, root=None):
    """The name of the scenario a writer may write to, or raise.

    With no `name` the writer wants whichever game is live; with one, it wants
    that game and is refused if it is frozen. Either way a writer also needs
    `hoc.db` to hold the game, since every writer plays on the database.
    """
    live = live_name(root)
    if name is None:
        if live is None:
            raise FrozenScenarioError(
                "there is no live scenario: every game is frozen."
                " Nothing can be played, applied or saved until one is made live."
            )
        name = live
    elif not is_live(name, root):
        raise FrozenScenarioError(
            f"scenario {name!r} ({title(name, root)}) is frozen and cannot be written to."
        )
    if current_name(root) != name:
        raise ScenarioError(
            f"scenario {name!r} is live but hoc.db holds {current_name(root)!r};"
            f" run `python -m hoc scenario use {name}` and rebuild first"
        )
    return name


def blank_seed_dir(root=None):
    """The seed directory of an autoplay scenario — header rows only, the engine
    generates everything — for tools that need an empty world and no particular game."""
    for name in scenario_names(root):
        if read_manifest(name, root).get("kind") == "autoplay":
            return seed_dir(name, root)
    raise ScenarioError("no autoplay scenario to take an empty seed from")


def frozen_paths(paths, root=None):
    """Of repository-relative `paths`, those that write to a frozen scenario's
    record or seed. Used by the referee to refuse a push that does."""
    frozen = set(frozen_names(root))
    out = []
    for path in paths:
        parts = Path(path).parts
        if (
            len(parts) >= 3 and parts[0] == "scenarios" and parts[1] in frozen
            and parts[2] in ("seasons", "interventions", "turns", "seed")
        ):
            out.append(path)
    return out
