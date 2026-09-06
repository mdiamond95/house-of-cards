"""Build data/reference/geometry_simplified.geojson: one simplified feature per
riding, reprojected to WGS84, for the map exporter only (not for analysis —
adjacency is computed separately from the unsimplified projected geometry in
build_adjacency.py).

Usage: python scripts/build_geometry.py [tolerance_degrees]
Tolerance defaults to 0.005 degrees (~500 m), chosen empirically to keep the
output under the 5 MB budget while remaining recognisable at map scale.
"""

import json
import sys
from pathlib import Path

import shapefile
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform

ROOT = Path(__file__).resolve().parent.parent
RAW_SHP = ROOT / "data" / "reference" / "raw" / "FED_CA_2023_EN.shp"
OUT_GEOJSON = ROOT / "data" / "reference" / "geometry_simplified.geojson"

SOURCE_CRS = "EPSG:3347"
TARGET_CRS = "EPSG:4326"
MAX_BYTES = 5 * 1024 * 1024


def build(tolerance):
    sf = shapefile.Reader(str(RAW_SHP), encoding="utf-8")
    to_wgs84 = Transformer.from_crs(SOURCE_CRS, TARGET_CRS, always_xy=True).transform

    features = []
    for i, record in enumerate(sf.records()):
        d = record.as_dict()
        fed_id = str(d["FED_NUM"])
        name_en = d["ED_NAMEE"]
        geom = shape(sf.shape(i).__geo_interface__).buffer(0)
        geom = transform(to_wgs84, geom)
        geom = geom.simplify(tolerance, preserve_topology=True)
        features.append(
            {
                "type": "Feature",
                "properties": {"fed_id": fed_id, "name_en": name_en},
                "geometry": mapping(geom),
            }
        )

    return {"type": "FeatureCollection", "features": features}


def main():
    tolerance = float(sys.argv[1]) if len(sys.argv) > 1 else 0.005
    fc = build(tolerance)
    text = json.dumps(fc, separators=(",", ":"))
    size = len(text.encode("utf-8"))
    print(f"tolerance={tolerance} -> {size / 1024 / 1024:.2f} MB")
    if size > MAX_BYTES:
        print("WARNING: exceeds 5 MB budget; re-run with a larger tolerance", file=sys.stderr)
        sys.exit(1)
    OUT_GEOJSON.write_text(text, encoding="utf-8")
    print(f"wrote {len(fc['features'])} features to {OUT_GEOJSON}")


if __name__ == "__main__":
    main()
