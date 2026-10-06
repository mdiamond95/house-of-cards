"""Rules 0.9: the atlas a house reads, and what its ground is worth.

`atlas_jurisdiction` closes a riding to a house while the house's personal year
is before the riding's opens_year (riding_stats.csv: 1867 for 269 ridings, 1870
for 74). `riding_endowments` lets a riding's wealth_tier move founding capital
and the cost of taking it. One test, or more, for each bullet of the director's
specification of the first flag, in its order; then the second flag's two
numbers; then the display. Every test plays on the meridian-v1.0.3 set, the
only one with the tables, and most compare 0.9 against 0.8 on the same ground
so that the flag is shown to be the thing that made the difference.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import crosscheck  # noqa: E402
import load_seed  # noqa: E402

from hoc import places, scenario, sim  # noqa: E402
from hoc.turn import TurnError, apply_turn  # noqa: E402

MERIDIAN = "meridian-v1.0.3"
SEED = 1867

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not on PATH, so the JavaScript engine cannot run"
)


# --------------------------------------------------------------- fixtures --


def _world(tmp_path, version, name="w"):
    conn = load_seed.build(
        tmp_path / f"{name}.db", seed=scenario.blank_seed_dir(), reference_data=MERIDIAN
    )
    return sim.World(conn, world_seed=SEED, rules_version=version)


@pytest.fixture
def world(tmp_path):
    world = _world(tmp_path, "0.9")
    yield world
    world.conn.close()


@pytest.fixture
def old_world(tmp_path):
    world = _world(tmp_path, "0.8", name="old")
    yield world
    world.conn.close()


def _stats():
    return places.riding_stats(ROOT / scenario.reference_set_dir(MERIDIAN))


def _late():
    return sorted(f for f, s in _stats().items() if s["opens_year"] == 1870)


def _province(world, fed_id):
    return world.conn.execute(
        "SELECT province FROM ridings WHERE fed_id = ?", (fed_id,)
    ).fetchone()["province"]


def _land(world, fed_id):
    return [
        row["n"] for row in world.conn.execute(
            "SELECT CASE WHEN fed_id_a = ? THEN fed_id_b ELSE fed_id_a END AS n FROM adjacency"
            " WHERE adjacency_type = 'land' AND (fed_id_a = ? OR fed_id_b = ?) ORDER BY n",
            (fed_id, fed_id, fed_id),
        )
    ]


def _frontier(world):
    """An 1867 riding with at least one 1870 land neighbour, and those neighbours."""
    stats = _stats()
    for fed_id in sorted(stats):
        if stats[fed_id]["opens_year"] != 1867:
            continue
        late = [n for n in _land(world, fed_id) if stats[n]["opens_year"] == 1870]
        if late:
            return fed_id, late
    raise AssertionError("the Meridian map has no 1867 riding touching an 1870 one")


def _hold(world, house, fed_ids):
    """Give a house ridings directly — test scaffolding on a scratch database,
    never a way the game moves."""
    for fed_id in fed_ids:
        world.conn.execute(
            "INSERT INTO holdings (house, fed_id, seat_order, hex, acquired_event_id)"
            " VALUES (?, ?, (SELECT COALESCE(MAX(seat_order), 0) + 1 FROM holdings"
            "                WHERE house = ? AND released_event_id IS NULL), '#123456', NULL)",
            (house, fed_id, house),
        )
    world._turn_cache = {}


def _found_at(world, fed_id, season=1):
    return world.found_house(season, seat=world._riding_name(fed_id), rng=world.rng_for(season))


def _found_named(world, name, season=1):
    return world.found_house(season, seat=name, rng=world.rng_for(season))


def _set_year(world, house, year):
    world.conn.execute("UPDATE clocks SET personal_year = ? WHERE house = ?", (year, house))
    world._turn_cache = {}


def _claim_all_but(world, keep, house):
    """Hand every unclaimed riding not in `keep` to `house`."""
    free = [
        row["fed_id"] for row in world.conn.execute(
            "SELECT fed_id FROM ridings r WHERE NOT EXISTS (SELECT 1 FROM holdings h"
            " WHERE h.fed_id = r.fed_id AND h.released_event_id IS NULL) ORDER BY fed_id"
        )
    ]
    _hold(world, house, [f for f in free if f not in keep])


class SpyRng:
    """Wraps a LoggingRandom, recording what every weighted draw and choice was
    offered, so a test can see what a closed riding was *not* offered."""

    def __init__(self, inner):
        self.inner = inner
        self.offered = []

    def weighted(self, options, purpose=None):
        self.offered.append((purpose, [name for name, _ in options]))
        return self.inner.weighted(options, purpose=purpose)

    def choice(self, sequence, purpose=None):
        self.offered.append((purpose, list(sequence)))
        return self.inner.choice(sequence, purpose=purpose)

    def __getattr__(self, name):
        return getattr(self.inner, name)


# ------------------------------------------------------------- the data --


def test_the_data_the_flag_reads():
    stats = _stats()
    years = sorted({s["opens_year"] for s in stats.values()})
    assert years == [1867, 1870]
    assert len(_late()) == 74
    assert sum(1 for s in stats.values() if s["opens_year"] == 1867) == 269


def test_the_flags_are_on_in_09_and_off_before():
    from hoc.rules_data import load_rules

    for version in ("0.7", "0.8"):
        rules = load_rules(version=version)
        assert not rules.feature("atlas_jurisdiction"), version
        assert not rules.feature("riding_endowments"), version
    rules = load_rules(version="0.9")
    assert rules.feature("atlas_jurisdiction") and rules.feature("riding_endowments")


# ------------------------------------- bullet 1: founding by the Crown --


def test_season_1_never_seats_a_house_on_a_closed_riding(world):
    for fed_id in _late()[:5]:
        with pytest.raises(sim.SimError) as caught:
            world.initialise(SEED, seat=world._riding_name(fed_id))
        message = str(caught.value)
        assert world._riding_name(fed_id) in message
        assert "1867" in message and "1870" in message


def test_season_1_may_still_seat_a_house_there_under_08(old_world):
    fed_id = _late()[0]
    record = old_world.initialise(SEED, seat=old_world._riding_name(fed_id))
    assert record["founded"]


def test_the_founding_roll_seats_only_on_opens_1867(world):
    """Sixty seasons of the founding roll on the empty Meridian map: every Crown
    founding lands on an 1867 riding, and the Prairie region is never drawn."""
    stats = _stats()
    world.initialise(SEED)
    for _ in range(60):
        world.run_season()
    seats = [
        row["fed_id"] for row in world.conn.execute(
            "SELECT h.fed_id FROM holdings h JOIN events e ON e.id = h.acquired_event_id"
            " WHERE e.kind = 'founding' AND e.mechanical_delta NOT LIKE '%partition%'"
        )
    ]
    assert len(seats) > 10
    assert all(stats[f]["opens_year"] == 1867 for f in seats)


def test_a_region_with_no_foundable_seat_has_no_weight(world, old_world):
    for w in (world, old_world):
        w.initialise(SEED, seat="Kingston and the Islands")
    spy_new, spy_old = SpyRng(world.rng_for(2)), SpyRng(old_world.rng_for(2))
    world._draw_region(spy_new)
    old_world._draw_region(spy_old)
    offered_new = dict(spy_new.offered)["founding.region"]
    offered_old = dict(spy_old.offered)["founding.region"]
    assert "prairie" in offered_old
    assert "prairie" not in offered_new  # every Prairie riding opens in 1870
    assert world._draw_seat(spy_new, "prairie") is None


def test_p_found_reaches_zero_when_the_foundable_map_is_full(world, old_world):
    for w in (world, old_world):
        w.initialise(SEED, seat="Kingston and the Islands")
        house = w.active_houses()[0]["house"]
        _claim_all_but(w, set(_late()), house)
    assert world.founding_room() == 0
    assert old_world.founding_room() > 0  # 0.8 still counts the 1870 ridings
    rng = world.rng_for(2)
    assert world._founding_roll(2, rng) is None
    p_found = [d for d in world.log if d["purpose"] == "founding.p_found"][-1]["result"]
    assert p_found == {"room": 0, "p": 0.0}


# ---------------------------------------------------- bullet 2: expansion --


def test_a_closed_riding_is_not_an_expansion_candidate(world):
    seat, late = _frontier(world)
    house = _found_at(world, seat)
    neighbours = _land(world, seat)
    assert set(late) <= set(world.expansion_targets(house))
    assert not set(late) & set(world.open_expansion_targets(house))
    _set_year(world, house, 1870)
    assert set(late) <= set(world.open_expansion_targets(house))
    assert set(world.open_expansion_targets(house)) == set(neighbours) - set(
        r["fed_id"] for r in world.holdings(house)
    )


def test_a_house_with_only_closed_neighbours_cannot_expand(world):
    seat, late = _frontier(world)
    house = _found_at(world, seat)
    other = _found_named(world, "Halifax")
    _hold(world, other, [n for n in _land(world, seat) if n not in late])
    world.conn.execute("UPDATE house_stats SET capital = 90, enclosed = 0 WHERE house = ?", (house,))
    world._turn_cache = {}
    assert world.has_expansion_target(house)  # there is unclaimed land next door…
    assert "Expand" not in world.legal_actions(house)  # …but none of it is open
    _set_year(world, house, 1870)
    assert "Expand" in world.legal_actions(house)


def test_a_closed_riding_consumes_no_draw(world):
    """The target draw is offered the open ridings only — filtered before the
    draw, as land adjacency is, so a closed riding never moves the stream."""
    seat, late = _frontier(world)
    house = _found_at(world, seat)
    open_before = world.open_expansion_targets(house)
    spy = SpyRng(world.rng_for(2))
    world._do_expand(house, 2, spy, True, "confederation", 9)
    offered = dict(spy.offered)[f"expand.target.{house}"]
    assert offered == open_before
    assert not set(late) & set(offered)


def test_enclosure_is_unchanged_by_closed_neighbours(world):
    """A house bordering only closed ridings is not enclosed (§7b is unchanged);
    it simply cannot Expand until its own clock reaches the year."""
    seat, late = _frontier(world)
    house = _found_at(world, seat)
    other = _found_named(world, "Halifax")
    _hold(world, other, [n for n in _land(world, seat) if n not in late])
    world._recompute_enclosure(2)
    assert world.house_row(house)["enclosed"] == 0


# ------------------------------------------ bullet 3: cadets are not gated --


def test_a_cadet_line_may_be_seated_on_a_riding_its_parent_gives_up(world):
    """Partition is not a Crown grant: the junior heir takes the outer holdings,
    1870 ridings included, at a cadet clock of 1867."""
    stats = _stats()
    seat, late = _frontier(world)
    house = _found_at(world, seat)
    # A run of ridings reaching away from the seat into the 1870 country.
    chain, frontier = [], list(late)
    held = {seat}
    while frontier and len(chain) < 11:
        nxt = frontier.pop(0)
        if nxt in held:
            continue
        held.add(nxt)
        chain.append(nxt)
        frontier.extend(n for n in _land(world, nxt) if stats[n]["opens_year"] == 1870)
    _hold(world, house, chain)
    _set_year(world, house, 1890)
    for role, age in (("heir", 30), ("heir2", 28)):
        world.conn.execute(
            "INSERT INTO persons (house, name, gender, age, role, alive, born_season)"
            " VALUES (?, ?, 'm', ?, ?, 1, 1)",
            (house, f"Heir {role}", age, role),
        )
    junior = world.heirs(house)[1]
    cadet = world._partition(house, junior, 5, world.rng_for(5), "confederation")
    assert cadet is not None
    cadet_seat = world.holdings(cadet)[0]["fed_id"]
    assert stats[cadet_seat]["opens_year"] == 1870
    assert world.personal_year(cadet) == 1867


# ------------------- bullet 4: nothing held is lost when a clock resets --


def test_a_succession_reset_to_1867_takes_nothing_away(world):
    seat, late = _frontier(world)
    house = _found_at(world, seat)
    _set_year(world, house, 1880)
    _hold(world, house, late)
    world.conn.execute(
        "INSERT INTO persons (house, name, gender, age, role, alive, born_season)"
        " VALUES (?, 'An Heir', 'f', 30, 'heir', 1, 1)",
        (house,),
    )
    before = [h["fed_id"] for h in world.holdings(house)]
    # The holder dies, as _mortality would have it, and the heir succeeds.
    world.conn.execute(
        "UPDATE persons SET alive = 0, died_season = 3 WHERE house = ? AND role = 'holder'",
        (house,),
    )
    world._succeed(house, 3, world.rng_for(3), cause="test")
    assert world.personal_year(house) == 1867
    assert [h["fed_id"] for h in world.holdings(house)] == before
    # Nothing that reads the closed ridings afterwards takes them away either:
    # the enclosure test, the action list and the debt check all leave them.
    world.conn.execute("UPDATE house_stats SET capital = 50 WHERE house = ?", (house,))
    world._recompute_enclosure(3)
    world.legal_actions(house)
    world._debt_check(house, 3, world.rng_for(3))
    assert [h["fed_id"] for h in world.holdings(house)] == before


# ----------------------------- bullet 5: shared events are unaffected --


def test_a_transfer_hands_a_closed_riding_to_a_house_at_1867(world):
    seat, late = _frontier(world)
    giver = _found_at(world, seat)
    _hold(world, giver, late[:1])
    taker = _found_named(world, "Halifax")
    assert world.personal_year(taker) == 1867
    moved = world._lose_riding(giver, 2, "test", to_house=taker)
    assert moved == late[0]
    assert late[0] in [h["fed_id"] for h in world.holdings(taker)]


def test_absorption_carries_closed_ridings_across(world):
    seat, late = _frontier(world)
    weak = _found_at(world, seat)
    _hold(world, weak, late)
    strong = _found_named(world, "Halifax")
    world._absorb_into(strong, weak, 2, "confederation", reason="test")
    held = {h["fed_id"] for h in world.holdings(strong)}
    assert set(late) <= held


# ------------------------------ bullet 6: director interventions refused --


def _turn(tmp_path, name, operations):
    path = tmp_path / name
    path.write_text(json.dumps({
        "directive": "test",
        "event": {"kind": "other", "title": "test", "narrative": "A test.", "houses": []},
        "operations": operations,
    }), encoding="utf-8")
    return path


def _started(world):
    world.initialise(SEED, seat="Kingston and the Islands")
    world.conn.commit()
    return world.active_houses()[0]["house"]


def test_grant_house_is_refused_on_a_closed_riding_by_name(world, tmp_path):
    _started(world)
    riding = world._riding_name(_late()[0])
    path = _turn(tmp_path, "0001_s0001-grant.json", [
        {"op": "grant_house", "riding": riding, "reason": "test"},
    ])
    with pytest.raises(TurnError) as caught:
        apply_turn(world.conn, path)
    message = str(caught.value)
    assert riding in message and "personal year 1867" in message and "1870" in message


def test_force_expand_is_refused_when_every_neighbour_is_closed(world, tmp_path):
    other = _started(world)
    seat, late = _frontier(world)
    house = _found_at(world, seat)
    _hold(world, other, [n for n in _land(world, seat) if n not in late])
    world.conn.commit()
    path = _turn(tmp_path, "0002_s0001-force.json", [
        {"op": "force_action", "house": house, "action": "Expand", "reason": "test"},
    ])
    with pytest.raises(TurnError) as caught:
        apply_turn(world.conn, path)
    message = str(caught.value)
    assert world._riding_name(late[0]) in message
    assert "personal year 1868" in message and "1870" in message


def test_force_expand_is_accepted_when_the_year_will_have_come(world, tmp_path):
    """The refusal reads the year the house will act in: a house at 1869 acts
    next season at 1870, when the riding is open."""
    other = _started(world)
    seat, late = _frontier(world)
    house = _found_at(world, seat)
    _hold(world, other, [n for n in _land(world, seat) if n not in late])
    _set_year(world, house, 1869)
    world.conn.commit()
    path = _turn(tmp_path, "0003_s0001-force.json", [
        {"op": "force_action", "house": house, "action": "Expand", "reason": "test"},
    ])
    apply_turn(world.conn, path)
    assert world.house_row(house)["forced_action"] == "Expand"


@needs_node
def test_the_javascript_engine_refuses_the_same_interventions():
    script = f"""
import {{ readFileSync, existsSync }} from 'node:fs';
import path from 'node:path';
import {{ loadWorldData, newWorld, WORLD_TABLES }} from './web/engine/index.js';
const root = {json.dumps(str(ROOT))};
const read = (p) => readFileSync(path.join(root, p), 'utf8');
const dir = {json.dumps(scenario.reference_set_dir(MERIDIAN).as_posix())};
const tables = ['ridings.csv', 'adjacency.csv', 'places_by_riding.csv', 'riding_tokens.csv',
  ...WORLD_TABLES.filter((t) => existsSync(path.join(root, dir, t)))];
const data = loadWorldData(read, '0.9', {{ dir, tables }});
const {{ world }} = newWorld(read, {SEED}, 'Kingston and the Islands', {{ data }});
const out = {{}};
try {{
  world.intervene([{{ op: 'grant_house', riding: {json.dumps('Labrador')}, reason: 't' }}]);
  out.grant = 'accepted';
}} catch (e) {{ out.grant = e.message; }}
try {{
  newWorld(read, {SEED}, 'Labrador', {{ data }});
  out.seat = 'accepted';
}} catch (e) {{ out.seat = e.message; }}
console.log(JSON.stringify(out));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert _stats()["10004"]["opens_year"] == 1870  # Labrador
    for key in ("grant", "seat"):
        assert "Labrador" in out[key] and "personal year 1867" in out[key] and "1870" in out[key]


@needs_node
def test_both_engines_agree_through_interventions_under_09():
    """grant_house and a forced Expand on open ground, through hoc/turn.py and
    World.intervene, on Meridian under 0.9: the season files still match."""
    script = [
        {"after_season": 5, "title": "A house granted", "operations": [
            {"op": "grant_house", "riding": "Halifax", "community": "Irish Catholic",
             "rank": "Baron", "tag": "Mixed", "surname": "Crosscheck", "reason": "test"}]},
        {"after_season": 8, "title": "Expand forced", "operations": [
            {"op": "force_action", "house": "Crosscheck", "action": "Expand",
             "reason": "test"}]},
    ]
    differences = crosscheck.crosscheck(
        SEED, 40, seat="Kingston and the Islands", script=script,
        rules_version="0.9", reference_data=MERIDIAN,
    )
    assert not differences, differences[0][1] if differences else ""


# ------------------------------------------ riding_endowments: the numbers --


def test_founding_capital_carries_the_seats_wealth_tier(world, old_world):
    stats = _stats()
    seats = []
    for tier in (1, 3, 5):
        seats.append(next(
            f for f in sorted(stats)
            if stats[f]["wealth_tier"] == tier and stats[f]["opens_year"] == 1867
        ))
    for fed_id in seats:
        name = world._riding_name(fed_id)
        a = world.found_house(1, seat=name, rng=world.rng_for(1))
        b = old_world.found_house(1, seat=name, rng=old_world.rng_for(1))
        expected = 2 * (stats[fed_id]["wealth_tier"] - 3)
        delta = world.house_row(a)["capital"] - old_world.house_row(b)["capital"]
        assert delta == expected, (name, delta, expected)


def test_a_successful_expand_costs_fifteen_plus_the_targets_tier(world):
    stats = _stats()
    house = _found_named(world, "Kingston and the Islands")
    world.conn.execute("UPDATE house_stats SET capital = 80 WHERE house = ?", (house,))
    outcome = world._do_expand(house, 2, world.rng_for(2), True, "confederation", 9)
    target = world._resolve_riding(outcome["riding"])
    assert world.house_row(house)["capital"] == 80 - (15 + stats[target]["wealth_tier"] - 3)


def test_a_failed_expand_still_costs_five(world):
    house = _found_named(world, "Kingston and the Islands")
    world.conn.execute("UPDATE house_stats SET capital = 80 WHERE house = ?", (house,))
    world._do_expand(house, 2, world.rng_for(2), False, "confederation", 3)
    assert world.house_row(house)["capital"] == 75


def test_the_flags_change_nothing_on_ne_2026(tmp_path):
    """No riding_stats.csv: every riding opens at 1867 and reads tier 3."""
    conn = load_seed.build(tmp_path / "ne.db", seed=scenario.blank_seed_dir())
    world = sim.World(conn, world_seed=SEED, rules_version="0.9")
    assert world.riding_stats == {}
    assert world.foundable("59001") and world.wealth_offset("59001") == 0
    assert world.jurisdiction_name("59001", 1867) is None
    conn.close()


# --------------------------------------- bullet 7: display, never engine --


def test_season_records_name_the_jurisdiction(tmp_path):
    out = tmp_path / "seasons"
    crosscheck.run_python(1868, 30, out, rules_version="0.9", reference_data=MERIDIAN)
    founding = []
    expansions = []
    lines = []
    for path in sorted(out.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        founding += [d for d in record["draws"] if d["purpose"] == "founding.jurisdiction"]
        expansions += [
            a for a in record["actions"] if a.get("action") == "Expand" and a.get("success")
        ]
        lines += record["chronicle"]
    assert founding and all(d["result"]["jurisdiction"] for d in founding)
    assert expansions and all("jurisdiction" in a for a in expansions)
    # A riding whose jurisdiction then was named otherwise than now says so —
    # seed 1868 seats a house at St. John's East in its fifth season — and one
    # named the same then and now does not.
    assert any("St. John's East (Newfoundland)." in line for line in lines)
    assert not any("(Ontario)" in line for line in lines)


def test_08_records_carry_no_jurisdiction(tmp_path):
    out = tmp_path / "seasons"
    crosscheck.run_python(1868, 30, out, rules_version="0.8", reference_data=MERIDIAN)
    text = "".join(p.read_text(encoding="utf-8") for p in sorted(out.glob("*.json")))
    assert "jurisdiction" not in text


def test_the_house_page_and_map_name_the_jurisdiction(world):
    from hoc.export import site

    seat, late = _frontier(world)
    house = _found_at(world, seat)
    _hold(world, house, late[:1])
    _set_year(world, house, 1880)
    slugs = site._slugs(world.conn)
    house_row = next(r for r in site._houses(world.conn) if r["house"] == house)
    page = site._house_page(world.conn, house_row, slugs)
    jurisdiction = places.jurisdiction_at(world.riding_jurisdictions[late[0]], 1880)
    assert "Jurisdiction in 1880" in page
    assert jurisdiction in page

    lookup = site._riding_lookup(world.conn)
    stats, spans = site._reference(world.conn)
    attrs = site._jurisdiction_attrs(late[0], lookup[late[0]], stats, spans)
    assert f'data-jurisdiction="{site.esc(jurisdiction)}"' in attrs and 'data-year="1880"' in attrs
    free = next(f for f in _late() if lookup[f]["house"] is None)
    assert 'data-opens="1870"' in site._jurisdiction_attrs(free, lookup[free], stats, spans)


def test_the_ridings_page_shows_the_resource_tier(world):
    from hoc.export import site

    page = site._ridings_page(world.conn, site._slugs(world.conn))
    assert "resource tier" in page and "opens 1870" in page
    assert "wealth" not in page.lower()


def test_the_narrate_block_names_jurisdictions_on_meridian(monkeypatch):
    from hoc.export import turn_block

    monkeypatch.setattr(scenario, "reference_dir", lambda name=None, root=None:
                        ROOT / scenario.reference_set_dir(MERIDIAN))
    block = turn_block.narrate_block(1, 5, scenario_name="new")
    assert "riding_jurisdictions.csv" in block and "personal year" in block
    monkeypatch.undo()
    assert "riding_jurisdictions.csv" not in turn_block.narrate_block(1, 5, scenario_name="new")
