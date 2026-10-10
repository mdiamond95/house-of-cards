"""Rules 1.0 `dated_openings` (rules/README.md; docs/hex-trial/v2/README.md).

Under `world_calendar`, a unit takes no grant, no expansion and no claim before
its opening year — the later of its opens_year and its first year under Canada —
and is open for good from then on. A Crown founding still needs a province.
The flag is false in 0.7–0.9 and on in the draft, in both engines (the
cross-check plays it). On the riding sets it repeats the atlas: the season
files of a draft game are the same with it on and off, but for the two ridings
the atlas takes out of Canada and back.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import load_seed  # noqa: E402
from hoc import rules_data, scenario, sim  # noqa: E402


def world(tmp_path, key, on=True, seed=1867):
    rules = rules_data.load_rules(version="1.0")
    rules.features = dict(rules.features, dated_openings=on)
    conn = load_seed.build(tmp_path / f"{key}-{on}.db", seed=scenario.blank_seed_dir(), reference_data=key)
    return sim.World(conn, rules=rules, world_seed=seed, seasons_dir=tmp_path / f"{key}-{on}-{seed}")


def test_the_flag_is_the_drafts_alone():
    assert rules_data.FEATURE_DEFAULTS["dated_openings"] is False
    for version in ("0.7", "0.8", "0.9"):
        assert rules_data.load_features(version)["dated_openings"] is False
    assert rules_data.load_features("1.0")["dated_openings"] is True


def test_the_opening_year_is_the_later_of_opens_year_and_the_atlas(tmp_path):
    w = world(tmp_path, "meridian-v1.0.3")
    assert w.opens_year("59001") == 1867 and w.opening_year("59001") == 1871  # British Columbia
    assert w.opening_year("11001") == 1873  # Prince Edward Island
    assert w.opening_year("10001") == 1949  # Newfoundland
    assert w.opening_year("35001") == 1867
    assert w.opening_year("46001") == 1870


def test_open_for_good_whatever_the_atlas_says_later(tmp_path):
    on, off = world(tmp_path, "meridian-v1.0.3"), world(tmp_path, "meridian-v1.0.3", on=False)
    # Nunavut's largest-share unit is the British Arctic Islands in 1876-1879.
    assert not off.riding_open("62001", 1877) and on.riding_open("62001", 1877)
    # Labrador is Newfoundland's, not Canada's, in 1927-1948.
    assert not off.riding_open("10004", 1930) and on.riding_open("10004", 1930)
    for w in (on, off):
        assert not w.riding_open("59001", 1870) and w.riding_open("59001", 1871)


def seasons(w, turns):
    with w.conn:
        w.initialise(w.world_seed)
        while w.season_no < turns:
            w.run_season()
    files = {p.name: p.read_bytes() for p in sorted(w.seasons_dir.iterdir())}
    w.conn.close()
    return files


@pytest.mark.parametrize("key,seed", [
    ("ne-2026", 1867), ("ne-2026", 2), ("ne-2026", 3),
    ("meridian-v1.0.3", 1867), ("meridian-v1.0.3", 2),
])
def test_a_riding_game_is_the_same_with_the_flag_on_and_off(tmp_path, key, seed):
    on = seasons(world(tmp_path, key, seed=seed), 100)
    off = seasons(world(tmp_path, key, on=False, seed=seed), 100)
    assert len(on) == 100 and on == off


def test_where_the_atlas_takes_a_riding_out_the_flag_keeps_it(tmp_path):
    # meridian-v1.0.3, seed 3: identical through turn 10; in 1877 Nunavut, out
    # of Canada in the atlas, is open, and a frontier draw sees it.
    on = seasons(world(tmp_path, "meridian-v1.0.3", seed=3), 11)
    off = seasons(world(tmp_path, "meridian-v1.0.3", on=False, seed=3), 11)
    assert all(on[n] == off[n] for n in sorted(on)[:10])
    assert on["0011.json"] != off["0011.json"]
