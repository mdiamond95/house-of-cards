"""Build data/reference/geometry_simplified.geojson: one feature per riding,
clipped to the coastline, with topology-preserving simplification shared across
neighbours. For the map exporter only — adjacency is computed separately from
the unsimplified, unclipped projected geometry in build_adjacency.py, and this
script never touches ridings.csv or adjacency.csv.

Why clipping is needed: the Elections Canada digital boundary file is the
version meant for area/population calculations, not cartography, so it extends
into open water — ridings visibly bleed into lakes and the sea on a rendered
map. This script clips every riding to a land mask built from Natural Earth's
10m coastline, with major inland water bodies (see LAKE_AREA_THRESHOLD_KM2
below) removed from that mask so the Great Lakes etc. read as water too.

Why shared-topology simplification: simplifying each riding's polygon
independently (the previous approach) lets shared borders drift apart, which
after clipping would also open slivers of "no land" along every riding
boundary. `topojson` builds one shared-arc topology first and simplifies each
arc once, so neighbours keep touching exactly.

Usage: python scripts/build_geometry.py [tolerance]
Tolerance is in degrees (topojson's toposimplify epsilon), same units as the
old per-feature simplify. Auto-searches upward from a starting guess if the
output would exceed the 5 MB budget.
"""

import json
import sys
from pathlib import Path

import shapefile
import topojson
from pyproj import Geod, Transformer
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping, shape
from shapely.ops import clip_by_rect, transform, unary_union
from shapely.validation import make_valid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hoc.export import map as map_export  # noqa: E402  (after sys.path setup)

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "reference" / "raw"
FED_SHP = RAW_DIR / "FED_CA_2023_EN.shp"
LAND_SHP = RAW_DIR / "ne_10m_land.shp"
LAKES_SHP = RAW_DIR / "ne_10m_lakes.shp"

OUT_GEOJSON = ROOT / "data" / "reference" / "geometry_simplified.geojson"
OUT_BORDERS = ROOT / "data" / "reference" / "borders_shared.geojson"
OUT_STATS = ROOT / "data" / "reference" / "geometry_clip_stats.json"

# A second, more aggressively simplified pair for the site's inline map only —
# outputs/map.svg, the workbook, and adjacency all use the pair above. On a
# phone the difference is invisible; the byte count is not.
OUT_SITE_GEOJSON = ROOT / "data" / "reference" / "geometry_site.geojson"
OUT_SITE_BORDERS = ROOT / "data" / "reference" / "borders_site.geojson"

SOURCE_CRS = "EPSG:3347"  # the FED shapefile's native projection
TARGET_CRS = "EPSG:4326"  # WGS84, what Natural Earth and the map exporter use
MAX_BYTES = 5 * 1024 * 1024

# Budget for the *raw path data* (fills + borders, not the surrounding HTML or
# each path's data-* attributes) of the site's inline map, measured the same
# way hoc/export/site.py renders it (integer projected units at MAP_WIDTH).
# Left with headroom under the 400 KB whole-page target for ~343 paths' worth
# of data attributes (name/province/house/holder) and page boilerplate.
SITE_PATH_BYTES_BUDGET = 300 * 1024

# A riding whose clipped area falls below this fraction of its original area is
# treated as a coastline-mismatch or an all-water clip (e.g. a small-island
# riding Natural Earth's 10m coastline doesn't resolve) and kept unclipped.
MIN_CLIPPED_FRACTION = 0.01

# Lakes at or above this true (geodesic) area are cut out of the land mask as
# open water. Chosen so the director's named lakes clear it with room to spare
# while ordinary lakes stay filled in as land: the smallest named lake (Lake
# Mistassini, ~2,829 km^2) clears 1,000 km^2 by better than 2.8x, while a lake
# in the high hundreds (e.g. Lake Nipissing, ~909 km^2) stays land. See
# data/reference/raw/SOURCE.md for the full lake-area survey behind this
# number.
LAKE_AREA_THRESHOLD_KM2 = 1000

# Ridings that must survive clipping non-empty: the three territories and
# Labrador, whose Arctic/sub-Arctic coastlines are the ones most likely to be
# lost to a coastline mismatch between the two datasets.
MUST_SURVIVE = {"62001": "Nunavut", "61001": "Northwest Territories", "60001": "Yukon", "10004": "Labrador"}

GEOD = Geod(ellps="WGS84")


def geodesic_area_km2(geom):
    area, _ = GEOD.geometry_area_perimeter(geom)
    return abs(area) / 1e6


def load_fed_ridings():
    """FED polygons, reprojected to WGS84 and made valid. Returns a list of
    dicts with fed_id, name_en, geom."""
    sf = shapefile.Reader(str(FED_SHP), encoding="utf-8")
    to_wgs84 = Transformer.from_crs(SOURCE_CRS, TARGET_CRS, always_xy=True).transform

    ridings = []
    for i, record in enumerate(sf.records()):
        d = record.as_dict()
        geom = shape(sf.shape(i).__geo_interface__)
        geom = make_valid(geom)
        geom = transform(to_wgs84, geom)
        geom = make_valid(geom)
        ridings.append({"fed_id": str(d["FED_NUM"]), "name_en": d["ED_NAMEE"], "geom": geom})
    return ridings


def load_shapes(path):
    sf = shapefile.Reader(str(path), encoding="utf-8")
    return [make_valid(shape(sf.shape(i).__geo_interface__)) for i in range(len(sf))]


def build_land_mask(bounds):
    """Union of Natural Earth land, minus lakes at or above the area
    threshold. `bounds` (minx, miny, maxx, maxy) crops both inputs first so the
    union/difference only does as much work as the map actually needs."""
    minx, miny, maxx, maxy = bounds

    land_pieces = load_shapes(LAND_SHP)
    land_pieces = [clip_by_rect(g, minx, miny, maxx, maxy) for g in land_pieces]
    land_pieces = [g for g in land_pieces if not g.is_empty]
    land = make_valid(unary_union(land_pieces))

    sf = shapefile.Reader(str(LAKES_SHP), encoding="utf-8")
    big_lakes = []
    for i, record in enumerate(sf.records()):
        geom = make_valid(shape(sf.shape(i).__geo_interface__))
        if geodesic_area_km2(geom) < LAKE_AREA_THRESHOLD_KM2:
            continue
        clipped = clip_by_rect(geom, minx, miny, maxx, maxy)
        if not clipped.is_empty:
            big_lakes.append(clipped)

    if not big_lakes:
        return land

    lakes_union = make_valid(unary_union(big_lakes))
    return make_valid(land.difference(lakes_union))


def clip_ridings(ridings):
    """Clip each riding to the land mask. Returns (clipped_ridings, stats)."""
    minx = min(r["geom"].bounds[0] for r in ridings)
    miny = min(r["geom"].bounds[1] for r in ridings)
    maxx = max(r["geom"].bounds[2] for r in ridings)
    maxy = max(r["geom"].bounds[3] for r in ridings)
    pad = 1.0  # degrees; generous enough that clipping the mask never clips a riding
    land_mask = build_land_mask((minx - pad, miny - pad, maxx + pad, maxy + pad))

    fallback = []
    pre_clip_total_km2 = 0.0
    post_clip_total_km2 = 0.0
    clipped_ridings = []

    for riding in ridings:
        fed_id, name_en, geom = riding["fed_id"], riding["name_en"], riding["geom"]
        original_area = geodesic_area_km2(geom)
        pre_clip_total_km2 += original_area

        clipped = make_valid(geom.intersection(land_mask))
        clipped_area = geodesic_area_km2(clipped) if not clipped.is_empty else 0.0

        if clipped.is_empty or clipped_area < MIN_CLIPPED_FRACTION * original_area:
            print(f"  fallback to unclipped geometry: {fed_id} {name_en} "
                  f"(clipped {clipped_area:.1f} km^2 of {original_area:.1f} km^2 original)")
            fallback.append({"fed_id": fed_id, "name_en": name_en,
                              "original_km2": round(original_area, 1),
                              "clipped_km2": round(clipped_area, 1)})
            final_geom = geom
            final_area = original_area
        else:
            final_geom = clipped
            final_area = clipped_area

        if fed_id in MUST_SURVIVE:
            assert not final_geom.is_empty, f"{MUST_SURVIVE[fed_id]} ({fed_id}) came out empty"

        post_clip_total_km2 += final_area
        clipped_ridings.append({"fed_id": fed_id, "name_en": name_en, "geom": final_geom})

    stats = {
        "pre_clip_total_km2": round(pre_clip_total_km2, 1),
        "post_clip_total_km2": round(post_clip_total_km2, 1),
        "lake_area_threshold_km2": LAKE_AREA_THRESHOLD_KM2,
        "fallback_to_unclipped": fallback,
    }
    return clipped_ridings, stats


def to_feature_collection(ridings):
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"fed_id": r["fed_id"], "name_en": r["name_en"]},
                "geometry": mapping(r["geom"]),
            }
            for r in ridings
        ],
    }


def _polygonal_part(geom):
    """The polygon/multipolygon part of a geometry, discarding any point or
    line slivers make_valid() can introduce at a degenerate vertex."""
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    if isinstance(geom, GeometryCollection):
        polygons = [g for g in geom.geoms if isinstance(g, (Polygon, MultiPolygon))]
        if polygons:
            return unary_union(polygons)
    return Polygon()


def repair_feature_validity(feature_collection):
    """Toposimplify can occasionally collapse a tiny ring (a small island's
    sliver, past prevent_oversimplify's protection) into too few points to be
    a valid polygon. Repair those with make_valid and drop any non-polygonal
    debris it introduces; report how many features needed it.
    """
    repaired = 0
    features = []
    for feature in feature_collection["features"]:
        geom = shape(feature["geometry"])
        if not geom.is_valid:
            geom = _polygonal_part(make_valid(geom))
            repaired += 1
        features.append({**feature, "geometry": mapping(geom)})
    return {"type": feature_collection["type"], "features": features}, repaired


def build_topology(feature_collection, tolerance):
    topo = topojson.Topology(feature_collection, prequantize=False, prevent_oversimplify=True)
    return topo.toposimplify(tolerance)


def _walk_ring_arcs(ring, usage):
    for index in ring:
        arc_id = index if index >= 0 else ~index
        usage[arc_id] = usage.get(arc_id, 0) + 1


def _walk_geometry_arcs(geometry, usage):
    if geometry["type"] == "Polygon":
        for ring in geometry["arcs"]:
            _walk_ring_arcs(ring, usage)
    elif geometry["type"] == "MultiPolygon":
        for polygon in geometry["arcs"]:
            for ring in polygon:
                _walk_ring_arcs(ring, usage)


def extract_shared_borders(topo):
    """Riding-to-riding borders only, as WGS84 LineStrings — never the
    coastline. An arc used by exactly one polygon ring borders open water
    (ocean or a lake we cut from the mask) and is dropped; an arc used by two
    or more rings is a real border between neighbours and is kept. This reuses
    the topology's own arc-sharing bookkeeping rather than recomputing
    adjacency geometrically.
    """
    topo_dict = topo.to_dict()
    usage = {}
    for obj in topo_dict["objects"].values():
        for geometry in obj["geometries"]:
            _walk_geometry_arcs(geometry, usage)

    features = []
    for arc_id, count in usage.items():
        if count < 2:
            continue
        coords = topo_dict["arcs"][arc_id]
        if len(coords) < 2:
            continue
        features.append(
            {"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": coords}}
        )
    return {"type": "FeatureCollection", "features": features}


def build(tolerance):
    print("loading and reprojecting FED ridings...")
    ridings = load_fed_ridings()
    print(f"  {len(ridings)} ridings loaded")

    print("clipping to coastline (Natural Earth 10m land, minus major lakes)...")
    clipped_ridings, stats = clip_ridings(ridings)

    print("building shared topology and simplifying...")
    fc = to_feature_collection(clipped_ridings)
    topo = build_topology(fc, tolerance)
    return topo, stats, fc


# Must match hoc/export/site.py's MAP_WIDTH: the estimate below only predicts
# that page's actual rendered size if it uses the same projected width.
SITE_MAP_WIDTH = 1000


def _measure_site_bytes(topo):
    """Render fills+borders the same way hoc/export/site.py's index page does
    (integer projected units at SITE_MAP_WIDTH) and return the total path-data
    byte count, without needing a database connection — site.py needs one (for
    house colours and holders), this script never does.
    """
    fc = json.loads(topo.to_geojson())
    borders_fc = extract_shared_borders(topo)
    transformer = Transformer.from_crs(TARGET_CRS, map_export.PROJECTION, always_xy=True)

    features = []
    for feature in fc["features"]:
        rings = []
        for polygon in map_export._polygons(feature["geometry"]):
            for ring in polygon:
                lons = [p[0] for p in ring]
                lats = [p[1] for p in ring]
                xs, ys = transformer.transform(lons, lats)
                rings.append(list(zip(xs, ys)))
        features.append({"rings": rings})

    lines = []
    for feature in borders_fc["features"]:
        coords = feature["geometry"]["coordinates"]
        lons = [p[0] for p in coords]
        lats = [p[1] for p in coords]
        xs, ys = transformer.transform(lons, lats)
        lines.append(list(zip(xs, ys)))

    _, to_svg = map_export.viewport(features, SITE_MAP_WIDTH)
    fills_bytes = sum(len(map_export.path_data(f["rings"], to_svg, 0).encode()) for f in features)
    borders_bytes = len(map_export.border_path_data(lines, to_svg, 0).encode())
    return fills_bytes + borders_bytes, fc, borders_fc


def build_site_geometry(fc, starting_tolerance):
    """A second, more aggressively simplified pair for the site's inline map,
    built fresh from the clipped (pre-simplification) feature collection —
    not derived from the already-simplified main topology, so tightening this
    tolerance can never compound error on top of the main one.
    """
    tolerance = starting_tolerance
    topo = build_topology(fc, tolerance)
    total_bytes, site_fc, site_borders = _measure_site_bytes(topo)
    while total_bytes > SITE_PATH_BYTES_BUDGET:
        tolerance *= 1.3
        print(f"  site map over budget ({total_bytes / 1024:.1f} KB); re-simplifying at tolerance={tolerance:.5f}")
        topo = build_topology(fc, tolerance)
        total_bytes, site_fc, site_borders = _measure_site_bytes(topo)
    print(f"site geometry: tolerance={tolerance:.5f} -> {total_bytes / 1024:.1f} KB estimated path data")
    site_fc, repaired = repair_feature_validity(site_fc)
    if repaired:
        print(f"  repaired {repaired} site feature(s) left invalid by simplification")
    return site_fc, site_borders


def main():
    tolerance = float(sys.argv[1]) if len(sys.argv) > 1 else 0.003
    topo, stats, clipped_fc = build(tolerance)

    while True:
        fc = json.loads(topo.to_geojson())
        text = json.dumps(fc, separators=(",", ":"))
        size = len(text.encode("utf-8"))
        print(f"tolerance={tolerance} -> {size / 1024 / 1024:.2f} MB")
        if size <= MAX_BYTES:
            break
        tolerance *= 1.5
        print(f"  over budget; re-simplifying at tolerance={tolerance:.5f}")
        topo = topo.toposimplify(tolerance)

    fc, repaired = repair_feature_validity(fc)
    if repaired:
        print(f"  repaired {repaired} feature(s) left invalid by simplification")
    text = json.dumps(fc, separators=(",", ":"))

    assert len(fc["features"]) == 343, f"expected 343 features, got {len(fc['features'])}"
    for fed_id, label in MUST_SURVIVE.items():
        feature = next(f for f in fc["features"] if f["properties"]["fed_id"] == fed_id)
        assert feature["geometry"] is not None and feature["geometry"]["coordinates"], (
            f"{label} ({fed_id}) has no geometry after simplification"
        )
        assert shape(feature["geometry"]).area > 0, f"{label} ({fed_id}) has zero area after repair"

    borders = extract_shared_borders(topo)

    OUT_GEOJSON.write_text(text, encoding="utf-8")
    OUT_BORDERS.write_text(json.dumps(borders, separators=(",", ":")), encoding="utf-8")
    OUT_STATS.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {len(fc['features'])} features to {OUT_GEOJSON}")
    print(f"wrote {len(borders['features'])} shared border arcs to {OUT_BORDERS}")
    print(f"wrote clip stats to {OUT_STATS}")
    print(f"  pre-clip total area:  {stats['pre_clip_total_km2']:,.1f} km^2")
    print(f"  post-clip total area: {stats['post_clip_total_km2']:,.1f} km^2")
    print(f"  ridings kept unclipped: {len(stats['fallback_to_unclipped'])}")

    print("building site-specific simplification...")
    site_fc, site_borders = build_site_geometry(clipped_fc, starting_tolerance=max(tolerance, 0.01))
    OUT_SITE_GEOJSON.write_text(json.dumps(site_fc, separators=(",", ":")), encoding="utf-8")
    OUT_SITE_BORDERS.write_text(json.dumps(site_borders, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(site_fc['features'])} features to {OUT_SITE_GEOJSON}")
    print(f"wrote {len(site_borders['features'])} shared border arcs to {OUT_SITE_BORDERS}")


if __name__ == "__main__":
    main()
