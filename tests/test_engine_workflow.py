"""Phase 9e: the engine workflow, the director's interventions, and the console.

Nothing here dispatches anything or touches the network. The workflow is checked
as a document, the interventions against a temporary database, and the console
as generated HTML and JavaScript.
"""

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import load_seed  # noqa: E402

from hoc import scenario, sim  # noqa: E402
from hoc.export import site  # noqa: E402
from hoc.turn import apply_turn  # noqa: E402
from hoc.turnfile import TurnFileError, validate  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "engine.yml"
DIRECTOR = "mdiamond95"


# ------------------------------------------------------------- the workflow --


@pytest.fixture(scope="module")
def workflow():
    yaml = pytest.importorskip("yaml", reason="pyyaml is needed to parse the workflow")
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_the_workflow_parses(workflow):
    assert workflow["name"] == "Engine"
    assert "engine" in workflow["jobs"]


def test_only_the_director_may_run_it(workflow):
    """The workflow commits to main. Anyone else who can dispatch it must be
    stopped at the first step, before a checkout with a write token."""
    steps = workflow["jobs"]["engine"]["steps"]
    guard = steps[0]
    assert f"github.actor != '{DIRECTOR}'" in guard["if"]
    assert "exit 1" in guard["run"]
    # github.actor names the acting user for either trigger — the guard's
    # condition does not (and must not) mention which event fired, so the same
    # check covers a workflow_dispatch click and a repository_dispatch alike.
    assert "event_name" not in guard["if"]

    checkout = next(step for step in steps if str(step.get("uses", "")).startswith("actions/checkout"))
    assert steps.index(checkout) > steps.index(guard)


def test_both_trigger_events_are_wired(workflow):
    """A fine-grained token with Contents read/write but not Actions read/write
    gets a 403 from workflow_dispatch; repository_dispatch is the fallback the
    console retries with (see hoc/export/site.py's dispatch())."""
    on = workflow[True]  # PyYAML reads the `on:` key as the boolean True.
    assert "workflow_dispatch" in on
    assert on["repository_dispatch"]["types"] == ["engine"]


def test_inputs_are_normalized_before_any_command_step(workflow):
    """Every command step must read steps.in.outputs.*, never inputs.* or
    github.event.client_payload.* directly, so the two triggers stay
    interchangeable from that point on."""
    steps = workflow["jobs"]["engine"]["steps"]
    normalize = next(step for step in steps if step.get("id") == "in")
    assert normalize["env"]["EVENT_NAME"] == "${{ github.event_name }}"

    command_steps = [
        step for step in steps
        if "steps.in.outputs.command ==" in str(step.get("if", ""))
    ]
    assert len(command_steps) == 4
    for step in steps[steps.index(normalize) + 1:]:
        text = str(step.get("if", "")) + str(step.get("run", "")) + json.dumps(step.get("env", {}))
        assert "github.event.inputs" not in text
        assert "client_payload" not in text
        assert " inputs." not in text


def test_runs_are_serialised_and_never_cancelled(workflow):
    """A cancelled run could leave the season logs written and the database
    uncommitted, which is the one state the record cannot describe."""
    assert workflow["concurrency"]["group"] == "engine"
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_every_command_has_a_step(workflow):
    # PyYAML reads the `on:` key as the boolean True.
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"command", "seasons", "stop_on", "payload", "note"}
    commands = inputs["command"]["options"]
    assert commands == ["run", "intervene", "rules", "rebuild"]

    steps = workflow["jobs"]["engine"]["steps"]
    for command in commands:
        assert any(
            f"steps.in.outputs.command == '{command}'" in str(step.get("if", "")) for step in steps
        ), f"no step handles the {command!r} command"


def test_node_is_set_up_for_the_js_syntax_tests(workflow):
    """The suite the workflow runs includes tests/test_js_syntax.py, which
    shells out to `node --check`. ubuntu-latest ships node already, but that is
    the runner image's business, not this workflow's; pin it explicitly so a
    future image change can't silently turn those tests into a skip."""
    steps = workflow["jobs"]["engine"]["steps"]
    setup_node = next(
        (step for step in steps if str(step.get("uses", "")).startswith("actions/setup-node")),
        None,
    )
    assert setup_node is not None, "no actions/setup-node step found"
    names = [step.get("name") for step in steps]
    assert steps.index(setup_node) < names.index("Test")


def test_the_smoke_and_build_marks_are_kept_out_of_the_workflow(workflow):
    """smoke (the 300-season sanity run) and build (needs shapely, which this
    runner deliberately does not install) both belong to a Code session, not
    here — see pytest.ini for what each marker means."""
    steps = workflow["jobs"]["engine"]["steps"]
    test_step = next(step for step in steps if step.get("name") == "Test")
    assert '-m "not smoke and not build"' in test_step["run"]


def test_the_workflow_commits_as_the_engine(workflow):
    steps = workflow["jobs"]["engine"]["steps"]
    commit = next(step for step in steps if "git commit" in str(step.get("run", "")))
    assert "House of Cards Engine" in commit["run"]
    assert "actions@github.com" in commit["run"]
    # Tests and export come before the commit, or a red run could still land.
    names = [step.get("name") for step in steps]
    assert names.index("Test") < names.index(commit["name"])
    assert names.index("Export") < names.index(commit["name"])


def test_no_model_is_called_anywhere_in_the_workflow():
    """Phase 9e's standing condition: Claude is not part of any workflow."""
    text = WORKFLOW.read_text(encoding="utf-8").lower()
    for needle in ("anthropic", "api.anthropic", "claude-code-action", "openai"):
        assert needle not in text


# ------------------------------------------------------- interventions ------


@pytest.fixture
def world(tmp_path):
    conn = load_seed.build(tmp_path / "w.db", seed=scenario.seed_dir("new"))
    engine = sim.World(conn, world_seed=1867)
    engine.initialise(1867)
    return engine


def turn_file(tmp_path, operations, directive="A director's intervention.", turn_id=1):
    path = tmp_path / f"{turn_id:04d}_s0001-intervention.json"
    path.write_text(
        json.dumps(
            {
                "directive": directive,
                "event": {
                    "kind": "other",
                    "title": "Director's intervention",
                    "narrative": directive,
                    "houses": [],
                },
                "operations": operations,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_turnfile_accepts_the_new_intervention_operations(world, tmp_path):
    house = world.active_houses()[0]["house"]
    data = json.loads(
        turn_file(
            tmp_path,
            [
                {"op": "set_objective", "house": house, "objective": "Seek elevation"},
                {"op": "force_action", "house": house, "action": "Invest"},
                {"op": "adjust_stat", "house": house, "stat": "capital", "delta": 5,
                 "reason": "a Crown grant"},
            ],
        ).read_text(encoding="utf-8")
    )
    assert validate(world.conn, data) == []


def test_a_stat_adjustment_without_a_reason_is_refused(world, tmp_path):
    house = world.active_houses()[0]["house"]
    data = json.loads(
        turn_file(
            tmp_path,
            [{"op": "adjust_stat", "house": house, "stat": "capital", "delta": 5}],
        ).read_text(encoding="utf-8")
    )
    with pytest.raises(TurnFileError) as raised:
        validate(world.conn, data)
    assert "reason" in str(raised.value)


def test_an_empty_reason_is_refused_too(world, tmp_path):
    """A reason that is present and says nothing is the same problem."""
    house = world.active_houses()[0]["house"]
    data = json.loads(
        turn_file(
            tmp_path,
            [{"op": "adjust_stat", "house": house, "stat": "capital", "delta": 5, "reason": "   "}],
        ).read_text(encoding="utf-8")
    )
    with pytest.raises(TurnFileError) as raised:
        validate(world.conn, data)
    assert "reason" in str(raised.value)


def test_an_unknown_objective_or_action_is_refused(world, tmp_path):
    house = world.active_houses()[0]["house"]
    for operation, needle in (
        ({"op": "set_objective", "house": house, "objective": "Rule the world"}, "objective"),
        ({"op": "force_action", "house": house, "action": "Invade"}, "action"),
    ):
        data = json.loads(turn_file(tmp_path, [operation]).read_text(encoding="utf-8"))
        with pytest.raises(TurnFileError) as raised:
            validate(world.conn, data)
        assert needle in str(raised.value)


def test_a_forced_action_is_taken_once_and_then_cleared(world, tmp_path):
    house = world.active_houses()[0]["house"]
    apply_turn(
        world.conn,
        turn_file(tmp_path, [
            {"op": "adjust_stat", "house": house, "stat": "capital", "delta": 60,
             "reason": "so Expand is affordable"},
            {"op": "force_action", "house": house, "action": "Expand"},
        ]),
    )
    assert world.house_row(house)["forced_action"] == "Expand"

    record = world.run_season()
    taken = [entry for entry in record["actions"] if entry.get("forced")]
    assert taken and taken[0]["action"] == "Expand"
    assert world.house_row(house)["forced_action"] is None

    # And it does not carry over: the next season is drawn normally.
    following = world.run_season()
    assert not [entry for entry in following["actions"] if entry.get("forced")]


def test_an_intervention_shows_up_in_the_next_season_record(world, tmp_path):
    house = world.active_houses()[0]["house"]
    apply_turn(
        world.conn,
        turn_file(tmp_path, [
            {"op": "adjust_stat", "house": house, "stat": "cohesion", "delta": -7,
             "reason": "a quarrel in the household"},
        ]),
    )
    record = world.run_season()
    interventions = record["interventions"]
    assert interventions, "the season log must carry the director's hand"
    assert interventions[0]["operation"] == "adjust_stat"
    assert interventions[0]["reason"] == "a quarrel in the household"


def test_a_granted_house_is_built_by_the_engine(world, tmp_path):
    """The director chooses the seat and the shape; the banks supply the name,
    the peerage, the colours, the holder and the opening stats."""
    unclaimed = world.conn.execute(
        "SELECT r.name_en FROM ridings r WHERE r.province = 'ON' AND NOT EXISTS"
        " (SELECT 1 FROM holdings h WHERE h.fed_id = r.fed_id AND h.released_event_id IS NULL)"
        " ORDER BY r.name_en LIMIT 1"
    ).fetchone()["name_en"]

    apply_turn(
        world.conn,
        turn_file(tmp_path, [
            {"op": "grant_house", "riding": unclaimed, "community": "Irish Catholic",
             "rank": "Viscount", "tag": "Progressive", "surname": "Kavanagh"},
        ]),
    )

    granted = world.conn.execute(
        "SELECT h.house, h.peerage, h.rank, h.primary_hex, s.community, s.tag"
        " FROM houses h JOIN house_stats s ON s.house = h.house"
        " WHERE h.house LIKE 'Kavanagh%'"
    ).fetchone()
    assert granted is not None
    assert granted["rank"] == "Viscount"
    assert granted["tag"] == "Progressive"
    assert granted["community"] == "Irish Catholic"
    assert granted["peerage"].startswith("Viscount Kavanagh of ")
    assert re.match(r"^#[0-9a-f]{6}$", granted["primary_hex"])
    assert world.holder(granted["house"]) is not None


# ------------------------------------------------------- stop conditions ----


def test_all_six_stop_conditions_are_known():
    assert sim.STOP_CONDITIONS == {
        "removal", "challenge", "major", "marquis", "partition", "extinction",
    }


def test_an_unknown_stop_condition_is_refused(world):
    with pytest.raises(sim.SimError):
        world.run(1, stop_on=("apocalypse",))


def test_a_run_halts_on_a_removal(world, monkeypatch):
    """Synthesised rather than waited for: a real extinction is dozens of
    seasons away, and what is under test is the halt, not the cause."""
    real_run_season = world.run_season
    removed = {}

    def run_season_then_remove(*args, **kwargs):
        record = real_run_season(*args, **kwargs)
        if record["season"] == 3 and not removed:
            house = world.active_houses()[0]["house"]
            world._remove_house(house, record["season"], reason="test")
            removed["house"] = house
        return record

    monkeypatch.setattr(world, "run_season", run_season_then_remove)
    records = world.run(10, stop_on=("removal",))

    assert removed, "the test did not manage to remove a house"
    # The world already stands at season 1, so run() opens at season 2: the
    # removal in season 3 is the second record, and the run stops there.
    assert [record["season"] for record in records] == [2, 3]
    assert records[-1]["stopped_on"] == ["removal"]


def test_the_run_summary_says_what_changed(world):
    before = world.counts()
    records = world.run(3)
    summary = world.run_summary(records, before)

    assert summary["seasons_run"] == 3
    assert summary["houses_before"] == before[0]
    assert summary["ridings_before"] == before[1]
    assert summary["season_to"] == world.season_no
    assert len(summary["chronicle"]) <= sim.SUMMARY_CHRONICLE_LINES
    json.dumps(summary)  # the workflow parses this off stdout


# ------------------------------------------------------------- the console --


@pytest.fixture(scope="module")
def console(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("console")
    conn = load_seed.build(tmp / "c.db", seed=scenario.seed_dir("new"))
    world = sim.World(conn, world_seed=1867)
    world.initialise(1867)
    site.write_site(conn, out_dir=tmp)
    return tmp / site.SITE_DIRNAME


def test_the_console_renders_every_control(console):
    html = (console / "console.html").read_text(encoding="utf-8")
    for control in (
        'id="token"', 'id="connect"', 'id="disconnect"',
        'id="run"', 'name="stop"',
        'data-op="set_objective"', 'data-op="veto_objective"', 'data-op="force_action"',
        'data-op="adjust_stat"', 'data-op="grant_house"', 'data-op="set_clock"',
        'data-op="relation"',
        'id="load-rules"', 'id="propose-rules"',
        'id="build-narrate"', 'id="copy-narrate"',
        'id="rebuild"', 'id="runs"',
    ):
        assert control in html, control


def test_the_console_holds_no_token(console):
    """The token is the director's and lives in their browser. Nothing that is
    published may contain one, or resemble a place one could be baked in."""
    for name in ("console.html", "console.js"):
        text = (console / name).read_text(encoding="utf-8")
        assert "github_pat_" not in text.replace("github_pat_…", "")
        assert "ghp_" not in text
        assert "Authorization: Bearer gh" not in text


def test_the_console_explains_where_the_token_lives(console):
    html = (console / "console.html").read_text(encoding="utf-8")
    assert "local storage" in html
    assert "github.com/settings/personal-access-tokens" in html
    assert "api.github.com" in html


def test_without_a_token_everything_renders_and_nothing_can_fire(console):
    """Degrading gracefully means the page is still readable and honest about
    why the buttons do nothing — not that the page is empty."""
    html = (console / "console.html").read_text(encoding="utf-8")
    js = (console / "console.js").read_text(encoding="utf-8")

    assert html.count("data-needs-token") >= 5
    assert "button.disabled = !connected" in js
    assert "Connect a GitHub token first" in js
    assert "Not connected" in js


def test_the_console_dispatches_the_engine_workflow(console):
    js = (console / "console.js").read_text(encoding="utf-8")
    assert "actions/workflows/' + WORKFLOW + '/dispatches" in js
    assert "engine.yml" in js
    assert "https://api.github.com/repos/" in js
    assert "var REPO = 'mdiamond95/house-of-cards'" in js
    for command in ("run", "intervene", "rules", "rebuild"):
        assert f"command: '{command}'" in js


def test_the_console_falls_back_to_repository_dispatch_on_a_403(console):
    """A token with Contents read/write but not Actions read/write gets a 403
    from workflow_dispatch; the console must retry as a repository_dispatch
    rather than just reporting the failure (see engine.yml's second trigger)."""
    js = (console / "console.js").read_text(encoding="utf-8")
    assert "err.status = response.status" in js
    assert "error.status !== 403" in js
    assert "event_type: 'engine'" in js
    assert "client_payload: inputs" in js
    # The fallback posts straight to the repo's own /dispatches, not the
    # workflow-scoped endpoint workflow_dispatch needs.
    assert "api('/dispatches'" in js


def test_the_console_polls_every_ten_seconds(console):
    js = (console / "console.js").read_text(encoding="utf-8")
    assert "var POLL_MS = 10000" in js


def test_the_narrate_block_names_only_the_record(console):
    js = (console / "console.js").read_text(encoding="utf-8")
    assert "NARRATE_TEMPLATE" in js
    assert "hard rule 9" in js
    # The console builds text for a person to paste; it calls no model itself.
    for needle in ("anthropic", "api.anthropic", "openai"):
        assert needle not in js.lower()


def test_the_archive_has_no_console(tmp_path):
    import build_archive

    build_archive.build_archive(out_dir=tmp_path)
    archive = tmp_path / site.SITE_DIRNAME / site.ARCHIVE_DIRNAME
    assert not (archive / "console.html").exists()
    for path in archive.rglob("*.html"):
        assert "console.html" not in path.read_text(encoding="utf-8"), path.name
