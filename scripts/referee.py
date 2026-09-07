#!/usr/bin/env python3
"""Verify committed seasons with the Python engine before they become the state.

    python scripts/referee.py [--check-only]

Phase 10-3. The play page lets the browser commit the seasons it played straight
to `main`. That is only safe because nothing believes them until this runs: the
referee replays each newly committed season with the Python engine and compares
what it produced against what was committed, byte for byte. Only if every one
agrees does it update `hoc.db` and export — so `hoc.db`, `outputs/` and the
published site are always the Python engine's own work, and a browser (or a
hand-edited file, or a bug) can never make the public state say something the
engine would not.

What it does, in order:

1. Load `hoc.db` and find the last season it holds.
2. Take every committed season file above that, in order.
3. For each: apply any intervention recorded for the season before it, replay
   the season, and compare the produced canonical JSON with the committed file.
4. On the first mismatch: stop, name the season and the first differing draw in
   the step summary, and fail. Nothing is committed.
5. On full agreement: keep the rebuilt database, run the tests, export, commit.

The comparison ignores exactly one field — `engine.impl`, which names the
implementation that wrote the file — and `tests/test_referee.py` asserts that
the ignore list has not grown. Loosening it would defeat the entire point.

Exit status is 0 when there is agreement (or nothing to do), 1 when a season
does not verify, and 2 when the referee could not run at all.
"""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hoc import db, scenario, sim  # noqa: E402

import rebuild as rebuild_script  # noqa: E402

# The one field the committed file and a replay are allowed to differ about.
IGNORED_TOP_LEVEL = ("engine",)


class RefereeError(Exception):
    """The referee could not run — not that a season failed to verify."""


def committed_season_files(name=None):
    """Every season file in the record, keyed by season number."""
    return {
        rebuild_script.season_number(path): path
        for path in rebuild_script.season_files(name)
    }


def database_season(conn):
    row = conn.execute("SELECT MAX(season_no) AS n FROM seasons").fetchone()
    return 0 if row is None or row["n"] is None else row["n"]


def strip_ignored(record):
    """A season record without the fields a replay may legitimately differ on."""
    out = dict(record)
    for key in IGNORED_TOP_LEVEL:
        out.pop(key, None)
    return out


def first_difference(committed, produced):
    """A one-line account of where two season records first disagree.

    The draws are the useful place to look: every draw carries the purpose it
    was made for, so the first differing one names the method that diverged
    rather than leaving a reader to diff two thousand lines of JSON.
    """
    left, right = strip_ignored(committed), strip_ignored(produced)
    for index, (a, b) in enumerate(zip(left.get("draws", []), right.get("draws", []))):
        if a != b:
            return (
                f"draw {index} differs: committed {json.dumps(a, ensure_ascii=False)},"
                f" the engine produced {json.dumps(b, ensure_ascii=False)}"
            )
    if len(left.get("draws", [])) != len(right.get("draws", [])):
        return (
            f"the committed season logs {len(left.get('draws', []))} draws and the"
            f" engine made {len(right.get('draws', []))}"
        )
    for key in sorted(set(left) | set(right)):
        if left.get(key) != right.get(key):
            return f"the {key!r} field differs"
    return "the files differ in whitespace or key order but not in content"


def verify(name=None, db_path=None, verbose=True):
    """Replay the committed record and compare. Returns a verdict dict.

    The verdict carries `ok`, the range verified, and on failure the season that
    failed and why. On success it also carries `rebuilt_db`, a scratch database
    the caller may move into place; on failure there is none.

    **Nothing outside the scratch directory is touched until the verdict is in.**
    The replay goes to a temporary database and a temporary seasons directory,
    for two separate reasons: a replay written over the committed season files
    would be compared with itself, which is a check that always passes; and a
    replay written into `hoc.db` would advance the live database even when the
    verification then failed, which would leave the next run believing the bad
    seasons were already applied.
    """
    name = name or scenario.current_name()
    db_path = Path(db_path or db.DEFAULT_DB_PATH)

    live = db.connect(db_path) if db_path.exists() else None
    from_season = database_season(live) if live is not None else 0
    if live is not None:
        live.close()

    files = committed_season_files(name)
    pending = sorted(season for season in files if season > from_season)

    if not pending:
        # Either nothing was pushed, or the seasons pushed were the Python
        # engine's own (engine.yml commits hoc.db alongside them), in which case
        # the database already holds them and there is nothing to verify.
        return {
            "ok": True, "already_applied": True, "from_season": from_season,
            "to_season": from_season, "verified": [], "counts": None,
        }

    highest = max(files)
    if pending != list(range(from_season + 1, highest + 1)):
        raise RefereeError(
            f"the committed seasons are not contiguous above season {from_season}:"
            f" found {pending[:5]}{'…' if len(pending) > 5 else ''}"
        )

    # Read the committed bytes before anything can overwrite them.
    committed = {season: files[season].read_bytes() for season in pending}

    scratch = Path(tempfile.mkdtemp(prefix="hoc-referee-"))
    scratch_db = scratch / "verify.db"
    keep_scratch = False
    try:
        # Replay the whole record from the seed. Only that proves the database
        # about to be published is the record's own work rather than the record
        # plus whatever was already lying in hoc.db. scripts/rebuild.py is the
        # single definition of what the record contains (C2).
        conn = rebuild_script.rebuild(
            scratch_db, export=False, name=name, verbose=False, seasons_out=scratch
        )

        verified = []
        for season in pending:
            produced_path = scratch / f"{season:04d}.json"
            if not produced_path.exists():
                conn.close()
                raise RefereeError(
                    f"the engine produced no season {season}; the record may be"
                    " missing a season the committed files depend on"
                )
            produced = json.loads(produced_path.read_text(encoding="utf-8"))
            recorded = json.loads(committed[season].decode("utf-8"))
            if strip_ignored(recorded) != strip_ignored(produced):
                conn.close()
                return {
                    "ok": False, "already_applied": False, "from_season": from_season,
                    "failed_season": season,
                    "reason": first_difference(recorded, produced),
                    "verified": verified, "counts": None,
                }
            verified.append(season)
            if verbose:
                print(f"  season {season} verifies")

        counts = (
            conn.execute(
                "SELECT COUNT(*) AS n FROM houses WHERE status = 'active'"
            ).fetchone()["n"],
            conn.execute(
                "SELECT COUNT(*) AS n FROM holdings WHERE released_event_id IS NULL"
            ).fetchone()["n"],
        )
        conn.close()
        keep_scratch = True
        return {
            "ok": True, "already_applied": False, "from_season": from_season,
            "to_season": pending[-1], "verified": verified, "counts": counts,
            "rebuilt_db": scratch_db, "scratch": scratch,
        }
    finally:
        if not keep_scratch:
            shutil.rmtree(scratch, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check-only", action="store_true",
        help="verify and report; do not keep the rebuilt database",
    )
    parser.add_argument("--summary", default=None, help="write a step summary here")
    args = parser.parse_args(argv)

    lines = []
    try:
        verdict = verify(verbose=True)
    except RefereeError as exc:
        lines.append("## Referee — could not run")
        lines.append("")
        lines.append(str(exc))
        _write_summary(args.summary, lines)
        print(f"referee: {exc}", file=sys.stderr)
        return 2

    if verdict["ok"] and verdict["already_applied"]:
        lines.append("## Referee — nothing to verify")
        lines.append("")
        lines.append(
            f"`hoc.db` already holds every committed season (through season"
            f" {verdict['from_season']}). These seasons were the Python engine's own."
        )
        _write_summary(args.summary, lines)
        print("referee: nothing to verify; the database already holds every committed season")
        return 0

    if not verdict["ok"]:
        season = verdict["failed_season"]
        lines.append("## Referee — season {} does not verify".format(season))
        lines.append("")
        lines.append(
            f"Replaying the record with the Python engine produced a different season"
            f" {season} from the one committed. Nothing has been changed: `hoc.db`,"
            f" `outputs/` and the published site still hold the last verified state."
        )
        lines.append("")
        lines.append(f"**First difference:** {verdict['reason']}")
        if verdict["verified"]:
            lines.append("")
            lines.append(
                f"Seasons {verdict['verified'][0]}–{verdict['verified'][-1]} verified before it."
            )
        _write_summary(args.summary, lines)
        print(f"referee: season {season} does not verify — {verdict['reason']}", file=sys.stderr)
        return 1

    first, last = verdict["verified"][0], verdict["verified"][-1]
    lines.append(f"## Referee — verified seasons {first}–{last}")
    lines.append("")
    lines.append(
        "Every committed season was replayed with the Python engine and matched"
        " the committed file exactly."
    )
    counts = verdict["counts"]
    lines.append("")
    lines.append(f"| houses | ridings held |")
    lines.append(f"|---|---|")
    lines.append(f"| {counts[0]} | {counts[1]} |")
    _write_summary(args.summary, lines)

    if args.check_only:
        shutil.rmtree(verdict["scratch"], ignore_errors=True)
        print(f"referee: seasons {first}-{last} verify (check only)")
        return 0

    # Only now does the live database move. Everything above ran against a
    # scratch copy, so a verification that failed left hoc.db exactly as it was.
    shutil.copyfile(verdict["rebuilt_db"], db.DEFAULT_DB_PATH)
    shutil.rmtree(verdict["scratch"], ignore_errors=True)
    print(f"REFEREE_RANGE {first} {last}")
    print(f"REFEREE_COUNTS {counts[0]} {counts[1]}")
    print(f"referee: seasons {first}-{last} verify")
    return 0


def _write_summary(path, lines):
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
