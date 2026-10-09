"""The hex board's reference set, meridian-hex-v1.0.5 (docs/hex-trial/v2/README.md).

What is held here:

* the raw files are the four pinned v1.0.5 ones, refused on any other hash or unit;
* the committed tables are exactly what scripts/build_world_hexboard.py builds;
* 494 units: 423 resolution-4 hexagons, and 71 city hexes of the 16 split
  parents (16 cores, 55 others), with unique names, each recorded with its source;
* the links: symmetric, six land groups before water links, all joined by water;
* every unit's opening year is the latest of its four parts, as units.csv records;
* the border drawing by year;
* nothing an engine reads holds a float, and both engines play the same game
  on the set;
* and, recorded as an expected failure, that the engines do not yet keep a unit
  closed until its opening year under the 1.0 draft (the stop this set was
  built to: docs/hex-trial/v2/README.md, "Where this stopped").
"""

import csv
import gzip
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_meridian  # noqa: E402
import load_seed  # noqa: E402
from hoc import places, rules_data, scenario, sim  # noqa: E402
from hoc.names import name_key  # noqa: E402

KEY = "meridian-hex-v1.0.5"
BOARD = ROOT / "data" / "reference" / "meridian" / "hex-v1.0.5"
ENGINE_TABLES = (
    "ridings.csv", "adjacency.csv", "places_by_riding.csv", "riding_tokens.csv",
    "riding_stats.csv", "riding_jurisdictions.csv",
)
DRAWING_FILES = (
    "units.csv", "links.csv", "build_report.json", "hexes.geojson",
    "geometry_simplified.geojson", "borders_shared.geojson", "routes.geojson",
    "jurisdictions.geojson", "set.json",
)

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")


def load(name):
    with open(BOARD / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def report():
    return json.loads((BOARD / "build_report.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def units():
    return {u["fed_id"]: u for u in load("units.csv")}


# ------------------------------------------------------------- the raw files --


def test_the_raw_files_are_the_pinned_ones():
    assert fetch_meridian.BOARD_TAG == "v1.0.5"
    assert {local: digest for _, local, digest in fetch_meridian.BOARD_FILES} == {
        "hexes.r4.v1.2.json.gz": "163019e1cbf8bd97b4df568e58d006f2caf8b7503df40ce13e414ea74ee052d7",
        "hexes.r4.v1.2.topojson.gz": "817ccf7d03c18e6bee8cd093ce98bd2f0473b979412c9e9547ca0c114942c279",
        "hexes.r5.v1.json.gz": "2b0e76bf0c8cba89df845f5d42fe7403a2001661a44230e4b9b762288cf75d1e",
        "hexes.r5.v1.topojson.gz": "95f864b1623ecbf445a22f6e54dcec4a17190982def486db34c148d43bb791e7",
    }
    r4 = fetch_meridian.read_board_table(fetch_meridian.BOARD_R4_TABLE)
    r5 = fetch_meridian.read_board_table(fetch_meridian.BOARD_R5_TABLE)
    assert (r4["unit"], len(r4["rows"])) == ("h3_r4", 5986)
    assert (r5["unit"], len(r5["rows"])) == ("h3_r5", 407)
    fetch_meridian.read_board_layer(fetch_meridian.BOARD_R4_LAYER)
    fetch_meridian.read_board_layer(fetch_meridian.BOARD_R5_LAYER)


def test_a_table_of_the_other_unit_is_refused(tmp_path):
    raw = gzip.decompress((fetch_meridian.BOARD_RAW_DIR / fetch_meridian.BOARD_R5_TABLE).read_bytes())
    with pytest.raises(fetch_meridian.MeridianError, match="unit"):
        fetch_meridian.check_table(json.loads(raw), "h3_r4")


def test_a_changed_file_is_refused(tmp_path):
    for name in fetch_meridian.BOARD_TABLES:
        shutil.copy(fetch_meridian.BOARD_RAW_DIR / name, tmp_path / name)
    with open(tmp_path / fetch_meridian.BOARD_R4_TABLE, "ab") as f:
        f.write(b"\0")
    with pytest.raises(fetch_meridian.MeridianError, match="SHA-256"):
        fetch_meridian.read_board_table(fetch_meridian.BOARD_R4_TABLE, tmp_path)


# ------------------------------------------------------------- the build --


def test_the_committed_tables_are_what_the_builder_builds(tmp_path):
    pytest.importorskip("shapely")
    pytest.importorskip("pyproj")
    import build_world_hexboard

    build_world_hexboard.build(out_dir=tmp_path, verbose=False)
    for name in ENGINE_TABLES + DRAWING_FILES:
        assert (tmp_path / name).read_bytes() == (BOARD / name).read_bytes(), name


def test_the_set_is_registered():
    assert scenario.REFERENCE_SETS[KEY] == Path("data") / "reference" / "meridian" / "hex-v1.0.5"
    info = json.loads((BOARD / "set.json").read_text(encoding="utf-8"))
    assert info["key"] == KEY and info["hexes"] is True
    assert info["unit_word"] == {"singular": "holding", "plural": "holdings"}


# ------------------------------------------------------------- units --


def test_494_units(units, report):
    assert len(load("ridings.csv")) == 494 == len(units)
    roles = [u["role"] for u in units.values()]
    assert (roles.count("hex"), roles.count("core"), roles.count("city")) == (423, 16, 55)
    assert len(report["split_parents"]) == 16
    assert all(p["population"] >= 500000 for p in report["split_parents"])


def test_an_id_is_nine_digits_with_the_province_first(units):
    codes = {"NL": 10, "PE": 11, "NS": 12, "NB": 13, "QC": 24, "ON": 35, "MB": 46,
             "SK": 47, "AB": 48, "BC": 59, "YT": 60, "NT": 61, "NU": 62}
    for row in load("ridings.csv"):
        fed = row["fed_id"]
        assert len(fed) == 9 and fed.isdigit()
        assert int(fed[:2]) == codes[row["province"]]
        u = units[fed]
        t = int(fed[2:])
        assert (t >= 1_000_000) == (u["resolution"] == "5")


def test_a_city_hexs_id_holds_its_parents(units):
    import build_world_hexboard

    for u in units.values():
        if u["resolution"] == "5":
            seq5 = int(u["fed_id"][2:]) - 1_000_000
            assert seq5 // 7 == build_world_hexboard.h3_sequence(u["parent_h3"], 4)


def test_names_are_unique_and_each_has_a_source(units, report):
    rows = load("ridings.csv")
    assert len({r["name_key"] for r in rows}) == len(rows)
    assert all(r["name_key"] == name_key(r["name_en"]) for r in rows)
    sources = {u["name_source"] for u in units.values()}
    assert sources == {"parent's principal city", "own place", "riding token", "borrowed"}
    for u in units.values():
        if u["role"] == "core":
            assert u["name_source"] == "parent's principal city"
        if u["name_source"] == "riding token":
            assert u["role"] == "city" and u["name_riding"]
        if u["name_source"] == "borrowed":
            assert u["named_from_h3"]
    # The director's count: 17 city hexes hold no place of a town or municipal
    # type (12 others and 5 cores).
    assert report["city_hexes_without_a_place_of_their_own"] == 17


def test_a_core_is_named_for_its_parents_principal_city():
    names = {r["fed_id"]: r["name_en"] for r in load("ridings.csv")}
    cores = {names[u["fed_id"]] for u in load("units.csv") if u["role"] == "core"}
    assert {"Toronto", "Montréal", "Vancouver", "Calgary", "Winnipeg", "Québec"} <= cores


# ------------------------------------------------------------- links --


def test_links_are_symmetric_and_stored_once():
    adjacency = load("adjacency.csv")
    pairs = [(a["fed_id_a"], a["fed_id_b"]) for a in adjacency]
    assert all(a < b for a, b in pairs) and len(set(pairs)) == len(pairs)
    links = {(l["fed_id_a"], l["fed_id_b"]): l["adjacency_type"] for l in load("links.csv")}
    assert links == {(a["fed_id_a"], a["fed_id_b"]): a["adjacency_type"] for a in adjacency}
    ids = {r["fed_id"] for r in load("ridings.csv")}
    assert all(a in ids and b in ids for a, b in pairs)


def test_six_land_groups_all_joined_by_water(report):
    import build_world_hex

    ids = sorted(r["fed_id"] for r in load("ridings.csv"))
    land, board = build_world_hex.Groups(ids), build_world_hex.Groups(ids)
    for a in load("adjacency.csv"):
        board.union(a["fed_id_a"], a["fed_id_b"])
        if a["adjacency_type"] == "land":
            land.union(a["fed_id_a"], a["fed_id_b"])
    assert land.sizes() == [462, 15, 10, 5, 1, 1]
    assert board.sizes() == [494]
    assert all(g["water_links_to"] for g in report["land_groups"])
    assert report["links"]["before_cap"]["land_links"] == 1235
    assert report["links"]["before_cap"]["land_groups"] == [462, 15, 10, 5, 1, 1]


# ------------------------------------------------------------- opening years --


def test_the_opening_year_is_the_latest_of_its_parts(units):
    stats = {r["fed_id"]: int(r["opens_year"]) for r in load("riding_stats.csv")}
    for fed, u in units.items():
        parts = [int(u[k]) for k in ("open_atlas", "open_settled", "open_city", "open_override") if u[k]]
        assert stats[fed] == int(u["opens_year"]) == max(parts)
        if u["role"] == "city":
            assert u["open_city"]
        else:
            assert not u["open_city"]
        if u["resolution"] == "5":
            assert not u["open_settled"]  # the city-hex table carries no dates


def test_the_atlas_part_is_the_first_year_under_canada(units):
    spans = {}
    for j in load("riding_jurisdictions.csv"):
        spans.setdefault(j["fed_id"], []).append(j)
    for fed, u in units.items():
        first = next(int(s["from_year"]) for s in spans[fed] if s["sovereign"] == "Canada")
        assert int(u["open_atlas"]) == first


def test_the_directors_overrides_and_city_years():
    names = {r["fed_id"]: r["name_en"] for r in load("ridings.csv")}
    by_name = {names[u["fed_id"]]: u for u in load("units.csv")}
    for place, year in (("Thompson", 1956), ("Elliot Lake", 1955), ("Chibougamau", 1952),
                        ("Wabush", 1955), ("Kitimat", 1953)):
        assert int(by_name[place]["opens_year"]) == year, place
    # A city hex that is not its parent's core opens with its metropolitan core's city.
    assert int(by_name["Burnaby"]["opens_year"]) == 1886
    assert int(by_name["Calgary Signal Hill"]["opens_year"]) == 1894
    assert int(by_name["Calgary"]["opens_year"]) < 1894
    assert int(by_name["Headingley"]["opens_year"]) == 1873
    assert int(by_name["Winnipeg"]["opens_year"]) == 1870


def test_quebecs_city_year_is_the_corrected_one(report):
    years = {y["parent"]: y["year"] for y in report["city_years"]}
    assert years["842bac5ffffffff"] == 1833
    assert [c["city"] for c in report["city_years_changed"]] == ["Québec"]


def test_units_by_year(report):
    by_year = report["units_by_year"]
    assert by_year["1867"]["in_a_province"] == 265
    assert by_year["1966"]["open"] == 494
    assert [by_year[y]["open"] for y in ("1867", "1885", "1914", "1945", "1966")] == [
        220, 361, 444, 469, 494]


# ------------------------------------------------------------- borders by year --


def test_borders_by_year():
    features = json.loads((BOARD / "jurisdictions.geojson").read_text(encoding="utf-8"))["features"]

    def at(year):
        return [f["properties"] for f in features
                if f["properties"]["from_year"] <= year
                and (f["properties"]["to_year"] is None or year <= f["properties"]["to_year"])]

    def names(year):
        return {p["name"] for p in at(year) if p["kind"] == "label"}

    assert names(1867) == {
        "Ontario", "Quebec", "Nova Scotia", "New Brunswick", "Rupert's Land",
        "North-Western Territory", "British Columbia", "Prince Edward Island", "Newfoundland",
        "British Arctic Islands"}
    assert {"Manitoba", "North-West Territories"} <= names(1871)
    assert "Rupert's Land" not in names(1871)
    assert {"Alberta", "Saskatchewan", "Yukon Territory"} <= names(1905)
    assert "District of Keewatin" in names(1904) and "District of Keewatin" not in names(1905)
    assert "Newfoundland" in names(1949)
    for year in (1867, 1871, 1905, 1949):
        props = at(year)
        labels = [p["jurisdiction"] for p in props if p["kind"] == "label"]
        assert len(labels) == len(set(labels))
        assert all(p["a"] != p["b"] and p["a"] in labels and p["b"] in labels
                   for p in props if p["kind"] == "border")
    starts = sorted({f["properties"]["from_year"] for f in features})
    assert starts[0] == 1867 and {1870, 1873, 1905, 1912, 1949} <= set(starts)


# ------------------------------------------------------------- the engines --


def test_no_table_an_engine_reads_holds_a_float():
    for name in ENGINE_TABLES:
        with open(BOARD / name, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for column, value in row.items():
                    if column in ("name_en", "name_fr", "name_key", "place", "token", "name", "unit",
                                  "status", "sovereign", "province", "adjacency_type"):
                        continue
                    assert value == "" or value.lstrip("-").isdigit(), (name, column, value)
    assert all(isinstance(v, int) for s in places.riding_stats(BOARD).values() for v in s.values())


def test_a_world_reads_the_size_of_its_map(tmp_path):
    conn = load_seed.build(tmp_path / "board.db", seed=scenario.blank_seed_dir(), reference_data=KEY)
    assert sim.World(conn, world_seed=1867).total_units == 494
    conn.close()


@needs_node
@pytest.mark.parametrize("seed", [1867, 2, 3])
def test_both_engines_play_the_same_game_on_the_board(seed):
    import crosscheck

    differences = crosscheck.crosscheck(seed, 100, rules_version="1.0", reference_data=KEY)
    assert differences == [], differences[0][1][:4000]


@pytest.mark.xfail(strict=True, reason=(
    "under the 1.0 draft (`world_calendar`) neither engine reads opens_year: a unit"
    " is open while the atlas has it under Canada. Keeping it closed until its"
    " opening year is a rules change the director has not made"
    " (docs/hex-trial/v2/README.md, 'Where this stopped')."))
def test_no_unit_is_held_before_its_opening_year(tmp_path):
    opens = {r["fed_id"]: int(r["opens_year"]) for r in load("riding_stats.csv")}
    early = []
    for seed in (1867, 2, 3):
        conn = load_seed.build(tmp_path / f"{seed}.db", seed=scenario.blank_seed_dir(), reference_data=KEY)
        world = sim.World(conn, rules=rules_data.load_rules(version="1.0"), world_seed=seed)
        with conn:
            world.initialise(seed)
            while True:
                year = 1866 + world.season_no
                early += [
                    (seed, row["fed_id"], year) for row in conn.execute(
                        "SELECT fed_id FROM holdings WHERE released_event_id IS NULL")
                    if opens[str(row["fed_id"])] > year
                ]
                if world.season_no >= 100:
                    break
                world.run_season()
        conn.close()
    assert early == []
