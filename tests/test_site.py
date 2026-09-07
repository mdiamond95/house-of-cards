"""Static site exporter tests."""

import importlib.util
import json
import re
import shutil
import subprocess
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


# ------------------------------------------------------------- the play page --
#
# Phase 10-2. play.html runs the JavaScript engine in the browser against the
# committed world. Three things have to hold, and the page is useless if any of
# them slips: the engine and its tables have to be *copied into the site* (the
# browser cannot reach web/ or rules/), the page has to stay small enough to
# open on mobile data, and the whole path through the engine has to still
# produce the seasons the Python engine produces.


@pytest.fixture(scope="module")
def played_site(tmp_path_factory):
    """A site built from a played world, which is the only kind that has a
    play page: the archive is frozen and the legacy game is not the live one."""
    from hoc import sim

    tmp = tmp_path_factory.mktemp("playsite")
    conn = _load_seed_module().build(tmp / "played.db", seed=scenario.seed_dir("new"))
    world = sim.World(conn, world_seed=1867)
    world.initialise(1867)
    for _ in range(9):
        world.run_season()
    site.write_site(conn, out_dir=tmp)
    conn.close()
    return tmp / site.SITE_DIRNAME


def test_the_play_page_exists_and_is_in_the_nav(played_site):
    play = played_site / "play.html"
    assert play.exists()
    for page_name in ("index.html", "chronicle.html", "play.html"):
        text = (played_site / page_name).read_text(encoding="utf-8")
        assert 'href="play.html"' in text, f"{page_name} does not link to the play page"


def test_the_archive_has_no_play_page(tmp_path):
    """The archive is a frozen game; a play page over it would offer controls
    that cannot do anything, exactly as the console would."""
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import build_archive

    build_archive.build_archive(out_dir=tmp_path)
    archive = tmp_path / site.SITE_DIRNAME / site.ARCHIVE_DIRNAME
    assert not (archive / "play.html").exists()
    for path in archive.rglob("*.html"):
        assert 'href="play.html"' not in path.read_text(encoding="utf-8"), path.name


def test_the_engine_and_its_tables_are_copied_into_the_site(played_site):
    """The browser cannot reach web/engine/ or rules/. If an export forgets to
    copy one, the page fails to load with a 404 that no test would otherwise
    see."""
    from hoc.export import play as play_export

    for name in play_export.ENGINE_MODULES:
        assert (played_site / "engine" / name).exists(), f"engine/{name} was not exported"
    for name in play_export.RULES_FILES:
        assert (played_site / "data" / "rules" / name).exists(), f"rules/{name} was not exported"
    for name in play_export.REFERENCE_FILES:
        assert (played_site / "data" / "reference" / name).exists(), name
    assert (played_site / "data" / "world.json").exists()


def test_the_exported_engine_is_identical_to_the_repository_engine(played_site):
    """A copy that drifted from web/engine/ would be a third implementation of
    the game, cross-checked by nothing."""
    from hoc.export import play as play_export

    for name in play_export.ENGINE_MODULES:
        assert (played_site / "engine" / name).read_bytes() == (
            ROOT / "web" / "engine" / name
        ).read_bytes(), f"engine/{name} differs from the repository's"


def test_the_world_snapshot_matches_the_world_the_site_was_built_from(played_site):
    world_json = json.loads((played_site / "data" / "world.json").read_text(encoding="utf-8"))
    assert world_json["season"] == 10
    assert world_json["world_seed"] == 1867
    assert world_json["rules_version"] == sim_rules_version()
    assert world_json["houses"], "a ten-season world has houses"


def sim_rules_version():
    from hoc import sim

    return sim.RULES_VERSION


def test_every_element_the_play_script_reaches_for_exists(played_site):
    """The page and its script are generated separately, so a renamed id is a
    silent no-op in the browser rather than an error anywhere."""
    html = (played_site / "play.html").read_text(encoding="utf-8")
    js = (played_site / "play.js").read_text(encoding="utf-8")

    wanted = set(re.findall(r"el\('([^']+)'\)", js))
    present = set(re.findall(r'id="([^"]+)"', html))
    missing = sorted(wanted - present)
    assert not missing, f"play.js reaches for elements the page does not have: {missing}"

    for selector, needle in (
        ('input[name="play-stop"]', 'name="play-stop"'),
        ("#map-fills path", 'id="map-fills"'),
        (".speed", 'class="speed'),
        (".run-n", 'class="run-n"'),
        (".iv-for", 'class="field iv-for"'),
    ):
        assert selector in js, f"{selector} is not used by play.js any more"
        assert needle in html, f"play.js selects {selector} but the page has no {needle}"


def test_the_play_page_and_its_assets_stay_under_the_download_budget(played_site):
    """A phone on mobile data pays for every byte of this. The budget is on the
    raw bytes because that is what the browser parses; Pages serves it gzipped,
    and the gzipped figure is reported for the record."""
    import gzip

    from hoc.export import play as play_export

    files = [played_site / "play.html", played_site / "play.js"]
    files += [played_site / "engine" / name for name in play_export.ENGINE_MODULES]
    files += [played_site / "data" / "rules" / name for name in play_export.RULES_FILES]
    files += [played_site / "data" / "reference" / name for name in play_export.REFERENCE_FILES]
    files += [played_site / "data" / "world.json"]

    raw = sum(path.stat().st_size for path in files)
    compressed = sum(len(gzip.compress(path.read_bytes())) for path in files)
    assert raw < site.PLAY_SIZE_BUDGET, (
        f"the play page and its assets are {raw:,} bytes raw"
        f" ({compressed:,} gzipped), over the {site.PLAY_SIZE_BUDGET:,} budget"
    )


def test_the_map_is_not_shipped_twice(played_site):
    """The play page and the index draw the same coastline. Building it twice
    would be the single most expensive thing this page could do, so they share
    _map_geometry — and the two SVGs should be the same size to within the
    house data the index bakes in and the play page does not."""
    index_html = (played_site / "index.html").read_text(encoding="utf-8")
    play_html = (played_site / "play.html").read_text(encoding="utf-8")
    index_paths = re.findall(r'<path fill="[^"]*" data-fed="([^"]+)"', index_html)
    play_paths = re.findall(r'<path fill="[^"]*" data-fed="([^"]+)"', play_html)
    assert play_paths == index_paths, "the two maps do not carry the same ridings in the same order"
    assert 'data-view-south' in play_html and 'data-view-full' in play_html


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
def test_the_play_pages_own_path_through_the_engine_matches_python(played_site, tmp_path):
    """The headless smoke: import the *exported* modules, load the *exported*
    world.json, play three hundred seasons, and compare every one against the
    Python engine playing the same seasons. This is the page's whole claim —
    that a season computed in a browser is the season the repository would have
    computed — with the browser taken out of it."""
    from hoc import sim

    out = tmp_path / "js"
    result = subprocess.run(
        ["node", str(played_site / "engine" / "playtest.js"),
         "--site", str(played_site), "--seasons", "300", "--out", str(out)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["seasons"] == 300
    assert report["snapshot_round_trips"] is True

    # The same seasons in Python, from the same starting point.
    conn = _load_seed_module().build(tmp_path / "py.db", seed=scenario.seed_dir("new"))
    python_dir = tmp_path / "python"
    python_dir.mkdir()
    world = sim.World(conn, world_seed=1867, seasons_dir=python_dir)
    world.initialise(1867)
    world.run(309)
    conn.close()

    for season in range(11, 311):
        name = f"{season:04d}.json"
        python_record = json.loads((python_dir / name).read_text(encoding="utf-8"))
        js_record = json.loads((out / name).read_text(encoding="utf-8"))
        python_record.pop("engine")
        js_record.pop("engine")
        assert python_record == js_record, f"season {season} differs from the Python engine"
