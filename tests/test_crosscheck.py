"""The two engines must play the same game.

This is the test the whole of Phase 10-1 exists to make possible: `hoc/sim.py`
and `web/engine/sim.js` are run for the same seed and their season files
compared byte for byte. Anything short of identical is a failure, and the
failure names the season and the field (scripts/crosscheck.py).

The tests skip — loudly, with a reason — when the comparison cannot be made at
all: no node on PATH, or no JavaScript engine built yet. A skip here is not a
pass, and the skip reason says so.
"""

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import crosscheck  # noqa: E402

# 120 seasons is long enough to be a real test and short enough to run in the
# ordinary suite: by season 120 the map is around 80% claimed, so every
# mechanism the engine has — founding, mortality, succession, partition,
# expansion, friction, disputes, challenges, absorption — has fired many times.
CROSSCHECK_SEASONS = 120
CROSSCHECK_SEEDS = (1867, 2, 3)

# What "fast enough to run a game in a browser" means (Phase 10-2 puts this
# engine behind a live UI). A 300-season run is the whole game.
JS_SPEED_SEASONS = 300
JS_SPEED_BUDGET = 10.0  # seconds


def _why_unavailable():
    """The reason the cross-check cannot run, or None if it can."""
    if not crosscheck.JS_CLI.exists():
        return (
            f"{crosscheck.JS_CLI.relative_to(ROOT)} does not exist: the JavaScript"
            " engine is not built yet, so there is nothing to compare against."
            " This is a gap in the port, not a passing test."
        )
    if not crosscheck.node_available():
        return "node is not on PATH, so the JavaScript engine cannot be run"
    return None


requires_both_engines = pytest.mark.skipif(
    _why_unavailable() is not None, reason=_why_unavailable() or ""
)


@requires_both_engines
@pytest.mark.parametrize("seed", CROSSCHECK_SEEDS)
def test_the_two_engines_write_identical_seasons(seed):
    try:
        differences = crosscheck.crosscheck(seed, CROSSCHECK_SEASONS)
    except crosscheck.CrosscheckUnavailable as exc:
        pytest.skip(str(exc))

    if differences:
        season, diff = differences[0]
        pytest.fail(
            f"seed {seed}: the engines diverge at season {season}"
            f" ({len(differences)} of {CROSSCHECK_SEASONS} seasons differ).\n\n{diff}"
        )


@requires_both_engines
def test_the_javascript_engine_plays_a_full_game_quickly():
    """Phase 10-2 runs this engine in a browser, where a 300-season game has to
    feel like a page and not like a build."""
    import tempfile

    workspace = Path(tempfile.mkdtemp(prefix="hoc-js-speed-"))
    try:
        started = time.time()
        crosscheck.run_js(1867, JS_SPEED_SEASONS, workspace / "seasons")
        elapsed = time.time() - started
    except crosscheck.CrosscheckUnavailable as exc:
        pytest.skip(str(exc))
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    assert elapsed < JS_SPEED_BUDGET, (
        f"the JavaScript engine took {elapsed:.1f}s for {JS_SPEED_SEASONS} seasons,"
        f" over the {JS_SPEED_BUDGET}s budget"
    )


def test_the_crosscheck_script_reports_unavailability_rather_than_passing():
    """A missing engine must not look like agreement. This is the one test here
    that runs whether or not the JavaScript engine exists, because 'the
    comparison silently did nothing' is the failure mode that would make every
    other test in this file worthless."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "crosscheck.py"), "--seed", "1", "--seasons", "1"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    # 0 = agreed, 1 = diverged, 2 = could not compare. Never anything else, and
    # never 0 when there was nothing to compare.
    assert result.returncode in (0, 1, 2), result.stderr
    if not crosscheck.JS_CLI.exists():
        assert result.returncode == 2, (
            "with no JavaScript engine present the cross-check must report that it"
            f" could not compare, not success. stdout={result.stdout!r}"
        )
        assert "does not exist" in result.stderr


def test_the_ignored_field_is_only_the_engine_name():
    """The comparison is allowed to ignore exactly one thing. If that list ever
    grows, the cross-check is being loosened to fit a disagreement, which is the
    one way of 'fixing' a divergence that Phase 10-1 forbids."""
    assert crosscheck.IGNORED_TOP_LEVEL == ("engine",)


def test_stripping_removes_the_engine_field_and_nothing_else():
    import json

    record = {
        "season": 3,
        "engine": {"impl": "python", "rules_version": "0.7"},
        "chronicle": ["Season 3 · a thing happened."],
    }
    stripped = json.loads(crosscheck.strip_ignored(json.dumps(record)))
    assert "engine" not in stripped
    assert stripped == {"season": 3, "chronicle": ["Season 3 · a thing happened."]}
