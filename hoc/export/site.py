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

from hoc.db import HOUSE_BLOCK_FIELDS
from hoc.export import map as map_export

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


# ------------------------------------------------------------------- pages --


def _status_strip(conn):
    counts = _counts(conn)
    turn = _latest_turn(conn)
    climate = "".join(
        f'<span class="stat"><b>{esc(row["cumulative_after"])}</b> {esc(row["era_cohort"])}</span>'
        for row in conn.execute("SELECT * FROM v_current_climate ORDER BY era_cohort")
    )
    turn_text = f"turn {turn:04d}" if turn is not None else "no turns yet"
    return (
        '<div class="status">'
        f'<span class="stat"><b>{counts["active"]}</b> active houses</span>'
        f'<span class="stat"><b>{counts["removed"]}</b> removed</span>'
        f'<span class="stat"><b>{counts["claimed"]}</b> of {counts["ridings"]} ridings held</span>'
        f"{climate}"
        f'<span class="stat">{esc(turn_text)}</span>'
        "</div>"
    )


def _index(conn, features, slugs):
    fills, legend = map_export.house_fills(conn, use_secondary=False)
    lookup = _riding_lookup(conn)
    height, to_svg = map_export.viewport(features, MAP_WIDTH)

    paths = []
    for feature in features:
        fed_id = feature["fed_id"]
        data = map_export.path_data(feature["rings"], to_svg, MAP_PRECISION)
        if not data:
            continue
        row = lookup.get(fed_id)
        house = (row["house"] if row else None) or ""
        holder = (row["holder"] if row else None) or ""
        seat = "" if not row or row["seat_order"] is None else str(row["seat_order"])
        paths.append(
            f'<path fill="{fills.get(fed_id, map_export.UNCLAIMED_FILL)}"'
            f' data-riding="{esc(row["name_en"] if row else fed_id)}"'
            f' data-province="{esc(row["province"] if row else "")}"'
            f' data-house="{esc(house)}" data-holder="{esc(holder)}"'
            f' data-seat="{esc(seat)}" data-slug="{esc(slugs.get(house, ""))}"'
            f' d="{data}"/>'
        )

    svg = (
        f'<svg id="map" viewBox="0 0 {MAP_WIDTH} {height:.0f}" role="img"'
        ' aria-label="Map of the 343 federal ridings, coloured by house"'
        ' xmlns="http://www.w3.org/2000/svg">'
        '<g stroke="#ffffff" stroke-width="0.6" stroke-linejoin="round">'
        + "".join(paths)
        + "</g></svg>"
    )

    legend_rows = "".join(
        f'<li><a href="houses/{esc(slugs[house])}.html">'
        f'<span class="swatch" style="background:{esc(colour)}"></span>'
        f'<span class="legend-name">{esc(house)}</span>'
        f'<span class="legend-count">{count}</span></a></li>'
        for house, count, colour in legend
    )

    body = (
        f"{_status_strip(conn)}\n"
        '<figure class="map-figure">' + svg + "</figure>\n"
        '<div id="panel" class="panel" hidden>'
        '<button id="panel-close" type="button" aria-label="Close">×</button>'
        '<div id="panel-body"></div></div>\n'
        '<p class="hint">Tap a riding for its holder. Grey ridings are unclaimed.</p>\n'
        "<h2>Houses by ridings held</h2>\n"
        f'<ul class="legend">{legend_rows}</ul>\n'
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
            items.append(
                f'<li><span class="marker">{text_or(row["marker"], "—")}</span> {link}'
                f'<span class="meta">{text_or(row["event_text"])}</span></li>'
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


def _chronicle_page(conn, slugs):
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
        f'<p><a href="{REPO_URL}/blob/main/docs/RECONSTRUCTION.md">Read the full reconstruction'
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
    features = map_export.projected_features()

    written = []

    def write(path, text):
        path.write_text(text, encoding="utf-8")
        written.append(path)

    write(site_dir / "style.css", STYLE)
    write(site_dir / "map.js", MAP_JS)
    write(site_dir / "index.html", _index(conn, features, slugs))
    write(site_dir / "ridings.html", _ridings_page(conn, slugs))
    write(site_dir / "climate.html", _climate_page(conn))
    write(site_dir / "chronicle.html", _chronicle_page(conn, slugs))
    write(site_dir / "about.html", _about_page(conn, slugs))

    for house_row in _houses(conn):
        write(houses_dir / f"{slugs[house_row['house']]}.html", _house_page(conn, house_row, slugs))

    # GitHub Pages would otherwise run the output through Jekyll.
    write(site_dir / ".nojekyll", "")
    return written
