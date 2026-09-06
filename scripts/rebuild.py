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

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hoc import db, scenario  # noqa: E402  (after sys.path setup)
from hoc.export import dump, map as map_export, site, workbook  # noqa: E402
from hoc.turn import TurnError, apply_turn  # noqa: E402

import build_archive  # noqa: E402  (same directory; imported after sys.path setup)
import load_seed  # noqa: E402


# A director's intervention is applied between two seasons, so replaying it in
# the wrong place would change every season after it. The season it follows is
# in its filename — 0003_s0042-adjust-cashin.json follows season 42 — and a turn
# file without that marker belongs to a director-written game, which has no
# seasons to interleave with and replays first.
INTERVENTION_SEASON = re.compile(r"^\d{4}_s(\d{4})-")


def turn_files(name=None):
    directory = scenario.turns_dir(name)
    if not directory.is_dir():
        return []
    return sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.json"))


def turn_after_season(path):
    """The season a turn file follows, or None if it is not an intervention."""
    match = INTERVENTION_SEASON.match(path.name)
    return int(match.group(1)) if match else None


def season_number(path):
    return int(path.stem)


def season_files(name=None):
    directory = scenario.seasons_dir(name)
    if not directory.is_dir():
        return []
    return sorted(directory.glob("[0-9][0-9][0-9][0-9].json"))


def replay_turns(conn, name=None, verbose=True, paths=None):
    for path in turn_files(name) if paths is None else paths:
        try:
            summary = apply_turn(conn, path)
        except TurnError as exc:
            where = "" if exc.operation_index is None else f" (operation {exc.operation_index})"
            raise SystemExit(f"replay failed at {path.name}{where}: {exc.reason}") from exc
        if verbose:
            print(f"  replayed {path.name} -> event {summary['event_id']}, holdings {summary['holdings']}")


def replay_seasons(conn, name=None, verbose=True, interventions=()):
    """Replay an autoplay scenario's season logs, interleaving interventions.

    The engine is deterministic from (world seed, season number), so replay
    re-runs the season loop rather than re-applying recorded deltas; the logs
    are the audit trail that the replay must reproduce. An intervention changes
    the state the next season starts from, so it has to go back in at the point
    it was applied.
    """
    paths = season_files(name)
    if not paths:
        return
    from hoc import sim  # imported here so a turn-only rebuild needs no engine

    pending = sorted(interventions, key=lambda item: (item[0], item[1].name))

    # The engine never commits — the caller owns the transaction, exactly as the
    # turn runner does — so the replay has to be wrapped or it rolls back on close.
    with conn:
        world = None
        for path in paths:
            season = season_number(path)
            while pending and pending[0][0] < season:
                _, turn_path = pending.pop(0)
                replay_turns(conn, name, verbose=verbose, paths=[turn_path])
            world = sim.World.replay(conn, [path], seasons_dir=scenario.seasons_dir(name),
                                     world=world)
        for _, turn_path in pending:
            replay_turns(conn, name, verbose=verbose, paths=[turn_path])

    if verbose and world is not None:
        print(f"  replayed {len(paths)} season(s) -> season {world.season_no}")


def rebuild(db_path, export=True, name=None, verbose=True):
    """Load the seed, replay the scenario's record, optionally export."""
    conn = load_seed.build(db_path, seed=scenario.seed_dir(name))

    plain, interventions = [], []
    for path in turn_files(name):
        after = turn_after_season(path)
        (interventions if after is not None else plain).append(
            (after, path) if after is not None else path
        )

    replay_turns(conn, name, verbose=verbose, paths=plain)
    replay_seasons(conn, name, verbose=verbose, interventions=interventions)

    if export:
        dump.write_dump(conn)
        workbook.write_workbook(conn)
        map_export.write_maps(conn)
        site.write_site(conn)
        build_archive.build_archive()
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
