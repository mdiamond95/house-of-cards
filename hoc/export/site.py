"""Static site for reading the game on a phone.

Standard library only — no framework, no build step. Output is deterministic:
stable ordering everywhere and no timestamps beyond a single "generated from
turn NNNN" line, so a turn's diff shows only what the turn changed.

The site is written to outputs/site/ and published by .github/workflows/pages.yml.
It is a generated view: nothing here is ever read back as input.
"""

import html
import unicodedata
from pathlib import Path

from hoc import scenario
from hoc.db import HOUSE_BLOCK_FIELDS
from hoc.export import map as map_export, timeline as timeline_export

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent.parent / "outputs"
SITE_DIRNAME = "site"

MAP_WIDTH = 1000
MAP_PRECISION = 0
NOT_RECOVERED = "not recovered"

REPO_URL = "https://github.com/mdiamond95/house-of-cards"

# The one piece of build state on every page. Set by write_site so the footer
# can say which turn the site was generated from — the only "when" the site
# carries, since a wall-clock timestamp would churn the diff on every export.
_GENERATED_FROM = ""

__all__ = ["write_site", "DEFAULT_OUT_DIR", "SITE_DIRNAME"]


# ------------------------------------------------------------------ helpers --


def esc(value):
    return html.escape(str(value), quote=True)


def text_or(value, fallback=NOT_RECOVERED):
    """Render a value, or say plainly that it was never recovered.

    A blank cell in this game means "we do not know", which is worth saying out
    loud rather than leaving an empty space the reader has to interpret.
    """
    if value is None:
        return f'<span class="unrecovered">{fallback}</span>'
    text = str(value).strip()
    if not text:
        return f'<span class="unrecovered">{fallback}</span>'
    return esc(text)


def slugify(name):
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    out = []
    for ch in ascii_name.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")


def _block_order(field):
    if field in HOUSE_BLOCK_FIELDS:
        return (HOUSE_BLOCK_FIELDS.index(field), "")
    return (len(HOUSE_BLOCK_FIELDS), field)


def swatch(hex_value, label):
    if not hex_value:
        return f'<span class="swatch-row">{text_or(None)} <span class="swatch-label">{esc(label)}</span></span>'
    return (
        f'<span class="swatch-row"><span class="swatch" style="background:{esc(hex_value)}"></span>'
        f'<code>{esc(hex_value)}</code> <span class="swatch-label">{esc(label)}</span></span>'
    )


def page(title, body, depth=0, subtitle=None):
    """The shared shell. `depth` is how many directories deep the page sits."""
    up = "../" * depth
    nav = [
        ("index.html", "Map"),
        ("ridings.html", "Ridings"),
        ("chronicle.html", "Chronicle"),
        ("climate.html", "Climate"),
        ("about.html", "About"),
    ]
    links = "".join(f'<a href="{up}{href}">{esc(label)}</a>' for href, label in nav)
    sub = f'<p class="subtitle">{subtitle}</p>' if subtitle else ""
    footer = f'<footer>{esc(_GENERATED_FROM)}</footer>' if _GENERATED_FROM else ""
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)} — House of Cards</title>\n"
        f'<link rel="stylesheet" href="{up}style.css">\n'
        "</head>\n<body>\n"
        f'<header><a class="wordmark" href="{up}index.html">House of Cards</a>'
        f'<nav>{links}</nav></header>\n'
        f"<main>\n<h1>{esc(title)}</h1>\n{sub}\n{body}\n{footer}\n</main>\n"
        "</body>\n</html>\n"
    )


# -------------------------------------------------------------------- data --


def _houses(conn):
    return conn.execute(
        "SELECT h.house, h.peerage, h.rank, h.status, h.notes,"
        "       c.primary_hex, c.secondary_hex"
        " FROM houses h JOIN v_house_colours c ON c.house = h.house"
        " ORDER BY h.house"
    ).fetchall()


def _holder(conn, house):
    return conn.execute(
        "SELECT * FROM holders WHERE house = ? AND is_current = 1", (house,)
    ).fetchone()


def _holdings(conn, house):
    return conn.execute(
        "SELECT h.seat_order, h.hex, r.name_en, r.province"
        " FROM holdings h JOIN ridings r ON r.fed_id = h.fed_id"
        " WHERE h.house = ? AND h.released_event_id IS NULL ORDER BY h.seat_order",
        (house,),
    ).fetchall()


def _counts(conn):
    return conn.execute(
        "SELECT (SELECT COUNT(*) FROM houses WHERE status = 'active') AS active,"
        "       (SELECT COUNT(*) FROM houses WHERE status = 'removed') AS removed,"
        "       (SELECT COUNT(*) FROM ridings) AS ridings,"
        "       (SELECT COUNT(*) FROM holdings WHERE released_event_id IS NULL) AS claimed"
    ).fetchone()


def _latest_turn(conn):
    row = conn.execute("SELECT MAX(turn_id) AS turn FROM turns").fetchone()
    return None if row is None else row["turn"]


def _riding_lookup(conn):
    """fed_id -> everything the map panel needs about a riding."""
    lookup = {}
    for row in conn.execute(
        "SELECT r.fed_id, r.name_en, r.province, h.house, h.seat_order, hd.name AS holder"
        " FROM ridings r"
        " LEFT JOIN holdings h ON h.fed_id = r.fed_id AND h.released_event_id IS NULL"
        " LEFT JOIN holders hd ON hd.house = h.house AND hd.is_current = 1"
        " ORDER BY r.fed_id"
    ):
        lookup[row["fed_id"]] = row
    return lookup




# ------------------------------------------------------------------ charts --
#
# Inline SVG, no library. Every chart is drawn server-side into the page, so it
# renders with scripting off and costs the reader no download.

SPARK_WIDTH = 240
SPARK_HEIGHT = 44
CHART_HEIGHT = 90


def _sparkline(points, low=0, high=100, colour="#6b4f2a", label=""):
    """A stat over time. `points` is a list of (season, value)."""
    if len(points) < 2:
        return '<span class="unrecovered">not enough history yet</span>'

    seasons = [season for season, _ in points]
    span = max(seasons) - min(seasons) or 1
    spread = (high - low) or 1

    def place(season, value):
        x = (season - min(seasons)) / span * (SPARK_WIDTH - 2) + 1
        y = SPARK_HEIGHT - 1 - (value - low) / spread * (SPARK_HEIGHT - 2)
        return f"{x:.1f},{y:.1f}"

    line = " ".join(place(season, value) for season, value in points)
    last_season, last_value = points[-1]
    cx, cy = place(last_season, last_value).split(",")
    return (
        f'<svg class="spark" viewBox="0 0 {SPARK_WIDTH} {SPARK_HEIGHT}" role="img"'
        f' aria-label="{esc(label)}: {last_value} at season {last_season}">'
        f'<polyline fill="none" stroke="{colour}" stroke-width="1.4"'
        f' stroke-linejoin="round" points="{line}"/>'
        f'<circle cx="{cx}" cy="{cy}" r="2" fill="{colour}"/>'
        "</svg>"
    )


def _line_chart(points, label, colour="#6b4f2a"):
    """A ledger over its own sequence, scaled to whatever range it actually uses
    — a climate ledger has no fixed bounds, and pinning one would flatten the
    only thing the chart is for."""
    if len(points) < 2:
        return '<p class="unrecovered">not enough history to chart</p>'

    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    x_span = (max(xs) - min(xs)) or 1
    low, high = min(min(ys), 0), max(max(ys), 0)
    spread = (high - low) or 1

    def place(x, y):
        px = (x - min(xs)) / x_span * (SPARK_WIDTH - 2) + 1
        py = CHART_HEIGHT - 1 - (y - low) / spread * (CHART_HEIGHT - 2)
        return f"{px:.1f},{py:.1f}"

    line = " ".join(place(x, y) for x, y in points)
    zero_y = CHART_HEIGHT - 1 - (0 - low) / spread * (CHART_HEIGHT - 2)
    return (
        f'<svg class="chart" viewBox="0 0 {SPARK_WIDTH} {CHART_HEIGHT}" role="img"'
        f' aria-label="{esc(label)}, {min(ys)} to {max(ys)}">'
        f'<line x1="1" y1="{zero_y:.1f}" x2="{SPARK_WIDTH - 1}" y2="{zero_y:.1f}"'
        ' stroke="#e3ded3" stroke-width="1"/>'
        f'<polyline fill="none" stroke="{colour}" stroke-width="1.4"'
        f' stroke-linejoin="round" points="{line}"/>'
        "</svg>"
        f'<p class="chart-key">{esc(label)} &middot; {min(ys)} to {max(ys)}</p>'
    )


# ------------------------------------------------------- engine-aware data --


def _is_autoplay(conn):
    """Whether this database holds a game the engine played. The two scenarios
    render the same pages; the engine sections simply have nothing to say about
    a director-written game, and say so by being absent rather than empty."""
    return conn.execute("SELECT COUNT(*) AS n FROM seasons").fetchone()["n"] > 0


def _house_stats(conn, house):
    return conn.execute("SELECT * FROM house_stats WHERE house = ?", (house,)).fetchone()


def _stat_series(conn, house):
    rows = conn.execute(
        "SELECT season_no, capital, influence, cohesion FROM stat_snapshots"
        " WHERE house = ? ORDER BY season_no",
        (house,),
    ).fetchall()
    return {
        stat: [(row["season_no"], row[stat]) for row in rows]
        for stat in ("capital", "influence", "cohesion")
    }


def _event_season(row):
    """The season an engine event happened in, from its JSON delta."""
    import json as _json

    if not row["mechanical_delta"]:
        return None
    try:
        return _json.loads(row["mechanical_delta"]).get("season")
    except (ValueError, TypeError):
        return None



# ------------------------------------------------------------------- pages --


def _latest_season(conn):
    row = conn.execute("SELECT MAX(season_no) AS season FROM seasons").fetchone()
    return None if row is None else row["season"]


def _status_strip(conn):
    counts = _counts(conn)
    turn = _latest_turn(conn)
    season = _latest_season(conn)
    climate = "".join(
        f'<span class="stat"><b>{esc(row["cumulative_after"])}</b> {esc(row["era_cohort"])}</span>'
        for row in conn.execute("SELECT * FROM v_current_climate ORDER BY era_cohort")
    )
    # An autoplay scenario counts seasons and a director-written one counts turns;
    # show whichever the active scenario actually has, and say which game it is,
    # so a page never leaves the reader guessing which world they are looking at.
    if season is not None:
        progress_text = f"season {season}"
    elif turn is not None:
        progress_text = f"turn {turn:04d}"
    else:
        progress_text = "not started"
    return (
        '<div class="status">'
        f'<span class="stat scenario">scenario <b>{esc(scenario.current_name())}</b></span>'
        f'<span class="stat"><b>{counts["active"]}</b> active houses</span>'
        f'<span class="stat"><b>{counts["removed"]}</b> removed</span>'
        f'<span class="stat"><b>{counts["claimed"]}</b> of {counts["ridings"]} ridings held</span>'
        f"{climate}"
        f'<span class="stat">{esc(progress_text)}</span>'
        "</div>"
    )


NORTHERN_TERRITORIES = {"NU", "NT", "YT"}
BASE_STROKE_WIDTH = 0.4  # at the full-country viewBox, matching outputs/map.svg
SOUTH_VIEW_PAD_FRACTION = 0.03


def _extent(rings_source):
    xs = [x for rings in rings_source for ring in rings for x, _ in ring]
    ys = [y for rings in rings_source for ring in rings for _, y in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _index(conn, features, borders, slugs):
    fills, legend = map_export.house_fills(conn, use_secondary=False)
    lookup = _riding_lookup(conn)
    height, to_svg = map_export.viewport(features, MAP_WIDTH)

    paths = []
    southern_rings = []
    for feature in features:
        fed_id = feature["fed_id"]
        data = map_export.path_data(feature["rings"], to_svg, MAP_PRECISION)
        if not data:
            continue
        row = lookup.get(fed_id)
        house = (row["house"] if row else None) or ""
        holder = (row["holder"] if row else None) or ""
        seat = "" if not row or row["seat_order"] is None else str(row["seat_order"])
        province = row["province"] if row else ""
        if province not in NORTHERN_TERRITORIES:
            southern_rings.append(feature["rings"])
        paths.append(
            f'<path fill="{fills.get(fed_id, map_export.UNCLAIMED_FILL)}"'
            f' data-fed="{esc(fed_id)}"'
            f' data-riding="{esc(row["name_en"] if row else fed_id)}"'
            f' data-province="{esc(province)}"'
            f' data-house="{esc(house)}" data-holder="{esc(holder)}"'
            f' data-seat="{esc(seat)}" data-slug="{esc(slugs.get(house, ""))}"'
            f' d="{data}"/>'
        )

    border_data = map_export.border_path_data(borders, to_svg, MAP_PRECISION)

    # Full view: the whole country, as drawn (0,0)-(MAP_WIDTH,height). South
    # view (the default, per the director: territories crowd out the
    # populated south on a phone) is the bounding box of everything outside
    # Nunavut, the Northwest Territories and Yukon, padded 3%, expressed in the
    # same coordinate space so switching is just a viewBox swap — every riding
    # stays in the DOM and the tap panel keeps working either way.
    s_min_x, s_min_y, s_max_x, s_max_y = _extent(southern_rings)
    pad_x = (s_max_x - s_min_x) * SOUTH_VIEW_PAD_FRACTION
    pad_y = (s_max_y - s_min_y) * SOUTH_VIEW_PAD_FRACTION
    top_left = to_svg(s_min_x - pad_x, s_max_y + pad_y)
    bottom_right = to_svg(s_max_x + pad_x, s_min_y - pad_y)
    south_view_box = (
        f"{top_left[0]:.1f} {top_left[1]:.1f} "
        f"{bottom_right[0] - top_left[0]:.1f} {bottom_right[1] - top_left[1]:.1f}"
    )
    full_view_box = f"0 0 {MAP_WIDTH} {height:.0f}"

    # A south view narrower than the full width is a zoom-in of that factor;
    # without correcting for it the same stroke-width would render thicker
    # on screen than it does in the full view, since the same number of SVG
    # user units then covers more physical pixels.
    zoom_factor = MAP_WIDTH / (bottom_right[0] - top_left[0])
    south_stroke_width = BASE_STROKE_WIDTH / zoom_factor

    svg = (
        f'<svg id="map" viewBox="{south_view_box}" role="img"'
        ' aria-label="Map of the 343 federal ridings, coloured by house"'
        f' data-view-south="{south_view_box}" data-view-full="{full_view_box}"'
        f' data-stroke-south="{south_stroke_width:.4f}" data-stroke-full="{BASE_STROKE_WIDTH}"'
        ' xmlns="http://www.w3.org/2000/svg">'
        '<g stroke="none">' + "".join(paths) + "</g>"
        f'<path id="map-borders" fill="none" stroke="#ffffff" stroke-width="{south_stroke_width:.4f}"'
        f' stroke-linejoin="round" stroke-linecap="round" pointer-events="none" d="{border_data}"/>'
        "</svg>"
    )

    legend_rows = "".join(
        f'<li><a href="houses/{esc(slugs[house])}.html">'
        f'<span class="swatch" style="background:{esc(colour)}"></span>'
        f'<span class="legend-name">{esc(house)}</span>'
        f'<span class="legend-count">{count}</span></a></li>'
        for house, count, colour in legend
    )

    latest = _latest_season(conn)
    scrubber = ""
    if latest and latest > 1:
        # Only worth showing once there is history to scrub through; a
        # one-season world has nothing to say that the map is not already saying.
        scrubber = (
            '<div class="scrubber">'
            '<button id="play" type="button">Play</button>'
            f'<input id="season" type="range" min="1" max="{latest}" value="{latest}"'
            ' step="1" aria-label="Season">'
            f'<output id="season-label" for="season">season {latest}</output>'
            "</div>"
        )

    body = (
        f"{_status_strip(conn)}\n"
        '<figure class="map-figure">' + svg + "</figure>\n"
        f"{scrubber}\n"
        '<div class="map-toolbar">'
        '<button id="view-toggle" type="button">Show the north</button></div>\n'
        '<div id="panel" class="panel" hidden>'
        '<button id="panel-close" type="button" aria-label="Close">×</button>'
        '<div id="panel-body"></div></div>\n'
        '<p class="hint">Tap a riding for its holder. Grey ridings are unclaimed.</p>\n'
        "<h2>Houses by ridings held</h2>\n"
        f'<ul id="legend" class="legend">{legend_rows}</ul>\n'
        '<script src="map.js"></script>'
    )
    return page("The map", body, depth=0)


MAP_JS = """(function () {
  var map = document.getElementById('map');
  var panel = document.getElementById('panel');
  var body = document.getElementById('panel-body');
  var close = document.getElementById('panel-close');
  if (!map || !panel || !body || !close) return;

  function show(path) {
    var house = path.getAttribute('data-house');
    var holder = path.getAttribute('data-holder');
    var seat = path.getAttribute('data-seat');
    var slug = path.getAttribute('data-slug');
    var rows = [
      '<h3>' + path.getAttribute('data-riding') + '</h3>',
      '<p class="panel-meta">' + path.getAttribute('data-province') + '</p>'
    ];
    if (house) {
      rows.push('<p><a href="houses/' + slug + '.html">' + house + '</a>' +
                (seat ? ' &middot; seat ' + seat : '') + '</p>');
      rows.push('<p class="panel-meta">' + (holder || 'holder not recovered') + '</p>');
    } else {
      rows.push('<p class="panel-meta">Unclaimed</p>');
    }
    body.innerHTML = rows.join('');
    panel.hidden = false;
  }

  map.addEventListener('click', function (event) {
    var path = event.target.closest('path');
    if (path) show(path);
  });
  close.addEventListener('click', function () { panel.hidden = true; });

  var toggle = document.getElementById('view-toggle');
  var borders = document.getElementById('map-borders');
  if (toggle) {
    var showingSouth = true;
    toggle.addEventListener('click', function () {
      showingSouth = !showingSouth;
      map.setAttribute('viewBox', map.getAttribute(showingSouth ? 'data-view-south' : 'data-view-full'));
      if (borders) {
        borders.setAttribute('stroke-width', map.getAttribute(showingSouth ? 'data-stroke-south' : 'data-stroke-full'));
      }
      toggle.textContent = showingSouth ? 'Show the north' : 'Show the south';
    });
  }

  // ---------------------------------------------------------- the scrubber --
  //
  // The site is static, so the whole history arrives as one file and the
  // browser replays it. timeline.json holds a diff per season — only the
  // ridings that changed hands — so walking to season N means applying every
  // frame up to N, which is cheap enough to do on every drag of the slider.

  var slider = document.getElementById('season');
  if (!slider) return;

  var label = document.getElementById('season-label');
  var play = document.getElementById('play');
  var legend = document.getElementById('legend');
  var strip = document.querySelector('.status');
  var paths = Array.prototype.slice.call(map.querySelectorAll('path[data-riding]'));
  var byRiding = {};
  paths.forEach(function (path) {
    var fed = path.getAttribute('data-fed');
    if (fed) byRiding[fed] = path;
  });

  var timeline = null;
  var UNCLAIMED = '#e8e4dc';

  function ownersAt(season) {
    var owners = {};
    var frames = Object.keys(timeline.changes).map(Number).sort(function (a, b) { return a - b; });
    for (var i = 0; i < frames.length; i++) {
      if (frames[i] > season) break;
      var frame = timeline.changes[String(frames[i])];
      for (var fed in frame) owners[fed] = frame[fed];
    }
    return owners;
  }

  function paint(season) {
    var owners = ownersAt(season);
    var counts = {};
    for (var fed in byRiding) {
      var house = owners[fed] || null;
      var info = house ? timeline.houses[house] : null;
      byRiding[fed].setAttribute('fill', (info && info.primary) || UNCLAIMED);
      byRiding[fed].setAttribute('data-house', house || '');
      if (house) counts[house] = (counts[house] || 0) + 1;
    }

    if (label) label.textContent = 'season ' + season;

    var tally = timeline.counts[String(season)];
    if (strip && tally) {
      var stats = strip.querySelectorAll('.stat b');
      if (stats.length > 1) stats[1].textContent = tally[0];
      if (stats.length > 3) stats[3].textContent = tally[1];
    }

    if (legend) {
      var names = Object.keys(counts).sort(function (a, b) {
        return counts[b] - counts[a] || (a < b ? -1 : 1);
      });
      legend.innerHTML = names.map(function (name) {
        var info = timeline.houses[name] || {};
        return '<li><a href="houses/' + slugOf(name) + '.html">' +
               '<span class="swatch" style="background:' + (info.primary || UNCLAIMED) + '"></span>' +
               '<span class="legend-name">' + name + '</span>' +
               '<span class="legend-count">' + counts[name] + '</span></a></li>';
      }).join('');
    }
  }

  var slugs = {};
  paths.forEach(function (path) {
    var house = path.getAttribute('data-house');
    var slug = path.getAttribute('data-slug');
    if (house && slug) slugs[house] = slug;
  });
  function slugOf(name) {
    return slugs[name] || name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  }

  fetch('data/timeline.json').then(function (response) {
    return response.json();
  }).then(function (data) {
    timeline = data;
    Object.keys(data.houses).forEach(function (name) {
      if (!slugs[name]) {
        slugs[name] = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
      }
    });
    slider.disabled = false;
    slider.addEventListener('input', function () { paint(Number(slider.value)); });
  }).catch(function () {
    // No timeline (or opened from the filesystem): leave the map on the
    // season it was rendered at rather than blanking it.
    slider.disabled = true;
    if (label) label.textContent = 'history unavailable';
  });

  var timer = null;
  var SEASONS_PER_SECOND = 4;
  if (play) {
    play.addEventListener('click', function () {
      if (timer) {
        clearInterval(timer);
        timer = null;
        play.textContent = 'Play';
        return;
      }
      if (!timeline) return;
      if (Number(slider.value) >= Number(slider.max)) slider.value = slider.min;
      play.textContent = 'Pause';
      timer = setInterval(function () {
        var next = Number(slider.value) + 1;
        if (next > Number(slider.max)) {
          clearInterval(timer);
          timer = null;
          play.textContent = 'Play';
          return;
        }
        slider.value = next;
        paint(next);
      }, 1000 / SEASONS_PER_SECOND);
    });
  }
})();
"""




def _house_engine_sections(conn, house, slugs):
    """Everything the engine records about a house: stats and their history,
    objectives, what it has actually done, who it is related to and when, and
    the people. A director-written house has none of this, so the whole block is
    omitted rather than rendered empty."""
    stats = _house_stats(conn, house)
    if stats is None:
        return []

    parts = ["<h2>State</h2>", '<dl class="facts">']
    parts.append(f"<dt>Tag</dt><dd>{text_or(stats['tag'])}</dd>")
    parts.append(f"<dt>Community</dt><dd>{text_or(stats['community'])}</dd>")
    parts.append(f"<dt>Region</dt><dd>{text_or(stats['region'])}</dd>")
    founded = stats["founded_season"]
    founded_text = "—" if founded is None else f"season {founded}"
    parts.append(f"<dt>Founded</dt><dd>{esc(founded_text)}</dd>")
    if stats["removed_season"] is not None:
        parts.append(f"<dt>Removed</dt><dd>season {stats['removed_season']}</dd>")
    parts.append(
        f"<dt>Enclosed</dt><dd>{'yes' if stats['enclosed'] else 'no'}"
        + (f" (since season {stats['enclosed_since']})" if stats["enclosed_since"] else "")
        + "</dd>"
    )
    parts.append("</dl>")

    series = _stat_series(conn, house)
    rows = []
    for stat, colour in (("capital", "#6b4f2a"), ("influence", "#4a6f8a"), ("cohesion", "#5d7a4a")):
        rows.append(
            f"<tr><th scope=\"row\">{stat}</th>"
            f'<td class="num">{stats[stat]}</td>'
            f"<td>{_sparkline(series[stat], colour=colour, label=stat)}</td></tr>"
        )
    parts.append(
        '<table class="sparks"><thead><tr><th>Stat</th><th>Now</th>'
        f"<th>History</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )
    parts.append(
        f'<p class="footnote">Ambition {stats["ambition"]} of 10. Stats are snapshot every'
        " few seasons, so a sparkline shows the shape of a house's fortunes rather than"
        " every turn of them.</p>"
    )

    objectives = conn.execute(
        "SELECT * FROM objectives WHERE house = ? ORDER BY acquired_season, id", (house,)
    ).fetchall()
    parts.append("<h2>Objectives</h2>")
    if not objectives:
        parts.append("<p>This house holds no objective.</p>")
    else:
        items = "".join(
            f"<li><b>{esc(row['objective'])}</b>"
            f'<span class="meta">taken season {row["acquired_season"]}'
            + (
                f", satisfied season {row['satisfied_season']}"
                if row["satisfied_season"] is not None else ", still held"
            )
            + "</span></li>"
            for row in objectives
        )
        parts.append(f'<ul class="line">{items}</ul>')

    actions = conn.execute(
        "SELECT * FROM house_actions WHERE house = ? ORDER BY season_no DESC, id DESC LIMIT 30",
        (house,),
    ).fetchall()
    parts.append("<h2>Actions <span class=\"count\">last 30</span></h2>")
    if not actions:
        parts.append("<p>This house has taken no recorded action.</p>")
    else:
        rows = "".join(
            f"<tr><td class=\"num\">{row['season_no']}</td><td>{esc(row['action'])}</td>"
            f"<td>{'kept' if row['success'] else 'failed'}</td>"
            f"<td>{text_or(row['detail'], '—')}</td></tr>"
            for row in actions
        )
        parts.append(
            '<table><thead><tr><th>Season</th><th>Action</th><th>Outcome</th>'
            f"<th>Detail</th></tr></thead><tbody>{rows}</tbody></table>"
        )

    persons = conn.execute(
        "SELECT * FROM persons WHERE house = ? ORDER BY alive DESC,"
        " CASE role WHEN 'holder' THEN 0 WHEN 'heir' THEN 1 WHEN 'heir2' THEN 2 ELSE 3 END, id",
        (house,),
    ).fetchall()
    parts.append("<h2>People</h2>")
    if not persons:
        parts.append("<p>No person is recorded for this house.</p>")
    else:
        cells = []
        for row in persons:
            standing = "living" if row["alive"] else f"died season {row['died_season']}"
            married = "married" if row["married"] else "—"
            cells.append(
                f"<tr><td>{esc(row['name'])}</td><td>{esc(row['role'])}</td>"
                f'<td class="num">{row["age"]}</td>'
                f"<td>{esc(married)}</td><td>{esc(standing)}</td></tr>"
            )
        rows = "".join(cells)
        parts.append(
            '<table><thead><tr><th>Name</th><th>Role</th><th>Age</th><th>Married</th>'
            f"<th>Standing</th></tr></thead><tbody>{rows}</tbody></table>"
        )

    return parts


def _kin_line(conn, house, slugs):
    """"Cadet of" and "parent of": the partition lines, read from the founding
    events that created them (§9)."""
    parent = conn.execute(
        "SELECT e.mechanical_delta FROM events e"
        " JOIN event_houses eh ON eh.event_id = e.id AND eh.house = ?"
        " WHERE e.kind = 'founding' AND e.mechanical_delta LIKE '%partition%'"
        " ORDER BY e.id LIMIT 1",
        (house,),
    ).fetchall()

    import json as _json

    cadet_of = None
    for row in parent:
        try:
            delta = _json.loads(row["mechanical_delta"])
        except (ValueError, TypeError):
            continue
        if delta.get("nature") == "partition" and delta.get("parent") != house:
            cadet_of = delta.get("parent")

    children = []
    for row in conn.execute(
        "SELECT eh.house, e.mechanical_delta FROM events e"
        " JOIN event_houses eh ON eh.event_id = e.id"
        " WHERE e.kind = 'founding' AND e.mechanical_delta LIKE '%partition%'"
        " ORDER BY e.id"
    ):
        try:
            delta = _json.loads(row["mechanical_delta"])
        except (ValueError, TypeError):
            continue
        if delta.get("parent") == house and row["house"] != house:
            children.append(row["house"])

    def link(name):
        return (
            f'<a href="{esc(slugs[name])}.html">{esc(name)}</a>'
            if name in slugs else esc(name)
        )

    lines = []
    if cadet_of:
        lines.append(f"<p class=\"kin\">Cadet of {link(cadet_of)}, founded by partition.</p>")
    if children:
        lines.append(
            '<p class="kin">Parent of ' + ", ".join(link(name) for name in sorted(set(children)))
            + ".</p>"
        )
    return lines



JUMP_JS = """(function () {
  var select = document.getElementById('jump-season');
  if (!select) return;
  select.addEventListener('change', function () {
    var target = document.getElementById(select.value);
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
})();
"""


def _house_page(conn, house_row, slugs):
    house = house_row["house"]
    holder = _holder(conn, house)
    clock = conn.execute("SELECT * FROM clocks WHERE house = ?", (house,)).fetchone()
    holdings = _holdings(conn, house)

    parts = []

    parts.append('<dl class="facts">')
    parts.append(f"<dt>Peerage</dt><dd>{text_or(house_row['peerage'])}</dd>")
    parts.append(f"<dt>Rank</dt><dd>{text_or(house_row['rank'])}</dd>")
    parts.append(f"<dt>Status</dt><dd>{esc(house_row['status'])}</dd>")
    parts.append(
        "<dt>Colours</dt><dd>"
        + swatch(house_row["primary_hex"], "primary")
        + swatch(house_row["secondary_hex"], "secondary")
        + "</dd>"
    )
    if house_row["notes"]:
        parts.append(f"<dt>Notes</dt><dd>{esc(house_row['notes'])}</dd>")
    parts.append("</dl>")

    parts.extend(_kin_line(conn, house, slugs))
    parts.extend(_house_engine_sections(conn, house, slugs))

    parts.append("<h2>Holder</h2>")
    if holder is None:
        parts.append(f"<p>{text_or(None)}</p>")
    else:
        parts.append('<dl class="facts">')
        parts.append(f"<dt>Name</dt><dd>{text_or(holder['name'])}</dd>")
        parts.append(f"<dt>Generation</dt><dd>{text_or(holder['generation'])}</dd>")
        parts.append(f"<dt>Acceded</dt><dd>{text_or(holder['acceded'])}</dd>")
        parts.append(
            f"<dt>Biological age at accession</dt><dd>{text_or(holder['bio_age_at_accession'])}</dd>"
        )
        parts.append(f"<dt>Predecessor</dt><dd>{text_or(holder['predecessor'])}</dd>")
        parts.append(f"<dt>Heir apparent</dt><dd>{text_or(holder['heir_apparent'])}</dd>")
        parts.append(
            "<dt>Personal clock</dt><dd>"
            + (text_or(None) if clock is None else
               f"{text_or(clock['personal_year'])} — {text_or(clock['basis'])}")
            + "</dd>"
        )
        parts.append(
            f"<dt>Source</dt><dd>{text_or(holder['source'])}"
            f" <span class=\"confidence\">confidence: {text_or(holder['confidence'])}</span></dd>"
        )
        parts.append("</dl>")

    parts.append(f"<h2>Holdings <span class=\"count\">{len(holdings)}</span></h2>")
    if not holdings:
        parts.append("<p>This house holds no ridings.</p>")
    else:
        rows = "".join(
            f"<tr><td>{row['seat_order']}</td><td>{esc(row['name_en'])}</td>"
            f"<td>{esc(row['province'])}</td>"
            f'<td><span class="swatch" style="background:{esc(row["hex"])}"></span>'
            f"<code>{esc(row['hex'])}</code></td></tr>"
            for row in holdings
        )
        parts.append(
            '<table><thead><tr><th>Seat</th><th>Riding</th><th>Prov.</th><th>Colour</th></tr>'
            f"</thead><tbody>{rows}</tbody></table>"
        )
        parts.append(
            '<p class="footnote">Seat 1 is the principal seat and carries the house\'s'
            " primary colour.</p>"
        )

    blocks = sorted(
        conn.execute("SELECT * FROM house_blocks WHERE house = ?", (house,)).fetchall(),
        key=lambda row: _block_order(row["field"]),
    )
    parts.append("<h2>House block</h2>")
    if not blocks:
        parts.append(
            f"<p>{text_or(None)} — no Section 5 block has been recovered for this house."
            " See the reconstruction record.</p>"
        )
    else:
        for row in blocks:
            parts.append(
                f"<section class=\"block\"><h3>{esc(row['field'])}</h3>"
                f"<p class=\"prose\">{text_or(row['text'])}</p>"
                f"<p class=\"source\">{text_or(row['source'])}</p></section>"
            )

    successions = conn.execute(
        "SELECT * FROM successions WHERE house = ? ORDER BY seq", (house,)
    ).fetchall()
    parts.append("<h2>Succession line</h2>")
    if not successions:
        parts.append("<p>No succession has been recorded for this house.</p>")
    else:
        items = "".join(
            f"<li><b>{text_or(row['transition'])}</b>"
            f"<span class=\"meta\">{text_or(row['personal_date'], 'date not recovered')}"
            f" &middot; {text_or(row['nature'])}</span></li>"
            for row in successions
        )
        parts.append(f'<ol class="line">{items}</ol>')

    relations = conn.execute(
        "SELECT * FROM relations WHERE house_a = ? OR house_b = ? ORDER BY id", (house, house)
    ).fetchall()
    parts.append("<h2>Relations</h2>")
    if not relations:
        parts.append("<p>No relation has been recorded for this house.</p>")
    else:
        items = []
        for row in relations:
            other = row["house_b"] if row["house_a"] == house else row["house_a"]
            link = (
                f'<a href="{esc(slugs[other])}.html">{esc(other)}</a>'
                if other in slugs else esc(other)
            )
            season = None
            if row["event_id"] is not None:
                event = conn.execute(
                    "SELECT mechanical_delta FROM events WHERE id = ?", (row["event_id"],)
                ).fetchone()
                season = _event_season(event) if event is not None else None
            when = f"season {season} &middot; " if season else ""
            items.append(
                f'<li><span class="marker">{text_or(row["marker"], "—")}</span> {link}'
                f'<span class="meta">{when}{text_or(row["event_text"])}</span></li>'
            )
        parts.append(f'<ul class="relations">{"".join(items)}</ul>')

    events = conn.execute(
        "SELECT e.* FROM events e JOIN event_houses eh ON eh.event_id = e.id"
        " WHERE eh.house = ? ORDER BY e.id DESC",
        (house,),
    ).fetchall()
    parts.append("<h2>Events</h2>")
    if not events:
        parts.append("<p>This house appears in no recorded event.</p>")
    else:
        for row in events:
            head = (
                f"<h3>{text_or(row['title'])}</h3>"
                f'<p class="meta">{esc(row["kind"])}'
                + (f" &middot; turn {row['turn_id']:04d}" if row["turn_id"] is not None else "")
                + (f" &middot; {esc(row['era_cohort'])}" if row["era_cohort"] else "")
                + f" &middot; {text_or(row['source'])}</p>"
            )
            narrative = ""
            if row["narrative"]:
                paragraphs = "".join(
                    f"<p>{esc(para.strip())}</p>"
                    for para in row["narrative"].split("\n\n") if para.strip()
                )
                narrative = f'<div class="prose narrative">{paragraphs}</div>'
            parts.append(f'<article class="event">{head}{narrative}</article>')

    subtitle = (
        f'<span class="swatch" style="background:{esc(house_row["primary_hex"])}"></span>'
        if house_row["primary_hex"] else ""
    ) + esc(house_row["peerage"] or house)
    return page(house, "\n".join(parts), depth=1, subtitle=subtitle)


def _ridings_page(conn, slugs):
    rows = conn.execute(
        "SELECT r.fed_id, r.name_en, r.province, h.house, h.seat_order"
        " FROM ridings r"
        " LEFT JOIN holdings h ON h.fed_id = r.fed_id AND h.released_event_id IS NULL"
        " ORDER BY r.province, r.name_en"
    ).fetchall()

    by_province = {}
    for row in rows:
        by_province.setdefault(row["province"], []).append(row)

    parts = [f'<p class="lede">All {len(rows)} ridings of the 2023 Representation Order,'
             " by province.</p>"]
    for province in sorted(by_province):
        entries = by_province[province]
        held = sum(1 for row in entries if row["house"])
        parts.append(
            f'<h2>{esc(province)} <span class="count">{held} of {len(entries)} held</span></h2>'
        )
        items = []
        for row in entries:
            if row["house"]:
                holder = (
                    f'<a href="houses/{esc(slugs[row["house"]])}.html">{esc(row["house"])}</a>'
                )
                if row["seat_order"] == 1:
                    holder += ' <span class="seat">principal seat</span>'
            else:
                holder = '<span class="unclaimed">unclaimed</span>'
            items.append(f'<li><span class="riding">{esc(row["name_en"])}</span>{holder}</li>')
        parts.append(f'<ul class="ridings">{"".join(items)}</ul>')
    return page("Ridings", "\n".join(parts), depth=0)


def _climate_page(conn):
    parts = [
        '<p class="lede prose">The game runs more than one era-cohort of societal events at'
        " once, and the ledgers are kept apart. A climate value only means something next to"
        " the cohort it belongs to; the cohorts are never added together or averaged. The"
        " per-event calculator that produced these movements was lost with the workbook, so"
        " each cumulative value is recorded exactly as its source stated it.</p>"
    ]

    current = {
        row["era_cohort"]: row["cumulative_after"]
        for row in conn.execute("SELECT * FROM v_current_climate")
    }
    parts.append('<div class="status">')
    for cohort in sorted(current):
        parts.append(
            f'<span class="stat"><b>{esc(current[cohort])}</b> {esc(cohort)}</span>'
        )
    parts.append("</div>")

    for cohort in sorted({row["era_cohort"] for row in conn.execute("SELECT era_cohort FROM climate")}):
        parts.append(f"<h2>{esc(cohort)}</h2>")
        rows = conn.execute(
            "SELECT * FROM climate WHERE era_cohort = ? ORDER BY seq", (cohort,)
        ).fetchall()
        series = []
        for row in rows:
            try:
                series.append((row["seq"], int(row["cumulative_after"])))
            except (TypeError, ValueError):
                continue  # a cumulative recorded as prose is not a point on a line
        parts.append(_line_chart(series, f"{cohort} ledger"))
        body_rows = "".join(
            f"<tr><td>{row['seq']}</td><td>{text_or(row['event'])}</td>"
            f"<td>{text_or(row['magnitude'], '—')}</td><td>{text_or(row['tag'], '—')}</td>"
            f"<td class=\"num\">{text_or(row['cumulative_after'], '—')}</td></tr>"
            for row in rows
        )
        parts.append(
            "<table><thead><tr><th>#</th><th>Event</th><th>Magnitude</th><th>Tag</th>"
            f"<th>After</th></tr></thead><tbody>{body_rows}</tbody></table>"
        )
    return page("Climate", "\n".join(parts), depth=0)


def _link_houses(text, slugs, depth):
    """Link every house named in a chronicle line.

    Longest name first so 'Bouchard 2' is matched before 'Bouchard', and each
    name is linked once: a line that names a house twice reads worse for having
    two links in it, not better.
    """
    up = "../" * depth
    out = esc(text)
    for house in sorted(slugs, key=len, reverse=True):
        needle = esc(house)
        if needle not in out:
            continue
        replacement = f'<a href="{up}houses/{esc(slugs[house])}.html">{needle}</a>'
        out = out.replace(needle, replacement, 1)
    return out


def _season_chronicle(conn, slugs):
    """The engine's chronicle: one line per thing that happened, newest season
    first, with a jump control because three hundred seasons is a long scroll."""
    rows = conn.execute(
        "SELECT id, kind, title, narrative, mechanical_delta FROM events"
        " WHERE source = 'engine' AND narrative IS NOT NULL ORDER BY id"
    ).fetchall()

    by_season = {}
    for row in rows:
        season = _event_season(row)
        if season is None:
            continue
        by_season.setdefault(season, []).append(row)

    if not by_season:
        return page("Chronicle", "<p>No season has been played yet.</p>", depth=0)

    seasons = sorted(by_season, reverse=True)
    options = "".join(f'<option value="season-{s}">Season {s}</option>' for s in seasons)
    parts = [
        '<p class="lede">Every season, newest first.</p>',
        '<div class="jump"><label for="jump-season">Jump to</label>'
        f'<select id="jump-season">{options}</select></div>',
    ]
    for season in seasons:
        parts.append(f'<article class="season" id="season-{season}">')
        parts.append(f"<h2>Season {season}</h2>")
        lines = "".join(
            f'<li class="{esc(row["kind"])}">{_link_houses(row["narrative"], slugs, 0)}</li>'
            for row in by_season[season]
        )
        parts.append(f'<ul class="chronicle">{lines}</ul>')
        parts.append("</article>")
    parts.append('<script src="jump.js"></script>')
    return page("Chronicle", "\n".join(parts), depth=0)


def _chronicle_page(conn, slugs):
    if _is_autoplay(conn):
        return _season_chronicle(conn, slugs)
    turns = conn.execute("SELECT * FROM turns ORDER BY turn_id DESC").fetchall()
    if not turns:
        return page("Chronicle", "<p>No turn has been played yet.</p>", depth=0)

    parts = ['<p class="lede">Every turn, newest first.</p>']
    for turn in turns:
        events = conn.execute(
            "SELECT * FROM events WHERE turn_id = ? ORDER BY id", (turn["turn_id"],)
        ).fetchall()
        parts.append('<article class="turn">')
        parts.append(f'<h2>Turn {turn["turn_id"]:04d}</h2>')
        parts.append(f'<p class="directive">{text_or(turn["directive"])}</p>')
        for event in events:
            houses = [
                row["house"]
                for row in conn.execute(
                    "SELECT house FROM event_houses WHERE event_id = ? ORDER BY house",
                    (event["id"],),
                )
            ]
            links = ", ".join(
                f'<a href="houses/{esc(slugs[house])}.html">{esc(house)}</a>'
                if house in slugs else esc(house)
                for house in houses
            )
            parts.append(f'<h3>{text_or(event["title"])}</h3>')
            parts.append(
                f'<p class="meta">{esc(event["kind"])}'
                + (f" &middot; {esc(event['era_cohort'])}" if event["era_cohort"] else "")
                + (f" &middot; {links}" if links else "")
                + "</p>"
            )
            if event["narrative"]:
                paragraphs = "".join(
                    f"<p>{esc(para.strip())}</p>"
                    for para in event["narrative"].split("\n\n") if para.strip()
                )
                parts.append(f'<div class="prose narrative">{paragraphs}</div>')
        parts.append("</article>")
    return page("Chronicle", "\n".join(parts), depth=0)


def _about_page(conn, slugs):
    unnamed = conn.execute(
        "SELECT house FROM holders WHERE is_current = 1 AND name IS NULL ORDER BY house"
    ).fetchall()
    blockless = conn.execute(
        "SELECT house FROM houses WHERE house NOT IN (SELECT DISTINCT house FROM house_blocks)"
        " ORDER BY house"
    ).fetchall()
    no_secondary = conn.execute(
        "SELECT c.house FROM v_house_colours c JOIN houses h ON h.house = c.house"
        " WHERE h.status = 'active' AND c.secondary_hex IS NULL ORDER BY c.house"
    ).fetchall()

    def house_list(rows):
        if not rows:
            return "<p>None outstanding.</p>"
        links = ", ".join(
            f'<a href="houses/{esc(slugs[row["house"]])}.html">{esc(row["house"])}</a>'
            for row in rows
        )
        return f'<p class="house-list">{links}</p>'

    body = (
        '<p class="lede prose">House of Cards is a long-running alternate history of the 1867'
        " Canadian Confederation. Fictional noble houses hold peerages over the 343 real federal"
        " electoral districts of the 2023 Representation Order. Each house keeps its own personal"
        " clock beginning at 1867 — there is no shared calendar, and clocks meet only when houses"
        " do. This site is generated from the game database and is read-only.</p>\n"
        '<h2>Reconstruction</h2>\n'
        '<p class="prose">The original workbook was lost, and the game state here was rebuilt from'
        " conversation transcripts. What follows is what the record still does not hold. Nothing"
        " on this site fills those gaps with invention: an unrecovered value is shown as"
        ' <span class="unrecovered">not recovered</span>.</p>\n'
        f'<p><a href="{REPO_URL}/blob/main/scenarios/legacy/RECONSTRUCTION.md">Read the full reconstruction'
        " record on GitHub</a>.</p>\n"
        f'<h3>Holders whose name was never recovered <span class="count">{len(unnamed)}</span></h3>\n'
        f"{house_list(unnamed)}\n"
        f'<h3>Houses with no Section 5 block recovered <span class="count">{len(blockless)}</span></h3>\n'
        f"{house_list(blockless)}\n"
        f'<h3>Active houses with no secondary colour recorded <span class="count">{len(no_secondary)}</span></h3>\n'
        f"{house_list(no_secondary)}\n"
    )
    return page("About", body, depth=0)


STYLE = """/* House of Cards — one stylesheet, mobile first. */
:root {
  --paper: #fbfaf7;
  --ink: #1f1c17;
  --muted: #6d675c;
  --rule: #e3ded3;
  --accent: #6b4f2a;
  --serif: Georgia, "Iowan Old Style", "Times New Roman", serif;
  --sans: system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: var(--sans);
  font-size: 16px;
  line-height: 1.5;
  -webkit-text-size-adjust: 100%;
}
header {
  border-bottom: 1px solid var(--rule);
  padding: 0.75rem 1rem 0.5rem;
}
.wordmark {
  display: block;
  font-family: var(--serif);
  font-size: 1.1rem;
  letter-spacing: 0.02em;
  color: var(--ink);
  text-decoration: none;
}
nav { display: flex; flex-wrap: wrap; gap: 0.9rem; margin-top: 0.4rem; }
nav a { font-size: 0.82rem; color: var(--muted); text-decoration: none; }
nav a:hover, nav a:focus { color: var(--accent); text-decoration: underline; }
main { padding: 1rem 1rem 4rem; max-width: 40rem; margin: 0 auto; }
h1 { font-family: var(--serif); font-size: 1.6rem; line-height: 1.2; margin: 0.4rem 0 0.2rem; font-weight: 600; }
h2 { font-family: var(--serif); font-size: 1.15rem; margin: 2rem 0 0.5rem; font-weight: 600;
     border-top: 1px solid var(--rule); padding-top: 0.9rem; }
h3 { font-size: 0.95rem; margin: 1.2rem 0 0.3rem; font-weight: 600; }
p { margin: 0.5rem 0; }
a { color: var(--accent); }
.subtitle { font-family: var(--serif); color: var(--muted); margin: 0 0 1rem; }
.stat.scenario b { text-transform: uppercase; letter-spacing: 0.06em; }
.lede { color: var(--muted); }
.count { font-family: var(--sans); font-size: 0.75rem; font-weight: 400; color: var(--muted); }
.meta, .source, .footnote, .confidence { font-size: 0.8rem; color: var(--muted); }
.source { font-style: italic; }
.unrecovered { color: var(--muted); font-style: italic; }

/* Prose gets the serif and a narrower measure: this is a reference work. */
.prose { font-family: var(--serif); font-size: 1.02rem; line-height: 1.62; max-width: 34rem; }
.narrative p { margin: 0.75rem 0; }
.narrative p:first-child { margin-top: 0.4rem; }

.status { display: flex; flex-wrap: wrap; gap: 0.4rem 1rem; padding: 0.6rem 0;
          border-bottom: 1px solid var(--rule); font-size: 0.8rem; color: var(--muted); }
.stat b { color: var(--ink); font-size: 0.95rem; }

.map-figure { margin: 0.8rem 0 0; }
#map { width: 100%; height: auto; display: block; background: #fff; border: 1px solid var(--rule); }
#map path { cursor: pointer; }
.map-toolbar { margin: 0.5rem 0; }
.map-toolbar button { font: inherit; font-size: 0.82rem; padding: 0.4rem 0.8rem; border: 1px solid var(--rule);
                       background: #fff; color: var(--ink); border-radius: 3px; cursor: pointer; }
.map-toolbar button:hover, .map-toolbar button:focus { border-color: var(--accent); color: var(--accent); }
.hint { font-size: 0.78rem; color: var(--muted); }
.panel { position: relative; border: 1px solid var(--rule); background: #fff;
         padding: 0.7rem 2rem 0.7rem 0.8rem; margin-top: 0.6rem; }
.panel h3 { margin: 0 0 0.15rem; font-family: var(--serif); font-size: 1rem; }
.panel p { margin: 0.15rem 0; font-size: 0.88rem; }
.panel-meta { color: var(--muted); font-size: 0.8rem; }
#panel-close { position: absolute; top: 0.3rem; right: 0.4rem; border: 0; background: none;
               font-size: 1.2rem; line-height: 1; color: var(--muted); cursor: pointer; }

.swatch { display: inline-block; width: 0.8rem; height: 0.8rem; border: 1px solid rgba(0,0,0,0.18);
          vertical-align: -0.08rem; margin-right: 0.35rem; }
.swatch-row { display: inline-flex; align-items: center; margin-right: 0.9rem; }
.swatch-label { color: var(--muted); font-size: 0.75rem; margin-left: 0.3rem; }

ul, ol { padding-left: 1.1rem; }
.legend { list-style: none; padding: 0; margin: 0.4rem 0 0; }
.legend li { border-bottom: 1px solid var(--rule); }
.legend a { display: flex; align-items: center; gap: 0.1rem; padding: 0.5rem 0;
            text-decoration: none; color: var(--ink); }
.legend-name { flex: 1; }
.legend-count { color: var(--muted); font-size: 0.82rem; }

.facts { display: grid; grid-template-columns: 1fr; gap: 0; margin: 0.6rem 0; }
.facts dt { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em;
            color: var(--muted); margin-top: 0.7rem; }
.facts dd { margin: 0.1rem 0 0; }

table { width: 100%; border-collapse: collapse; margin: 0.5rem 0; font-size: 0.88rem; }
th, td { text-align: left; padding: 0.4rem 0.4rem 0.4rem 0; border-bottom: 1px solid var(--rule);
         vertical-align: top; }
th { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted);
     font-weight: 600; }
td.num { text-align: right; }
code { font-size: 0.78rem; color: var(--muted); }

.block { margin-bottom: 1rem; }
.line { margin: 0.5rem 0; }
.line li { margin-bottom: 0.5rem; }
.line .meta { display: block; }
.relations { list-style: none; padding: 0; }
.relations li { border-bottom: 1px solid var(--rule); padding: 0.5rem 0; }
.relations .marker { display: inline-block; min-width: 2.4rem; font-size: 1rem; }
.relations .meta { display: block; }

.ridings { list-style: none; padding: 0; margin: 0.3rem 0 0; }
.ridings li { display: flex; flex-wrap: wrap; gap: 0.3rem 0.6rem; justify-content: space-between;
              padding: 0.45rem 0; border-bottom: 1px solid var(--rule); font-size: 0.9rem; }
.riding { flex: 1 1 60%; }
.unclaimed { color: var(--muted); font-style: italic; }
.seat { color: var(--muted); font-size: 0.75rem; }

.spark, .chart { display: block; width: 100%; max-width: 15rem; height: auto; }
.sparks td { vertical-align: middle; }
.chart-key { font-size: 0.75rem; color: var(--muted); margin: 0.1rem 0 0.8rem; }
.kin { font-size: 0.85rem; color: var(--muted); }

.scrubber { display: flex; align-items: center; gap: 0.6rem; margin: 0.6rem 0 0.2rem; }
.scrubber input[type=range] { flex: 1; min-width: 0; }
.scrubber button { font: inherit; font-size: 0.82rem; padding: 0.3rem 0.7rem; border: 1px solid var(--rule);
                   background: #fff; color: var(--ink); border-radius: 3px; cursor: pointer; min-width: 4rem; }
.scrubber output { font-size: 0.78rem; color: var(--muted); min-width: 6.5rem; text-align: right; }

.jump { margin: 0.6rem 0 1rem; font-size: 0.85rem; color: var(--muted); }
.jump select { font: inherit; margin-left: 0.4rem; padding: 0.2rem; }
.season { margin-bottom: 1.6rem; }
.chronicle { list-style: none; padding: 0; margin: 0.3rem 0 0; }
.chronicle li { padding: 0.35rem 0; border-bottom: 1px solid var(--rule); font-size: 0.9rem; }
.chronicle li.challenge, .chronicle li.succession { font-family: var(--serif); }

.turn { margin-bottom: 2rem; }
.directive { font-family: var(--serif); font-style: italic; color: var(--ink);
             border-left: 2px solid var(--accent); padding-left: 0.7rem; margin: 0.4rem 0 0.8rem; }
.event { margin-bottom: 1.4rem; }
.house-list { line-height: 1.9; }
footer { margin-top: 3rem; padding-top: 0.8rem; border-top: 1px solid var(--rule); font-size: 0.75rem; color: var(--muted); }

@media (min-width: 40rem) {
  main { padding: 1.5rem 2rem 5rem; }
  h1 { font-size: 2rem; }
  .facts { grid-template-columns: 12rem 1fr; }
  .facts dt { margin-top: 0.35rem; }
  .facts dd { margin-top: 0.35rem; }
}
"""


# ------------------------------------------------------------------- build --


def _slugs(conn):
    slugs = {}
    for row in conn.execute("SELECT house FROM houses ORDER BY house"):
        slug = slugify(row["house"])
        if slug in slugs.values():
            raise ValueError(f"house slug collision on {slug!r} for {row['house']!r}")
        slugs[row["house"]] = slug
    return slugs


def write_site(conn, out_dir=DEFAULT_OUT_DIR):
    """Write outputs/site/. Returns the paths written."""
    site_dir = Path(out_dir) / SITE_DIRNAME
    houses_dir = site_dir / "houses"
    houses_dir.mkdir(parents=True, exist_ok=True)

    global _GENERATED_FROM
    turn = _latest_turn(conn)
    _GENERATED_FROM = (
        f"generated from turn {turn:04d}" if turn is not None else "generated before any turn"
    )

    slugs = _slugs(conn)
    index_features = map_export.projected_site_features()
    index_borders = map_export.projected_site_borders()

    written = []

    def write(path, text):
        path.write_text(text, encoding="utf-8")
        written.append(path)

    write(site_dir / "style.css", STYLE)
    write(site_dir / "map.js", MAP_JS)
    write(site_dir / "jump.js", JUMP_JS)

    # The scrubber reads the whole history from one file; nothing else does.
    timeline_path, timeline_bytes = timeline_export.write_timeline(conn, site_dir / "data")
    written.append(timeline_path)
    if timeline_bytes > timeline_export.SIZE_BUDGET:
        print(
            f"warning: {timeline_path} is {timeline_bytes:,} bytes, over the"
            f" {timeline_export.SIZE_BUDGET:,} budget — snapshot less often"
        )
    write(site_dir / "index.html", _index(conn, index_features, index_borders, slugs))
    write(site_dir / "ridings.html", _ridings_page(conn, slugs))
    write(site_dir / "climate.html", _climate_page(conn))
    write(site_dir / "chronicle.html", _chronicle_page(conn, slugs))
    write(site_dir / "about.html", _about_page(conn, slugs))

    for house_row in _houses(conn):
        write(houses_dir / f"{slugs[house_row['house']]}.html", _house_page(conn, house_row, slugs))

    # GitHub Pages would otherwise run the output through Jekyll.
    write(site_dir / ".nojekyll", "")
    return written
