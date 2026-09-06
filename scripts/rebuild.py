"""Rebuild hoc.db from the reproducible record of the active scenario.

    python scripts/rebuild.py [db_path]

The seed CSVs plus the scenario's record are what is under version control;
`hoc.db` is a convenience copy of what they produce. A director-written scenario
records itself in `turns/*.json` and is replayed by the turn runner; an autoplay
scenario records itself in `seasons/NNNN.json` and is replayed by the engine.
This script loads the seed, replays whichever record the scenario has, and
exports, so the database can always be reconstructed from files.

Exporting is skipped when a database path other than the default is given, so a
test rebuild does not overwrite the committed outputs/.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hoc import db, scenario  # noqa: E402  (after sys.path setup)
from hoc.export import dump, map as map_export, site, workbook  # noqa: E402
from hoc.turn import TurnError, apply_turn  # noqa: E402

import load_seed  # noqa: E402  (same directory; imported after sys.path setup)


def turn_files(name=None):
    directory = scenario.turns_dir(name)
    if not directory.is_dir():
        return []
    return sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.json"))


def season_files(name=None):
    directory = scenario.seasons_dir(name)
    if not directory.is_dir():
        return []
    return sorted(directory.glob("[0-9][0-9][0-9][0-9].json"))


def replay_turns(conn, name=None, verbose=True):
    for path in turn_files(name):
        try:
            summary = apply_turn(conn, path)
        except TurnError as exc:
            where = "" if exc.operation_index is None else f" (operation {exc.operation_index})"
            raise SystemExit(f"replay failed at {path.name}{where}: {exc.reason}") from exc
        if verbose:
            print(f"  replayed {path.name} -> event {summary['event_id']}, holdings {summary['holdings']}")


def replay_seasons(conn, name=None, verbose=True):
    """Replay an autoplay scenario's season logs.

    The engine is deterministic from (world seed, season number), so replay
    re-runs the season loop rather than re-applying recorded deltas; the logs
    are the audit trail that the replay must reproduce.
    """
    paths = season_files(name)
    if not paths:
        return
    from hoc import sim  # imported here so a turn-only rebuild needs no engine

    world = sim.World.replay(conn, paths)
    if verbose:
        print(f"  replayed {len(paths)} season(s) -> season {world.season_no}")


def rebuild(db_path, export=True, name=None, verbose=True):
    """Load the seed, replay the scenario's record, optionally export."""
    conn = load_seed.build(db_path, seed=scenario.seed_dir(name))
    replay_turns(conn, name, verbose=verbose)
    replay_seasons(conn, name, verbose=verbose)

    if export:
        dump.write_dump(conn)
        workbook.write_workbook(conn)
        map_export.write_maps(conn)
        site.write_site(conn)
    return conn


def main():
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else db.DEFAULT_DB_PATH
    export = db_path == db.DEFAULT_DB_PATH
    name = scenario.current_name()
    print(f"rebuilding scenario {name!r}")
    conn = rebuild(db_path, export=export, name=name)

    turns = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
    seasons = conn.execute("SELECT COUNT(*) FROM seasons").fetchone()[0]
    holdings = conn.execute(
        "SELECT COUNT(*) FROM holdings WHERE released_event_id IS NULL"
    ).fetchone()[0]
    print(
        f"rebuilt {db_path}: {turns} turn(s), {seasons} season(s) replayed,"
        f" {holdings} current holdings"
    )
    if export:
        print("outputs/ regenerated")
    conn.close()


if __name__ == "__main__":
    main()
