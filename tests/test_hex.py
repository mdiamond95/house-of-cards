"""The hex trial's reference set, meridian-hex-v1.0.4 (docs/hex-trial/README.md).

What is held here:

* the raw files are the pinned v1.0.4 ones, refused on any other hash or unit;
* the committed tables are exactly what scripts/build_world_hex.py builds;
* 439 units with ids derived from the H3 index and the province, unique names
  each taken from a place of a town or municipal type, its own or borrowed;
* the links: symmetric, one board counting water links, the director's
  figures before the length cap;
* the jurisdictions year by year as the director gave them;
* nothing an engine reads holds a float, and both engines play the same game
  on the set, with the founding denominator read from it.
"""

import csv
import gzip
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import build_world_hex  # noqa: E402
import fetch_meridian  # noqa: E402
import load_seed  # noqa: E402
from hoc import places, prng, rules_data, scenario, sim  # noqa: E402
from hoc.names import name_key  # noqa: E402

KEY = "meridian-hex-v1.0.4"
HEX = ROOT / "data" / "reference" / "meridian" / "hex-v1.0.4"
ENGINE_TABLES = (
    "ridings.csv", "adjacency.csv", "places_by_riding.csv", "riding_tokens.csv",
    "riding_stats.csv", "riding_jurisdictions.csv",
)

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")


def load(name):
    with open(HEX / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def table():
    return fetch_meridian.read_hex_table()


@pytest.fixture(scope="module")
def report():
    return json.loads((HEX / "build_report.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------- the raw files --


def test_the_raw_files_are_the_pinned_ones(table):
    assert table["unit"] == "h3_r4" and len(table["rows"]) == 6011
    fetch_meridian.read_hex_layer()
    pinned = {local: digest for _, local, digest in fetch_meridian.HEX_FILES}
    assert pinned == {
        "hexes.r4.v1.json.gz": "94c2f806ed3ed6315647858b63cc777209c3a97280da7caa98a65734eb455a8a",
        "hexes.r4.v1.topojson.gz": "336cb743b1da8184af2cf515ef75a34312126c09243d15a735c108c855330325",
    }
    assert fetch_meridian.HEX_TAG == "v1.0.4"


def test_a_ridings_table_is_refused_as_hexes():
    raw = json.loads(gzip.decompress((fetch_meridian.RAW_DIR / fetch_meridian.TABLE_FILE).read_bytes()))
    with pytest.raises(fetch_meridian.MeridianError, match="unit"):
        fetch_meridian.check_table(raw, fetch_meridian.HEX_UNIT)


def test_the_committed_tables_are_what_the_builder_builds(tmp_path):
    build_world_hex.build(out_dir=tmp_path, verbose=False)
    built = sorted(p.name for p in tmp_path.iterdir())
    committed = sorted(p.name for p in HEX.iterdir() if p.is_file())
    assert built == committed
    for name in built:
        assert (tmp_path / name).read_bytes() == (HEX / name).read_bytes(), name


def test_the_set_is_registered():
    assert scenario.REFERENCE_SETS[KEY] == Path("data/reference/meridian/hex-v1.0.4")
    info = places.set_info(HEX)
    assert info["hexes"] is True and info["unit_word"] == {"singular": "holding", "plural": "holdings"}
    assert places.set_info(ROOT / "data" / "reference" / "meridian" / "v1.0.3") == {}


# --------------------------------------------------------------------- units --


def test_439_units_of_5000_people_or_more(table):
    ridings = load("ridings.csv")
    assert len(ridings) == 439
    assert sum(1 for r in table["rows"] if r["population"] >= 5000) == 439


def test_an_id_is_the_province_code_and_the_h3_cell(table):
    rows = {r["id"]: r for r in table["rows"]}
    units = {u["fed_id"]: u for u in load("units.csv")}
    for riding in load("ridings.csv"):
        fed = riding["fed_id"]
        assert len(fed) == 8 and fed.isdigit()
        row = rows[units[fed]["h3"]]
        assert int(fed[:2]) == build_world_hex.PROVINCE_CODES[row["province"]] == int(fed) // 1_000_000
        assert riding["province"] == row["province"]
        assert int(fed) % 1_000_000 == build_world_hex.h3_sequence(row["id"])


def test_h3_sequence_reads_the_base_cell_and_four_digits():
    # 842b9bdffffffff: base cell 21, digits 3 3 3 6 (Toronto's hexagon).
    assert build_world_hex.h3_sequence("842b9bdffffffff") == ((21 * 7 + 3) * 7 + 3) * 7 * 7 + 3 * 7 + 6
    with pytest.raises(build_world_hex.HexBuildError):
        build_world_hex.h3_sequence("852b9bdbfffffff")  # resolution 5


def test_names_are_unique():
    ridings = load("ridings.csv")
    assert len({r["name_en"] for r in ridings}) == 439
    assert len({r["name_key"] for r in ridings}) == 439
    assert all(r["name_key"] == name_key(r["name_en"]) for r in ridings)


def test_every_unit_is_named_for_a_place_of_a_town_or_municipal_type(table):
    rows = {r["id"]: r for r in table["rows"]}
    units = {u["fed_id"]: u for u in load("units.csv")}
    borrowed = 0
    for riding in load("ridings.csv"):
        unit = units[riding["fed_id"]]
        source = rows[unit["named_from_h3"] or unit["h3"]]
        if unit["named_from_h3"]:
            borrowed += 1
            assert unit["named_from_h3"] != unit["h3"]
        place = next(p for p in source["places"] if p["csd"] == unit["name_csd"])
        assert place["name"] == riding["name_en"], "a place's name is never rewritten"
        assert place["csdType"] in build_world_hex.NAMEABLE
    # The director's decision of 8 October 2026: the 34 units with no such
    # place of their own, and two more whose own were taken by a larger unit.
    assert borrowed == 36


def test_a_unit_with_a_town_of_its_own_is_named_for_its_largest_unused_one(table):
    rows = {r["id"]: r for r in table["rows"]}
    for unit in load("units.csv"):
        if unit["named_from_h3"]:
            continue
        own = build_world_hex.own_candidates(rows[unit["h3"]])
        assert own and unit["name_csd"] in [p["csd"] for p in own]


def test_designations_are_chosen_by_csd_type(table):
    rows = {r["id"]: r for r in table["rows"]}
    units = {u["fed_id"]: u for u in load("units.csv")}
    for place in load("places_by_riding.csv"):
        row = rows[units[place["fed_id"]]["h3"]]
        kind = next(p["csdType"] for p in row["places"] if p["name"] == place["place"])
        expected = int(kind in build_world_hex.NAMEABLE and place["spans_ridings"] == "0")
        assert int(place["designation_ok"]) == expected, place


# --------------------------------------------------------------------- links --


def test_the_tables_neighbour_lists_are_symmetric(table):
    kinds = {(r["id"], n["id"]): n["kind"] for r in table["rows"] for n in r["neighbours"]}
    assert all(kinds.get((b, a)) == kind for (a, b), kind in kinds.items())


def test_links_are_stored_once_each_way_and_agree_with_links_csv():
    adjacency = load("adjacency.csv")
    pairs = [(r["fed_id_a"], r["fed_id_b"]) for r in adjacency]
    assert all(a < b for a, b in pairs) and len(set(pairs)) == len(pairs)
    links = load("links.csv")
    assert [(r["fed_id_a"], r["fed_id_b"], r["adjacency_type"]) for r in links] == [
        (r["fed_id_a"], r["fed_id_b"], r["adjacency_type"]) for r in adjacency
    ]
    ids = {r["fed_id"] for r in load("ridings.csv")}
    assert all(a in ids and b in ids for a, b in pairs)


def test_one_board_counting_water_links():
    ids = sorted(r["fed_id"] for r in load("ridings.csv"))
    groups = build_world_hex.Groups(ids)
    for row in load("adjacency.csv"):
        groups.union(row["fed_id_a"], row["fed_id_b"])
    assert groups.sizes() == [439]


def test_the_land_links_before_and_after_the_cap(report):
    before = report["links"]["before_cap"]
    assert before["land_links"] == 1127
    assert before["mean_land_links_per_unit"] == "5.13"
    assert before["land_groups"] == [438, 1]
    after = report["links"]["after_cap"]
    assert after["land_groups"] == [438, 1]
    assert after["groups_counting_water_links"] == [439]
    land = [r for r in load("links.csv") if r["adjacency_type"] == "land"]
    bridges = {(b["a"], b["b"]) for b in after["bridges_kept_over_cap"]}
    for r in land:
        length = int(r["length"])
        assert length <= build_world_hex.LENGTH_CAP or (int(r["fed_id_a"]), int(r["fed_id_b"])) in bridges


def test_les_iles_de_la_madeleine_have_one_water_link(report):
    alone = report["links"]["after_cap"]["units_alone_given_a_water_link"]
    assert len(alone) == 1
    unit = str(alone[0]["unit"])
    assert next(r for r in load("ridings.csv") if r["fed_id"] == unit)["name_en"] == "Les Îles-de-la-Madeleine"
    linked = [r for r in load("adjacency.csv") if unit in (r["fed_id_a"], r["fed_id_b"])]
    assert len(linked) == 1 and linked[0]["adjacency_type"] == "water"


# ------------------------------------------------------------ jurisdictions --


@pytest.mark.parametrize("year,count", [
    (1867, 227), (1870, 240), (1871, 300), (1873, 305), (1905, 417), (1949, 436),
])
def test_units_in_a_province(year, count):
    held = set()
    for row in load("riding_jurisdictions.csv"):
        to_year = int(row["to_year"]) if row["to_year"] else None
        if (int(row["from_year"]) <= year and (to_year is None or year <= to_year)
                and row["status"] == "province" and row["sovereign"] == "Canada"):
            held.add(row["fed_id"])
    assert len(held) == count


# -------------------------------------------------------------- the engines --


def test_no_table_an_engine_reads_holds_a_float():
    for name in ENGINE_TABLES:
        for row in load(name):
            for column, value in row.items():
                if column in ("name_en", "name_fr", "name_key", "place", "token", "name", "unit",
                              "status", "sovereign", "province", "adjacency_type"):
                    continue
                assert value == "" or value.lstrip("-").isdigit(), (name, column, value)
    assert all(isinstance(v, int) for s in places.riding_stats(HEX).values() for v in s.values())


def test_a_world_reads_the_size_of_its_map(tmp_path):
    for key, total in ((KEY, 439), ("meridian-v1.0.3", 343), ("ne-2026", 343)):
        conn = load_seed.build(tmp_path / f"{key}.db", seed=scenario.blank_seed_dir(), reference_data=key)
        world = sim.World(conn, world_seed=1867)
        assert world.total_units == total
        conn.close()
    assert sim.TOTAL_RIDINGS == 343
    assert prng.p_found(439, 439, 0.5) == 0.5


@needs_node
@pytest.mark.parametrize("version,seasons", [("1.0", 100), ("0.9", 60)])
def test_both_engines_play_the_same_game_on_the_hex_board(version, seasons):
    import crosscheck

    differences = crosscheck.crosscheck(1867, seasons, rules_version=version, reference_data=KEY)
    assert differences == [], differences[0][1][:4000]


def test_a_draft_game_on_the_hex_board_names_its_units_holdings(tmp_path):
    from hoc.export import beats as beats_export

    conn = load_seed.build(tmp_path / "hex.db", seed=scenario.blank_seed_dir(), reference_data=KEY)
    world = sim.World(conn, rules=rules_data.load_rules(version="1.0"), world_seed=1867)
    with conn:
        world.initialise(1867)
        for _ in range(4):
            world.run_season()
    beats_export.write_beats(conn, tmp_path / "data")
    index = json.loads((tmp_path / "data" / "beats" / "index.json").read_text(encoding="utf-8"))
    assert index["unit_word"] == {"singular": "holding", "plural": "holdings"}
    conn.close()
