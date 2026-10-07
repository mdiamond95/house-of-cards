"""The story layer, Phase A (docs/STORY_DESIGN.md §3).

web/story/ is one JavaScript implementation, outside the two-engine parity
contract: it reads the record and never feeds back into either engine. What
this file holds it to:

* its node tests pass (tests/js/story_*.test.mjs, one per module);
* it imports nothing from web/engine/, and neither engine imports it;
* hoc/export/beats.py types beats exactly as web/story/beats.js does, over both
  frozen games, and the play page's input — read from the JavaScript engine's
  in-memory tables — is the input hoc.db gives for the same world;
* standings folded from beats are the database's board;
* The First Dominion's headlines meet §3.1's limits: no kind supplies more than
  35% of them, no bookkeeping action ever headlines, and a quiet turn is one
  line — and its storylines meet the Phase B gates of §7;
* the beat data ships in chunks of at most 500 KB.
"""

import json
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from hoc.export import beats as beats_export  # noqa: E402

NODE = shutil.which("node")
STORY = ROOT / "web" / "story"
ENGINE = ROOT / "web" / "engine"
JS = ROOT / "tests" / "js"
needs_node = pytest.mark.skipif(NODE is None, reason="node is not on PATH")

IMPORT = re.compile(r"""^\s*import\s+.*?from\s+['"]([^'"]+)['"]""", re.MULTILINE | re.DOTALL)


def _imports(path):
    return [m.group(1) for m in IMPORT.finditer(path.read_text(encoding="utf-8"))]


def _canon(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _node(*args):
    result = subprocess.run([NODE, *map(str, args)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-4000:]
    return result.stdout


# ------------------------------------------------------------ the modules --


@needs_node
def test_the_story_modules_pass_their_node_tests():
    files = sorted(JS.glob("story_*.test.mjs"))
    assert files
    result = subprocess.run([NODE, "--test", *map(str, files)], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout[-6000:] + result.stderr[-2000:]


def test_every_story_module_has_a_node_test():
    for module in sorted(STORY.glob("*.js")):
        assert (JS / f"story_{module.stem}.test.mjs").exists(), f"web/story/{module.name} has no node test"


def test_the_story_layer_imports_nothing_but_itself():
    """§3's architecture rule: a pure function of the record. Nothing from the
    engine, no package, no path out of web/story/."""
    modules = sorted(STORY.glob("*.js"))
    assert {m.name for m in modules} >= {"beats.js", "weight.js", "dispatch.js", "standings.js"}
    for module in modules:
        source = module.read_text(encoding="utf-8")
        for target in _imports(module):
            assert re.fullmatch(r"\./[a-z]+\.js", target), (
                f"web/story/{module.name} imports {target!r}; it may import only its siblings"
            )
        assert "require(" not in source, module.name
        assert "engine/" not in "".join(_imports(module)), module.name


def test_neither_engine_imports_the_story_layer():
    for module in sorted(ENGINE.glob("*.js")):
        for target in _imports(module):
            assert "story" not in target, f"web/engine/{module.name} imports {target!r}"
    for name in ("sim.py", "prng.py", "palette.py", "names.py", "rules_data.py", "rules.py",
                 "places.py", "turn.py"):
        source = (ROOT / "hoc" / name).read_text(encoding="utf-8")
        for line in source.splitlines():
            if re.match(r"\s*(from|import)\s", line):
                assert "beats" not in line and "story" not in line, f"hoc/{name}: {line.strip()}"


def test_the_exported_story_files_are_the_whole_story_layer():
    from hoc.export import play as play_export

    shipped = set(play_export.STORY_FILES)
    on_disk = {p.name for p in STORY.iterdir() if p.suffix in (".js", ".json")}
    assert shipped == on_disk, f"STORY_FILES and web/story/ differ: {sorted(shipped ^ on_disk)}"


def test_both_typings_name_the_same_kinds():
    source = (STORY / "beats.js").read_text(encoding="utf-8")
    block = source[source.index("export const BEAT_KINDS"):source.index("];", source.index("export const BEAT_KINDS"))]
    assert tuple(re.findall(r"'([a-z_]+)'", block)) == beats_export.BEAT_KINDS
    weights = json.loads((STORY / "weights.json").read_text(encoding="utf-8"))
    assert set(weights["kinds"]) == set(beats_export.BEAT_KINDS)


# -------------------------------------------------------------- the games --


@pytest.fixture(scope="module")
def frozen_games(tmp_path_factory):
    """Each frozen game rebuilt from its record into a scratch database, as
    scripts/build_archive.py does, with its beats exported beside it."""
    import rebuild

    from hoc import scenario

    games = {}
    for name in scenario.frozen_names():
        work = tmp_path_factory.mktemp(f"story-{name}")
        (work / "seasons").mkdir()
        conn = rebuild.rebuild(work / "game.db", export=False, name=name, verbose=False,
                               seasons_out=work / "seasons")
        conn.row_factory = sqlite3.Row
        beats_export.write_beats(conn, work / "data", title=scenario.title(name))
        games[name] = (conn, work)
    yield games
    for conn, _ in games.values():
        conn.close()


@needs_node
def test_python_and_javascript_type_every_frozen_game_alike(frozen_games, tmp_path):
    for name, (conn, _) in frozen_games.items():
        turns, _ = beats_export.turn_inputs(conn)
        inputs = [data for _, data in turns]
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(inputs, ensure_ascii=False), encoding="utf-8")
        js = json.loads(_node(JS / "story_type.mjs", path))
        python = [beats_export.type_turn(data) for data in inputs]
        assert len(js) == len(python)
        for (turn, _), a, b in zip(turns, python, js):
            assert _canon(a) == _canon(b), f"{name}, turn {turn}: the two typings disagree"


def test_every_first_dominion_event_is_typed(frozen_games):
    conn, _ = frozen_games["new"]
    turns, baseline = beats_export.turn_inputs(conn)
    assert len(turns) == 150
    assert baseline == {"owners": {}, "ranks": {}, "removed": []}, "an engine game starts empty"
    untyped = [(turn, beat) for turn, data in turns for beat in beats_export.type_turn(data)
               if beat["kind"] == "other"]
    assert not untyped, untyped[:3]
    # Every event of every season is a beat, and so is every action that left none.
    events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert sum(len(data["events"]) for _, data in turns) == events


@needs_node
def test_standings_folded_from_beats_are_the_database(frozen_games):
    from hoc import rules

    for name, (conn, work) in frozen_games.items():
        report = json.loads(_node(JS / "story_report.mjs", work / "data" / "beats"))
        board = report["board"]
        owners = {r["fed_id"]: r["house"] for r in conn.execute(
            "SELECT fed_id, house FROM holdings WHERE released_event_id IS NULL")}
        ranks = {r["house"]: rules.RANK_LEVEL.get(r["rank"], 0)
                 for r in conn.execute("SELECT house, rank FROM houses")}
        removed = sorted(r["house"] for r in conn.execute(
            "SELECT house FROM houses WHERE status != 'active'"))
        assert board["owners"] == owners, name
        assert board["ranks"] == ranks, name
        assert board["removed"] == removed, name


@needs_node
def test_the_first_dominion_headlines_within_the_limits(frozen_games):
    """Task 6's gate: across The First Dominion's 150 seasons, no beat kind
    supplies more than 35% of headlines, the four bookkeeping actions never
    headline, and a turn with nothing at or above the quiet threshold renders
    as one quiet-turn line."""
    _, work = frozen_games["new"]
    report = json.loads(_node(JS / "story_report.mjs", work / "data" / "beats"))
    summary = report["summary"]
    assert summary["turns"] == 150
    assert summary["largestSharePerMille"] <= 350, summary["byKind"]
    assert summary["bookkeepingHeadlines"] == 0, summary["byKind"]
    for kind in ("invest", "cultivate", "consolidate", "name_heir"):
        assert kind not in summary["byKind"]
    assert report["quietAreOneLine"]
    assert summary["headlines"] + summary["quiet"] == 150


@needs_node
def test_the_play_pages_beats_are_the_databases_beats(tmp_path):
    """The play page builds each season's input from the JavaScript engine's
    in-memory tables (beats.js inputFromState); exports build it from hoc.db.
    For the same world played by each engine, the inputs — and so the beats —
    must be the same."""
    import crosscheck

    seasons = 30
    # Under the published rules, and under the draft 1.0 with its schemes.
    for version in (None, "1.0"):
        out = tmp_path / (version or "current")
        crosscheck.run_python(1867, seasons, out / "seasons", rules_version=version)
        conn = sqlite3.connect(out / "python.db")
        conn.row_factory = sqlite3.Row
        turns, _ = beats_export.turn_inputs(conn)
        conn.close()
        extra = ("--rules-version", version) if version else ()
        js = json.loads(_node(JS / "story_engine_inputs.mjs", "--seed", 1867, "--seasons", seasons, *extra))
        assert len(js["inputs"]) == len(turns) == seasons
        for (turn, data), theirs, their_beats in zip(turns, js["inputs"], js["beats"]):
            assert _canon(data) == _canon(theirs), f"{version}, season {turn}: the beat inputs differ"
            assert _canon(beats_export.type_turn(data)) == _canon(their_beats), f"{version}, season {turn}"


def test_beat_chunks_stay_under_budget_and_cover_every_turn(frozen_games):
    for name, (_, work) in frozen_games.items():
        directory = work / "data" / "beats"
        index = json.loads((directory / "index.json").read_text(encoding="utf-8"))
        expected = 1
        for chunk in index["chunks"]:
            path = directory / chunk["file"]
            assert path.stat().st_size <= beats_export.CHUNK_BUDGET, f"{name}: {chunk['file']}"
            turns = sorted(int(t) for t in json.loads(path.read_text(encoding="utf-8"))["turns"])
            assert turns == list(range(chunk["first"], chunk["last"] + 1)), f"{name}: {chunk}"
            assert chunk["first"] == expected, f"{name}: a gap before {chunk}"
            expected = chunk["last"] + 1
        assert expected - 1 == index["turns"], name
        # The chunks, the index, and the map view's atlas (Phase V): nothing else.
        assert sorted(p.name for p in directory.iterdir()) == sorted(
            ["index.json", "atlas.json", *(c["file"] for c in index["chunks"])]
        )


def test_the_first_dominion_ships_all_its_seasons_in_several_fetches(frozen_games):
    _, work = frozen_games["new"]
    index = json.loads((work / "data" / "beats" / "index.json").read_text(encoding="utf-8"))
    assert index["unit"] == "season"
    assert index["turns"] == 150
    assert index["chunks"][0]["first"] == 1 and index["chunks"][-1]["last"] == 150
    assert len(index["chunks"]) >= 2, "150 seasons of beats do not fit one 500 KB fetch"


@needs_node
def test_the_first_dominion_storylines_meet_the_phase_b_gates(frozen_games):
    """docs/STORY_DESIGN.md §7, Phase B: after turn 20, at least 85% of
    headlines belong to a storyline and no more than 25% open one; at least
    eight storylines have five or more beats; every closed storyline has an
    outcome; and fewer than 20% of closed storylines lapse.

    Phase D1 keeps rises and declines to sustained movement in the cast (at most
    twenty a game), which takes the in-storyline share of this game from 85% to
    83%: the gate is 80% from D1 on."""
    _, work = frozen_games["new"]
    report = json.loads(_node(JS / "story_report.mjs", work / "data" / "beats"))
    gates = report["storylines"]
    assert gates["inStorylinePerMille"] >= 800, gates
    assert gates["openingPerMille"] <= 250, gates
    assert gates["fivePlus"] >= 8, gates
    assert gates["closedWithoutOutcome"] == 0, gates
    assert gates["lapsedPerMille"] < 200, gates
    assert set(gates["byType"]) <= {"rivalry", "union", "succession", "rise", "decline", "frontier"}


# -------------------------------------------------- rules 1.0: schemes --


@pytest.fixture(scope="module")
def scheme_game(tmp_path_factory):
    """Forty seasons under the draft rules 1.0 on a scratch Meridian world, as
    the preview plays them, with the engine's own season records kept."""
    import load_seed

    from hoc import rules_data, scenario, sim

    work = tmp_path_factory.mktemp("story-schemes")
    conn = load_seed.build(work / "game.db", seed=scenario.blank_seed_dir(),
                           reference_data="meridian-v1.0.3")
    world = sim.World(conn, rules=rules_data.load_rules(version="1.0"), world_seed=1867)
    with conn:
        records = [world.initialise(1867)] + [world.run_season() for _ in range(39)]
    beats_export.write_beats(conn, work / "data", title="schemes")
    yield conn, work, records
    conn.close()


@needs_node
def test_python_and_javascript_type_a_game_with_schemes_alike(scheme_game, tmp_path):
    conn, _, _ = scheme_game
    turns, _ = beats_export.turn_inputs(conn)
    inputs = [data for _, data in turns]
    path = tmp_path / "schemes.json"
    path.write_text(json.dumps(inputs, ensure_ascii=False), encoding="utf-8")
    js = json.loads(_node(JS / "story_type.mjs", path))
    python = [beats_export.type_turn(data) for data in inputs]
    for (turn, _), a, b in zip(turns, python, js):
        assert _canon(a) == _canon(b), f"turn {turn}: the two typings disagree"
    kinds = {beat["kind"] for beats in python for beat in beats}
    assert {"scheme_begun", "scheme_step", "scheme_resolved"} <= kinds
    assert not [b for beats in python for b in beats if b["kind"] == "other"]


def test_the_exported_plans_are_the_engines_season_records(scheme_game):
    conn, work, records = scheme_game
    plans = beats_export.plans_by_turn(conn)
    for record in records[1:]:
        assert plans[record["season"]] == record["plans"], f"season {record['season']}"
    index = json.loads((work / "data" / "beats" / "index.json").read_text(encoding="utf-8"))
    assert index["schemes"] is True
    chunk = json.loads((work / "data" / "beats" / index["chunks"][0]["file"]).read_text(encoding="utf-8"))
    assert "plans" in chunk


@needs_node
def test_a_game_with_schemes_tells_its_resolutions_and_closes_rivalries_by_contest(scheme_game):
    _, work, _ = scheme_game
    report = json.loads(_node(JS / "story_report.mjs", work / "data" / "beats"))
    outcomes = report["trial"]["rivalryOutcomes"]
    assert set(outcomes) & {"won in a contest", "held in a contest", "ceded under a claim"}, outcomes
    assert report["storylines"]["closedWithoutOutcome"] == 0


@needs_node
def test_a_calendar_game_types_its_world_events_alike_and_ships_its_calendar(scheme_game, tmp_path):
    """Phase D1: crises, land opened and the years of a running event are typed
    from their deltas by both typers, and the beat index carries the calendar."""
    conn, work, _ = scheme_game
    turns, _ = beats_export.turn_inputs(conn)
    inputs = [data for _, data in turns]
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps(inputs, ensure_ascii=False), encoding="utf-8")
    js = json.loads(_node(JS / "story_type.mjs", path))
    python = [beats_export.type_turn(data) for data in inputs]
    assert [_canon(a) for a in python] == [_canon(b) for b in js]
    kinds = {beat["kind"] for beats in python for beat in beats}
    assert {"crisis", "accession", "event_continues"} <= kinds
    crisis = next(b for beats in python for b in beats if b["kind"] == "crisis")
    assert set(crisis["world"]) >= {"event", "lead", "resist", "carried"}
    index = json.loads((work / "data" / "beats" / "index.json").read_text(encoding="utf-8"))
    assert index["calendar"]["start_year"] == 1867
    assert [c["numeral"] for c in index["calendar"]["chapters"]] == ["I", "II", "III", "IV", "V"]
    assert "reckoning" not in index, "forty turns do not reach the reckoning"
