"""Rules 1.0 `land_rush`: a province's first years (docs/hex-trial/v2/README.md;
rules/README.md), and `dated_openings`' accession line for land already open.

* Each jurisdiction the atlas first has as a province after the start year has
  a rush for board.json's land_rush.years from that year. The world's turn
  records it (a `rush` beat in its first year, a chip after).
* In each rush year, while fewer than until_held_pct of the province's open
  units are held, the Crown makes one extra founding roll at roll_pct among
  its open, unclaimed units; an Expand into a rushing province costs
  expand_discount less.
* It runs on the hex board, and on a riding set only when board.json's
  land_rush.riding_sets is 1.
* Under dated_openings, a unit already open is not named again in an
  accession line (Kenora, open in 1882, joins Ontario in 1889).
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


def world(tmp_path, key, seed=1867, board=None, **flags):
    rules = rules_data.load_rules(version="1.0")
    rules.features = dict(rules.features, **flags)
    if board is not None:
        rules.board = json.loads(json.dumps(rules.board))
        rules.board["land_rush"].update(board)
    name = "-".join(f"{k}{int(v)}" for k, v in sorted(flags.items())) or "draft"
    name += "-" + "-".join(f"{k}{v}" for k, v in sorted((board or {}).items()))
    conn = load_seed.build(tmp_path / f"{key}-{name}-{seed}.db", seed=scenario.blank_seed_dir(), reference_data=key)
    return sim.World(conn, rules=rules, world_seed=seed, seasons_dir=tmp_path / f"{key}-{name}-{seed}")


def play(w, turns):
    records = []
    with w.conn:
        w.initialise(w.world_seed)
        records.append(json.loads(sorted(w.seasons_dir.iterdir())[-1].read_text(encoding="utf-8")))
        while w.season_no < turns:
            records.append(w.run_season())
    return records


def deltas(w, world_kind):
    out = []
    for r in w.conn.execute("SELECT mechanical_delta FROM events WHERE kind = 'other' ORDER BY id"):
        d = json.loads(r["mechanical_delta"] or "{}")
        if d.get("world") == world_kind:
            out.append(d)
    return out


@pytest.fixture(scope="module")
def hex_game(tmp_path_factory):
    w = world(tmp_path_factory.mktemp("rush"), HEX)
    records = play(w, 100)
    return w, records


def test_the_flag_is_the_drafts_alone():
    assert rules_data.FEATURE_DEFAULTS["land_rush"] is False
    for version in ("0.7", "0.8", "0.9"):
        assert rules_data.load_features(version)["land_rush"] is False
    assert rules_data.load_features("1.0")["land_rush"] is True
    rush = rules_data.load_rules(version="1.0").board["land_rush"]
    # The brief's start (8 years, 50%) tuned to 6 years and 40% (rules/CHANGELOG.md).
    assert rush == {"years": 6, "roll_pct": 40, "until_held_pct": 25, "expand_discount": 5, "riding_sets": 0}


def test_a_rush_for_each_jurisdiction_first_a_province_after_1867(tmp_path):
    w = world(tmp_path, HEX)
    assert w.rushes() == [
        (1870, "manitoba", "Manitoba"), (1871, "british_columbia", "British Columbia"),
        (1873, "prince_edward_island", "Prince Edward Island"), (1905, "alberta", "Alberta"),
        (1905, "saskatchewan", "Saskatchewan"), (1949, "newfoundland", "Newfoundland"),
    ]
    assert [r[1] for r in w.rushes_in(1875)] == ["manitoba", "british_columbia", "prince_edward_island"]
    assert [r[1] for r in w.rushes_in(1876)] == ["british_columbia", "prince_edward_island"]
    assert w.rushes_in(1890) == []


def test_each_rush_is_a_world_event_for_its_years(hex_game):
    w, _ = hex_game
    first = deltas(w, "rush")
    assert [(d["jurisdiction"], d["year"]) for d in first] == [
        ("Manitoba", 1870), ("British Columbia", 1871), ("Prince Edward Island", 1873),
        ("Alberta", 1905), ("Saskatchewan", 1905), ("Newfoundland", 1949)]
    for d in first:
        unit = next(u for y, u, n in w.rushes() if n == d["jurisdiction"])
        assert d["fed_ids"] == w.rush_units(unit, d["year"]) and d["years"] == 6 and d["year_of"] == 1
    later = deltas(w, "rush_continues")
    assert len(later) == 6 * 5
    assert all(2 <= d["year_of"] <= 6 for d in later)


def test_a_rush_founds_only_in_its_province_and_only_while_few_are_held(hex_game):
    w, records = hex_game
    rows = w.conn.execute(
        "SELECT e.mechanical_delta, h.fed_id, h.house FROM events e"
        " JOIN holdings h ON h.acquired_event_id = e.id AND h.seat_order = 1"
        " WHERE e.kind = 'founding' ORDER BY e.id").fetchall()
    rows = [row for row in rows if "rush" in json.loads(row["mechanical_delta"])]
    assert rows, "the trial seed founds in a rush"
    names = {n: u for _, u, n in w.rushes()}
    for row in rows:
        d = json.loads(row["mechanical_delta"])
        spans = w.riding_jurisdictions[row["fed_id"]]
        assert names[d["rush"]] in {s["unit"] for s in spans}
    rushed = [h for r in records for h in r.get("rushed", [])]
    assert sorted(rushed) == sorted(row["house"] for row in rows)
    spec = w.rules.board["land_rush"]
    for r in records:
        draws = r["draws"]
        for i, entry in enumerate(draws):
            if entry["purpose"] in {f"rush.{u}" for _, u, _ in w.rushes()}:
                held, n = entry["result"]["held"], entry["result"]["open"]
                rolled = i + 1 < len(draws) and draws[i + 1]["purpose"].startswith("rush.roll.")
                assert rolled == (n > 0 and held * 100 < spec["until_held_pct"] * n), (r["season"], entry)


def test_an_expand_into_a_rushing_province_costs_less(tmp_path):
    on = world(tmp_path, HEX, water_crossings=False)
    off = world(tmp_path, HEX, water_crossings=False, land_rush=False)
    fed = {r["name_en"]: r["fed_id"] for r in on.conn.execute("SELECT fed_id, name_en FROM ridings")}
    for w in (on, off):
        w._playing_season = 1905 - 1867 + 1
    assert on.expand_cost(None, fed["Red Deer"]) == off.expand_cost(None, fed["Red Deer"]) - 5
    assert on.expand_cost(None, fed["Brantford"]) == off.expand_cost(None, fed["Brantford"])
    on._playing_season = off._playing_season = 1911 - 1867 + 1
    assert on.expand_cost(None, fed["Red Deer"]) == off.expand_cost(None, fed["Red Deer"])


def test_an_open_unit_is_not_named_again_in_an_accession_line(hex_game):
    w, _ = hex_game
    kenora = w.conn.execute("SELECT fed_id FROM ridings WHERE name_en = 'Kenora'").fetchone()["fed_id"]
    assert w.opening_year(kenora) == 1882
    named = [(d["world"], d["year"]) for d in deltas(w, "accession") + deltas(w, "opening")
             if kenora in d["fed_ids"]]
    assert named == [("opening", 1882)]


def test_a_riding_game_is_the_same_with_the_flag_on_and_off(tmp_path):
    def files(w):
        play(w, 100)
        return {p.name: p.read_bytes() for p in sorted(w.seasons_dir.iterdir())}

    on = files(world(tmp_path, "meridian-v1.0.3", land_rush=True))
    off = files(world(tmp_path, "meridian-v1.0.3", land_rush=False))
    assert len(on) == 100 and on == off


def test_the_flags_own_switch_turns_it_on_for_a_riding_set(tmp_path):
    w = world(tmp_path, "meridian-v1.0.3", board={"riding_sets": 1})
    play(w, 8)  # through 1874
    assert [d["jurisdiction"] for d in deltas(w, "rush")] == ["Manitoba", "British Columbia", "Prince Edward Island"]
