"""Rebuild hoc.db from the reproducible record: seed CSVs plus turn files.

    python scripts/rebuild.py [db_path]

The seed and `turns/*.json` are the record; `hoc.db` is a convenience copy of
what they produce. This script loads the seed, replays every turn in filename
order — which is turn-id order — and exports, so the database can always be
reconstructed from the files under version control.

Exporting is skipped when a database path other than the default is given, so a
test rebuild does not overwrite the committed outputs/.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hoc import db  # noqa: E402  (after sys.path setup)
from hoc.export import dump, map as map_export, workbook  # noqa: E402
from hoc.turn import TurnError, apply_turn  # noqa: E402

TURNS_DIR = ROOT / "turns"

import load_seed  # noqa: E402  (same directory; imported after sys.path setup)


def turn_files():
    return sorted(TURNS_DIR.glob("[0-9][0-9][0-9][0-9]_*.json"))


def rebuild(db_path, export=True):
    """Load the seed, replay every turn, optionally export. Returns the connection."""
    conn = load_seed.build(db_path)

    for path in turn_files():
        try:
            summary = apply_turn(conn, path)
        except TurnError as exc:
            where = "" if exc.operation_index is None else f" (operation {exc.operation_index})"
            raise SystemExit(f"replay failed at {path.name}{where}: {exc.reason}") from exc
        print(f"  replayed {path.name} -> event {summary['event_id']}, holdings {summary['holdings']}")

    if export:
        dump.write_dump(conn)
        workbook.write_workbook(conn)
        map_export.write_maps(conn)
    return conn


def main():
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else db.DEFAULT_DB_PATH
    export = db_path == db.DEFAULT_DB_PATH
    conn = rebuild(db_path, export=export)

    turns = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
    holdings = conn.execute(
        "SELECT COUNT(*) FROM holdings WHERE released_event_id IS NULL"
    ).fetchone()[0]
    print(f"rebuilt {db_path}: {turns} turn(s) replayed, {holdings} current holdings")
    if export:
        print("outputs/ regenerated")
    conn.close()


if __name__ == "__main__":
    main()
