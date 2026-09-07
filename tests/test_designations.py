"""Rules 0.8: a house is named for its own ground, and quiet seasons say so.

Under 0.7 a territorial designation was drawn from a province-wide bank, so a
house seated in Halifax could be styled "of Kamloops" as readily as "of
Dartmouth" — the bank knew the province and nothing else. 0.8 draws from the
seat riding's own places, then the seat's own name, then its land neighbours,
and only then the old bank.

Both behaviours are live at once, because a season played under 0.7 is replayed
under 0.7. So the tests here are in two halves: what 0.8 does, and that 0.7
still does what it did.
"""

import csv
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from hoc import places, rules_data, scenario, sim  # noqa: E402
from hoc.names import NameGenerator  # noqa: E402

JS_CLI = ROOT / "web" / "engine" / "cli.js"
SEED = 1867
SEAT = "Kingston and the Islands"


# --------------------------------------------------------------- the data --


def test_every_riding_has_at_least_one_name_token():
    """The seat's own name is the tier that must always answer: only 111 of the
    343 ridings have a populated place of their own, so without this the draw
    would fall through to the province bank most of the time."""
    tokens = places.tokens_by_riding()
    ridings = {
        row["fed_id"]
        for row in csv.DictReader(open(ROOT / "data/reference/ridings.csv", encoding="utf-8"))
    }
    missing = sorted(ridings - set(tokens))
    assert missing == [], f"{len(missing)} riding(s) yield no designation token: {missing[:5]}"


def test_no_token_is_a_bare_compass_word():
    """"Vancouver East" is a place called Vancouver. A Baron of "East" is not a
    thing, and a token list that produced one would be worse than the province
    bank it replaced."""
    from build_places import COMPASS

    offenders = [
        token for tokens in places.tokens_by_riding().values() for token in tokens
        if token.lower() in COMPASS
    ]
    assert offenders == []


def test_french_particles_survive_tokenisation():
    """The hyphen in Saint-Jérôme is part of the name, not a separator."""
    tokens = {t for ts in places.tokens_by_riding().values() for t in ts}
    for name in ("Rivière-du-Loup", "Côte-Nord", "Les Îles-de-la-Madeleine"):
        assert name in tokens, name
    # And nothing was split at a hyphen into a fragment that names nothing.
    assert "Jérôme" not in tokens
    assert "Loup" not in tokens


def test_every_place_belongs_to_a_real_riding():
    ridings = {
        row["fed_id"]
        for row in csv.DictReader(open(ROOT / "data/reference/ridings.csv", encoding="utf-8"))
    }
    assert set(places.places_by_riding()) <= ridings


def test_the_place_data_is_as_thin_as_the_tiers_assume():
    """Recorded as a test because it is the reason the draw has four tiers. If a
    future source covers most ridings, the tiers can be simplified — and this
    test failing is how anyone would find out."""
    by_riding = places.places_by_riding()
    assert sum(len(v) for v in by_riding.values()) == 255
    assert len(by_riding) == 111


# ------------------------------------------------------------- the tiers --


@pytest.fixture
def world(tmp_path):
    import load_seed

    conn = load_seed.build(tmp_path / "d.db", seed=scenario.seed_dir("new"))
    world = sim.World(conn, world_seed=SEED, rules_version="0.8")
    yield world
    conn.close()


def test_the_tiers_are_local_first(world):
    """Kingston and the Islands: the seat's own places, then its name, then its
    neighbours', then the province bank."""
    fed_id = world._resolve_riding(SEAT)
    tiers = world._designation_tiers(fed_id, "ON")

    assert len(tiers) == world.DESIGNATION_TIERS
    assert tiers[0] == places.places_by_riding()[fed_id]
    assert tiers[1] == places.tokens_by_riding()[fed_id]
    assert tiers[2], "a seat with land neighbours should have neighbouring places"
    assert tiers[3], "the province bank is the last resort and must not be empty"
    # The bank is the 0.7 behaviour, unchanged.
    assert set(tiers[3]) == {p.place for p in world.rules.places if p.province == "ON"}


def test_a_tier_is_skipped_when_everything_in_it_is_held(world):
    """A seat whose one town is already a designation should fall through to its
    own name, not fail."""
    generator = NameGenerator(world.rules, world.rng_for(1))
    tiers = [["Alpha"], ["Beta"], [], ["Gamma"]]
    assert generator.draw_designation(tiers, taken=())[0] == 0
    assert generator.draw_designation(tiers, taken={"Alpha"})[0] == 1
    assert generator.draw_designation(tiers, taken={"Alpha", "Beta"})[0] == 3


def test_a_designation_is_never_reused(world):
    generator = NameGenerator(world.rules, world.rng_for(1))
    tiers = [["Alpha", "Beta"], ["Gamma"], [], []]
    _, first = generator.draw_designation(tiers, taken={"Alpha"})
    assert first == "Beta"
    with pytest.raises(Exception):
        generator.draw_designation([["Alpha"], [], [], []], taken={"Alpha"})


def test_the_seat_is_named_for_its_own_ground(world):
    """The behaviour in one sentence: found a house at Kingston and the
    Islands, and its designation comes from that riding rather than from
    anywhere in Ontario."""
    with world.conn:
        world.initialise(SEED, seat=SEAT)
    fed_id = world._resolve_riding(SEAT)
    local = set(places.places_by_riding().get(fed_id, ())) | set(
        places.tokens_by_riding()[fed_id]
    )
    seat_place = world.conn.execute(
        "SELECT seat_place FROM house_stats LIMIT 1"
    ).fetchone()["seat_place"]
    assert seat_place in local, f"{seat_place!r} is not from {SEAT}"


# ----------------------------------------------- the share, over a long run --


def _js_run(seasons, version, out_dir):
    if shutil.which("node") is None:
        pytest.skip("node is not on PATH")
    subprocess.run(
        ["node", str(JS_CLI), "--seed", str(SEED), "--seat", SEAT,
         "--seasons", str(seasons), "--out", str(out_dir), "--rules-version", version],
        check=True, capture_output=True, text=True,
    )
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(out_dir.glob("*.json"))
    ]


@pytest.mark.smoke
def test_most_designations_come_from_the_local_tiers(tmp_path):
    """Over three hundred seasons, at least 95% of designations must come from
    tiers 1–3 — the seat, its name, or a neighbour. The province bank is the
    fallback, and a run where it is doing most of the work would mean the local
    data is not reaching the draw."""
    records = _js_run(300, "0.8", tmp_path)
    tiers = Counter(
        draw["result"]["tier"]
        for record in records for draw in record["draws"]
        if draw["purpose"].endswith(".designation")
    )
    total = sum(tiers.values())
    assert total > 20, f"only {total} designations drawn; not enough to measure"
    local = sum(count for tier, count in tiers.items() if tier < 3)
    share = local / total
    assert share >= 0.95, (
        f"only {share:.1%} of {total} designations came from tiers 1-3"
        f" (by tier: {dict(sorted(tiers.items()))})"
    )


# -------------------------------------------------------- the quiet lines --


def test_a_season_with_nothing_in_it_says_so(tmp_path):
    records = _js_run(60, "0.8", tmp_path)
    for record in records:
        assert record["chronicle"], f"season {record['season']} has an empty chronicle"
    quiet = [
        line for record in records for line in record["chronicle"]
        if "A quiet year across the peerage." in line
    ]
    for line in quiet:
        assert line.startswith("Season ")
        assert line.endswith(" · A quiet year across the peerage.")


def test_an_idle_house_is_noticed_once(tmp_path):
    """The line fires at exactly ten quiet seasons, so a house that stays quiet
    for fifty is mentioned once rather than forty-one times."""
    records = _js_run(300, "0.8", tmp_path)
    idle = [
        (record["season"], line)
        for record in records for line in record["chronicle"]
        if " keeps to " in line
    ]
    if not idle:
        pytest.skip("no house was idle for ten seasons in this run")
    for _, line in idle:
        assert line.startswith("Season ")
        assert line.endswith(".")
    # A house is noticed at most once per idle stretch; two lines for the same
    # house in consecutive seasons would mean the counter is not resetting.
    seasons_by_house = {}
    for season, line in idle:
        peerage = line.split(" · ", 1)[1].split(" keeps to ")[0]
        seasons_by_house.setdefault(peerage, []).append(season)
    for peerage, seasons in seasons_by_house.items():
        gaps = [b - a for a, b in zip(seasons, seasons[1:])]
        assert all(gap >= 10 for gap in gaps), f"{peerage} noticed again after {gaps}"


# ------------------------------------------------------------ 0.7 unchanged --


def test_rules_07_still_draws_from_the_province_bank(tmp_path):
    """The point of versioning, tested on the behaviour it protects: a season
    played under 0.7 knows nothing about tiers."""
    import load_seed

    conn = load_seed.build(tmp_path / "old.db", seed=scenario.seed_dir("new"))
    world = sim.World(conn, world_seed=SEED, rules_version="0.7")
    assert world.feature("local_designations") is False
    with conn:
        world.initialise(SEED, seat=SEAT)
    seat_place = conn.execute("SELECT seat_place FROM house_stats LIMIT 1").fetchone()["seat_place"]
    bank = {p.place for p in world.rules.places if p.province == "ON"}
    assert seat_place in bank
    conn.close()


def test_rules_07_records_no_designation_or_quiet_draws(tmp_path):
    """A 0.7 season's log must look exactly as it did before 0.8 existed —
    which is what makes the committed seasons 1–41 still replay byte for byte."""
    records = _js_run(30, "0.7", tmp_path)
    purposes = {draw["purpose"] for record in records for draw in record["draws"]}
    assert not any(p.endswith(".designation") for p in purposes)
    lines = [line for record in records for line in record["chronicle"]]
    assert not any("A quiet year across the peerage." in line for line in lines)
    assert not any(" keeps to " in line for line in lines)
