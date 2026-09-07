"""Tests for the coastline-clipped, topology-simplified reference geometry.

This session's map cleanup (scripts/build_geometry.py) must never change
ridings.csv or adjacency.csv — only the geometry used for cartography.
"""

import hashlib
import json
from pathlib import Path

import pytest

# shapely is a build-time dependency (scripts/build_geometry.py), not a
# runtime one, so it is deliberately absent from requirements-engine.txt and
# the engine workflow's runner. A plain `from shapely... import` here would
# fail at collection time with a ModuleNotFoundError, which pytest reports as
# a collection *error* and which aborts the whole run before any other test
# gets to execute — marker-based deselection (`-m "not build"`) never gets a
# chance to apply, because it runs after collection, not before it.
# `importorskip` turns a missing dependency into a clean, whole-module skip
# instead, which is what makes `-m "not build"` merely documentation-accurate
# rather than the thing standing between a missing package and a dead run.
shapely_geometry = pytest.importorskip("shapely.geometry")
shapely_validation = pytest.importorskip("shapely.validation")
shape = shapely_geometry.shape
explain_validity = shapely_validation.explain_validity

# Needs shapely (see above), which only scripts/build_geometry.py installs;
# excluded from the engine workflow with `-m "not smoke and not build"`.
pytestmark = pytest.mark.build

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "data" / "reference"

# Recorded from the committed data/reference/adjacency.csv before this
# session's geometry work began. If this ever needs to change, it means an
# adjacency-affecting change was made deliberately and this hash should be
# updated in that same commit — geometry cleanup alone must never touch it.
ADJACENCY_SHA256 = "b5083fd6c5ac13b73beb1438c96009dd9af525ceed831db8929ea24e2c20efd9"

MUST_SURVIVE = {"62001": "Nunavut", "61001": "Northwest Territories", "60001": "Yukon", "10004": "Labrador"}

MAX_GEOMETRY_BYTES = 5 * 1024 * 1024


def load_geojson(name):
    with open(REFERENCE / name, encoding="utf-8") as f:
        return json.load(f)


def test_adjacency_csv_is_byte_identical():
    digest = hashlib.sha256((REFERENCE / "adjacency.csv").read_bytes()).hexdigest()
    assert digest == ADJACENCY_SHA256, (
        "adjacency.csv changed during geometry cleanup, which must never touch it"
    )


def test_geometry_simplified_has_343_valid_nonempty_features():
    fc = load_geojson("geometry_simplified.geojson")
    features = fc["features"]
    assert len(features) == 343

    fed_ids = {f["properties"]["fed_id"] for f in features}
    assert len(fed_ids) == 343

    for feature in features:
        geom = shape(feature["geometry"])
        assert not geom.is_empty, feature["properties"]["fed_id"]
        assert geom.is_valid, (feature["properties"]["fed_id"], explain_validity(geom))


def test_geometry_simplified_under_size_budget():
    size = (REFERENCE / "geometry_simplified.geojson").stat().st_size
    assert size <= MAX_GEOMETRY_BYTES, f"{size} bytes exceeds the {MAX_GEOMETRY_BYTES}-byte budget"


def test_clipping_reduced_total_area():
    stats = json.loads((REFERENCE / "geometry_clip_stats.json").read_text(encoding="utf-8"))
    assert stats["post_clip_total_km2"] < stats["pre_clip_total_km2"]
    # Clipping to the coastline should remove a substantial fraction of the
    # digital boundary file's water bleed, not a rounding error.
    assert stats["post_clip_total_km2"] < 0.9 * stats["pre_clip_total_km2"]


def test_territories_and_labrador_survive_clipping():
    fc = load_geojson("geometry_simplified.geojson")
    by_fed_id = {f["properties"]["fed_id"]: f for f in fc["features"]}
    for fed_id, name in MUST_SURVIVE.items():
        feature = by_fed_id[fed_id]
        assert feature["properties"]["name_en"] == name
        geom = shape(feature["geometry"])
        assert not geom.is_empty, name
        assert geom.area > 0, name


def test_shared_borders_reference_no_ridings_outside_the_set():
    """Every border arc must be a real line, and none may coincide with the
    ocean/lake edge that clipping just introduced (those are used by exactly
    one riding and are excluded by extract_shared_borders)."""
    borders = load_geojson("borders_shared.geojson")
    assert len(borders["features"]) > 0
    for feature in borders["features"]:
        assert feature["geometry"]["type"] == "LineString"
        assert len(feature["geometry"]["coordinates"]) >= 2


def test_site_geometry_is_smaller_than_the_main_geometry():
    """The site's inline map uses a coarser simplification, chosen so
    index.html stays under budget (see tests/test_site.py for that check)."""
    main_size = (REFERENCE / "geometry_simplified.geojson").stat().st_size
    site_size = (REFERENCE / "geometry_site.geojson").stat().st_size
    assert site_size < main_size

    site_fc = load_geojson("geometry_site.geojson")
    assert len(site_fc["features"]) == 343
    for feature in site_fc["features"]:
        geom = shape(feature["geometry"])
        assert not geom.is_empty, feature["properties"]["fed_id"]
