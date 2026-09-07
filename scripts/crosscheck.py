#!/usr/bin/env python3
"""Run both engines for the same seed and prove they wrote the same seasons.

    python scripts/crosscheck.py --seed 1867 --seasons 120

Phase 10-1. There are two implementations of the engine — `hoc/sim.py` and
`web/engine/sim.js` — and the only thing that makes the second one worth having
is that it agrees with the first. "Agrees" is defined here and nowhere else:
**the two engines write byte-identical season files**, once the one field they
are expected to differ about is removed.

That field is `engine.impl`, which names the implementation that wrote the file.
Everything else — every draw, every chronicle line, every stat — must match. The
comparison is deliberately a byte comparison of canonical JSON rather than a
structural diff: a structural diff has to decide for itself which differences
matter, and that decision is exactly the thing that would quietly let the two
engines drift apart.

On a disagreement this prints the first differing season and a unified diff of
the two files, so the failure names a season number and a field rather than
just saying no.

Exit status is 0 when the engines agree, 1 when they do not, and 2 when the
comparison could not be made at all (no node, no JS engine).
"""

import argparse
import difflib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

JS_CLI = ROOT / "web" / "engine" / "cli.js"

# The one field the two engines are expected to disagree about.
IGNORED_TOP_LEVEL = ("engine",)


class CrosscheckUnavailable(Exception):
    """The comparison could not be made — not that it failed."""


def node_available():
    return shutil.which("node") is not None


def _apply_script(conn, world, script, after_season):
    """Apply a scripted intervention through the Python turn runner.

    The turn runner is the only path a director's operation takes in the Python
    engine, so the cross-check has to go through it too: applying the operations
    some other way here would prove the two engines agree about a code path the
    game never uses. The turn runner insists on a NNNN_slug.json filename, so
    each entry is written under the season it follows.
    """
    import json as _json
    import tempfile as _tempfile

    from hoc.turn import apply_turn

    for index, entry in enumerate(script):
        if entry["after_season"] != after_season:
            continue
        directory = Path(_tempfile.mkdtemp(prefix="hoc-turn-"))
        path = directory / f"{index + 1:04d}_s{after_season:04d}-crosscheck.json"
        path.write_text(
            _json.dumps(
                {
                    "directive": entry.get("directive", "cross-check intervention"),
                    "event": {
                        "kind": entry.get("kind", "other"),
                        "title": entry["title"],
                        "narrative": entry.get(
                            "narrative", "A cross-check intervention."
                        ),
                        "houses": [],
                    },
                    "operations": entry["operations"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        apply_turn(conn, path)
        shutil.rmtree(directory, ignore_errors=True)


def run_python(seed, seasons, out_dir, seat=None, phases=None, script=(), resume_from=None):
    """Play `seasons` seasons with the Python engine, writing season files.

    `resume_from` is a season count to play *first* without writing anything —
    the state a snapshot would have been taken at — so that the seasons this
    does write are the ones a resumed world should reproduce.
    """
    import load_seed  # noqa: E402  (scripts/ is on the path above)

    from hoc import scenario, sim

    out_dir.mkdir(parents=True, exist_ok=True)
    conn = load_seed.build(out_dir.parent / "python.db", seed=scenario.seed_dir("new"))
    world = sim.World(conn, world_seed=seed, seasons_dir=out_dir, phases=phases)
    with conn:
        world.initialise(seed, seat=seat)
        _apply_script(conn, world, script, 1)
        for season in range(2, seasons + 1):
            world.run_season()
            _apply_script(conn, world, script, season)
    conn.close()


def run_js(seed, seasons, out_dir, seat=None, phases=None, resume=None, interventions=None):
    """Play the same seasons with the JavaScript engine."""
    if not JS_CLI.exists():
        raise CrosscheckUnavailable(
            f"{JS_CLI.relative_to(ROOT)} does not exist: the JavaScript engine is not"
            " built yet, so there is nothing to compare the Python engine against."
        )
    if not node_available():
        raise CrosscheckUnavailable("node is not on PATH, so the JavaScript engine cannot run")

    command = [
        "node", str(JS_CLI),
        "--seed", str(seed),
        "--seasons", str(seasons),
        "--out", str(out_dir),
    ]
    if resume is not None:
        command += ["--resume", str(resume)]
    if interventions is not None:
        command += ["--interventions", str(interventions)]
    if seat:
        command += ["--seat", seat]
    if phases:
        command += ["--phases", ",".join(phases)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        raise CrosscheckUnavailable(
            f"the JavaScript engine exited {result.returncode}:\n"
            f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
        )


def strip_ignored(text):
    """Re-serialise a season file without the fields the engines may differ on.

    Parsed and re-dumped rather than edited as text, so this cannot depend on
    where in the file the ignored key happens to sort.
    """
    record = json.loads(text)
    for key in IGNORED_TOP_LEVEL:
        record.pop(key, None)
    return json.dumps(record, sort_keys=True, ensure_ascii=False, indent=1) + "\n"


def compare(python_dir, js_dir, seasons):
    """Return a list of (season, unified diff) for every season that differs."""
    differences = []
    for season in range(1, seasons + 1):
        name = f"{season:04d}.json"
        py_path, js_path = python_dir / name, js_dir / name
        if not py_path.exists():
            differences.append((season, f"the Python engine wrote no {name}"))
            continue
        if not js_path.exists():
            differences.append((season, f"the JavaScript engine wrote no {name}"))
            continue

        py_raw = py_path.read_text(encoding="utf-8")
        js_raw = js_path.read_text(encoding="utf-8")
        if py_raw == js_raw:
            continue  # byte-identical, including the engine field

        py_text, js_text = strip_ignored(py_raw), strip_ignored(js_raw)
        if py_text == js_text:
            continue  # differ only in the ignored fields, which is allowed

        diff = "".join(
            difflib.unified_diff(
                py_text.splitlines(keepends=True),
                js_text.splitlines(keepends=True),
                fromfile=f"python/{name}",
                tofile=f"javascript/{name}",
            )
        )
        differences.append((season, diff))
    return differences


def crosscheck_resume(seed, snapshot_at, seasons, keep=None, script=()):
    """Snapshot a Python world, resume it in JavaScript, and compare what follows.

    This is Phase 10-2's central claim: the browser picks the committed game up
    exactly where the Python engine put it down. Both sides play the same
    seasons — Python straight through, JavaScript from `world.json` — and the
    files they write for those seasons must be identical.
    """
    import load_seed  # noqa: E402

    from hoc import scenario, sim
    from hoc.export import world as world_export

    workspace = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="hoc-resume-"))
    workspace.mkdir(parents=True, exist_ok=True)
    python_dir = workspace / "python"
    js_dir = workspace / "javascript"
    python_dir.mkdir(parents=True, exist_ok=True)
    js_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Play to the snapshot point writing nothing, snapshot, then keep going
        # and write only the seasons the resumed world should reproduce.
        conn = load_seed.build(workspace / "python.db", seed=scenario.seed_dir("new"))
        world = sim.World(conn, world_seed=seed, seasons_dir=None)
        with conn:
            world.initialise(seed)
            _apply_script(conn, world, script, 1)
            for season in range(2, snapshot_at + 1):
                world.run_season()
                _apply_script(conn, world, script, season)
            snapshot = world_export.world_snapshot(conn)
            snapshot_path = workspace / "world.json"
            snapshot_path.write_text(
                json.dumps(snapshot, sort_keys=True, ensure_ascii=False), encoding="utf-8"
            )

            world.seasons_dir = python_dir
            for season in range(snapshot_at + 1, snapshot_at + seasons + 1):
                world.run_season()
                _apply_script(conn, world, script, season)
        conn.close()

        script_path = None
        if script:
            script_path = workspace / "interventions.json"
            script_path.write_text(json.dumps(list(script), ensure_ascii=False), encoding="utf-8")

        run_js(seed, seasons, js_dir, resume=snapshot_path, interventions=script_path)
        return _compare_range(python_dir, js_dir, snapshot_at + 1, snapshot_at + seasons)
    finally:
        if keep is None:
            shutil.rmtree(workspace, ignore_errors=True)


def _compare_range(python_dir, js_dir, first, last):
    """Compare a run of seasons by number, rather than from season 1."""
    differences = []
    for season in range(first, last + 1):
        name = f"{season:04d}.json"
        py_path, js_path = python_dir / name, js_dir / name
        if not py_path.exists():
            differences.append((season, f"the Python engine wrote no {name}"))
            continue
        if not js_path.exists():
            differences.append((season, f"the JavaScript engine wrote no {name}"))
            continue
        py_raw = py_path.read_text(encoding="utf-8")
        js_raw = js_path.read_text(encoding="utf-8")
        if py_raw == js_raw:
            continue
        py_text, js_text = strip_ignored(py_raw), strip_ignored(js_raw)
        if py_text == js_text:
            continue
        differences.append((season, "".join(difflib.unified_diff(
            py_text.splitlines(keepends=True), js_text.splitlines(keepends=True),
            fromfile=f"python/{name}", tofile=f"javascript/{name}",
        ))))
    return differences


def crosscheck(seed, seasons, seat=None, keep=None, phases=None, script=()):
    """Run both engines and compare. Returns the list of differences.

    Raises CrosscheckUnavailable when the comparison cannot be made at all.
    """
    workspace = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="hoc-crosscheck-"))
    workspace.mkdir(parents=True, exist_ok=True)
    python_dir = workspace / "python"
    js_dir = workspace / "javascript"
    try:
        script_path = None
        if script:
            script_path = workspace / "interventions.json"
            script_path.write_text(json.dumps(list(script), ensure_ascii=False), encoding="utf-8")
        run_python(seed, seasons, python_dir, seat=seat, phases=phases, script=script)
        run_js(seed, seasons, js_dir, seat=seat, phases=phases, interventions=script_path)
        return compare(python_dir, js_dir, seasons)
    finally:
        if keep is None:
            shutil.rmtree(workspace, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=1867)
    parser.add_argument("--seasons", type=int, default=120)
    parser.add_argument("--seat", default=None, help="riding for the first house")
    parser.add_argument(
        "--keep", default=None,
        help="keep both engines' output in this directory instead of a temp dir",
    )
    parser.add_argument(
        "--phases",
        default=None,
        help=(
            "DEVELOPER ONLY: run only these phases of the season loop in both"
            " engines, so the port can be compared a phase at a time"
        ),
    )
    parser.add_argument(
        "--max-diffs", type=int, default=1,
        help="how many differing seasons to print in full (default: the first)",
    )
    args = parser.parse_args(argv)

    try:
        phases = [p.strip() for p in args.phases.split(",")] if args.phases else None
        differences = crosscheck(
            args.seed, args.seasons, seat=args.seat, keep=args.keep, phases=phases
        )
    except CrosscheckUnavailable as exc:
        print(f"cross-check unavailable: {exc}", file=sys.stderr)
        return 2

    if not differences:
        print(
            f"seed {args.seed}: the two engines agree on all {args.seasons} seasons."
        )
        return 0

    first = differences[0][0]
    print(
        f"seed {args.seed}: the engines diverge at season {first}"
        f" ({len(differences)} of {args.seasons} seasons differ).",
        file=sys.stderr,
    )
    for season, diff in differences[: args.max_diffs]:
        print(f"\n--- season {season} " + "-" * 50, file=sys.stderr)
        print(diff, file=sys.stderr)
    if len(differences) > args.max_diffs:
        remaining = ", ".join(str(s) for s, _ in differences[args.max_diffs:][:20])
        print(f"\nalso differing: {remaining}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
