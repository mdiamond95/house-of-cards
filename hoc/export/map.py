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

from hoc import places

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "outputs"

# The geometry is the reference-data set's, like the rest of the map: callers
# pass the directory the database was built from (places.reference_dir_for),
# and the default is ne-2026's data/reference/.
GEOMETRY_FILE = "geometry_simplified.geojson"
BORDERS_FILE = "borders_shared.geojson"
# A more aggressively simplified pair for the site's inline map only — see
# scripts/build_geometry.py's SITE_PATH_BYTES_BUDGET for why.
SITE_GEOMETRY_FILE = "geometry_site.geojson"
SITE_BORDERS_FILE = "borders_site.geojson"

GEOMETRY_PATH = places.DEFAULT_REFERENCE_DIR / GEOMETRY_FILE
BORDERS_PATH = places.DEFAULT_REFERENCE_DIR / BORDERS_FILE
SITE_GEOMETRY_PATH = places.DEFAULT_REFERENCE_DIR / SITE_GEOMETRY_FILE
SITE_BORDERS_PATH = places.DEFAULT_REFERENCE_DIR / SITE_BORDERS_FILE

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

# The hex board's own drawing files (scripts/build_world_hexboard.py): every land
# hexagon with the unit its land floods to, and the routes between units.
# Only a set that declares itself a hex board (set.json `hexes`) has them.
HEXES_FILE = "hexes.geojson"
ROUTES_FILE = "routes.geojson"

__all__ = [
    "write_maps", "DEFAULT_OUT_DIR", "UNCLAIMED_FILL", "PROJECTION",
    "projected_hexes", "projected_routes", "projected_jurisdictions",
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


def _reference(reference_dir):
    return places.DEFAULT_REFERENCE_DIR if reference_dir is None else Path(reference_dir)


def _drawing_path(reference_dir, name):
    """A drawing file of the set: its own if it carries one, else the shared
    coast-clipped file in data/reference/ (scripts/build_geometry.py). Only
    ne-2026 has its own; meridian-v1.0.3 draws the same 343 ridings from the
    shared files. No engine reads a drawing file, so which one a set resolves
    to is never part of a game."""
    path = _reference(reference_dir) / name
    return path if path.exists() else places.DEFAULT_REFERENCE_DIR / name


def _site_path(reference_dir, site_file, main_file):
    directory = _reference(reference_dir)
    for path in (directory / site_file, directory / main_file,
                 places.DEFAULT_REFERENCE_DIR / site_file):
        if path.exists():
            return path
    return places.DEFAULT_REFERENCE_DIR / main_file


def projected_features(reference_dir=None):
    """Every riding as projected rings. Shared by the SVG map and the site map."""
    transformer = Transformer.from_crs("EPSG:4326", PROJECTION, always_xy=True)
    return _project_features(transformer, path=_drawing_path(reference_dir, GEOMETRY_FILE))


def projected_borders(reference_dir=None):
    """Riding-to-riding borders as projected lines. Shared by the SVG map and
    the site map — never the coastline."""
    transformer = Transformer.from_crs("EPSG:4326", PROJECTION, always_xy=True)
    return _project_borders(transformer, path=_drawing_path(reference_dir, BORDERS_FILE))


def projected_site_features(reference_dir=None):
    """Every riding, at the site's coarser simplification (see
    scripts/build_geometry.py)."""
    transformer = Transformer.from_crs("EPSG:4326", PROJECTION, always_xy=True)
    return _project_features(
        transformer, path=_site_path(reference_dir, SITE_GEOMETRY_FILE, GEOMETRY_FILE)
    )


def projected_site_borders(reference_dir=None):
    """Riding-to-riding borders at the site's coarser simplification."""
    transformer = Transformer.from_crs("EPSG:4326", PROJECTION, always_xy=True)
    return _project_borders(
        transformer, path=_site_path(reference_dir, SITE_BORDERS_FILE, BORDERS_FILE)
    )


def projected_hexes(reference_dir=None):
    """Every land hexagon of a hex set, projected: [{h3, unit, dist, rings}].
    unit and dist are None for a hexagon no unit's land reaches. [] for a set
    without the file (every riding set)."""
    path = _reference(reference_dir) / HEXES_FILE
    if not path.exists():
        return []
    transformer = Transformer.from_crs("EPSG:4326", PROJECTION, always_xy=True)
    out = []
    for feature in json.loads(path.read_text(encoding="utf-8"))["features"]:
        if feature["geometry"] is None:
            continue
        rings = []
        for polygon in _polygons(feature["geometry"]):
            for ring in polygon:
                xs, ys = transformer.transform([p[0] for p in ring], [p[1] for p in ring])
                rings.append(list(zip(xs, ys)))
        props = feature["properties"]
        out.append({"h3": props["h3"], "unit": props["unit"], "dist": props["dist"], "rings": rings})
    return out


def projected_jurisdictions(reference_dir=None):
    """A hex set's first-order borders and names by span of years
    (set.json `jurisdictions`, built by scripts/build_world_hexboard.py),
    projected: ([{from, to, a, b, lines}], [{from, to, key, name, sovereign,
    status, point}]). ([], []) for a set without them."""
    name = places.set_info(_reference(reference_dir)).get("jurisdictions")
    path = _reference(reference_dir) / name if name else None
    if path is None or not path.exists():
        return [], []
    transformer = Transformer.from_crs("EPSG:4326", PROJECTION, always_xy=True)
    borders, labels = [], []
    for feature in json.loads(path.read_text(encoding="utf-8"))["features"]:
        props = feature["properties"]
        if props["kind"] == "border":
            lines = []
            for line in feature["geometry"]["coordinates"]:
                xs, ys = transformer.transform([p[0] for p in line], [p[1] for p in line])
                lines.append(list(zip(xs, ys)))
            borders.append({"from": props["from_year"], "to": props["to_year"],
                            "a": props["a"], "b": props["b"], "lines": lines})
        else:
            lon, lat = feature["geometry"]["coordinates"]
            x, y = transformer.transform(lon, lat)
            labels.append({"from": props["from_year"], "to": props["to_year"],
                           "key": props["jurisdiction"], "name": props["name"],
                           "sovereign": props["sovereign"], "status": props["status"], "point": (x, y)})
    return borders, labels


def projected_routes(reference_dir=None):
    """A hex set's routes (links longer than one step), projected:
    [{a, b, kind, length, line}], line running from unit a to unit b."""
    path = _reference(reference_dir) / ROUTES_FILE
    if not path.exists():
        return []
    transformer = Transformer.from_crs("EPSG:4326", PROJECTION, always_xy=True)
    out = []
    for feature in json.loads(path.read_text(encoding="utf-8"))["features"]:
        coords = feature["geometry"]["coordinates"]
        xs, ys = transformer.transform([p[0] for p in coords], [p[1] for p in coords])
        props = feature["properties"]
        out.append({"a": props["fed_id_a"], "b": props["fed_id_b"], "kind": props["kind"],
                    "length": props["length"], "line": list(zip(xs, ys))})
    return out


def _simplify(points, tolerance):
    """Douglas–Peucker on a ring of screen points, keeping its first and last.
    Squared distances, no square root; for drawing only."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    limit = tolerance * tolerance
    while stack:
        a, b = stack.pop()
        ax, ay = points[a]
        bx, by = points[b]
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        worst, index = -1.0, None
        for i in range(a + 1, b):
            px, py = points[i]
            if length == 0:
                d = (px - ax) ** 2 + (py - ay) ** 2
            else:
                cross = dx * (py - ay) - dy * (px - ax)
                d = cross * cross / length
            if d > worst:
                worst, index = d, i
        if index is not None and worst > limit:
            keep[index] = True
            stack.append((a, index))
            stack.append((index, b))
    return [pt for pt, k in zip(points, keep) if k]


def compact_path_data(rings, to_svg, precision=1, tolerance=0.0):
    """Path data for the hex board's layers: each ring simplified by
    `tolerance` map units (Douglas–Peucker), then written as relative moves at
    `precision` decimals, with implicit line-tos — about half the bytes of
    path_data's absolute form. Rounding is carried forward, so a ring closes
    where it began. Display only: no engine reads a drawing."""
    scale = 10 ** precision
    parts = []
    cx = cy = 0  # the pen, in integer tenths (or whatever precision gives)
    for ring in rings:
        points = [to_svg(x, y) for x, y in ring]
        if tolerance > 0:
            points = _simplify(points, tolerance)
        ints = []
        for x, y in points:
            q = (round(x * scale), round(y * scale))
            if not ints or q != ints[-1]:
                ints.append(q)
        if len(ints) > 1 and ints[0] == ints[-1]:
            ints.pop()
        if len(ints) < 3:
            continue
        out = []
        for i, (x, y) in enumerate(ints):
            dx, dy = x - cx, y - cy
            cx, cy = x, y
            out.append(f"{_fixed(dx, precision)},{_fixed(dy, precision)}")
        parts.append("m" + " ".join(out) + "z")
        # After z the pen returns to the ring's first point.
        cx, cy = ints[0]
    return "".join(parts)


def _fixed(value, precision):
    """An integer count of 10^-precision units as the shortest decimal."""
    if precision == 0:
        return str(value)
    sign = "-" if value < 0 else ""
    whole, frac = divmod(abs(value), 10 ** precision)
    text = f"{whole}.{frac:0{precision}d}".rstrip("0").rstrip(".")
    return sign + text


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

    reference_dir = places.reference_dir_for(conn)
    features = projected_features(reference_dir)
    borders = projected_borders(reference_dir)

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
