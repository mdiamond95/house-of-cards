"""Riding map as SVG, drawn from the simplified geometry and current holdings.

Two files are produced:
  map.svg            — every riding of a house in that house's primary colour.
  map_secondary.svg  — the principal seat (seat_order 1) in the primary colour
                       and the rest of the house's ridings in its secondary,
                       which is how the old map distinguished seats.
"""

import json
from pathlib import Path

from pyproj import Transformer

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "outputs"
GEOMETRY_PATH = REPO_ROOT / "data" / "reference" / "geometry_simplified.geojson"
BORDERS_PATH = REPO_ROOT / "data" / "reference" / "borders_shared.geojson"
# A more aggressively simplified pair for the site's inline map only — see
# scripts/build_geometry.py's SITE_PATH_BYTES_BUDGET for why.
SITE_GEOMETRY_PATH = REPO_ROOT / "data" / "reference" / "geometry_site.geojson"
SITE_BORDERS_PATH = REPO_ROOT / "data" / "reference" / "borders_site.geojson"

UNCLAIMED_FILL = "#E5E5E5"
BORDER = "#FFFFFF"
BORDER_WIDTH = 0.4
WIDTH = 1600
MARGIN = 20
LEGEND_WIDTH = 300
LEGEND_ROW_HEIGHT = 15
MAX_BYTES = 3 * 1024 * 1024

# Lambert Conformal Conic, the projection the old map used.
PROJECTION = "+proj=lcc +lat_1=49 +lat_2=77 +lat_0=49 +lon_0=-95 +datum=WGS84 +units=m +no_defs"

__all__ = [
    "write_maps", "DEFAULT_OUT_DIR", "UNCLAIMED_FILL", "PROJECTION",
    "projected_features", "projected_borders",
    "projected_site_features", "projected_site_borders",
    "viewport", "path_data", "border_path_data", "house_fills",
]


def _polygons(geometry):
    """Every ring set in a geometry, as a list of polygons (list of rings)."""
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return list(geometry["coordinates"])
    return []


def _project_features(transformer, path=GEOMETRY_PATH):
    data = json.loads(path.read_text(encoding="utf-8"))
    features = []
    for feature in data["features"]:
        rings = []
        for polygon in _polygons(feature["geometry"]):
            for ring in polygon:
                lons = [point[0] for point in ring]
                lats = [point[1] for point in ring]
                xs, ys = transformer.transform(lons, lats)
                rings.append(list(zip(xs, ys)))
        features.append(
            {
                "fed_id": feature["properties"]["fed_id"],
                "name": feature["properties"]["name_en"],
                "rings": rings,
            }
        )
    return features


def _project_borders(transformer, path=BORDERS_PATH):
    """Riding-to-riding borders only, projected the same way as the fills —
    never the coastline. See scripts/build_geometry.py's extract_shared_borders
    for how these arcs were picked out of the topology."""
    data = json.loads(path.read_text(encoding="utf-8"))
    lines = []
    for feature in data["features"]:
        coords = feature["geometry"]["coordinates"]
        lons = [point[0] for point in coords]
        lats = [point[1] for point in coords]
        xs, ys = transformer.transform(lons, lats)
        lines.append(list(zip(xs, ys)))
    return lines


def _bounds(features):
    xs = [x for f in features for ring in f["rings"] for x, _ in ring]
    ys = [y for f in features for ring in f["rings"] for _, y in ring]
    return min(xs), min(ys), max(xs), max(ys)


def house_fills(conn, use_secondary):
    """fed_id -> fill colour, and the house riding counts for the legend."""
    fills = {}
    counts = {}
    for row in conn.execute(
        "SELECT h.fed_id, h.house, h.seat_order, c.primary_hex, c.secondary_hex"
        " FROM holdings h JOIN v_house_colours c ON c.house = h.house"
        " WHERE h.released_event_id IS NULL"
    ):
        primary = row["primary_hex"] or UNCLAIMED_FILL
        if use_secondary and row["seat_order"] != 1:
            fills[row["fed_id"]] = row["secondary_hex"] or primary
        else:
            fills[row["fed_id"]] = primary
        counts[row["house"]] = counts.get(row["house"], 0) + 1

    legend = [
        (row["house"], counts.get(row["house"], 0), row["primary_hex"] or UNCLAIMED_FILL)
        for row in conn.execute(
            "SELECT c.house, c.primary_hex FROM v_house_colours c"
            " JOIN houses hs ON hs.house = c.house WHERE hs.status = 'active'"
        )
    ]
    legend = [entry for entry in legend if entry[1] > 0]
    legend.sort(key=lambda entry: (-entry[1], entry[0]))
    return fills, legend


def path_data(rings, to_svg, precision):
    parts = []
    for ring in rings:
        if len(ring) < 3:
            continue
        points = [to_svg(x, y) for x, y in ring]
        head = points[0]
        parts.append(f"M{head[0]:.{precision}f},{head[1]:.{precision}f}")
        previous = head
        for point in points[1:]:
            if round(point[0], precision) == round(previous[0], precision) and \
               round(point[1], precision) == round(previous[1], precision):
                continue  # a point that rounds onto the last one adds nothing
            parts.append(f"L{point[0]:.{precision}f},{point[1]:.{precision}f}")
            previous = point
        parts.append("Z")
    return "".join(parts)


def border_path_data(lines, to_svg, precision):
    """Path data for a set of open LineStrings (riding-to-riding borders) —
    no closing Z, unlike a fill ring."""
    parts = []
    for line in lines:
        if len(line) < 2:
            continue
        points = [to_svg(x, y) for x, y in line]
        head = points[0]
        parts.append(f"M{head[0]:.{precision}f},{head[1]:.{precision}f}")
        previous = head
        for point in points[1:]:
            if round(point[0], precision) == round(previous[0], precision) and \
               round(point[1], precision) == round(previous[1], precision):
                continue
            parts.append(f"L{point[0]:.{precision}f},{point[1]:.{precision}f}")
            previous = point
    return "".join(parts)


def _render(features, borders, fills, legend, title, precision):
    min_x, min_y, max_x, max_y = _bounds(features)
    span_x = max_x - min_x
    span_y = max_y - min_y
    map_width = WIDTH - LEGEND_WIDTH - 2 * MARGIN
    scale = map_width / span_x
    map_height = span_y * scale
    height = max(map_height, len(legend) * LEGEND_ROW_HEIGHT + 40) + 2 * MARGIN

    def to_svg(x, y):
        return (MARGIN + (x - min_x) * scale, MARGIN + (max_y - y) * scale)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height:.0f}"'
        f' viewBox="0 0 {WIDTH} {height:.0f}">',
        f'<title>{title}</title>',
        f'<rect width="{WIDTH}" height="{height:.0f}" fill="#FFFFFF"/>',
        '<g stroke="none">',
    ]
    for feature in features:
        fill = fills.get(feature["fed_id"], UNCLAIMED_FILL)
        data = path_data(feature["rings"], to_svg, precision)
        if not data:
            continue
        out.append(f'<path fill="{fill}" d="{data}"/>')
    out.append("</g>")

    # Riding-to-riding borders only, drawn on top; the coastline (where a
    # riding meets open water) never gets a stroke.
    border_data = border_path_data(borders, to_svg, precision)
    if border_data:
        out.append(
            f'<path fill="none" stroke="{BORDER}" stroke-width="{BORDER_WIDTH}"'
            f' stroke-linejoin="round" stroke-linecap="round" d="{border_data}"/>'
        )

    legend_x = WIDTH - LEGEND_WIDTH
    out.append(
        f'<text x="{legend_x}" y="{MARGIN + 12}" font-family="sans-serif" font-size="12"'
        f' font-weight="bold" fill="#222222">Houses by ridings held</text>'
    )
    for i, (house, count, colour) in enumerate(legend):
        y = MARGIN + 30 + i * LEGEND_ROW_HEIGHT
        out.append(
            f'<rect x="{legend_x}" y="{y - 9}" width="11" height="11" fill="{colour}"'
            f' stroke="#999999" stroke-width="0.5"/>'
        )
        out.append(
            f'<text x="{legend_x + 17}" y="{y}" font-family="sans-serif" font-size="11"'
            f' fill="#222222">{house} ({count})</text>'
        )
    out.append("</svg>")
    return "\n".join(out)


def projected_features():
    """Every riding as projected rings. Shared by the SVG map and the site map."""
    transformer = Transformer.from_crs("EPSG:4326", PROJECTION, always_xy=True)
    return _project_features(transformer)


def projected_borders():
    """Riding-to-riding borders as projected lines. Shared by the SVG map and
    the site map — never the coastline."""
    transformer = Transformer.from_crs("EPSG:4326", PROJECTION, always_xy=True)
    return _project_borders(transformer)


def projected_site_features():
    """Every riding, at the site's coarser simplification (see
    scripts/build_geometry.py)."""
    transformer = Transformer.from_crs("EPSG:4326", PROJECTION, always_xy=True)
    return _project_features(transformer, path=SITE_GEOMETRY_PATH)


def projected_site_borders():
    """Riding-to-riding borders at the site's coarser simplification."""
    transformer = Transformer.from_crs("EPSG:4326", PROJECTION, always_xy=True)
    return _project_borders(transformer, path=SITE_BORDERS_PATH)


def viewport(features, width, margin=0):
    """Fit the features to a given width. Returns (height, to_svg)."""
    min_x, min_y, max_x, max_y = _bounds(features)
    scale = (width - 2 * margin) / (max_x - min_x)
    height = (max_y - min_y) * scale + 2 * margin

    def to_svg(x, y):
        return (margin + (x - min_x) * scale, margin + (max_y - y) * scale)

    return height, to_svg


def write_maps(conn, out_dir=DEFAULT_OUT_DIR):
    """Write outputs/map.svg and outputs/map_secondary.svg. Returns the paths.

    Coordinate precision drops a step at a time if a file would exceed the 3 MB
    budget, which shrinks the file without changing the geometry it came from.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    transformer = Transformer.from_crs("EPSG:4326", PROJECTION, always_xy=True)
    features = _project_features(transformer)
    borders = _project_borders(transformer)

    written = []
    for filename, use_secondary, title in (
        ("map.svg", False, "House of Cards — ridings by house"),
        ("map_secondary.svg", True, "House of Cards — principal seats in primary colour"),
    ):
        fills, legend = house_fills(conn, use_secondary)
        for precision in (1, 0):
            svg = _render(features, borders, fills, legend, title, precision)
            if len(svg.encode("utf-8")) <= MAX_BYTES:
                break
        path = out_dir / filename
        path.write_text(svg, encoding="utf-8")
        written.append(path)
    return written
