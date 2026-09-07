"""Phase 10-3: the referee, which decides whether a committed season is real.

The play page commits the seasons a browser played straight to `main`. Nothing
believes them until `scripts/referee.py` replays each one with the Python engine
and finds it identical. These tests are about that decision and nothing else:
that seasons the JavaScript engine wrote are accepted, that a season altered by
so much as one draw is rejected and named, and that seasons the Python engine
itself produced are recognised as already applied rather than verified twice.

Everything runs against a temporary scenarios root, so no test can touch the
committed game.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from hoc import scenario  # noqa: E402

JS_CLI = ROOT / "web" / "engine" / "cli.js"
SEED = 1867
SEAT = "Kingston and the Islands"
SEASONS = 4


def _module(name):
    """scripts/ is not a package, and referee.py imports rebuild.py by name."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def referee():
    return _module("referee")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A scenarios root holding an unplayed copy of the live game.

    Only the seed and the manifest are copied: the seasons are what each test
    puts there, and the reference data (the 343 ridings and their adjacency) is
    shared with the real repository because it is not game state.
    """
    if shutil.which("node") is None:
        pytest.skip("node is not on PATH, so the JavaScript engine cannot play")
    if not JS_CLI.exists():
        pytest.skip("the JavaScript engine is not built in this checkout")

    root = tmp_path / "scenarios"
    (root / "new").mkdir(parents=True)
    shutil.copytree(scenario.SCENARIOS_DIR / "new" / "seed", root / "new" / "seed")
    shutil.copy(scenario.SCENARIOS_DIR / "new" / "scenario.json", root / "new")
    (root / "current.txt").write_text("new\n", encoding="utf-8")

    monkeypatch.setattr(scenario, "SCENARIOS_DIR", root)
    seasons = root / "new" / "seasons"
    seasons.mkdir()
    return {"root": root, "seasons": seasons, "db": tmp_path / "hoc.db"}


def play_with_js(out_dir, seasons=SEASONS):
    """Commit `seasons` seasons exactly as a browser would: canonical JSON,
    written by the JavaScript engine, and nothing else."""
    subprocess.run(
        [
            "node", str(JS_CLI),
            "--seed", str(SEED), "--seat", SEAT,
            "--seasons", str(seasons), "--out", str(out_dir),
        ],
        check=True, capture_output=True, text=True,
    )


# ------------------------------------------------------- what it agrees to --


def test_the_ignore_list_has_not_grown(referee):
    """The referee's whole value is that it compares everything. `engine` names
    the implementation that wrote the file and is the one field the two engines
    are expected to differ about; anything else added here would be a way for a
    browser to publish a season the Python engine would not have played."""
    assert referee.IGNORED_TOP_LEVEL == ("engine",)


def test_seasons_the_browser_engine_played_verify(referee, repo):
    play_with_js(repo["seasons"])
    verdict = referee.verify(name="new", db_path=repo["db"], verbose=False)

    assert verdict["ok"] is True
    assert verdict["already_applied"] is False
    assert verdict["verified"] == list(range(1, SEASONS + 1))
    assert verdict["from_season"] == 0
    assert verdict["to_season"] == SEASONS
    # A verified run leaves a database the caller may publish, and has touched
    # nothing outside its scratch directory.
    assert Path(verdict["rebuilt_db"]).exists()
    assert not repo["db"].exists()
    shutil.rmtree(verdict["scratch"], ignore_errors=True)


def test_the_committed_files_are_not_overwritten_by_the_replay(referee, repo):
    """A replay written over the committed files would be compared with itself,
    which is a check that passes no matter what was committed."""
    play_with_js(repo["seasons"])
    before = {p.name: p.read_bytes() for p in sorted(repo["seasons"].glob("*.json"))}

    verdict = referee.verify(name="new", db_path=repo["db"], verbose=False)
    shutil.rmtree(verdict["scratch"], ignore_errors=True)

    after = {p.name: p.read_bytes() for p in sorted(repo["seasons"].glob("*.json"))}
    assert after == before


# ------------------------------------------------------- what it refuses to --


def test_a_tampered_season_is_rejected_and_named(referee, repo):
    """One altered draw in one season. The referee must stop at that season,
    say which draw differed, and hand back no database to publish."""
    play_with_js(repo["seasons"])
    target = repo["seasons"] / "0003.json"
    record = json.loads(target.read_text(encoding="utf-8"))
    assert record["draws"], "season 3 recorded no draws to tamper with"
    record["draws"][0] = dict(record["draws"][0], purpose="a draw the engine never made")
    target.write_text(
        json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    verdict = referee.verify(name="new", db_path=repo["db"], verbose=False)

    assert verdict["ok"] is False
    assert verdict["failed_season"] == 3
    assert verdict["verified"] == [1, 2]
    assert "draw 0 differs" in verdict["reason"]
    assert "a draw the engine never made" in verdict["reason"]
    assert "rebuilt_db" not in verdict
    assert not repo["db"].exists()


def test_a_season_with_a_different_outcome_is_rejected(referee, repo):
    """Tampering that changes the story rather than the dice is caught too —
    the comparison is of the whole record, not of the draws alone."""
    play_with_js(repo["seasons"])
    target = repo["seasons"] / "0002.json"
    record = json.loads(target.read_text(encoding="utf-8"))
    record["chronicle"] = record["chronicle"] + ["A thing that did not happen."]
    target.write_text(
        json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    verdict = referee.verify(name="new", db_path=repo["db"], verbose=False)

    assert verdict["ok"] is False
    assert verdict["failed_season"] == 2
    assert "chronicle" in verdict["reason"]


def test_a_gap_in_the_committed_seasons_is_refused(referee, repo):
    """The record is a sequence. A push that skips a season is not something to
    verify half of — it is a record the referee cannot read."""
    play_with_js(repo["seasons"])
    (repo["seasons"] / "0003.json").unlink()

    with pytest.raises(referee.RefereeError) as caught:
        referee.verify(name="new", db_path=repo["db"], verbose=False)
    assert "not contiguous" in str(caught.value)


# -------------------------------------------- what it recognises as its own --


def test_seasons_the_python_engine_played_are_already_applied(referee, repo):
    """engine.yml commits `hoc.db` alongside the seasons it played, so the push
    that reaches the referee is of seasons the database already holds. There is
    nothing to verify and, importantly, nothing to commit a second time."""
    play_with_js(repo["seasons"])
    rebuild = _module("rebuild")
    conn = rebuild.rebuild(repo["db"], export=False, name="new", verbose=False)
    conn.close()
    assert repo["db"].exists()

    verdict = referee.verify(name="new", db_path=repo["db"], verbose=False)

    assert verdict["ok"] is True
    assert verdict["already_applied"] is True
    assert verdict["verified"] == []
    assert verdict["from_season"] == SEASONS


def test_only_the_seasons_above_the_database_are_verified(referee, repo):
    """A database part-way through the record verifies only what is new — but
    still replays the whole record from the seed to get there, so the database
    it publishes is the record's own work rather than the record plus whatever
    was already in hoc.db."""
    play_with_js(repo["seasons"], seasons=2)
    rebuild = _module("rebuild")
    conn = rebuild.rebuild(repo["db"], export=False, name="new", verbose=False)
    conn.close()

    play_with_js(repo["seasons"], seasons=SEASONS)
    verdict = referee.verify(name="new", db_path=repo["db"], verbose=False)

    assert verdict["ok"] is True
    assert verdict["verified"] == [3, 4]
    assert verdict["from_season"] == 2
    shutil.rmtree(verdict["scratch"], ignore_errors=True)


def test_nothing_committed_is_nothing_to_do(referee, repo):
    verdict = referee.verify(name="new", db_path=repo["db"], verbose=False)
    assert verdict["ok"] is True
    assert verdict["already_applied"] is True
    assert verdict["from_season"] == 0


# ---------------------------------------------- what the browser would send --


def test_the_save_payload_is_the_seasons_as_played():
    """web/engine/savecheck.js plays five seasons, builds the Git Data API
    payload the play page would send with the same web/engine/record.js the page
    uses, and checks every blob against the file the engine wrote to disk. The
    network is mocked; nothing here needs a token or reaches GitHub.

    It lives in JavaScript because the thing under test is JavaScript — the
    payload the browser builds — and running it from the suite is what stops it
    from quietly rotting."""
    if shutil.which("node") is None:
        pytest.skip("node is not on PATH")
    script = ROOT / "web" / "engine" / "savecheck.js"
    if not script.exists():
        pytest.skip("the JavaScript engine is not built in this checkout")

    result = subprocess.run(
        ["node", str(script), "--seasons", "5"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "would be committed exactly as played" in result.stdout
