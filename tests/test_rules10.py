"""Rules 1.0 (draft): the six mechanical flags of docs/STORY_DESIGN.md Phase C1.

`upkeep_phase` (§4.1), `holder_traits` (§4.3), `marriage_pairing` (§4.7),
`prestige` (§4.5), `founding_curve` (§4.6) and `succession_watch` (§4.8), each
false in 0.7-0.9 and on in the draft 1.0. One test, or more, per flag, in the
manner of tests/test_atlas.py: most play on the Meridian world and set the one
flag against the same world without it, so the flag is shown to be what made
the difference. Rules 1.0 is a draft — rules/current.txt stays at 0.9 and no
committed game has a season under it — so these tests are what holds it.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import load_seed  # noqa: E402

from hoc import prng, rules_data, scenario, sim  # noqa: E402

MERIDIAN = "meridian-v1.0.3"
SEED = 1867
NEW_FLAGS = (
    "upkeep_phase", "holder_traits", "marriage_pairing", "prestige", "founding_curve",
    "succession_watch",
)
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")


def _world(tmp_path, version="1.0", name="w", reference=MERIDIAN, **flags):
    conn = load_seed.build(
        tmp_path / f"{name}.db", seed=scenario.blank_seed_dir(), reference_data=reference
    )
    rules = rules_data.load_rules(version=version)
    rules.features.update(flags)
    return sim.World(conn, rules=rules, world_seed=SEED)


def _play(world, seasons):
    with world.conn:
        world.initialise(SEED)
        records = [world.run_season() for _ in range(seasons - 1)]
    return records


def _first_house(world):
    return world.active_houses()[0]["house"]


# ------------------------------------------------------------ the version --


def test_rules_10_is_a_draft_with_every_new_flag_on():
    assert rules_data.current_version() == "0.9", "1.0 is a draft: current.txt stays at 0.9"
    assert "1.0" in rules_data.available_versions()
    features = rules_data.load_features("1.0")
    for flag in NEW_FLAGS:
        assert rules_data.FEATURE_DEFAULTS[flag] is False
        assert features[flag] is True
        for old in ("0.7", "0.8", "0.9"):
            assert rules_data.load_features(old)[flag] is False, (old, flag)
    bundle = rules_data.load_rules(version="1.0")
    assert [t.trait for t in bundle.traits] == [
        "Grasping", "Cautious", "Litigious", "Conciliator", "Dynast", "Courtier", "Improver", "Zealot",
    ]
    assert rules_data.load_rules(version="0.9").traits == []


def test_the_draft_says_so_in_the_readme_and_the_changelog():
    readme = (ROOT / "rules" / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "rules" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "draft" in readme and "1.0" in readme
    assert "1.0 (draft)" in changelog


# -------------------------------------------------------------- upkeep_phase --


def test_upkeep_takes_the_four_standing_actions_out_of_the_pool(tmp_path):
    on = _world(tmp_path, name="on")
    off = _world(tmp_path, name="off", upkeep_phase=False)
    for world in (on, off):
        _play(world, 12)
    on_actions = {r["action"] for r in on.conn.execute("SELECT action FROM house_actions")}
    off_actions = {r["action"] for r in off.conn.execute("SELECT action FROM house_actions")}
    assert not on_actions & sim.UPKEEP_ACTIONS
    assert off_actions & {"Invest", "Consolidate (rest)"}
    house = _first_house(on)
    assert not on.legal_actions(house) & sim.UPKEEP_ACTIONS


def test_upkeep_moves_the_stats_at_the_start_of_a_turn(tmp_path):
    world = _world(tmp_path, holder_traits=False)
    _play(world, 1)
    house = _first_house(world)
    before = world.house_row(house)
    spec = world.rules.upkeep
    world.conn.execute("UPDATE house_stats SET cohesion = 30 WHERE house = ?", (house,))
    world._upkeep(house)
    after = world.house_row(house)
    seat = world.holdings(house)[0]["fed_id"]
    assert after["capital"] - before["capital"] == spec["capital"]["base"] + 1 // spec["capital"]["holdings_per_point"] \
        + world.wealth_offset(seat)
    assert after["influence"] - before["influence"] == spec["influence"]["base"]
    assert after["cohesion"] == 30 + spec["cohesion"]["base"] + spec["cohesion"]["recovery"]
    assert world.log[-1]["purpose"] == f"upkeep.{house}"


def test_a_house_with_nothing_legal_bides(tmp_path, monkeypatch):
    world = _world(tmp_path)
    _play(world, 1)
    house = _first_house(world)
    monkeypatch.setattr(world, "legal_actions", lambda h: set())
    outcome = world.take_action(house, 2, world.rng_for(2))
    assert outcome == {"action": "Bide", "success": True, "note": "no legal action"}
    off = _world(tmp_path, name="off", upkeep_phase=False)
    _play(off, 1)
    monkeypatch.setattr(off, "legal_actions", lambda h: set())
    assert off.take_action(_first_house(off), 2, off.rng_for(2)) is None


def test_each_house_writes_one_automatic_letter_at_the_set_chance(tmp_path):
    world = _world(tmp_path)
    _play(world, 40)
    letters = [r for r in world.conn.execute(
        "SELECT mechanical_delta FROM events WHERE kind = 'relational'"
        " AND mechanical_delta LIKE '%\"letter\": true%'")]
    assert letters, "automatic letters reach the record"
    draws = [d for d in world.log if d["purpose"].startswith("letter.")]
    assert draws, "the letter roll is in the season record"
    assert world.rules.upkeep["correspondence_pct"] == 30


# ------------------------------------------------------------- holder_traits --


def test_traits_are_drawn_in_pairs_that_never_clash(tmp_path):
    world = _world(tmp_path)
    clashes = ({"Grasping", "Cautious"}, {"Litigious", "Conciliator"})
    seen = set()
    for n in range(400):
        rng = sim.LoggingRandom(prng.Prng(n + 1), [])
        traits = world._draw_traits("X", rng)
        assert len(traits) == 2 and traits[0] != traits[1]
        assert not any(c <= set(traits) for c in clashes), traits
        seen.update(traits)
    assert seen == {t.trait for t in world.rules.traits}


def test_founders_successors_and_heirs_carry_traits_into_the_record(tmp_path):
    world = _world(tmp_path)
    _play(world, 40)
    holders = world.conn.execute(
        "SELECT traits FROM persons WHERE role = 'holder' AND alive = 1").fetchall()
    assert holders and all(len(r["traits"].split(",")) == 2 for r in holders)
    heirs = world.conn.execute("SELECT traits FROM persons WHERE role IN ('heir', 'heir2')").fetchall()
    assert heirs and all(r["traits"] for r in heirs), "an heir's traits are drawn when named"
    founding = json.loads(world.conn.execute(
        "SELECT mechanical_delta FROM events WHERE kind = 'founding' ORDER BY id LIMIT 1"
    ).fetchone()[0])
    assert len(founding["traits"]) == 2
    named = world.conn.execute(
        "SELECT mechanical_delta FROM events WHERE title LIKE '%names an heir%' LIMIT 1").fetchone()
    assert "traits" in json.loads(named[0])
    off = _world(tmp_path, name="off", holder_traits=False)
    _play(off, 10)
    assert off.conn.execute("SELECT COUNT(*) FROM persons WHERE traits IS NOT NULL").fetchone()[0] == 0


def _set_traits(world, house, traits):
    world.conn.execute(
        "UPDATE persons SET traits = ? WHERE house = ? AND role = 'holder' AND alive = 1",
        (traits, house),
    )


def test_traits_shift_action_weights_and_upkeep(tmp_path):
    world = _world(tmp_path)
    _play(world, 3)
    house = _first_house(world)
    world.conn.execute("UPDATE house_stats SET capital = 80 WHERE house = ?", (house,))
    legal = world.legal_actions(house) | {"Expand"}
    _set_traits(world, house, "Dynast,Courtier")
    plain = dict(world.action_weights(house, legal))
    _set_traits(world, house, "Grasping,Courtier")
    grasping = dict(world.action_weights(house, legal))
    assert grasping["Expand"] - plain["Expand"] == 2 * sim.WEIGHT_SCALE
    _set_traits(world, house, "Cautious,Courtier")
    assert dict(world.action_weights(house, legal))["Expand"] - plain["Expand"] == -2 * sim.WEIGHT_SCALE
    before = world.house_row(house)["influence"]
    world._upkeep(house)
    with_courtier = world.house_row(house)["influence"] - before
    _set_traits(world, house, "Cautious,Dynast")
    before = world.house_row(house)["influence"]
    world._upkeep(house)
    assert with_courtier - (world.house_row(house)["influence"] - before) == 1


def test_a_zealot_never_stands_aside_and_heats_opposed_borders(tmp_path, monkeypatch):
    world = _world(tmp_path)
    _play(world, 2)
    house = _first_house(world)
    _set_traits(world, house, "Zealot,Dynast")
    monkeypatch.setattr(world, "_response_for", lambda roll: "Neutral")
    world.conn.execute("UPDATE clocks SET personal_year = ? WHERE house = ?",
                       (world.rules.events[0].personal_year, house))
    fired = world._era_event(house, 3, world.rng_for(3))
    assert fired["response"] == "Resist"
    _set_traits(world, house, "Dynast,Courtier")
    world.conn.execute("DELETE FROM event_houses WHERE house = ? AND event_id IN"
                       " (SELECT id FROM events WHERE kind = 'societal')", (house,))
    assert world._era_event(house, 3, world.rng_for(3))["response"] == "Neutral"
    row = dict(world.house_row(house))
    other = {**row, "house": "Other", "tag": "Progressive" if row["tag"] != "Progressive" else "Conservative"}
    row["tag"] = "Conservative" if other["tag"] == "Progressive" else "Progressive"
    cool = world._friction_delta(row, other, None)
    _set_traits(world, house, "Zealot,Dynast")
    assert world._friction_delta(row, other, None) - cool == 1


# ---------------------------------------------------------- marriage_pairing --


def _person(world, house, gender, role="heir", age=20):
    world.conn.execute(
        "INSERT INTO persons (house, name, gender, age, role, alive) VALUES (?, ?, ?, ?, ?, 1)",
        (house, f"{gender}-{role}", gender, age, role),
    )


def test_a_marriage_pairs_one_man_and_one_woman(tmp_path):
    world = _world(tmp_path)
    _play(world, 3)
    a, b = [r["house"] for r in world.active_houses()[:2]]
    world.conn.execute("DELETE FROM persons WHERE house IN (?, ?) AND role != 'holder'", (a, b))
    _person(world, a, "m")
    _person(world, b, "m")
    assert world._marriage_pair(a, b) is None, "two men are no pair"
    _person(world, b, "f", role="other")
    mine, theirs = world._marriage_pair(a, b)
    assert {mine["gender"], theirs["gender"]} == {"m", "f"}
    assert theirs["role"] == "other", "children count, not only named heirs"
    world.set_relation(a, b, sim.FRIENDLY)
    world._turn_cache = {}
    assert "Marriage alliance" in world.legal_actions(a)
    world.conn.execute("UPDATE persons SET married = 1 WHERE house = ? AND gender = 'f'", (b,))
    world._turn_cache = {}
    assert "Marriage alliance" not in world.legal_actions(a)


# ------------------------------------------------------------------ prestige --


def test_prestige_is_recomputed_every_season_and_recorded(tmp_path):
    world = _world(tmp_path)
    records = _play(world, 20)
    assert all("prestige" in r for r in records)
    house = _first_house(world)
    row = world.house_row(house)
    ties = world.conn.execute(
        "SELECT COUNT(*) FROM relations WHERE (house_a = ? OR house_b = ?) AND marker IN (?, ?)",
        (house, house, sim.COMPACT, sim.KIN)).fetchone()[0]
    expected = (10 * world.holding_count(house) + 20 * world.rank_index.get(row["rank"], 0)
                + row["influence"] // 5 + 5 * ties + 15 * row["contests_won"] - 15 * row["ridings_lost"])
    assert records[-1]["prestige"][house] == expected == row["prestige"]
    history = world.conn.execute(
        "SELECT COUNT(DISTINCT season_no) FROM prestige_history").fetchone()[0]
    assert history == 20
    off = _world(tmp_path, name="off", prestige=False)
    assert all("prestige" not in r for r in _play(off, 5))
    assert off.conn.execute("SELECT COUNT(*) FROM prestige_history").fetchone()[0] == 0


def test_prestige_counts_contests_won_and_ridings_lost(tmp_path):
    world = _world(tmp_path)
    _play(world, 2)
    house = _first_house(world)
    world._tally(house, won=2, lost=1)
    row = world.house_row(house)
    assert (row["contests_won"], row["ridings_lost"]) == (2, 1)
    off = _world(tmp_path, name="off", prestige=False)
    _play(off, 2)
    off._tally(_first_house(off), won=1)
    assert off.house_row(_first_house(off))["contests_won"] == 0


# ------------------------------------------------------------ founding_curve --


def test_the_founding_curve_seats_the_board_early_and_rarely_after(tmp_path):
    world = _world(tmp_path)
    _play(world, 70)
    crown = [r["founded_season"] for r in world.conn.execute(
        "SELECT founded_season FROM house_stats WHERE founded_by = 'crown' ORDER BY founded_season")]
    assert 24 <= sum(1 for s in crown if s <= 25) <= 36
    late = [s for s in crown if s > 40]
    assert all(b - a >= world.rules.founding["founding_curve"]["late_gap"] for a, b in zip(late, late[1:]))
    assert not any(d["purpose"] == "founding.p_found" for d in world.log)
    off = _world(tmp_path, name="off", founding_curve=False)
    _play(off, 3)
    assert any(d["purpose"] == "founding.p_found" for d in off.log)


def test_cadets_are_founded_by_partition_and_not_counted_as_crown(tmp_path):
    world = _world(tmp_path)
    _play(world, 2)
    kinds = {r["founded_by"] for r in world.conn.execute("SELECT founded_by FROM house_stats")}
    assert kinds == {"crown"}


# ---------------------------------------------------------- succession_watch --


def test_a_holder_turning_sixty_with_no_heir_and_an_heir_of_age_are_recorded(tmp_path):
    world = _world(tmp_path)
    _play(world, 2)
    house = _first_house(world)
    world.conn.execute("DELETE FROM persons WHERE house = ? AND role != 'holder'", (house,))
    world.conn.execute("UPDATE persons SET age = 60 WHERE house = ? AND role = 'holder'", (house,))
    world._succession_watch(house, 3)
    _person(world, house, "f", age=25)
    world._succession_watch(house, 3)
    watch = [json.loads(r[0]) for r in world.conn.execute(
        "SELECT mechanical_delta FROM events WHERE mechanical_delta LIKE '%watch%' ORDER BY id")]
    assert [w["watch"] for w in watch] == ["no_heir", "heir_of_age"]
    off = _world(tmp_path, name="off", succession_watch=False)
    _play(off, 30)
    assert off.conn.execute(
        "SELECT COUNT(*) FROM events WHERE mechanical_delta LIKE '%watch%'").fetchone()[0] == 0


# ------------------------------------------------------- both engines agree --


@needs_node
@pytest.mark.parametrize("flag", NEW_FLAGS)
def test_each_flag_alone_plays_the_same_in_both_engines(flag, tmp_path):
    """The cross-check under 1.0 runs every flag at once (tests/test_crosscheck.py);
    this plays each alone on the Meridian world, through a rules directory
    written for the purpose, so a divergence names its flag."""
    import crosscheck

    root = tmp_path / "rules"
    shutil.copytree(ROOT / "rules", root)
    features = json.loads((root / "versions" / "1.0" / "features.json").read_text())
    for other in NEW_FLAGS:
        features[other] = other == flag
    (root / "versions" / "1.0" / "features.json").write_text(json.dumps(features))
    seasons = 40
    py_dir, js_dir = tmp_path / "py" / "seasons", tmp_path / "js"
    rules = rules_data.load_rules(version="1.0", root=root)
    conn = load_seed.build(tmp_path / "py.db", seed=scenario.blank_seed_dir(), reference_data=MERIDIAN)
    world = sim.World(conn, rules=rules, world_seed=SEED, seasons_dir=py_dir)
    with conn:
        world.initialise(SEED)
        for _ in range(seasons - 1):
            world.run_season()
    # The JavaScript side reads its rules through a root holding this copy.
    js_root = tmp_path / "jsroot"
    js_root.mkdir()
    for name in ("rules", "data"):
        (js_root / name).symlink_to(root if name == "rules" else ROOT / "data")
    result = subprocess.run(
        ["node", str(crosscheck.JS_CLI), "--seed", str(SEED), "--seasons", str(seasons),
         "--out", str(js_dir), "--root", str(js_root), "--rules-version", "1.0",
         "--reference", scenario.reference_set_dir(MERIDIAN).as_posix()],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    differences = crosscheck.compare(py_dir, js_dir, seasons)
    assert not differences, f"{flag}: the engines diverge at season {differences[0]}"


def test_the_house_page_shows_traits_and_prestige(tmp_path):
    from hoc.export import site

    world = _world(tmp_path)
    _play(world, 15)
    house = _first_house(world)
    row = world.conn.execute(
        "SELECT h.house, h.peerage, h.rank, h.status, h.notes, c.primary_hex, c.secondary_hex"
        " FROM houses h JOIN v_house_colours c ON c.house = h.house WHERE h.house = ?", (house,)
    ).fetchone()
    html = site._house_page(world.conn, row, site._slugs(world.conn))
    traits = world.holder(house)["traits"].split(",")
    assert "Holder&#x27;s traits" in html or "Holder's traits" in html
    assert all(t in html for t in traits)
    assert f"<dt>Prestige</dt><dd>{world.house_row(house)['prestige']}</dd>" in html
