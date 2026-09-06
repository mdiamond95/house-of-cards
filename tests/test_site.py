"""Static site exporter tests."""

import importlib.util
import re
from pathlib import Path

import pytest

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

    conn = _load_seed_module().build(tmp_path_factory.mktemp("db") / "hoc.db")
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

    conn = _load_seed_module().build(tmp_path / "hoc.db")
    for path in sorted((ROOT / "scenarios" / "legacy" / "turns").glob("[0-9][0-9][0-9][0-9]_*.json")):
        apply_turn(conn, path)
    site.write_site(conn, out_dir=tmp_path / "out")
    conn.close()

    rebuilt = tmp_path / "out" / site.SITE_DIRNAME
    for path in html_files(built):
        twin = rebuilt / path.relative_to(built)
        assert twin.read_text(encoding="utf-8") == path.read_text(encoding="utf-8"), path.name
