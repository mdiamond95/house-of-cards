"""Rules are versioned, and a season replays under the rules it was played with.

The failure this prevents is quiet and expensive: tune a number, and every
season already in the record starts replaying differently. `scripts/rebuild.py`
stops reproducing `hoc.db`, and the referee starts refusing seasons that were
correct when they were played — with a diff that names a draw rather than the
rules change that caused it.

So the tests here are about the machinery, not about any one rule: that a
version is loadable and frozen, that the two engines agree on what the flags
mean, that a season file's recorded version is what gets loaded to replay it,
and that a version this checkout does not have is refused rather than guessed
at.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from hoc import rules_data, scenario, sim  # noqa: E402
from hoc.rules_data import RulesDataError  # noqa: E402

JS_RULES = ROOT / "web" / "engine" / "rules.js"


# ------------------------------------------------------------- the layout --


def test_the_current_version_exists_and_loads():
    version = rules_data.current_version()
    assert version in rules_data.available_versions()
    bundle = rules_data.load_rules()
    assert bundle.version == version
    assert bundle.actions and bundle.events and bundle.places


def test_no_table_is_left_outside_a_version():
    """A table at rules/actions.csv would be loadable and would belong to no
    version at all — which is exactly the ambiguity versioning removes."""
    strays = sorted(
        p.name for p in rules_data.RULES_ROOT.iterdir()
        if p.is_file() and p.suffix in {".csv", ".json"}
    )
    assert strays == [], f"rules tables outside a version directory: {strays}"


def test_every_version_loads_and_declares_only_known_features():
    for version in rules_data.available_versions():
        bundle = rules_data.load_rules(version=version)
        assert bundle.version == version
        assert set(bundle.features) <= set(rules_data.FEATURE_DEFAULTS)


def test_an_unknown_version_is_refused_with_a_clear_error():
    with pytest.raises(RulesDataError) as caught:
        rules_data.load_rules(version="9.9")
    message = str(caught.value)
    assert "9.9" in message
    assert "Available:" in message
    # It must say why replaying it under something else is not the answer.
    assert "must not be replayed under a different one" in message


# ------------------------------------------ the flags, in both engines ------


def _js_feature_defaults():
    text = JS_RULES.read_text(encoding="utf-8")
    start = text.index("export const FEATURE_DEFAULTS = {")
    end = text.index("};", start)
    body = text[text.index("{", start) + 1:end]
    out = {}
    for line in body.splitlines():
        line = line.strip().rstrip(",")
        if not line or line.startswith("//"):
            continue
        name, _, value = line.partition(":")
        out[name.strip()] = value.strip() == "true"
    return out


def test_the_two_engines_know_the_same_flags():
    """A flag that defaulted differently in the two engines would be a
    divergence the cross-check finds only when that code path is reached — that
    is, in a game nobody is watching."""
    assert _js_feature_defaults() == rules_data.FEATURE_DEFAULTS


def test_every_flag_defaults_to_off():
    """A version's features.json says what that version turns *on*. A flag that
    defaulted to true would change the behaviour of every version written before
    it existed, which is the one thing this arrangement exists to prevent."""
    assert all(value is False for value in rules_data.FEATURE_DEFAULTS.values())
    assert all(value is False for value in _js_feature_defaults().values())


def test_a_features_file_naming_an_unknown_flag_is_refused(tmp_path):
    version_root = tmp_path / "versions" / "9.9"
    shutil.copytree(rules_data.version_dir(rules_data.current_version()), version_root)
    (version_root / "features.json").write_text(
        json.dumps({"a_flag_the_engine_never_heard_of": True}), encoding="utf-8"
    )
    (tmp_path / "current.txt").write_text("9.9\n", encoding="utf-8")
    with pytest.raises(RulesDataError) as caught:
        rules_data.load_features("9.9", root=tmp_path)
    assert "a_flag_the_engine_never_heard_of" in str(caught.value)


# ------------------------------------------------- replay under the record --


def test_the_committed_record_names_a_version_this_checkout_has():
    """Every season in the record must be replayable. A season naming a version
    that is not here is a record that cannot be rebuilt."""
    import rebuild as rebuild_script

    known = set(rules_data.available_versions())
    seen = {}
    for path in rebuild_script.season_files():
        record = json.loads(path.read_text(encoding="utf-8"))
        version = record.get("rules_version")
        assert version, f"{path.name} records no rules_version"
        assert version in known, f"{path.name} was played under rules {version}, which is not here"
        seen.setdefault(version, []).append(rebuild_script.season_number(path))
    assert seen, "the record holds no seasons"


def test_a_world_replays_under_the_version_the_season_recorded(tmp_path):
    """The whole point, stated as a test: a world constructed for a replay picks
    up the recorded version's tables, not whatever current.txt says today."""
    import load_seed

    conn = load_seed.build(tmp_path / "r.db", seed=scenario.seed_dir("new"))
    world = sim.World(conn, world_seed=1867, rules_version="0.7")
    assert world.rules_version == "0.7"
    assert world.rules.version == "0.7"
    assert world.feature("local_designations") is False
    conn.close()


def test_switching_version_mid_replay_reloads_the_tables(tmp_path):
    """A record long enough to span a version change — which every long game
    eventually is — must not carry the old version's action table across the
    boundary."""
    import load_seed

    versions = rules_data.available_versions()
    if len(versions) < 2:
        pytest.skip("only one rules version in this checkout")

    conn = load_seed.build(tmp_path / "r.db", seed=scenario.seed_dir("new"))
    world = sim.World(conn, world_seed=1867, rules_version=versions[0])
    first_actions = world.actions
    world.use_rules_version(versions[-1])
    assert world.rules_version == versions[-1]
    assert world.rules.version == versions[-1]
    # The derived lookups are rebuilt, not carried over.
    assert world.actions is not first_actions
    conn.close()


def test_a_season_claiming_an_unknown_version_is_rejected(tmp_path, monkeypatch):
    """A synthetic season file naming a version this checkout does not have must
    stop the replay with an error that names the version — not be replayed under
    some other version and quietly produce a different game."""
    import load_seed
    import rebuild as rebuild_script

    root = tmp_path / "scenarios"
    (root / "new").mkdir(parents=True)
    shutil.copytree(scenario.SCENARIOS_DIR / "new" / "seed", root / "new" / "seed")
    shutil.copy(scenario.SCENARIOS_DIR / "new" / "scenario.json", root / "new")
    (root / "current.txt").write_text("new\n", encoding="utf-8")
    seasons = root / "new" / "seasons"
    seasons.mkdir()

    real = json.loads(
        (scenario.SCENARIOS_DIR / "new" / "seasons" / "0001.json").read_text(encoding="utf-8")
    )
    real["rules_version"] = "9.9"
    (seasons / "0001.json").write_text(json.dumps(real), encoding="utf-8")

    monkeypatch.setattr(scenario, "SCENARIOS_DIR", root)
    with pytest.raises(RulesDataError) as caught:
        rebuild_script.rebuild(tmp_path / "x.db", export=False, name="new", verbose=False)
    assert "9.9" in str(caught.value)


# --------------------------------------------------- the record still holds --


def test_the_committed_seasons_rebuild_byte_identically(tmp_path):
    """Seasons 1–41 were played under rules 0.7 and must keep replaying under
    it, byte for byte, whatever current.txt says now. This is the test that
    fails if a rules change was made in place rather than as a new version."""
    import rebuild as rebuild_script

    committed = {
        rebuild_script.season_number(path): path.read_bytes()
        for path in rebuild_script.season_files()
    }
    if not committed:
        pytest.skip("the record holds no seasons")

    out = tmp_path / "seasons"
    out.mkdir()
    conn = rebuild_script.rebuild(
        tmp_path / "rebuilt.db", export=False, verbose=False, seasons_out=out
    )
    conn.close()

    for season, original in sorted(committed.items()):
        produced = (out / f"{season:04d}.json").read_bytes()
        assert produced == original, f"season {season} no longer replays to the same bytes"
