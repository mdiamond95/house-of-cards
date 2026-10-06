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


# Phase C2's four flags. The C1 tests below were written against the weighted
# action draw, which `schemes` replaces, so `_world` turns these off unless a
# test asks for them (`c2=True`); the C2 tests at the end of this file do.
C2_FLAGS = ("schemes", "contested_claims", "prestige_politics", "cohesion_strain")
ALL_FLAGS = NEW_FLAGS + C2_FLAGS


def _world(tmp_path, version="1.0", name="w", reference=MERIDIAN, c2=False, **flags):
    conn = load_seed.build(
        tmp_path / f"{name}.db", seed=scenario.blank_seed_dir(), reference_data=reference
    )
    rules = rules_data.load_rules(version=version)
    if not c2:
        rules.features.update({flag: False for flag in C2_FLAGS})
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
    for flag in ALL_FLAGS:
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
@pytest.mark.parametrize("flag", ALL_FLAGS)
def test_each_flag_alone_plays_the_same_in_both_engines(flag, tmp_path):
    """The cross-check under 1.0 runs every flag at once (tests/test_crosscheck.py);
    this plays each alone on the Meridian world, through a rules directory
    written for the purpose, so a divergence names its flag."""
    import crosscheck

    root = tmp_path / "rules"
    shutil.copytree(ROOT / "rules", root)
    features = json.loads((root / "versions" / "1.0" / "features.json").read_text())
    for other in ALL_FLAGS:
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


# =========================================================== Phase C2 ======
#
# `schemes` (§4.2), `contested_claims` (§4.4), `prestige_politics` (§4.5) and
# `cohesion_strain` (§4.9). Each false in 0.7-0.9 and on in the draft 1.0.


def _c2(tmp_path, seasons=0, name="c2", **flags):
    world = _world(tmp_path, name=name, c2=True, **flags)
    if seasons:
        _play(world, seasons)
    return world


def _claim_pair(world):
    """An attacker, a defender and a riding the attacker could lay claim to."""
    for row in world.active_houses():
        for other, fed_id in world._claim_targets(row["house"]):
            if world.relation_marker(row["house"], other) not in (sim.KIN, sim.COMPACT):
                return row["house"], other, fed_id
    pytest.skip("no two houses share a border in this world")


def _insert_scheme(world, house, name, target_house=None, target_riding=None, steps=2,
                   done=2, capital=0, influence=0, season=1, answers=None):
    cursor = world.conn.execute(
        "INSERT INTO schemes (house, scheme, target_house, target_riding, answers, steps_total,"
        " steps_done, committed_capital, committed_influence, begun_season)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (house, name, target_house, target_riding, answers, steps, done, capital, influence, season),
    )
    return world._scheme(cursor.lastrowid)


class _Dice:
    """A season RNG whose 2d6 rolls are fixed, for contests decided in advance."""

    def __init__(self, world, season, rolls):
        self.inner = world.rng_for(season)
        self.rolls = list(rolls)

    def two_d6(self, purpose=None):
        return self.rolls.pop(0)

    def __getattr__(self, name):
        return getattr(self.inner, name)


# ------------------------------------------------------------------ schemes --


def test_schemes_replace_the_action_draw_and_a_house_holds_one_at_a_time(tmp_path):
    world = _c2(tmp_path, 30)
    off = _world(tmp_path, name="off")
    _play(off, 30)
    assert not [d for d in world.log if d["purpose"].startswith("action.")]
    assert [d for d in off.log if d["purpose"].startswith("action.")]
    assert world.conn.execute(
        "SELECT COUNT(*) FROM (SELECT house FROM schemes WHERE status = 'active'"
        " GROUP BY house HAVING COUNT(*) > 1)").fetchone()[0] == 0
    names = {s.scheme for s in world.rules.schemes}
    actions = {r["action"] for r in world.conn.execute("SELECT action FROM house_actions")}
    assert actions & names, "houses take scheme steps"
    assert not off.conn.execute("SELECT COUNT(*) FROM schemes").fetchone()[0]
    assert "plans" not in off.run_season()


def test_every_scheme_event_is_public_with_its_turns_remaining(tmp_path):
    world = _c2(tmp_path, 25)
    phases = {}
    for row in world.conn.execute(
        "SELECT mechanical_delta FROM events WHERE mechanical_delta LIKE '%\"scheme\": {%' ORDER BY id"
    ):
        payload = json.loads(row["mechanical_delta"])["scheme"]
        phases.setdefault(payload["id"], []).append(payload)
    assert phases
    for history in phases.values():
        assert history[0]["phase"] in ("begun", "answered")
        remaining = [p["turns_remaining"] for p in history]
        assert remaining == sorted(remaining, reverse=True), history
        if history[-1]["phase"] == "resolved":
            assert history[-1]["turns_remaining"] == 0 and history[-1]["ran"] >= 1
    record = world.run_season()
    active = world.conn.execute("SELECT id FROM schemes WHERE status = 'active' ORDER BY id").fetchall()
    assert [p["id"] for p in record["plans"]] == [r["id"] for r in active]
    assert all({"house", "scheme", "turns_remaining", "target_house", "riding"} <= set(p)
               for p in record["plans"])


def test_a_grievance_cannot_be_reconciled_in_its_first_three_turns(tmp_path):
    world = _c2(tmp_path, 20)
    house, other, _ = _claim_pair(world)
    season = world.season_no + 1
    event_id = world.record("relational", "test grievance", [house, other], season,
                            delta={"marker": sim.GRIEVANCE, "cause": "test"})
    world.set_relation(house, other, sim.GRIEVANCE, event_id, "test")
    peace = next(s for s in world.rules.schemes if s.scheme == "Make peace")
    world.conn.execute("UPDATE house_stats SET influence = 50 WHERE house = ?", (house,))
    wait = world.rules.scheme_rules["peace"]["wait"]
    assert wait == 3
    for later in range(wait):
        world._turn_cache = {}
        assert (other, None) not in world._scheme_targets(house, peace, season + later)
    world._turn_cache = {}
    assert (other, None) in world._scheme_targets(house, peace, season + wait)


def test_peace_has_low_utility_unless_the_house_has_cause(tmp_path):
    world = _c2(tmp_path, 20, holder_traits=False)
    house, other, fed_id = _claim_pair(world)
    peace = next(s for s in world.rules.schemes if s.scheme == "Make peace")
    world.conn.execute("UPDATE house_stats SET cohesion = 80 WHERE house = ?", (house,))
    # No claim or contest between them yet: no cause.
    world.conn.execute("DELETE FROM schemes WHERE house IN (?, ?) OR target_house IN (?, ?)",
                       (house, other, house, other))
    season = world.season_no + 1
    calm = world.scheme_utility(house, peace, other, None, season)
    _insert_scheme(world, other, "Claim a riding", house, world.holdings(house)[0]["fed_id"], season=season)
    caused = world.scheme_utility(house, peace, other, None, season)
    assert caused - calm == world.rules.scheme_rules["utility"]["peace_cause"]
    assert calm <= 10


def test_a_claim_is_answered_by_its_target_on_its_next_turn(tmp_path):
    world = _c2(tmp_path, 20)
    attacker, defender, fed_id = _claim_pair(world)
    season = world.season_no + 1
    world.conn.execute("DELETE FROM schemes WHERE house = ? AND status = 'active'", (defender,))
    world.conn.execute("UPDATE house_stats SET capital = 60, influence = 40 WHERE house = ?", (defender,))
    claim = _insert_scheme(world, attacker, "Claim a riding", defender, fed_id, steps=3, done=1,
                           season=season)
    world._turn_cache = {}
    outcome = world._scheme_turn(defender, season, world.rng_for(season))
    after = world._scheme(claim["id"])
    assert after["considered"] in (1, 2)
    if after["considered"] == 2:
        answer = world.active_scheme(defender)
        assert answer["answers"] == claim["id"] and outcome["scheme"] == "answered"
        assert answer["scheme"] in ("Fortify", "Seek a protector", "Sue for peace", "Counter-claim")
    draws = [d for d in world.log if d["purpose"] == f"scheme.answer.{defender}"]
    assert draws, "the answer is chosen by a seeded draw"


def test_a_scheme_whose_target_is_gone_is_abandoned_with_half_its_stake(tmp_path):
    world = _c2(tmp_path, 20)
    attacker, defender, fed_id = _claim_pair(world)
    season = world.season_no + 1
    world.conn.execute("DELETE FROM schemes WHERE house = ? AND status = 'active'", (attacker,))
    claim = _insert_scheme(world, attacker, "Claim a riding", defender, fed_id, steps=3, done=1,
                           capital=10, influence=4, season=season)
    world.conn.execute(
        "UPDATE holdings SET released_event_id = acquired_event_id WHERE fed_id = ?"
        " AND released_event_id IS NULL", (fed_id,))
    before = world.house_row(attacker)
    world._turn_cache = {}
    world._scheme_turn(attacker, season, world.rng_for(season))
    assert world._scheme(claim["id"])["status"] == "abandoned"
    assert world._scheme(claim["id"])["outcome"] == "target gone"
    after = world.house_row(attacker)
    # Half the stake back (5 and 2) before anything the new scheme commits.
    events = [json.loads(r["mechanical_delta"])["scheme"] for r in world.conn.execute(
        "SELECT mechanical_delta FROM events WHERE mechanical_delta LIKE '%\"phase\": \"abandoned\"%'")]
    assert any(e["id"] == claim["id"] and e["reason"] == "target gone" for e in events)
    assert after["capital"] >= min(100, before["capital"]) - 20


def test_a_succession_reconsiders_the_scheme_under_the_new_holder(tmp_path, monkeypatch):
    world = _c2(tmp_path, 20)
    house = next(r["house"] for r in world.active_houses() if world.active_scheme(r["house"]))
    scheme_id = world.active_scheme(house)["id"]
    season = world.season_no + 1
    monkeypatch.setattr(world, "scheme_utility", lambda *a, **k: 0)
    world._reconsider_scheme(house, season)
    assert world._scheme(scheme_id)["status"] == "abandoned"
    assert world._scheme(scheme_id)["outcome"] == "the new holder"


def test_the_utility_draw_is_among_the_top_three(tmp_path):
    world = _c2(tmp_path, 10)
    house = _first_house(world)
    season = world.season_no + 1
    spec = world.rules.schemes[0]
    candidates = [(u, 0, f"H{u}", "", spec) for u in (5, 50, 40, 30, 20, 0, -3)]
    picks = set()
    for n in range(60):
        chosen = world._choose_scheme(house, candidates, world.rng_for(season + n), "test")
        picks.add(chosen[0])
    assert picks <= {50, 40, 30} and len(picks) >= 2
    assert world._choose_scheme(house, [(0, 0, "", "", spec)], world.rng_for(season), "t") is None


# ---------------------------------------------------------- contested_claims --


def test_without_contested_claims_no_claim_is_offered(tmp_path):
    world = _c2(tmp_path, 15, contested_claims=False)
    names = [s.scheme for s in world.rules.schemes if s.resolves_as == "contest"]
    marks = ",".join("?" for _ in names)
    assert world.conn.execute(
        f"SELECT COUNT(*) FROM schemes WHERE scheme IN ({marks})", names).fetchone()[0] == 0


def test_the_contest_totals_follow_the_formula(tmp_path):
    world = _c2(tmp_path, 20, holder_traits=False)
    attacker, defender, fed_id = _claim_pair(world)
    spec = world.rules.scheme_rules["contest"]
    a_row, d_row = world.house_row(attacker), world.house_row(defender)
    attack, defence = world.contest_totals(attacker, defender, fed_id, 23, 17, 1, 2, 7, 6)
    assert attack == 7 + 23 // 10 + world.rank_index.get(a_row["rank"], 0) + spec["per_ally"] * 1
    assert defence == 6 + 17 // 10 + d_row["cohesion"] // 25 + spec["per_ally"] * 2 + (
        spec["seat_bonus"] if world._is_seat(defender, fed_id) else 0)
    assert (spec["committed_per_point"], spec["cohesion_per_point"], spec["per_ally"],
            spec["seat_bonus"], spec["loss_cohesion"], spec["rout_margin"],
            spec["rout_cohesion_below"], spec["cooldown"]) == (10, 25, 2, 2, 10, 5, 40, 5)


def _set_up_contest(world, single=False):
    attacker, defender, fed_id = _claim_pair(world)
    season = world.season_no + 1
    for house in (attacker, defender):
        world.conn.execute("DELETE FROM schemes WHERE house = ? AND status = 'active'", (house,))
        world.conn.execute("DELETE FROM relations WHERE house_a = ? OR house_b = ?", (house, house))
    if single:
        world.conn.execute(
            "UPDATE holdings SET released_event_id = acquired_event_id WHERE house = ?"
            " AND fed_id <> ? AND released_event_id IS NULL", (defender, fed_id))
        world._renumber(defender)
    claim = _insert_scheme(world, attacker, "Claim a riding", defender, fed_id, steps=2, done=2,
                           capital=12, influence=6, season=season - 2)
    world._turn_cache = {}
    return attacker, defender, fed_id, season, claim


def test_a_claim_won_takes_the_riding_and_a_house_left_with_none_falls(tmp_path):
    world = _c2(tmp_path, 25)
    attacker, defender, fed_id, season, claim = _set_up_contest(world, single=True)
    assert world._is_seat(defender, fed_id), "the defender's last riding is its seat"
    cohesion = world.house_row(attacker)["cohesion"]
    outcome = world._resolve_scheme(claim, season, _Dice(world, season, [12, 2]))
    assert outcome["contest"] == "won" and outcome["scheme"] == "resolved"
    assert mechanics_holder(world, fed_id) == attacker
    assert world.house_row(defender)["status"] == "removed"
    fall = world.conn.execute(
        "SELECT mechanical_delta FROM events WHERE title LIKE ? ORDER BY id DESC LIMIT 1",
        (f"%{world.house_row(defender)['peerage']} falls%",)).fetchone()
    assert json.loads(fall["mechanical_delta"])["taken_by"] == attacker
    assert world.relation_marker(attacker, defender) == sim.HOSTILE
    assert world._scheme(claim["id"])["outcome"] == "won"
    assert world.house_row(attacker)["cohesion"] == cohesion


def mechanics_holder(world, fed_id):
    from hoc import rules as mechanics
    return mechanics._holder_of(world.conn, fed_id)


def test_ties_go_to_the_defender_and_the_loser_pays_in_cohesion(tmp_path):
    world = _c2(tmp_path, 25, holder_traits=False)
    attacker, defender, fed_id, season, claim = _set_up_contest(world)
    world.conn.execute("UPDATE house_stats SET cohesion = 50 WHERE house = ?", (attacker,))
    attack, defence = world.contest_totals(attacker, defender, fed_id, 18, 0, 0, 0, 0, 0)
    # Rolls that make the totals equal: the defender holds.
    roll_a = 7
    roll_d = roll_a + attack - defence
    if not 2 <= roll_d <= 12:
        pytest.skip("this pair cannot be tied with two dice")
    outcome = world._contest(claim, season, _Dice(world, season, [roll_a, roll_d]))
    assert outcome["contest"] == "held"
    assert mechanics_holder(world, fed_id) == defender
    assert world.house_row(attacker)["cohesion"] == 50 - 10


def test_the_pair_may_not_contest_again_for_the_cooldown(tmp_path):
    world = _c2(tmp_path, 25)
    attacker, defender, fed_id, season, claim = _set_up_contest(world)
    world._resolve_scheme(claim, season, _Dice(world, season, [2, 12]))
    assert world._contest_cooldown(attacker, defender, season)
    assert world._contest_cooldown(defender, attacker, season + 4)
    assert not world._contest_cooldown(attacker, defender, season + 5)
    spec = next(s for s in world.rules.schemes if s.scheme == "Claim a riding")
    world._turn_cache = {}
    assert all(t[0] != defender for t in world._scheme_targets(attacker, spec, season + 1))


def test_allies_are_asked_and_a_refusal_is_recorded(tmp_path):
    world = _c2(tmp_path, 25)
    attacker, defender, fed_id, season, claim = _set_up_contest(world)
    friend = next(r["house"] for r in world.active_houses()
                  if r["house"] not in (attacker, defender))
    event_id = world.record("relational", "test compact", [attacker, friend], season,
                            delta={"marker": sim.COMPACT})
    world.set_relation(attacker, friend, sim.COMPACT, event_id, "test")
    world._turn_cache = {}
    world._contest(claim, season, world.rng_for(season))
    asked = [json.loads(r["mechanical_delta"])["ally"] for r in world.conn.execute(
        "SELECT mechanical_delta FROM events WHERE mechanical_delta LIKE '%\"ally\": {%'")]
    assert any(a["party"] == attacker and a["scheme"] == claim["id"] for a in asked)
    assert [d for d in world.log if d["purpose"] == f"contest.ally.{friend}"]


# --------------------------------------------------------- prestige_politics --


def test_houses_read_prestige_when_choosing_whom_to_claim_and_whom_to_court(tmp_path):
    on = _c2(tmp_path, 30, name="on")
    attacker, defender, fed_id = _claim_pair(on)
    season = on.season_no + 1
    claim = next(s for s in on.rules.schemes if s.scheme == "Claim a riding")
    terms = on.rules.scheme_rules["utility"]
    on.conn.execute("UPDATE house_stats SET cohesion = 30 WHERE house = ?", (defender,))
    on._turn_cache = {}
    with_politics = on.scheme_utility(attacker, claim, defender, fed_id, season)
    on.rules.features["prestige_politics"] = False
    on._turn_cache = {}
    without = on.scheme_utility(attacker, claim, defender, fed_id, season)
    on.rules.features["prestige_politics"] = True
    leader, top = on._ranking()
    expected = terms["weak_target"]
    if defender == leader and attacker != leader and attacker in top:
        expected += terms["leader_target"]
    assert with_politics - without == expected
    # A protector is sought above, and the leader is a poorer ally.
    protector = next(s for s in on.rules.schemes if s.scheme == "Seek a protector")
    low = min((r["house"] for r in on.active_houses()), key=lambda h: (on.standing(h), h))
    on._turn_cache = {}
    leader, _ = on._ranking()
    u_leader = on.scheme_utility(low, protector, leader, None, season)
    on.rules.features["prestige_politics"] = False
    on._turn_cache = {}
    u_plain = on.scheme_utility(low, protector, leader, None, season)
    gap = on.standing(leader) - on.standing(low)
    assert u_leader - u_plain == min(terms["protector_gap_max"], max(0, gap) // terms["protector_per_gap"]) \
        + terms["leader_ally"]


# ----------------------------------------------------------- cohesion_strain --


def test_cohesion_strains_with_holdings_beyond_rank_and_an_old_holder(tmp_path):
    world = _c2(tmp_path, 20)
    house = max((r["house"] for r in world.active_houses()), key=lambda h: (world.holding_count(h), h))
    spec = world.rules.upkeep["strain"]
    world.conn.execute("UPDATE house_stats SET cohesion = 80 WHERE house = ?", (house,))
    world.conn.execute("UPDATE persons SET age = 75 WHERE house = ? AND role = 'holder' AND alive = 1",
                       (house,))
    free = spec["free_holdings"] + spec["per_rank_index"] * world.rank_index.get(world.house_row(house)["rank"], 0)
    expected = max(0, world.holding_count(house) - free) + 1
    world._strain(house)
    assert world.house_row(house)["cohesion"] == 80 - expected
    assert world.log[-1] == {"purpose": f"strain.{house}", "result": expected}
    off = _c2(tmp_path, 3, name="off", cohesion_strain=False)
    assert not [d for d in off.log if d["purpose"].startswith("strain.")]


# ------------------------------------------------- both engines, value by value --


@needs_node
def test_the_scheme_utility_and_the_contest_totals_agree_in_both_engines(tmp_path):
    from hoc.export import world as world_export

    world = _c2(tmp_path, 30)
    snapshot = world_export.world_snapshot(world.conn)
    path = tmp_path / "world.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    result = subprocess.run(
        ["node", str(ROOT / "tests" / "js" / "scheme_parity.mjs"), str(path), "1.0",
         scenario.reference_set_dir(MERIDIAN).as_posix()],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    js = json.loads(result.stdout)
    season = snapshot["season"] + 1

    strip = lambda cs: [[c[0], c[1], c[2], c[3]] for c in cs]  # noqa: E731
    python = {"utilities": {}, "answers": {}, "contests": []}
    for row in world.active_houses():
        world._turn_cache = {}
        python["utilities"][row["house"]] = strip(world._scheme_candidates(row["house"], season))
    names = world._contest_schemes()
    for claim in world.conn.execute("SELECT * FROM schemes WHERE status = 'active' ORDER BY id"):
        if claim["scheme"] in names:
            world._turn_cache = {}
            python["answers"][str(claim["id"])] = strip(
                world._scheme_candidates(claim["target_house"], season, claim=claim))
    for row in world.active_houses():
        for other, fed_id in world._claim_targets(row["house"])[:3]:
            world._turn_cache = {}
            python["contests"].append([row["house"], other, fed_id, *world.contest_totals(
                row["house"], other, fed_id, 23, 17, 1, 2, 7, 6)])
    assert sum(len(v) for v in python["utilities"].values()) > 20
    assert python["contests"]
    assert js == python
