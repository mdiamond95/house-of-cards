"""Static site exporter tests."""

import importlib.util
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

import pytest

from hoc import scenario

from hoc.export import site

ROOT = Path(__file__).resolve().parent.parent

TOP_LEVEL_PAGES = ("index.html", "ridings.html", "chronicle.html", "climate.html", "about.html")
MAX_INDEX_BYTES = 400 * 1024


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("load_seed", ROOT / "scripts" / "load_seed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Build the site from a database rebuilt from the seed plus every turn."""
    from hoc.turn import apply_turn

    conn = _load_seed_module().build(
        tmp_path_factory.mktemp("db") / "hoc.db", seed=scenario.seed_dir("legacy")
    )
    for path in sorted((ROOT / "scenarios" / "legacy" / "turns").glob("[0-9][0-9][0-9][0-9]_*.json")):
        apply_turn(conn, path)

    out_dir = tmp_path_factory.mktemp("out")
    site.write_site(conn, out_dir=out_dir)
    yield out_dir / site.SITE_DIRNAME
    conn.close()


def html_files(site_dir):
    return sorted(site_dir.rglob("*.html"))


def test_top_level_pages_exist(built):
    for name in TOP_LEVEL_PAGES:
        path = built / name
        assert path.exists(), name
        assert path.stat().st_size > 0, name
    assert (built / "style.css").exists()
    assert (built / "map.js").exists()


def test_index_html_under_size_budget(built):
    # On a phone the index page's inline map dominates the byte count, so this
    # is really a check on the site-specific geometry tolerance (see
    # scripts/build_geometry.py's build_site_geometry / SITE_PATH_BYTES_BUDGET).
    size = (built / "index.html").stat().st_size
    assert size <= MAX_INDEX_BYTES, f"{size} bytes exceeds the {MAX_INDEX_BYTES}-byte budget"


def test_one_page_per_house(built):
    pages = sorted((built / "houses").glob("*.html"))
    assert len(pages) == 35  # 33 active + 2 removed


def test_macleod_page_carries_its_holdings_and_turn(built):
    html = (built / "houses" / "macleod.html").read_text(encoding="utf-8")
    assert "Calgary Centre" in html
    assert "The Counting-House Made Freehold" in html
    assert "Sir Alexander Donald Macleod" in html
    # The house block recovered in the reconstruction commit.
    assert "Turner Valley" in html


def test_no_python_none_leaks_into_any_page(built):
    """Unrecovered values must read as "not recovered", never as a bare None.

    The literal word does appear once in the data — Macleod's recovered heir
    block opens "None formally named at grant." — so this asserts the intent
    (no Python None rendered into the page) rather than the absence of the
    substring, and pins the one legitimate occurrence.
    """
    for path in html_files(built):
        html = path.read_text(encoding="utf-8")
        assert ">None<" not in html, path.name
        assert '="None"' not in html, path.name
        for match in re.finditer("None", html):
            context = html[max(0, match.start() - 60):match.start() + 60]
            assert "formally named at grant" in context, f"{path.name}: bare None in {context!r}"


def test_pages_are_self_contained_and_relatively_linked(built):
    for path in html_files(built):
        html = path.read_text(encoding="utf-8")
        assert html.startswith("<!doctype html>")
        assert html.rstrip().endswith("</html>")
        # Relative links only: the site is served from a repository subpath.
        assert 'href="/' not in html, path.name
        assert 'src="/' not in html, path.name

    for path in (built / "houses").glob("*.html"):
        assert '<link rel="stylesheet" href="../style.css">' in path.read_text(encoding="utf-8")


def test_map_carries_one_path_per_riding_with_data_attributes(built):
    html = (built / "index.html").read_text(encoding="utf-8")
    # 343 riding fills plus one border-mesh path (id="map-borders") — the
    # coastline-vs-interior-border distinction from scripts/build_geometry.py.
    assert html.count("<path") == 344
    assert 'id="map-borders"' in html
    assert html.count("data-riding=") == 343
    assert 'data-house="Macleod"' in html
    assert 'data-holder="Sir Alexander Donald Macleod"' in html


def test_map_defaults_to_southern_view_with_a_north_toggle(built):
    html = (built / "index.html").read_text(encoding="utf-8")
    assert 'id="view-toggle"' in html
    assert "Show the north" in html
    assert 'data-view-south="' in html
    assert 'data-view-full="' in html
    assert 'data-stroke-south="' in html
    assert 'data-stroke-full="' in html


def test_unrecovered_values_are_named_as_such(built):
    # Akatsiak's holder name was never recovered and it has no house block.
    html = (built / "houses" / "akatsiak.html").read_text(encoding="utf-8")
    assert "not recovered" in html

    about = (built / "about.html").read_text(encoding="utf-8")
    assert "Holders whose name was never recovered" in about
    assert "RECONSTRUCTION.md" in about


def test_output_is_deterministic(built, tmp_path):
    """A second build of the same state must be byte-identical, so a turn's diff
    shows only what the turn changed."""
    from hoc.turn import apply_turn

    conn = _load_seed_module().build(tmp_path / "hoc.db", seed=scenario.seed_dir("legacy"))
    for path in sorted((ROOT / "scenarios" / "legacy" / "turns").glob("[0-9][0-9][0-9][0-9]_*.json")):
        apply_turn(conn, path)
    site.write_site(conn, out_dir=tmp_path / "out")
    conn.close()

    rebuilt = tmp_path / "out" / site.SITE_DIRNAME
    for path in html_files(built):
        twin = rebuilt / path.relative_to(built)
        assert twin.read_text(encoding="utf-8") == path.read_text(encoding="utf-8"), path.name


class _IdCollector(HTMLParser):
    """Every id attribute on a page, in document order.

    A real parser rather than a regular expression: an id is an id however the
    attribute is quoted or ordered, and the bug this guards against was invisible
    to reading the template — the section and the button inside it both answered
    to `connect`, so `getElementById` returned the section and the connect
    handler fired on every click within it, clearing the token field.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == "id" and value:
                self.ids.append(value)


def element_ids(path):
    collector = _IdCollector()
    collector.feed(path.read_text(encoding="utf-8"))
    return collector.ids


def duplicate_ids(path):
    return {name: count for name, count in Counter(element_ids(path)).items() if count > 1}


def test_every_page_has_unique_element_ids(built):
    """An id shared by two elements makes getElementById a coin toss, and every
    script on the site reaches for elements by id."""
    pages = html_files(built)
    assert pages, "the site should have rendered some pages"

    offenders = {
        str(path.relative_to(built)): duplicate_ids(path)
        for path in pages
        if duplicate_ids(path)
    }
    assert not offenders, f"duplicate element ids: {offenders}"


def test_every_page_of_a_played_world_has_unique_element_ids(tmp_path):
    """The legacy site has no scrubber, no season chronicle and no engine
    sections on its house pages, so the pages that only an engine-played game
    produces need auditing too."""
    from hoc import sim

    conn = _load_seed_module().build(tmp_path / "played.db", seed=scenario.seed_dir("new"))
    world = sim.World(conn, world_seed=1867)
    world.initialise(1867)
    for _ in range(9):
        world.run_season()
    site.write_site(conn, out_dir=tmp_path)
    conn.close()

    site_dir = tmp_path / site.SITE_DIRNAME
    pages = html_files(site_dir)
    assert any(path.name == "console.html" for path in pages)
    assert 'id="season"' in (site_dir / "index.html").read_text(encoding="utf-8")

    offenders = {
        str(path.relative_to(site_dir)): duplicate_ids(path)
        for path in pages
        if duplicate_ids(path)
    }
    assert not offenders, f"duplicate element ids: {offenders}"


def test_the_archive_pages_have_unique_element_ids(tmp_path):
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import build_archive

    build_archive.build_archive(out_dir=tmp_path)
    archive = tmp_path / site.SITE_DIRNAME / site.ARCHIVE_DIRNAME

    pages = html_files(archive)
    assert pages
    offenders = {
        str(path.relative_to(archive)): duplicate_ids(path)
        for path in pages
        if duplicate_ids(path)
    }
    assert not offenders, f"duplicate element ids: {offenders}"


def test_the_console_connect_button_owns_its_id(built):
    """Regression: the section wrapping the Connect button carried the same id.

    getElementById returns the first match in document order — the section — so
    the handler was bound to the whole block and fired when the director clicked
    into the token field, calling setToken('') and wiping what they had pasted.
    """
    console = built / "console.html"
    ids = element_ids(console)
    assert ids.count("connect") == 1
    assert "connect-block" in ids

    html = console.read_text(encoding="utf-8")
    assert '<button type="button" id="connect">Connect</button>' in html
    assert 'id="connect-block"' in html


def test_the_console_refuses_to_connect_an_empty_field(built):
    """An empty field is not an instruction to forget the token; Disconnect is."""
    js = (built.parent / site.SITE_DIRNAME / "console.js").read_text(encoding="utf-8")
    assert "Paste a token first" in js
    index = js.index("Paste a token first")
    assert "setToken(value)" in js[index:], "the guard must precede the write"
