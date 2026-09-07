"""The play page: the live game, played in the browser.

Phase 10-2. `outputs/site/play.html` loads the JavaScript engine
(`web/engine/`, copied to `outputs/site/engine/` on export), the rules tables
and the reference map (copied to `outputs/site/data/`), and the world snapshot
(`outputs/site/data/world.json`), and then plays the committed game forward with
no network round-trip per season.

**Play here is local to the browser and is not saved anywhere.** Persistence to
the repository is Phase 10-3; until it lands, the page says so in a banner that
counts the unsaved seasons, and autosaves to IndexedDB only so that closing a
tab does not throw the afternoon away. The console's GitHub-Actions path remains
the only way a season reaches `main`.

The page is built from the same inline SVG the index page uses — the same
projected geometry, the same viewBox pair for the north/south toggle — because
duplicating a third of a megabyte of coastline to have two copies of the same
map would be the single most expensive thing this page could do.
"""

import json
import shutil
from pathlib import Path

from hoc import rules_data
from hoc.export import world as world_export

__all__ = [
    "write_play_assets", "ENGINE_MODULES", "ENGINE_TOOLS", "RULES_FILES", "REFERENCE_FILES",
]

# The engine's own modules. Copied rather than imported across directories so
# that Pages serves them from the site root and the page needs no build step.
ENGINE_MODULES = (
    "prng.js", "csv.js", "palette.js", "names.js", "rules.js",
    "adjacency.js", "state.js", "sim.js", "index.js", "record.js",
)

# Not imported by the page: `playtest.js` is the headless run of the page's own
# path through the engine (tests/test_site.py). It is copied so that it loads
# the *exported* modules — an export that forgot one fails the test rather than
# surprising someone's browser.
ENGINE_TOOLS = ("playtest.js",)

# Exactly the rules tables `web/engine/rules.js` reads, per version. Listed
# rather than globbed: a file that appears in a rules version and is not read by
# the engine is a file the browser should not be made to download.
RULES_FILES = (
    "actions.csv", "communities.csv", "denylist.csv", "events.csv",
    "given_names.csv", "mortality.csv", "objectives.csv", "places.csv",
    "surnames.csv", "eras.json", "founding.json", "friction.json",
    "responses.json", "succession.json", "features.json",
)

# The reference tables `web/engine/adjacency.js` reads. places_by_riding and
# riding_tokens joined them at rules 0.8, for the designation draw.
REFERENCE_FILES = (
    "ridings.csv", "adjacency.csv", "places_by_riding.csv", "riding_tokens.csv",
)


def write_play_assets(conn, site_dir, repo_root):
    """Copy the engine, its tables and the world snapshot into the site.

    Returns (paths written, total bytes) so the exporter can report the page's
    download weight — the number that decides whether this page is usable on a
    phone.
    """
    site_dir = Path(site_dir)
    engine_dir = site_dir / "engine"
    rules_dir = site_dir / "data" / "rules"
    reference_dir = site_dir / "data" / "reference"
    for directory in (engine_dir, rules_dir, reference_dir):
        directory.mkdir(parents=True, exist_ok=True)

    written = []
    for name in ENGINE_MODULES + ENGINE_TOOLS:
        source = Path(repo_root) / "web" / "engine" / name
        target = engine_dir / name
        shutil.copyfile(source, target)
        written.append(target)
    # Every version, not just the current one. A version is 80 KB, the page
    # plays under whichever `current.txt` names, and a browser holding a world
    # last played under an older version has to be able to read that version's
    # tables rather than guess. Shipping them all costs less than shipping the
    # wrong one.
    versions = rules_data.available_versions()
    current = rules_data.current_version()
    (rules_dir / "current.txt").write_text(f"{current}\n", encoding="utf-8")
    written.append(rules_dir / "current.txt")
    versions_dir = rules_dir / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)
    for version in versions:
        version_dir = versions_dir / version
        version_dir.mkdir(parents=True, exist_ok=True)
        source_dir = rules_data.version_dir(version)
        for name in RULES_FILES:
            source = source_dir / name
            if not source.exists():
                continue  # a version predating a table is not an error
            target = version_dir / name
            shutil.copyfile(source, target)
            written.append(target)
    for name in REFERENCE_FILES:
        target = reference_dir / name
        shutil.copyfile(Path(repo_root) / "data" / "reference" / name, target)
        written.append(target)

    world_path, _ = world_export.write_world(conn, site_dir / "data")
    written.append(world_path)

    # Sweep engine modules from an earlier export that no longer exist, the way
    # write_site sweeps stale house pages: a module left behind is a module the
    # browser could still import.
    live = set(ENGINE_MODULES) | set(ENGINE_TOOLS)
    for stale in engine_dir.glob("*.js"):
        if stale.name not in live:
            stale.unlink()

    # Likewise for a rules version removed from the repository, and for the flat
    # layout this replaced — a table left at data/rules/actions.csv would be
    # loadable and would belong to no version at all.
    for stale in versions_dir.iterdir():
        if stale.is_dir() and stale.name not in versions:
            shutil.rmtree(stale)
    for stale in rules_dir.iterdir():
        # The flat layout this replaced: a table left at data/rules/actions.csv
        # would still be loadable and would belong to no version at all.
        if stale.is_file() and stale.name != "current.txt":
            stale.unlink()

    return written, sum(path.stat().st_size for path in written)
