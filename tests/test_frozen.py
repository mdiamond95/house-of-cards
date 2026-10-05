"""A frozen scenario is never written to — by Python, by the browser, or by a push.

The game in `scenarios/new` (The First Dominion, seed 1867, seasons 1–150) is
finished. These tests run against the repository as it actually is: no
`live_game` fixture, because the point is that nothing is live. They prove the
manifests say so, that every writer refuses, that the pages say so plainly, and
that the closed record still replays byte for byte.
"""

import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import engine_command  # noqa: E402
import referee  # noqa: E402

from hoc import __main__ as cli  # noqa: E402
from hoc import db, scenario  # noqa: E402
from hoc.export import site  # noqa: E402


def _record_state():
    """What a write would have changed: the record, the manifests and the database."""
    state = {}
    for path in sorted((ROOT / "scenarios").rglob("*")):
        if path.is_file():
            state[str(path)] = path.read_bytes()
    state[str(db.DEFAULT_DB_PATH)] = Path(db.DEFAULT_DB_PATH).read_bytes()
    return state


# ---------------------------------------------------------------- manifests --


def test_both_games_are_frozen_and_named():
    assert scenario.status("legacy") == "frozen"
    assert scenario.status("new") == "frozen"
    assert scenario.title("new") == "The First Dominion"
    assert scenario.reference_data("legacy") == "ne-2026"
    assert scenario.reference_data("new") == "ne-2026"
    assert scenario.live_name() is None
    assert set(scenario.frozen_names()) == set(scenario.scenario_names())


def test_the_existing_manifest_fields_are_kept():
    new = scenario.read_manifest("new")
    assert new["seed"] == 1867 and new["started_season"] == 1
    assert new["kind"] == "autoplay" and new["rules_version"] == "0.7" and "restarted" in new
    assert scenario.read_manifest("legacy")["kind"] == "director"


def test_a_manifest_without_a_status_reads_as_frozen(tmp_path):
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "scenario.json").write_text('{"name": "game"}', encoding="utf-8")
    assert scenario.status("game", root=tmp_path) == "frozen"
    assert scenario.live_name(root=tmp_path) is None
    with pytest.raises(scenario.FrozenScenarioError):
        scenario.require_live("game", root=tmp_path)


def test_a_scenario_made_live_is_found_and_only_one_may_be(tmp_path):
    for name, status in (("a", "live"), ("b", "frozen")):
        (tmp_path / name).mkdir()
        (tmp_path / name / "scenario.json").write_text(
            json.dumps({"name": name, "status": status}), encoding="utf-8"
        )
    (tmp_path / "current.txt").write_text("a\n", encoding="utf-8")
    assert scenario.live_name(root=tmp_path) == "a"
    assert scenario.require_live(root=tmp_path) == "a"
    with pytest.raises(scenario.FrozenScenarioError, match="frozen"):
        scenario.require_live("b", root=tmp_path)

    (tmp_path / "b" / "scenario.json").write_text(
        json.dumps({"name": "b", "status": "live"}), encoding="utf-8"
    )
    with pytest.raises(scenario.ScenarioError, match="more than one"):
        scenario.live_name(root=tmp_path)


def test_a_live_scenario_the_database_does_not_hold_is_refused(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "scenario.json").write_text('{"name": "a", "status": "live"}', encoding="utf-8")
    (tmp_path / "current.txt").write_text("legacy\n", encoding="utf-8")
    with pytest.raises(scenario.ScenarioError, match="hoc.db holds"):
        scenario.require_live(root=tmp_path)


# ------------------------------------------------- Python writers refuse --


def test_the_engine_workflow_refuses_to_run_seasons_on_a_frozen_game(capsys):
    before = _record_state()
    status = engine_command.main(["run", "--seasons", "1"])
    assert status == 1
    assert "no live scenario" in capsys.readouterr().err
    assert _record_state() == before


def test_the_engine_workflow_refuses_an_intervention_on_a_frozen_game(capsys):
    payload = json.dumps({"directive": "x", "operations": [], "narrative": ""})
    before = _record_state()
    assert engine_command.main(["intervene", "--payload", payload]) == 1
    assert "no live scenario" in capsys.readouterr().err
    assert _record_state() == before


def test_a_refusal_is_the_whole_summary_and_commits_nothing(capsys):
    engine_command.main(["run", "--seasons", "1"])
    out = capsys.readouterr()
    assert engine_command.COMMIT_PREFIX not in out.out
    assert "Nothing was committed." in out.out


@pytest.mark.parametrize("argv", [
    ["sim", "run", "1"],
    ["sim", "new", "--seed", "1"],
    ["apply", "scenarios/new/seasons/0001.json"],
])
def test_the_command_line_refuses_to_write_to_a_frozen_game(argv, capsys):
    before = _record_state()
    assert cli.main(argv) == 1
    assert "no live scenario" in capsys.readouterr().err
    assert _record_state() == before


def test_the_rules_command_is_not_a_write_to_a_game():
    """Rules are versioned for the next game; tuning them touches no scenario,
    so it is not refused here (it is exercised in test_rules_versions)."""
    assert engine_command.COMMANDS["rules"] is engine_command.cmd_rules
    source = Path(engine_command.__file__).read_text(encoding="utf-8")
    body = source[source.index("def cmd_rules"):source.index("# ----", source.index("def cmd_rules"))]
    assert "live_scenario" not in body


# ----------------------------------------------------- the referee refuses --


def test_a_push_to_a_frozen_record_is_refused(capsys):
    paths = ["scenarios/new/seasons/0151.json", "scenarios/new/interventions/0150.json"]
    assert referee.refuse_frozen(paths) == 1
    assert referee.refuse_frozen(["scenarios/legacy/turns/0003_x.json"]) == 1
    assert referee.refuse_frozen(["narratives/0001-0041.md", "rules/CHANGELOG.md"]) == 0
    assert referee.refuse_frozen(["scenarios/new/scenario.json"]) == 0, "a manifest edit is not a record"


def test_the_referee_command_line_reads_paths_on_stdin(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("scenarios/new/seasons/0151.json\n"))
    assert referee.main(["--refuse-frozen"]) == 1
    monkeypatch.setattr(sys, "stdin", io.StringIO("README.md\n"))
    assert referee.main(["--refuse-frozen"]) == 0


def test_with_no_live_scenario_the_referee_has_nothing_to_verify(capsys):
    assert referee.main([]) == 0
    assert "no live scenario" in capsys.readouterr().out


def test_the_referee_will_not_publish_a_frozen_scenario():
    with pytest.raises(referee.RefereeError, match="frozen"):
        referee.verify(name="new")


def test_the_frozen_record_replays_all_150_seasons_byte_for_byte(capsys):
    """The freeze changes nothing about the record: every season, 1 to 150,
    replays from the seed under the rules it was played with and matches the
    committed file. The only field ignored is `engine.impl`."""
    before = _record_state()
    verdict = referee.verify(name="new", full=True, verbose=False)
    assert verdict["ok"], verdict
    assert verdict["verified"] == list(range(1, 151))
    assert verdict["from_season"] == 0 and verdict["to_season"] == 150
    assert "rebuilt_db" not in verdict, "a full replay hands back nothing to publish"
    assert _record_state() == before
    assert referee.main(["--all", "--scenario", "new"]) == 0
    assert "seasons 1-150 verify" in capsys.readouterr().out


# ------------------------------------------------- the site says so plainly --


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    out = tmp_path_factory.mktemp("frozen-site")
    conn = db.connect()
    site.write_site(conn, out_dir=out)
    conn.close()
    return out / site.SITE_DIRNAME


def test_play_and_console_say_there_is_no_live_game(exported):
    for name in ("play.html", "console.html"):
        text = (exported / name).read_text(encoding="utf-8")
        assert "There is no live game." in text, name
        assert "The First Dominion" in text, name
        assert f'href="{site.ARCHIVE_DIRNAME}/index.html"' in text, name
        assert "<script" not in text, name


def test_nothing_that_could_write_is_shipped(exported):
    for name in ("play.js", "console.js", "engine", "data/rules", "data/reference", "data/world.json"):
        assert not (exported / name).exists(), name


def test_a_previous_export_of_a_live_game_is_swept(tmp_path):
    """A site last exported while a game was live has an engine, a world snapshot
    and a play script in it; once the game is frozen they must go."""
    site_dir = tmp_path / site.SITE_DIRNAME
    (site_dir / "engine").mkdir(parents=True)
    (site_dir / "engine" / "sim.js").write_text("//", encoding="utf-8")
    (site_dir / "data").mkdir()
    (site_dir / "data" / "world.json").write_text("{}", encoding="utf-8")
    (site_dir / "play.js").write_text("//", encoding="utf-8")
    conn = db.connect()
    site.write_site(conn, out_dir=tmp_path)
    conn.close()
    assert not (site_dir / "engine").exists()
    assert not (site_dir / "data" / "world.json").exists()
    assert not (site_dir / "play.js").exists()


# ------------------------------------------------ the browser refuses too --


def test_the_browser_refuses_a_frozen_scenario_in_both_paths():
    """web/engine/savecheck.js builds the record's files and the commit with a
    frozen scenario for every manifest in scenarios/ that is not live, a manifest
    with no status, and no scenario at all. recordFiles and commitRecord must
    throw before building a file or making a request."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH")
    result = subprocess.run(
        [node, str(ROOT / "web" / "engine" / "savecheck.js"), "--seasons", "3"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "a frozen scenario is refused" in result.stdout


def test_the_browser_check_covers_the_real_manifests():
    """savecheck reads the repository's own manifests, so it fails if a scenario
    is frozen on disk and the browser would still write to it."""
    source = (ROOT / "web" / "engine" / "savecheck.js").read_text(encoding="utf-8")
    assert "scenario.json" in source and "readdirSync" in source


def test_the_page_script_is_told_its_scenario_and_says_why_it_will_not_save():
    sys.path.insert(0, str(ROOT))
    from hoc.export import play_js

    js = play_js.PLAY_JS
    assert "const SCENARIO = __SCENARIO__;" in js
    assert "SCENARIO.status !== 'live'" in js
    assert "is frozen and cannot be written to" in js
    assert "stopSave(" in js  # the message goes to #save-status, never silently
    browser = site._scenario_for_browser("new")
    assert browser == {"name": "new", "title": "The First Dominion", "status": "frozen"}


def test_the_console_script_refuses_a_frozen_scenario():
    assert "SCENARIO.status !== 'live'" in site.CONSOLE_JS
    assert "is frozen and cannot be written to" in site.CONSOLE_JS


# ------------------------------------------------ no scenario is named in code --


def test_no_scenario_is_named_in_code():
    """The live game comes from the manifests. `scenarios/new` and the like must
    not be spelled out in the engine, the exporters, the workflows or the page's
    scripts — only in the data and in the tests that read it."""
    pattern = re.compile(r"scenarios/(new|legacy)\b|seed_dir\([\"'](new)[\"']\)|(?:current_name\(\)|active|name) [=!]= [\"']new[\"']")
    roots = [ROOT / "hoc", ROOT / "web", ROOT / "scripts", ROOT / ".github"]
    offenders = []
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".js", ".yml"}:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line) and "RECONSTRUCTION" not in line:
                    offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert not offenders, "\n".join(offenders)
