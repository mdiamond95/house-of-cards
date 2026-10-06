"""The meridian-v1.0.3 reference-data version, built from Meridian's riding table.

What is held here:

* the raw files are the pinned ones, and a wrong hash, format, version or unit
  is refused (Meridian's unit-table consumer rules);
* the committed tables are exactly what scripts/build_world_meridian.py builds
  from them, so nothing in them was edited by hand;
* the ground is the same 343 ridings and 894 land pairs as ne-2026's;
* the jurisdictions read, year by year, as the atlas has them;
* riding_stats.csv is integers only and has no invented column;
* places that span their riding are marked, and dropped on load by both engines;
* a scenario chooses the set by its manifest, the database records it, and the
  two engines play the same game on it.
"""

import csv
import gzip
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import build_world_meridian  # noqa: E402
import fetch_meridian  # noqa: E402
import load_seed  # noqa: E402
from hoc import places, scenario, sim  # noqa: E402
from hoc.export import play as play_export  # noqa: E402

KEY = "meridian-v1.0.3"
NE = ROOT / "data" / "reference"
MERIDIAN = ROOT / "data" / "reference" / "meridian" / "v1.0.3"
YEARS = range(1867, 2027)

HBC_OR_UNORGANIZED = ("hbc_charter", "unorganized")
NUNAVUT = "62001"


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def jurisdictions():
    return load(MERIDIAN / "riding_jurisdictions.csv")


def on(jurisdictions, year):
    """{fed_id: row} for the span in force in `year`; fails on any overlap."""
    out = {}
    for row in jurisdictions:
        to_year = int(row["to_year"]) if row["to_year"] else None
        if int(row["from_year"]) <= year and (to_year is None or year <= to_year):
            assert row["fed_id"] not in out, f"{row['fed_id']} has two spans in {year}"
            out[row["fed_id"]] = row
    return out


# ----------------------------------------------------------- the raw files --


def test_the_raw_files_are_the_pinned_ones():
    table = fetch_meridian.read_table()
    assert (table["format"], table["version"], table["unit"]) == (
        "meridian.unitTable", 1, "fed_2023",
    )
    assert len(table["rows"]) == 343
    fetch_meridian.read_layer()
    source = (MERIDIAN / "raw" / "SOURCE.md").read_text(encoding="utf-8")
    assert "v1.0.3" in source
    for _, local, digest in fetch_meridian.FILES:
        assert local in source and digest in source


def test_the_table_pin_is_the_directors_hash():
    assert dict((f[1], f[2]) for f in fetch_meridian.FILES)["ridings.v1.json.gz"] == (
        "60f048f44c4952638ea941162a646cddadbf6fc11478b6838178dacd307e3eb7"
    )


def test_a_wrong_hash_is_refused():
    with pytest.raises(fetch_meridian.MeridianError, match="SHA-256"):
        fetch_meridian.check_hash("x", b"not the table", "0" * 64)


@pytest.mark.parametrize("field, value", [
    ("format", "meridian.regionPack"), ("version", 2), ("unit", "fed_2013"),
])
def test_a_wrong_format_version_or_unit_is_refused(field, value):
    table = {"format": "meridian.unitTable", "version": 1, "unit": "fed_2023", field: value}
    with pytest.raises(fetch_meridian.MeridianError, match=field):
        fetch_meridian.check_table(table)


def test_the_committed_tables_are_what_the_builder_builds(tmp_path):
    build_world_meridian.build(out_dir=tmp_path, verbose=False)
    built = sorted(p.name for p in tmp_path.iterdir())
    committed = sorted(p.name for p in MERIDIAN.iterdir() if p.is_file())
    assert built == committed
    for name in built:
        assert (tmp_path / name).read_bytes() == (MERIDIAN / name).read_bytes(), name


# --------------------------------------------------------------- the ground --


def test_adjacency_is_exactly_ne_2026s():
    meridian = load(MERIDIAN / "adjacency.csv")
    ne = load(NE / "adjacency.csv")
    assert len(meridian) == 894
    pairs = {(r["fed_id_a"], r["fed_id_b"], r["adjacency_type"]) for r in meridian}
    assert pairs == {(r["fed_id_a"], r["fed_id_b"], r["adjacency_type"]) for r in ne}
    assert len(pairs) == 894


def test_ridings_ids_names_and_provinces_are_ne_2026s():
    columns = ("fed_id", "name_en", "name_fr", "province")
    meridian = [tuple(r[c] for c in columns) for r in load(MERIDIAN / "ridings.csv")]
    ne = [tuple(r[c] for c in columns) for r in load(NE / "ridings.csv")]
    assert len(meridian) == 343
    assert meridian == ne


def _bounds(geometry):
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    return [pt for polygon in polygons for ring in polygon for pt in ring]


def _inside(point, geometry):
    from shapely.geometry import Point, shape
    return shape(geometry).contains(Point(point))


def test_the_set_carries_no_drawing_files_of_its_own():
    assert not list(MERIDIAN.glob("*.geojson"))


def test_the_map_is_drawn_from_the_coast_clipped_geometry():
    from hoc.export import map as map_export
    ids = [r["fed_id"] for r in load(MERIDIAN / "ridings.csv")]
    for projected in (map_export.projected_features, map_export.projected_site_features):
        assert sorted(f["fed_id"] for f in projected(MERIDIAN)) == sorted(ids)
    assert map_export._drawing_path(MERIDIAN, map_export.GEOMETRY_FILE) == NE / map_export.GEOMETRY_FILE
    assert map_export._site_path(MERIDIAN, map_export.SITE_GEOMETRY_FILE, map_export.GEOMETRY_FILE) == (
        NE / map_export.SITE_GEOMETRY_FILE
    )
    for name in ("geometry_simplified.geojson", "geometry_site.geojson"):
        fc = json.loads((NE / name).read_text(encoding="utf-8"))
        assert sorted(f["properties"]["fed_id"] for f in fc["features"]) == sorted(ids)
        # Not the unclipped layer: nothing drawn north of 84 N, and Hudson Bay
        # (60 N 85 W) is inside no riding.
        assert max(pt[1] for f in fc["features"] for pt in _bounds(f["geometry"])) <= 84
        assert not any(_inside((-85, 60), f["geometry"]) for f in fc["features"]), name
    borders = json.loads((NE / "borders_shared.geojson").read_text(encoding="utf-8"))
    assert borders["features"]
    assert all(f["geometry"]["type"] == "LineString" for f in borders["features"])


def test_no_engine_reads_a_drawing_file():
    for path in [*(ROOT / "hoc").glob("*.py"), *(ROOT / "web" / "engine").glob("*.js")]:
        text = path.read_text(encoding="utf-8")
        assert "geojson" not in text.lower(), path


# ------------------------------------------------------------ jurisdictions --


def test_1867(jurisdictions):
    year = on(jurisdictions, 1867)
    assert len(year) == 343
    assert sum(1 for r in year.values() if r["sovereign"] == "Canada") == 216
    assert sum(1 for r in year.values() if r["status"] == "colony") == 53
    assert sum(1 for r in year.values() if r["status"] in HBC_OR_UNORGANIZED) == 74


def test_1870_rupert_s_land_the_north_western_territory_and_nunavut_join(jurisdictions):
    before = on(jurisdictions, 1867)
    after = on(jurisdictions, 1870)
    ruperts = [f for f, r in before.items() if r["unit"] == "ruperts_land"]
    north_western = [f for f, r in before.items() if r["unit"] == "north_western_territory"]
    assert (len(ruperts), len(north_western)) == (66, 7)
    for fed_id in ruperts + north_western + [NUNAVUT]:
        assert after[fed_id]["sovereign"] == "Canada", fed_id
    assert before[NUNAVUT]["name"] == "British Arctic Islands"


def test_nunavut_reads_as_the_british_arctic_islands_again_1876_to_1879(jurisdictions):
    names = {year: on(jurisdictions, year)[NUNAVUT]["name"] for year in range(1870, 1882)}
    assert {year for year, name in names.items() if name == "British Arctic Islands"} == {
        1876, 1877, 1878, 1879,
    }
    assert on(jurisdictions, 1876)[NUNAVUT]["status"] == "unorganized"
    assert on(jurisdictions, 1880)[NUNAVUT]["sovereign"] == "Canada"


def test_every_riding_has_exactly_one_row_for_every_year(jurisdictions):
    fed_ids = {r["fed_id"] for r in load(MERIDIAN / "ridings.csv")}
    for year in YEARS:
        assert set(on(jurisdictions, year)) == fed_ids, year


def test_spans_are_whole_years_and_only_the_last_is_open(jurisdictions):
    by_riding = {}
    for row in jurisdictions:
        by_riding.setdefault(row["fed_id"], []).append(row)
    for fed_id, spans in by_riding.items():
        assert spans[0]["from_year"] == "1867", fed_id
        assert spans[-1]["to_year"] == "", fed_id
        for here, after in zip(spans, spans[1:]):
            assert int(here["to_year"]) == int(after["from_year"]) - 1, fed_id
            assert int(here["from_year"]) <= int(here["to_year"]), fed_id


def test_no_span_was_dropped():
    report = json.loads((MERIDIAN / "build_report.json").read_text(encoding="utf-8"))
    assert report["jurisdiction_spans_dropped"] == []


# --------------------------------------------------------------- the stats --


def test_riding_stats_are_integers_only_with_no_invented_column():
    rows = load(MERIDIAN / "riding_stats.csv")
    assert len(rows) == 343
    assert list(rows[0]) == [
        "fed_id", "population", "land_area_km2", "wealth_tier", "resource_tier",
        "french_permille", "indigenous_identity_permille", "urban_class",
        "industry_dominant", "opens_year",
    ]
    assert not any("cohesion" in column for column in rows[0])
    for row in rows:
        for column, value in row.items():
            assert value.isdigit(), (row["fed_id"], column, value)


def test_tiers_are_quintiles():
    rows = load(MERIDIAN / "riding_stats.csv")
    for column in ("wealth_tier", "resource_tier"):
        counts = Counter(int(r[column]) for r in rows)
        assert sorted(counts) == [1, 2, 3, 4, 5]
        assert all(68 <= n <= 69 for n in counts.values()), (column, counts)
        assert sum(counts.values()) == 343


def test_wealth_tier_follows_gdp_with_ties_by_fed_id():
    table = fetch_meridian.read_table()
    gdp = {str(r["id"]): r["score"]["gdp"] for r in table["rows"]}
    tiers = {r["fed_id"]: int(r["wealth_tier"]) for r in load(MERIDIAN / "riding_stats.csv")}
    ranked = sorted(gdp, key=lambda f: (gdp[f], int(f)))
    assert [tiers[f] for f in ranked] == sorted(tiers.values())


def test_shares_are_per_mille_rounded_half_up():
    from decimal import Decimal

    assert build_world_meridian.permille(Decimal("0.0237")) == 24
    assert build_world_meridian.permille(Decimal("0.0025")) == 3
    assert build_world_meridian.permille(Decimal("0.0024")) == 2
    assert build_world_meridian.permille(Decimal("1.0")) == 1000
    with pytest.raises(ValueError):
        build_world_meridian.permille(Decimal("1.01"))


def test_opens_year():
    rows = load(MERIDIAN / "riding_stats.csv")
    assert Counter(r["opens_year"] for r in rows) == {"1867": 269, "1870": 74}
    assert {r["fed_id"]: r["opens_year"] for r in rows}[NUNAVUT] == "1870"


# --------------------------------------------------------------- the places --


def test_places_that_span_their_riding_are_marked():
    rows = load(MERIDIAN / "places_by_riding.csv")
    population = {r["fed_id"]: int(r["population"]) for r in load(MERIDIAN / "riding_stats.csv")}
    for row in rows:
        spans = int(row["population"]) > population[row["fed_id"]]
        assert row["spans_ridings"] == ("1" if spans else "0"), row

    first = {}
    for row in rows:
        first.setdefault(row["fed_id"], row)
    assert 343 - len(first) == 108
    assert sum(1 for row in first.values() if row["spans_ridings"] == "1") == 47
    assert len({r["fed_id"] for r in rows if r["spans_ridings"] == "0"}) == 203


def test_a_place_that_spans_its_riding_is_never_its_designation():
    by_riding = places.places_by_riding(MERIDIAN)
    assert len(by_riding) == 194
    halifax_riding = next(r["fed_id"] for r in load(MERIDIAN / "ridings.csv")
                          if r["name_en"] == "Central Nova")
    assert "Halifax" in {r["place"] for r in load(MERIDIAN / "places_by_riding.csv")
                         if r["fed_id"] == halifax_riding}
    assert "Halifax" not in by_riding.get(halifax_riding, [])
    # ne-2026 has no such column and loses nothing.
    assert sum(map(len, places.places_by_riding(NE).values())) == len(
        load(NE / "places_by_riding.csv")
    )


def test_designation_ok_counts():
    rows = load(MERIDIAN / "places_by_riding.csv")
    assert len(rows) == 4830
    ok = [r for r in rows if r["designation_ok"] == "1"]
    assert len(ok) == 3353
    assert len({r["fed_id"] for r in ok}) == 194
    assert all(r["spans_ridings"] == "0" for r in ok)
    report = json.loads((MERIDIAN / "build_report.json").read_text(encoding="utf-8"))
    assert (report["places_designation_ok"], report["ridings_with_a_designation_place"]) == (
        3353, 194,
    )


@pytest.mark.parametrize("name, expected", [
    ("Saint-Jérôme", 1),
    ("Baie-D’Urfé", 1),
    ("St. Mary's", 1),
    ("Notre-Dame-de-l'Île-Perrot", 1),
    ("Partridge Island", 1),                 # "Part" only as a whole word
    ("Division No.  1, Subd. U", 0),          # digits, comma, Division, No, Subd
    ("Yarmouth 33", 0),                       # a digit: refused, never trimmed to Yarmouth
    ("Cariboo I", 0),                         # a lettered subdivision
    ("Fraser Valley E", 0),
    ("Kings, Subd. A", 0),
    ("Halifax (Part)", 0),                    # parentheses
    ("Lac-Saint-Jean-Est/Ouest", 0),          # a slash
    ("Unorganized Thunder Bay", 0),
    ("Rural Municipality of Corman Park", 0),
    ("Sturgeon County", 0),
    ("Communauté Wendake", 0),
    ("Peguis Reserve", 0),
    ("Smith Part", 0),
    ("One Two Three Four", 1),
    ("One Two Three Four Five", 0),           # more than four words
])
def test_the_designation_rule(name, expected):
    assert build_world_meridian.designation_ok(name, 0) == expected


def test_a_place_that_spans_its_riding_is_never_designation_ok():
    assert build_world_meridian.designation_ok("Halifax", 1) == 0


def test_no_candidate_offered_on_meridian_contains_a_digit_or_a_comma(tmp_path):
    """Every tier of every riding's designation candidates — its own places, its
    name's words, its neighbours' places and the province bank."""
    conn = load_seed.build(tmp_path / "c.db", seed=scenario.blank_seed_dir(), reference_data=KEY)
    world = sim.World(conn, world_seed=1867)
    offered = 0
    for row in conn.execute("SELECT fed_id, province FROM ridings ORDER BY fed_id"):
        for tier in world._designation_tiers(row["fed_id"], row["province"]):
            for candidate in tier:
                offered += 1
                assert not any(ch.isdigit() or ch == "," for ch in candidate), (
                    row["fed_id"], candidate,
                )
    conn.close()
    assert offered > 3353


def test_tokens_are_ne_2026s():
    assert (MERIDIAN / "riding_tokens.csv").read_bytes() == (NE / "riding_tokens.csv").read_bytes()


# ------------------------------------------------------------- the load path --


def test_the_set_is_registered_and_the_frozen_games_keep_ne_2026():
    assert scenario.REFERENCE_SETS[KEY] == Path("data/reference/meridian/v1.0.3")
    assert scenario.reference_set_dir("ne-2026") == Path("data/reference")
    for name in scenario.frozen_names():
        assert scenario.reference_data(name) == "ne-2026", name
        assert scenario.reference_path(name) == NE


def test_an_unknown_set_is_refused():
    with pytest.raises(scenario.ScenarioError, match="unknown reference data"):
        scenario.reference_set_dir("meridian-v0")


def test_a_database_records_its_set_and_a_world_reads_from_it(tmp_path):
    conn = load_seed.build(tmp_path / "m.db", seed=scenario.blank_seed_dir(), reference_data=KEY)
    assert tuple(conn.execute("SELECT key, path FROM reference_data").fetchone()) == (
        KEY, "data/reference/meridian/v1.0.3",
    )
    assert conn.execute("SELECT COUNT(*) FROM ridings").fetchone()[0] == 343
    assert conn.execute("SELECT COUNT(*) FROM adjacency").fetchone()[0] == 894
    world = sim.World(conn, world_seed=1867)
    assert world.reference_dir == MERIDIAN
    assert len(world.riding_stats) == 343
    assert world.riding_jurisdictions[NUNAVUT][0]["name"] == "British Arctic Islands"
    conn.close()

    ne = load_seed.build(tmp_path / "n.db", seed=scenario.blank_seed_dir())
    assert ne.execute("SELECT key FROM reference_data").fetchone()[0] == "ne-2026"
    world = sim.World(ne, world_seed=1867)
    assert world.reference_dir == NE
    assert world.riding_stats == {} and world.riding_jurisdictions == {}
    ne.close()


def test_the_play_page_ships_the_world_tables_only_with_the_set_that_has_them():
    assert play_export.reference_files(NE) == play_export.REFERENCE_FILES
    assert play_export.reference_files(MERIDIAN) == (
        play_export.REFERENCE_FILES + play_export.WORLD_FILES
    )


# ---------------------------------------------------------------- two engines --

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not on PATH, so the JavaScript engine cannot run"
)

JS_LOAD = """
import { loadReferenceMap, REFERENCE_TABLES, WORLD_TABLES } from '%s';
import { readFileSync } from 'node:fs';
const read = (p) => readFileSync('%s/' + p, 'utf8');
const map = loadReferenceMap(read, '%s', REFERENCE_TABLES.concat(WORLD_TABLES));
const obj = (m) => Object.fromEntries([...m.entries()]);
process.stdout.write(JSON.stringify({
  places: obj(map.placesByRiding), tokens: obj(map.tokensByRiding),
  stats: obj(map.ridingStats), jurisdictions: obj(map.ridingJurisdictions),
}));
"""


@needs_node
def test_both_engines_load_the_same_tables():
    script = JS_LOAD % (
        (ROOT / "web" / "engine" / "adjacency.js").as_uri(), ROOT.as_posix(),
        "data/reference/meridian/v1.0.3",
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr[-2000:]
    js = json.loads(result.stdout)
    assert js["places"] == places.places_by_riding(MERIDIAN)
    assert js["tokens"] == places.tokens_by_riding(MERIDIAN)
    assert js["stats"] == places.riding_stats(MERIDIAN)
    assert js["jurisdictions"] == places.riding_jurisdictions(MERIDIAN)


@needs_node
def test_both_engines_play_the_same_game_on_meridian():
    import crosscheck

    differences = crosscheck.crosscheck(1867, 30, reference_data=KEY)
    assert differences == [], differences[0][1][:4000]


def test_a_game_on_meridian_takes_its_designations_from_meridian(tmp_path):
    """Thirty seasons on the Meridian set: every seat designation is one of that
    set's own designation_ok places, a riding-name token, or the province bank — never
    a place filed under a riding it is bigger than, unless the riding is
    named for it."""
    conn = load_seed.build(tmp_path / "m.db", seed=scenario.blank_seed_dir(), reference_data=KEY)
    world = sim.World(conn, world_seed=1867)
    with conn:
        world.initialise(1867)
        for _ in range(2, 31):
            world.run_season()
    seats = [
        tuple(row) for row in conn.execute(
            "SELECT s.seat_place, hd.fed_id FROM house_stats s"
            " JOIN holdings hd ON hd.house = s.house AND hd.seat_order = 1"
            " WHERE s.seat_place IS NOT NULL"
        )
    ]
    conn.close()
    assert seats, "thirty seasons found no house"
    rows = load(MERIDIAN / "places_by_riding.csv")
    usable = {r["place"] for r in rows if r["designation_ok"] == "1"}
    spanning = {(r["place"], r["fed_id"]) for r in rows if r["spans_ridings"] == "1"}
    tokens = {r["token"] for r in load(MERIDIAN / "riding_tokens.csv")}
    bank = {row.place for row in sim.load_rules().places}
    own_tokens = {(r["token"], r["fed_id"]) for r in load(MERIDIAN / "riding_tokens.csv")}
    for place, fed_id in seats:
        assert place in usable | tokens | bank, place
        # Terrebonne may style a house seated in Terrebonne: from the riding's
        # own name (tier 2), not from the census city bigger than the riding.
        if (place, fed_id) in spanning:
            assert (place, fed_id) in own_tokens, (place, fed_id)
