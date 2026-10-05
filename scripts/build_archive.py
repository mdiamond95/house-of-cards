"""Render every frozen scenario into outputs/site/archive/.

    python scripts/build_archive.py [out_dir]

    outputs/site/archive/index.html       lists the frozen games
    outputs/site/archive/<name>/...       one full site per frozen scenario

The archive is not a copy of anything: each frozen scenario is built fresh into
a temporary database from its seed and its record — `turns/` for a
director-written game, `seasons/` (and `interventions/`) for an engine-played
one — and rendered by the same exporter that renders the live game, two
directories deeper and in archive mode. Doing it that way means the two can
never drift: a change to the site is a change to both, and the archive is
rebuilt on every export rather than kept as a stale artefact.

Which scenarios are archived is read from the manifests (`status`), never named
here. The temporary databases are thrown away afterwards, and the season files
a replay writes go to the scratch directory, never over the committed record.
`hoc.db` holds the current game and is never touched here.
"""

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hoc import scenario  # noqa: E402  (after sys.path setup)
from hoc.export import site  # noqa: E402


def _summary(conn, name):
    """What the archive's index says about a game, read from its own database."""
    season = conn.execute("SELECT MAX(season_no) AS n FROM seasons").fetchone()["n"]
    turns = conn.execute("SELECT COUNT(*) AS n FROM turns").fetchone()["n"]
    return {
        "name": name,
        "title": scenario.title(name),
        "kind": scenario.read_manifest(name).get("kind"),
        "seed": scenario.read_manifest(name).get("seed"),
        "seasons": season,
        "turns": turns,
        "active": conn.execute(
            "SELECT COUNT(*) AS n FROM houses WHERE status = 'active'"
        ).fetchone()["n"],
        "removed": conn.execute(
            "SELECT COUNT(*) AS n FROM houses WHERE status != 'active'"
        ).fetchone()["n"],
        "held": conn.execute(
            "SELECT COUNT(*) AS n FROM holdings WHERE released_event_id IS NULL"
        ).fetchone()["n"],
    }


def build_archive(out_dir=site.DEFAULT_OUT_DIR, name=None, verbose=False):
    """Render `name` (default: every frozen scenario) and the archive's index.

    Returns the paths written. Refuses a scenario that is live: a game still
    being played is not an archive.
    """
    import rebuild  # here, not at the top: rebuild.py imports this module for its export

    names = [name] if name else scenario.frozen_names()
    for each in names:
        if scenario.is_live(each):
            raise SystemExit(f"scenario {each!r} is live; only a frozen game is archived")

    archive_dir = Path(out_dir) / site.SITE_DIRNAME / site.ARCHIVE_DIRNAME
    if name is None:
        # The whole archive is generated; clearing it is what keeps a layout
        # from an earlier export (or a game since made live) from lingering.
        shutil.rmtree(archive_dir, ignore_errors=True)

    written = []
    entries = []
    for each in names:
        with tempfile.TemporaryDirectory(prefix="hoc-archive-") as workspace:
            workspace = Path(workspace)
            (workspace / "seasons").mkdir()
            # The seasons a replay writes go to the scratch directory: the
            # committed record is what the replay is checked against, and must
            # never be overwritten by it.
            conn = rebuild.rebuild(
                workspace / "archive.db", export=False, name=each, verbose=False,
                seasons_out=workspace / "seasons",
            )
            written.extend(site.write_site(
                conn,
                out_dir=out_dir,
                subdir=f"{site.SITE_DIRNAME}/{site.ARCHIVE_DIRNAME}/{each}",
                archive=True,
                archive_name=each,
            ))
            entries.append(_summary(conn, each))
            conn.close()
        if verbose:
            print(f"archive: {each!r} rendered")

    if name is None:
        written.append(site.write_archive_index(out_dir, entries))
    if verbose:
        print(f"archive: {len(written)} files from {len(names)} scenario(s)")
    return written


def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else site.DEFAULT_OUT_DIR
    written = build_archive(out_dir, verbose=True)
    print(f"wrote {Path(out_dir) / site.SITE_DIRNAME / site.ARCHIVE_DIRNAME}")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
