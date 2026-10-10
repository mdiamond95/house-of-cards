"""Rules 1.0 `water_crossings` and `block_grants`: the hex board, step 3
(docs/hex-trial/v2/README.md; rules/README.md).

* water_crossings: a water row of adjacency.csv joins two units for expansion
  targets, claim targets and neighbouring houses; an Expand across water costs
  board.json's water_crossings.expand_cost more; enclosure stays land only.
* block_grants: a Crown founding on a resolution-4 hexagon also grants up to
  board.json's block_grants.extra_hexes of its open, unclaimed resolution-4 land
  neighbours, the most populous first; a city hex is granted alone.
* both are false in 0.7-0.9 and on in the draft, and change nothing on a riding
  set, which has no water rows and no `resolution` column.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import load_seed  # noqa: E402
from hoc import rules_data, scenario, sim  # noqa: E402

HEX = "meridian-hex-v1.0.5"
FLAGS = ("water_crossings", "block_grants")


def world(tmp_path, key, seed=1867, **flags):
    rules = rules_data.load_rules(version="1.0")
    rules.features = dict(rules.features, **flags)
    name = "-".join(f"{k}{int(v)}" for k, v in sorted(flags.items())) or "draft"
    conn = load_seed.build(tmp_path / f"{key}-{name}-{seed}.db", seed=scenario.blank_seed_dir(), reference_data=key)
    return sim.World(conn, rules=rules, world_seed=seed, seasons_dir=tmp_path / f"{key}-{name}-{seed}")


def fed_of(w, name):
    return w.conn.execute("SELECT fed_id FROM ridings WHERE name_en = ?", (name,)).fetchone()["fed_id"]


def test_the_flags_are_the_drafts_alone():
    for flag in FLAGS:
        assert rules_data.FEATURE_DEFAULTS[flag] is False
        for version in ("0.7", "0.8", "0.9"):
            assert rules_data.load_features(version)[flag] is False
        assert rules_data.load_features("1.0")[flag] is True
    board = rules_data.load_rules(version="1.0").board
    assert board["water_crossings"]["expand_cost"] == 5
    assert board["block_grants"]["extra_hexes"] == 2
    assert rules_data.load_rules(version="0.9").board == {}


# ------------------------------------------------------------ water_crossings --


def test_a_water_row_gives_an_expansion_target_at_a_cost(tmp_path):
    on = world(tmp_path, HEX, water_crossings=True, block_grants=False)
    off = world(tmp_path, HEX, water_crossings=False, block_grants=False)
    for w in (on, off):
        with w.conn:
            w.initialise(1867, seat="Digby")
    house = on.conn.execute("SELECT house FROM holdings").fetchone()["house"]
    sussex = fed_of(on, "Sussex")
    assert sussex in on.expansion_targets(house)
    assert sussex not in off.expansion_targets(off.conn.execute("SELECT house FROM holdings").fetchone()["house"])
    land = [f for f in on.expansion_targets(house) if f != sussex and f in on._land_neighbours(fed_of(on, "Digby"))]
    assert land
    assert on.expand_cost(house, sussex) == on.expand_cost(house, land[0]) - on.wealth_offset(land[0]) \
        + on.wealth_offset(sussex) + 5
    # Enclosure reads land rows alone.
    assert on.has_expansion_target(house) == off.has_expansion_target(off.conn.execute("SELECT house FROM holdings").fetchone()["house"])


def test_a_water_row_makes_neighbouring_houses(tmp_path):
    w = world(tmp_path, HEX, water_crossings=True, block_grants=False)
    with w.conn:
        w.initialise(1867, seat="Digby")
        w.found_house(1, seat="Sussex")
    houses = [r["house"] for r in w.conn.execute("SELECT DISTINCT house FROM holdings ORDER BY house")]
    assert len(houses) == 2
    assert w.neighbouring_houses(houses[0]) == [houses[1]]
    off = world(tmp_path, HEX, water_crossings=False, block_grants=False)
    with off.conn:
        off.initialise(1867, seat="Digby")
        off.found_house(1, seat="Sussex")
    first = off.conn.execute("SELECT house FROM holdings ORDER BY house").fetchone()["house"]
    assert off.neighbouring_houses(first) == []


# --------------------------------------------------------------- block_grants --


def test_a_founding_on_a_hexagon_grants_its_most_populous_open_neighbours(tmp_path):
    w = world(tmp_path, HEX, water_crossings=False, block_grants=True)
    with w.conn:
        w.initialise(1867, seat="Brantford")
    seat = fed_of(w, "Brantford")
    rows = w.conn.execute("SELECT fed_id, seat_order FROM holdings ORDER BY seat_order").fetchall()
    assert rows[0]["fed_id"] == seat and len(rows) == 3
    stats = w.riding_stats
    expected = sorted(
        (n for n in w._land_neighbours(seat) if stats[n]["resolution"] == 4 and w.riding_open(n, 1867)),
        key=lambda n: (-stats[n]["population"], n))[:2]
    assert [r["fed_id"] for r in rows[1:]] == expected
    delta = json.loads(w.conn.execute("SELECT mechanical_delta FROM events WHERE kind = 'founding'").fetchone()[0])
    assert delta["block"] == [w._riding_name(f) for f in expected]


def test_a_founding_on_a_city_hex_grants_that_hex_alone(tmp_path):
    w = world(tmp_path, HEX, water_crossings=False, block_grants=True)
    with w.conn:
        w.initialise(1867, seat="Toronto")
    assert w.conn.execute("SELECT COUNT(*) AS n FROM holdings").fetchone()["n"] == 1


def seasons(w, turns):
    with w.conn:
        w.initialise(w.world_seed)
        while w.season_no < turns:
            w.run_season()
    files = {p.name: p.read_bytes() for p in sorted(w.seasons_dir.iterdir())}
    w.conn.close()
    return files


@pytest.mark.parametrize("key", ["ne-2026", "meridian-v1.0.3"])
@pytest.mark.parametrize("seed", [1867, 2, 3])
def test_a_riding_game_is_the_same_with_both_flags_on_and_off(tmp_path, key, seed):
    on = seasons(world(tmp_path, key, seed=seed, water_crossings=True, block_grants=True), 100)
    off = seasons(world(tmp_path, key, seed=seed, water_crossings=False, block_grants=False), 100)
    assert len(on) == 100 and on == off
