"""Tests for the autoplay engine (hoc/sim.py).

The smoke test at the bottom is the one that matters most: it plays three
300-season worlds and checks them against docs/ENGINE_DESIGN.md §17's sanity
targets. It is slow by design — a game that only looks right for ten seasons is
not a game that plays itself.
"""

import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import load_seed  # noqa: E402

from hoc import names, palette, scenario, sim  # noqa: E402
from hoc.rules_data import load_rules, probability_for_age  # noqa: E402

SMOKE_SEEDS = (1, 2, 3)
SMOKE_SEASONS = 300
SMOKE_TIME_BUDGET = 120  # seconds, all three seeds together

# §17's targets.
PEAK_HOUSES = (45, 90)
COLLAPSE_FLOOR = 20
CLAIMED_FRACTION = 0.8
CLAIMED_BY_SEASON = (90, 200)

# Phase 9d's conflict bounds. A game whose houses only ever cooperate is not a
# game about power, and one that only ever fights is not this one.
DISPUTES_PER_GENERATION = (0.6, 1.5)
CHALLENGES_PER_RUN = (15, 25)
MAX_COOPERATION_RATIO = 4  # compacts + marriages, against disputes + challenges


@pytest.fixture(scope="module")
def rules():
    return load_rules()


def empty_world(tmp_path, seed, rules=None, name="w"):
    """A database holding the empty (autoplay) seed, and a World over it."""
    conn = load_seed.build(tmp_path / f"{name}.db", seed=scenario.seed_dir("new"))
    world = sim.World(conn, rules=rules, world_seed=seed)
    world.initialise(seed)
    return world


def snapshot(conn):
    """Everything the engine writes, in a stable order, with the wall-clock
    columns dropped — two runs of the same seed differ in `created_at` alone."""
    out = {}
    for table, order in (
        ("houses", "house"),
        ("house_stats", "house"),
        ("persons", "id"),
        ("objectives", "id"),
        ("clocks", "house"),
        ("climate", "id"),
    ):
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
        out[table] = [tuple(row) for row in rows]
    out["holdings"] = [
        tuple(row)
        for row in conn.execute(
            "SELECT house, fed_id, seat_order, hex FROM holdings"
            " WHERE released_event_id IS NULL ORDER BY house, seat_order"
        )
    ]
    out["seasons"] = [
        (row["season_no"], row["seed"], row["houses_after"], row["ridings_after"])
        for row in conn.execute("SELECT * FROM seasons ORDER BY season_no")
    ]
    return out


# ------------------------------------------------------------- determinism --


def test_same_seed_produces_an_identical_world(tmp_path, rules):
    left = empty_world(tmp_path, 99, rules, name="left")
    right = empty_world(tmp_path, 99, rules, name="right")
    for _ in range(49):
        left.run_season()
        right.run_season()

    assert snapshot(left.conn) == snapshot(right.conn)
    assert left.season_no == right.season_no == 50


def test_different_seeds_diverge(tmp_path, rules):
    left = empty_world(tmp_path, 7, rules, name="a")
    right = empty_world(tmp_path, 8, rules, name="b")
    for _ in range(49):
        left.run_season()
        right.run_season()

    assert snapshot(left.conn) != snapshot(right.conn)


def test_season_seed_is_stable_across_processes():
    """Not merely stable within one run: replay in a fresh process must agree,
    which Python's salted string hash would not give us."""
    assert sim.season_seed(42, 7) == sim.season_seed(42, 7)
    assert sim.season_seed(42, 7) != sim.season_seed(42, 8)
    assert sim.season_seed(43, 7) != sim.season_seed(42, 7)


def test_every_draw_is_logged(tmp_path, rules):
    world = empty_world(tmp_path, 5, rules)
    record = world.run_season()
    assert record["draws"], "a season with houses in it must draw something"
    for entry in record["draws"]:
        assert set(entry) == {"purpose", "result"}
        assert entry["purpose"]
    json.dumps(record)  # the log has to survive being written out


# ------------------------------------------------------------------ naming --


def test_generated_names_never_hit_the_denylist(rules):
    denylist = names.load_denylist()
    assert denylist, "the denylist must not be empty"

    generator = names.NameGenerator(rules, random.Random(11))
    produced = set()
    for community in {c.community for c in rules.communities}:
        for _ in range(40):
            given, surname, _ = generator.draw_person(community)
            produced.add(names._fold(f"{given} {surname}"))

    assert not (produced & denylist)


def test_a_denylisted_pairing_is_redrawn(rules):
    """Force the collision: a generator whose denylist covers most of a community
    still returns a name, and never one that is on the list."""
    community = "Métis"
    generator = names.NameGenerator(rules, random.Random(3))
    surnames = generator.surnames_by_community[community]
    givens = generator.given_by_tradition[(generator.tradition_for(community), "m")]

    blocked = {names._fold(f"{givens[0]} {surname}") for surname in surnames}
    generator.denylist = blocked

    given, surname, _ = generator.draw_person(community, gender="m")
    assert names._fold(f"{given} {surname}") not in blocked


def test_french_tradition_takes_the_right_particle():
    assert names.peerage_title("Baron", "Tessier", "Saint-Jérôme", "french") == (
        "Baron Tessier de Saint-Jérôme"
    )
    assert names.peerage_title("Baron", "Tessier", "Assiniboia", "french") == (
        "Baron Tessier d'Assiniboia"
    )
    assert names.peerage_title("Baron", "Tessier", "La Pocatière", "french") == (
        "Baron Tessier de la Pocatière"
    )
    assert names.peerage_title("Baron", "Tessier", "Le Gardeur", "french") == (
        "Baron Tessier du Gardeur"
    )
    assert names.peerage_title("Baron", "Tessier", "Les Éboulements", "french") == (
        "Baron Tessier des Éboulements"
    )


def test_other_traditions_take_of():
    for tradition in ("english", "anishinaabe", "inuit", "ukrainian", "metis"):
        title = names.peerage_title("Baron", "Beardy", "Nipigon", tradition)
        assert title == "Baron Beardy of Nipigon"


def test_a_place_is_never_reused_while_a_house_holds_it(tmp_path, rules):
    world = empty_world(tmp_path, 21, rules)
    for _ in range(120):
        world.run_season()

    places = world.conn.execute(
        "SELECT s.seat_place, s.province FROM house_stats s"
        " JOIN houses h ON h.house = s.house AND h.status = 'active'"
        " WHERE s.seat_place IS NOT NULL"
    ).fetchall()
    assert places, "the run should have founded houses"
    designations = [(row["seat_place"]) for row in places]
    assert len(designations) == len(set(designations))


def test_draw_place_refuses_to_reuse(rules):
    generator = names.NameGenerator(rules, random.Random(1))
    all_ns = set(generator.places_by_province["NS"])
    for _ in range(20):
        assert generator.draw_place("NS", taken=all_ns - {"Pictou"}) == "Pictou"
    with pytest.raises(names.NameError_):
        generator.draw_place("NS", taken=all_ns)


# ----------------------------------------------------------------- colours --


def test_palette_keeps_houses_apart(rules):
    """The separation target is a target, not a guarantee (hoc/palette.py), but a
    full map must still never produce two houses the eye would merge."""
    rng = random.Random(4)
    primaries = []
    for _ in range(90):
        primary, secondary = palette.assign_colours(primaries, rng)
        primaries.append(primary)

    assert len(set(primaries)) == 90
    hsls = [palette.hex_to_hsl(value) for value in primaries]
    closest = min(
        palette.hsl_distance(a, b)
        for index, a in enumerate(hsls)
        for b in hsls[index + 1:]
    )
    assert closest > 0.04


def test_secondary_is_the_lighter_same_hue():
    primary, secondary = palette.assign_colours([], random.Random(2))
    ph, ps, pl = palette.hex_to_hsl(primary)
    sh, ss, sl = palette.hex_to_hsl(secondary)
    assert palette.hue_distance(ph, sh) < 1
    assert sl > pl


# --------------------------------------------------------------- mortality --


def test_mortality_at_95_matches_the_table(rules):
    """§9 puts a 90+ holder at 20% a year. Ten thousand holder-years, +/- 2 points."""
    probability = probability_for_age(rules.mortality, 95)
    assert probability == 0.20

    rng = sim.LoggingRandom(random.Random(17), [])
    deaths = sum(1 for _ in range(10_000) if rng.chance(probability, purpose="test"))
    rate = 100 * deaths / 10_000
    assert 18 <= rate <= 22, f"deaths per year {rate:.1f}% is outside 20% +/- 2"


def test_mortality_bands_cover_the_design_document(rules):
    for age, expected in ((30, 0.01), (65, 0.02), (75, 0.05), (85, 0.10), (95, 0.20)):
        assert probability_for_age(rules.mortality, age) == expected


# ---------------------------------------------------------------- founding --


def test_p_found_is_zero_on_a_full_map(tmp_path, rules):
    """The formula reaches zero when no unclaimed riding has a land neighbour,
    so founding stops by itself rather than by a house cap (§10)."""
    conn = load_seed.build(tmp_path / "full.db", seed=scenario.seed_dir("new"))
    world = sim.World(conn, rules=rules, world_seed=1)
    world.initialise(1)

    house = world.active_houses()[0]["house"]
    event_id = world.record("other", "test fill", [house], 1)
    conn.execute(
        "INSERT INTO holdings (house, fed_id, seat_order, hex, acquired_event_id)"
        " SELECT ?, r.fed_id, 100 + ROW_NUMBER() OVER (ORDER BY r.fed_id), '#000000', ?"
        " FROM ridings r WHERE NOT EXISTS"
        " (SELECT 1 FROM holdings h WHERE h.fed_id = r.fed_id AND h.released_event_id IS NULL)",
        (house, event_id),
    )

    assert world.unclaimed_land_adjacent_count() == 0
    spec = rules.founding["p_found"]
    p_found = spec["coefficient"] * (0 / sim.TOTAL_RIDINGS) ** spec["exponent"]
    assert p_found == 0

    rng = world.rng_for(2)
    assert world._founding_roll(2, rng) is None


def test_founding_initialises_stats_from_the_table(tmp_path, rules):
    world = empty_world(tmp_path, 31, rules)
    row = world.house_row(world.active_houses()[0]["house"])

    rank_index = rules.founding["rank_index"][row["rank"]]
    assert 30 + 5 * rank_index + 1 <= row["capital"] <= 30 + 5 * rank_index + 20
    assert 20 + 5 * rank_index + 1 <= row["influence"] <= 20 + 5 * rank_index + 20
    assert 61 <= row["cohesion"] <= 80
    assert 0 <= row["ambition"] <= 10
    assert world.holder(row["house"])["age"] >= 41

    assert len(world.held_objectives(row["house"])) == sim.OBJECTIVES_AT_FOUNDING


def test_season_one_founds_exactly_one_house(tmp_path, rules):
    world = empty_world(tmp_path, 12, rules)
    assert len(world.active_houses()) == 1
    assert world.season_no == 1


def test_a_named_seat_is_honoured(tmp_path, rules):
    conn = load_seed.build(tmp_path / "seat.db", seed=scenario.seed_dir("new"))
    world = sim.World(conn, rules=rules, world_seed=4)
    world.initialise(4, seat="Calgary Centre")

    holdings = world.holdings(world.active_houses()[0]["house"])
    assert [row["name_en"] for row in holdings] == ["Calgary Centre"]


# -------------------------------------------------------------- era events --


def test_an_era_event_fires_once_per_house(tmp_path, rules):
    world = empty_world(tmp_path, 44, rules)
    for _ in range(80):
        world.run_season()

    fired = world.conn.execute(
        "SELECT eh.house, e.title, COUNT(*) AS n FROM events e"
        " JOIN event_houses eh ON eh.event_id = e.id"
        " WHERE e.kind = 'societal' GROUP BY eh.house, e.title HAVING n > 1"
    ).fetchall()
    assert not fired, f"an event fired twice for one house: {[tuple(r) for r in fired]}"


def test_direct_effects_only_reach_houses_in_scope(tmp_path, rules):
    world = empty_world(tmp_path, 55, rules)
    house = world.active_houses()[0]["house"]
    row = world.house_row(house)

    assert world._in_scope(row, "all")
    assert world._in_scope(row, row["region"])
    assert world._in_scope(row, row["tag"])

    other_region = next(r for r in ("maritime", "quebec", "ontario", "prairie", "bc", "north")
                        if r != row["region"])
    assert not world._in_scope(row, other_region)

    # A community-group scope reaches only its communities.
    in_group = world._in_scope(row, "metis")
    assert in_group == (row["community"] == "Métis")


def test_a_major_event_applies_its_direct_effect(tmp_path, rules):
    """The Great War costs every house capital and demands an extra mortality
    roll, whatever their region or tag."""
    world = empty_world(tmp_path, 61, rules)
    house = world.active_houses()[0]["house"]
    war = next(e for e in rules.events if e.name == "The Great War")

    before = world.house_row(house)["capital"]
    extra = world._apply_direct_effects(house, war, season=2)
    after = world.house_row(house)["capital"]

    assert extra is True
    assert after == max(0, before - 5)


def test_a_response_moves_the_band_ledger(tmp_path, rules):
    world = empty_world(tmp_path, 71, rules)
    world._initial_climate()
    event = next(e for e in rules.events if e.tag == "Conservative")

    from hoc import rules as mechanics

    before = mechanics.current_climate(world.conn, "confederation")
    world._shift_climate("confederation", event, +1)
    after = mechanics.current_climate(world.conn, "confederation")
    assert after == before - 1  # toward Conservative is negative on the ledger


# ------------------------------------------------------------------ replay --


def test_a_world_replays_into_an_identical_database(tmp_path, rules):
    """Replay re-runs the seasons from the seed, so a log plus a seed must
    reproduce the committed database exactly (§11)."""
    played = empty_world(tmp_path, 88, rules, name="played")
    for _ in range(19):
        played.run_season()

    replayed_conn = load_seed.build(tmp_path / "replayed.db", seed=scenario.seed_dir("new"))
    replayed = sim.World(replayed_conn, rules=rules, world_seed=88)
    replayed.initialise(88)
    for season in range(2, 21):
        replayed.run_season(season)

    assert snapshot(replayed_conn) == snapshot(played.conn)


# ------------------------------------------------------------------- smoke --


@pytest.mark.slow
def test_smoke_three_seeds_stay_within_the_sanity_targets(tmp_path, rules):
    """docs/ENGINE_DESIGN.md §17, across three seeds and 300 seasons each."""
    started = time.time()
    results = []

    for seed in SMOKE_SEEDS:
        world = empty_world(tmp_path, seed, rules, name=f"smoke{seed}")
        history = [(1, 1, 1)]
        for _ in range(SMOKE_SEASONS - 1):
            record = world.run_season()
            history.append(
                (record["season"], record["houses_after"], record["ridings_after"])
            )

        peak = max(houses for _, houses, _ in history)
        final = history[-1][1]
        claimed_at = next(
            (season for season, _, ridings in history
             if ridings >= CLAIMED_FRACTION * sim.TOTAL_RIDINGS),
            None,
        )
        natures = Counter()
        for row in world.conn.execute(
            "SELECT mechanical_delta FROM events WHERE source = 'engine'"
        ):
            try:
                natures[json.loads(row["mechanical_delta"] or "{}").get("nature")] += 1
            except ValueError:
                continue

        counts = world.conn.execute(
            "SELECT"
            " (SELECT COUNT(*) FROM events WHERE kind = 'relational'"
            "  AND (title LIKE '%wins a dispute%' OR title LIKE '%loses a dispute%')) AS disputes,"
            " (SELECT COUNT(*) FROM events WHERE kind = 'challenge') AS challenges,"
            " (SELECT COUNT(*) FROM events WHERE title LIKE '%form a compact%') AS compacts,"
            " (SELECT COUNT(*) FROM events WHERE title LIKE '%joined by marriage%') AS marriages,"
            " (SELECT COUNT(*) FROM persons WHERE role = 'holder') AS generations"
        ).fetchone()

        bounds = world.conn.execute(
            "SELECT MIN(capital) AS a, MAX(capital) AS b, MIN(influence) AS c,"
            " MAX(influence) AS d, MIN(cohesion) AS e, MAX(cohesion) AS f,"
            " MIN(ambition) AS g, MAX(ambition) AS h FROM house_stats"
        ).fetchone()
        results.append(
            {"seed": seed, "peak": peak, "final": final, "claimed_at": claimed_at,
             "bounds": tuple(bounds), "natures": natures,
             "disputes": counts["disputes"], "challenges": counts["challenges"],
             "cooperation": counts["compacts"] + counts["marriages"],
             "generations": counts["generations"]}
        )
        world.conn.close()

    elapsed = time.time() - started
    detail = "; ".join(
        f"seed {r['seed']}: peak {r['peak']}, final {r['final']}, 80% at {r['claimed_at']}"
        for r in results
    )

    for result in results:
        assert PEAK_HOUSES[0] <= result["peak"] <= PEAK_HOUSES[1], (
            f"house count peaked at {result['peak']}, outside {PEAK_HOUSES} ({detail})"
        )
        assert result["final"] >= COLLAPSE_FLOOR, (
            f"house count collapsed to {result['final']} by season {SMOKE_SEASONS} ({detail})"
        )
        assert result["claimed_at"] is not None, f"the map never reached 80% claimed ({detail})"
        assert CLAIMED_BY_SEASON[0] <= result["claimed_at"] <= CLAIMED_BY_SEASON[1], (
            f"80% claimed at season {result['claimed_at']}, outside {CLAIMED_BY_SEASON} ({detail})"
        )

        capital_min, capital_max, influence_min, influence_max, cohesion_min, cohesion_max, ambition_min, ambition_max = result["bounds"]
        for low, high, label in (
            (capital_min, capital_max, "capital"),
            (influence_min, influence_max, "influence"),
            (cohesion_min, cohesion_max, "cohesion"),
        ):
            assert 0 <= low <= 100 and 0 <= high <= 100, f"{label} left 0-100: {low}-{high}"
        assert 0 <= ambition_min and ambition_max <= 10

    # Phase 9d: conflict has to be a live part of the game in every seed, not a
    # rounding error. Friction (rules 0.6) is what makes it so.
    for result in results:
        per_generation = result["disputes"] / max(1, result["generations"])
        assert DISPUTES_PER_GENERATION[0] <= per_generation <= DISPUTES_PER_GENERATION[1], (
            f"seed {result['seed']}: {per_generation:.2f} disputes per house-generation,"
            f" outside {DISPUTES_PER_GENERATION}"
        )
        assert CHALLENGES_PER_RUN[0] <= result["challenges"] <= CHALLENGES_PER_RUN[1], (
            f"seed {result['seed']}: {result['challenges']} challenges,"
            f" outside {CHALLENGES_PER_RUN}"
        )
        conflict = result["disputes"] + result["challenges"]
        assert result["cooperation"] <= MAX_COOPERATION_RATIO * conflict, (
            f"seed {result['seed']}: {result['cooperation']} compacts and marriages against"
            f" {conflict} disputes and challenges, over {MAX_COOPERATION_RATIO}x"
        )

    # PART B: the late game has to actually happen somewhere across the seeds.
    # These are the mechanisms that keep a full map moving (§7b, §9), so a run in
    # which none of them ever fires is a game that has quietly stopped playing.
    totals = Counter()
    for result in results:
        totals.update(result["natures"])
    for nature in ("partition", "absorption", "extinction"):
        assert totals[nature] >= 1, (
            f"no {nature} occurred across seeds {SMOKE_SEEDS}:"
            f" {dict(totals)} ({detail})"
        )

    assert elapsed < SMOKE_TIME_BUDGET, (
        f"the smoke run took {elapsed:.0f}s, over the {SMOKE_TIME_BUDGET}s budget"
    )


def test_rebuild_commits_a_replayed_autoplay_scenario(tmp_path, rules, monkeypatch):
    """Regression: the engine never commits (the caller owns the transaction), so
    a rebuild that replays seasons has to wrap them or the whole game rolls back
    the moment the connection closes."""
    import rebuild as rebuild_script

    scenarios = tmp_path / "scenarios"
    (scenarios / "solo" / "seasons").mkdir(parents=True)
    for name in ("seed",):
        (scenarios / "solo" / name).mkdir()
    for csv_path in scenario.seed_dir("new").glob("*.csv"):
        (scenarios / "solo" / "seed" / csv_path.name).write_text(
            csv_path.read_text(encoding="utf-8"), encoding="utf-8"
        )
    (scenarios / "current.txt").write_text("solo\n", encoding="utf-8")
    monkeypatch.setattr(scenario, "SCENARIOS_DIR", scenarios)
    monkeypatch.setattr(scenario, "CURRENT_FILE", scenarios / "current.txt")

    played = load_seed.build(tmp_path / "played.db", seed=scenarios / "solo" / "seed")
    world = sim.World(
        played, rules=rules, world_seed=64, seasons_dir=scenarios / "solo" / "seasons"
    )
    with played:
        world.initialise(64)
        for _ in range(9):
            world.run_season()
    expected = snapshot(played)
    played.close()

    conn = rebuild_script.rebuild(tmp_path / "rebuilt.db", export=False, name="solo", verbose=False)
    conn.close()

    reopened = load_seed.db.connect(tmp_path / "rebuilt.db")
    assert snapshot(reopened) == expected
    assert reopened.execute("SELECT COUNT(*) AS n FROM houses").fetchone()["n"] > 0
    reopened.close()
