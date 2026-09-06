"""Render the frozen legacy playthrough into outputs/site/archive/.

    python scripts/build_archive.py [out_dir]

The archive is not a copy of anything: it is the legacy scenario built fresh
into a temporary database and rendered by the same exporter that renders the
live game, one directory deeper and in archive mode. Doing it that way means the
two can never drift — a change to the site is a change to both, and the archive
is rebuilt on every export rather than kept as a stale artefact.

The temporary database is thrown away afterwards. `hoc.db` holds the live game
and is never touched here.
"""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hoc import scenario  # noqa: E402  (after sys.path setup)
from hoc.export import site  # noqa: E402
from hoc.turn import TurnError, apply_turn  # noqa: E402

import load_seed  # noqa: E402

ARCHIVE_SCENARIO = "legacy"


def build_archive(out_dir=site.DEFAULT_OUT_DIR, name=ARCHIVE_SCENARIO, verbose=False):
    """Build `name` into a temporary database and render it as the archive.

    Returns the paths written.
    """
    with tempfile.TemporaryDirectory(prefix="hoc-archive-") as workspace:
        db_path = Path(workspace) / "archive.db"
        conn = load_seed.build(db_path, seed=scenario.seed_dir(name))

        turns_dir = scenario.turns_dir(name)
        if turns_dir.is_dir():
            for path in sorted(turns_dir.glob("[0-9][0-9][0-9][0-9]_*.json")):
                try:
                    apply_turn(conn, path)
                except TurnError as exc:
                    where = "" if exc.operation_index is None else f" (operation {exc.operation_index})"
                    raise SystemExit(
                        f"archive build failed at {path.name}{where}: {exc.reason}"
                    ) from exc

        written = site.write_site(
            conn,
            out_dir=out_dir,
            subdir=f"{site.SITE_DIRNAME}/{site.ARCHIVE_DIRNAME}",
            archive=True,
        )
        conn.close()

    if verbose:
        print(f"archive: {len(written)} files from scenario {name!r}")
    return written


def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else site.DEFAULT_OUT_DIR
    written = build_archive(out_dir, verbose=True)
    print(f"wrote {Path(out_dir) / site.SITE_DIRNAME / site.ARCHIVE_DIRNAME}")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
