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

# The machinery under test plays and saves a game, which only a live scenario allows.
# See tests/conftest.py; the refusal itself is tested in tests/test_frozen.py.
pytestmark = pytest.mark.usefixtures("live_game")

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

    conn = _load_seed_module().build(tmp_path / "played.db", seed=scenario.blank_seed_dir())
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
    assert len(pages) > 30, "the frozen games should be archived"
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
    conn = _load_seed_module().build(tmp / "played.db", seed=scenario.blank_seed_dir())
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
    games = [path for path in archive.iterdir() if path.is_dir()]
    assert games
    for game in games:
        assert not (game / "play.html").exists()
        for path in game.rglob("*.html"):
            assert 'href="play.html"' not in path.read_text(encoding="utf-8"), path.name


def test_the_engine_and_its_tables_are_copied_into_the_site(played_site):
    """The browser cannot reach web/engine/ or rules/. If an export forgets to
    copy one, the page fails to load with a 404 that no test would otherwise
    see."""
    from hoc.export import play as play_export

    for name in play_export.ENGINE_MODULES:
        assert (played_site / "engine" / name).exists(), f"engine/{name} was not exported"
    # Rules are versioned, and the page reads current.txt to learn which
    # directory to fetch. Every version is exported, because a version left
    # behind is a season the browser could not replay.
    from hoc import rules_data

    version_root = played_site / "data" / "rules" / "versions"
    assert (played_site / "data" / "rules" / "current.txt").exists()
    for version in rules_data.available_versions():
        for name in play_export.RULES_FILES:
            if name in play_export.OPTIONAL_RULES_FILES and not (
                rules_data.version_dir(version) / name
            ).exists():
                continue  # a version predating the table has none to export
            assert (version_root / version / name).exists(), \
                f"rules/versions/{version}/{name} was not exported"
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
    # Only the version the page actually fetches counts against the budget:
    # the others are on disk for a replay, not on the page's critical path.
    from hoc import rules_data

    current = rules_data.current_version()
    files += [
        played_site / "data" / "rules" / "current.txt",
        *(played_site / "data" / "rules" / "versions" / current / name
          for name in play_export.RULES_FILES
          if (played_site / "data" / "rules" / "versions" / current / name).exists()),
    ]
    files += [played_site / "data" / "reference" / name for name in play_export.REFERENCE_FILES]
    files += [played_site / "data" / "world.json"]
    files += [played_site / "story" / name for name in play_export.STORY_FILES]

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
    conn = _load_seed_module().build(tmp_path / "py.db", seed=scenario.blank_seed_dir())
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


# ------------------------------------------------------ the story layer ------
#
# Phase A of docs/STORY_DESIGN.md: every frozen game has a Replay page that
# tells it one turn at a time as dispatches, and the play page tells each
# season it plays the same way, with the chronicle kept, collapsed, as the
# full record.


@pytest.fixture(scope="module")
def archive_site(tmp_path_factory):
    sys_path = str(ROOT / "scripts")
    import sys

    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    import build_archive

    tmp = tmp_path_factory.mktemp("archive-story")
    build_archive.build_archive(out_dir=tmp)
    return tmp / site.SITE_DIRNAME / site.ARCHIVE_DIRNAME


def _story_ids_reached(js):
    return set(re.findall(r"el\('([^']+)'\)", js))


def test_every_frozen_game_has_a_replay_page(archive_site):
    from hoc.export import play as play_export

    for name in scenario.frozen_names():
        game = archive_site / name
        html = (game / "replay.html").read_text(encoding="utf-8")
        js = (game / "replay.js").read_text(encoding="utf-8")
        missing = sorted(_story_ids_reached(js) - set(re.findall(r'id="([^"]+)"', html)))
        assert not missing, f"{name}: replay.js reaches for elements the page lacks: {missing}"
        assert '<script type="module" src="replay.js"></script>' in html
        assert 'id="map-fills"' in html and "data-view-south" in html
        assert json.dumps(name) in js, "the replay remembers a followed house per game"
        for file_name in play_export.STORY_FILES:
            assert (game / "story" / file_name).read_bytes() == (
                ROOT / "web" / "story" / file_name
            ).read_bytes(), f"{name}: story/{file_name} differs from web/story/"
        index = json.loads((game / "data" / "beats" / "index.json").read_text(encoding="utf-8"))
        assert index["chunks"], name
        for chunk in index["chunks"]:
            assert (game / "data" / "beats" / chunk["file"]).stat().st_size <= 500_000


def test_the_replay_is_linked_from_the_archive_and_from_every_page_of_its_game(archive_site):
    listing = (archive_site / "index.html").read_text(encoding="utf-8")
    for name in scenario.frozen_names():
        assert f'href="{name}/replay.html"' in listing, f"the archive index does not link {name}'s replay"
        game = archive_site / name
        for page_path in game.rglob("*.html"):
            depth = len(page_path.relative_to(game).parts) - 1
            href = f'href="{"../" * depth}replay.html"'
            assert href in page_path.read_text(encoding="utf-8"), f"{page_path.relative_to(archive_site)}"


def test_every_frozen_game_has_a_storylines_page(archive_site):
    listing = (archive_site / "index.html").read_text(encoding="utf-8")
    for name in scenario.frozen_names():
        game = archive_site / name
        html = (game / "storylines.html").read_text(encoding="utf-8")
        js = (game / "storylines-page.js").read_text(encoding="utf-8")
        missing = sorted(_story_ids_reached(js) - set(re.findall(r'id="([^"]+)"', html)))
        assert not missing, f"{name}: storylines-page.js reaches for elements the page lacks: {missing}"
        assert '<script type="module" src="storylines-page.js"></script>' in html
        # Built in the browser by the story layer, never by a second implementation.
        assert "./story/dispatch.js" in js and "./story/storylines.js" in js
        assert "replay.html#" in js, "each beat links into the Replay at its turn"
        assert f'href="{name}/storylines.html"' in listing
        for page_path in game.rglob("*.html"):
            depth = len(page_path.relative_to(game).parts) - 1
            assert f'href="{"../" * depth}storylines.html"' in page_path.read_text(encoding="utf-8"), \
                f"{page_path.relative_to(archive_site)}"


def test_the_replay_and_play_pages_carry_the_afoot_panel(archive_site, played_site):
    pages = [(archive_site / name / "replay.html", archive_site / name / "replay.js")
             for name in scenario.frozen_names()]
    pages.append((played_site / "play.html", played_site / "play.js"))
    for html_path, js_path in pages:
        html = html_path.read_text(encoding="utf-8")
        js = js_path.read_text(encoding="utf-8")
        assert 'id="afoot-heading"' in html and ">Afoot</h2>" in html, html_path
        for element in ("story-afoot-list", "story-afoot-detail"):
            assert f'id="{element}"' in html and f"el('{element}')" in js, (html_path, element)
        assert "afootHtml" in js and "storylineHtml" in js and "pauseReason" in js
        assert "classList.toggle('afoot'" in js, "a chosen storyline marks its houses on the map"


def test_the_live_site_has_no_replay_page(played_site):
    assert not (played_site / "replay.html").exists()
    assert 'href="replay.html"' not in (played_site / "index.html").read_text(encoding="utf-8")


def test_the_play_page_leads_with_the_dispatch_and_keeps_the_chronicle_as_the_full_record(played_site):
    html = (played_site / "play.html").read_text(encoding="utf-8")
    js = (played_site / "play.js").read_text(encoding="utf-8")
    for element in ("story-next", "story-auto", "story-follow", "story-strip", "story-dispatch",
                    "story-log", "story-note"):
        assert f'id="{element}"' in html, element
    record = re.search(r'<details id="full-record"([^>]*)>(.*?)</details>', html, re.DOTALL)
    assert record, "the chronicle is not in a Full record <details>"
    assert "open" not in record.group(1), "the full record is collapsed until asked for"
    assert "<summary>Full record</summary>" in record.group(2)
    assert 'id="feed"' in record.group(2) and 'id="feed-filter"' in record.group(2)
    assert html.index('id="story-dispatch"') < html.index('id="full-record"')
    # Every existing control is still on the page and still wired.
    for control in ("play-toggle", "play-step", "play-season", "play-undo", "save", "iv-apply",
                    "view-toggle", "feed-filter"):
        assert f'id="{control}"' in html and f"el('{control}')" in js, control
    assert "./story/dispatch.js" in js and "./story/beats.js" in js
    assert "inputFromState" in js and "typeTurn" in js


def test_the_story_layer_is_copied_into_the_played_site(played_site):
    from hoc.export import play as play_export

    for name in play_export.STORY_FILES:
        assert (played_site / "story" / name).read_bytes() == (
            ROOT / "web" / "story" / name
        ).read_bytes(), f"story/{name} differs from web/story/"
