"""Which game `hoc.db` currently holds.

A scenario is a directory under `scenarios/` with its own seed CSVs and its own
record of what has happened since — `turns/` for a director-written game,
`seasons/` for an engine-played one. `scenarios/current.txt` names the one the
database is built from, and every loader, rebuild and export reads it rather
than hard-coding a path.

    scenarios/
      current.txt          the active scenario's name, one line
      legacy/              the reconstructed 2026 playthrough, frozen
        scenario.json      name, seed, started_season
        seed/*.csv         the audited reconstruction (CLAUDE.md hard rule: never edited outside a reconstruction commit)
        turns/NNNN_*.json  director-written turns
        RECONSTRUCTION.md  where the seed came from
      new/                 the live autoplay game
        scenario.json
        seed/*.csv         header rows only: the engine generates everything
        seasons/NNNN.json  one file per played season

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
]

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent
SCENARIOS_DIR = REPO_ROOT / "scenarios"
CURRENT_FILE = SCENARIOS_DIR / "current.txt"

DEFAULT_SCENARIO = "legacy"


class ScenarioError(Exception):
    """A scenario was named that does not exist, or is missing its parts."""


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
