"""The Archive: the frozen legacy playthrough, rendered beside the live game.

The archive is not a snapshot kept on the side — it is rebuilt from the legacy
scenario on every export by the same exporter. These tests hold that line: the
same pages, the banner, the way out, and no scrubber.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_archive  # noqa: E402
import load_seed  # noqa: E402

from hoc import scenario  # noqa: E402
from hoc.export import site  # noqa: E402


@pytest.fixture(scope="module")
def archive(tmp_path_factory):
    out = tmp_path_factory.mktemp("archive")
    build_archive.build_archive(out_dir=out)
    return out / site.SITE_DIRNAME / site.ARCHIVE_DIRNAME


def _pages(archive_dir):
    return sorted(archive_dir.rglob("*.html"))


def test_the_archive_renders_the_whole_legacy_site(archive):
    names = {path.name for path in archive.iterdir() if path.is_file()}
    assert {"index.html", "ridings.html", "chronicle.html", "climate.html", "about.html"} <= names
    assert (archive / "style.css").exists()
    assert (archive / "houses").is_dir()


def test_the_archive_holds_the_legacy_houses(archive, tmp_path):
    """The archive's whole job is to keep the old world readable after hoc.db
    has moved on to the new one."""
    conn = load_seed.build(tmp_path / "legacy.db", seed=scenario.seed_dir("legacy"))
    expected = {
        site.slugify(row["house"])
        for row in conn.execute("SELECT house FROM houses")
    }
    conn.close()

    rendered = {path.stem for path in (archive / "houses").glob("*.html")}
    assert expected == rendered
    assert len(rendered) > 30, "the reconstructed playthrough had 35 houses"


def test_every_archive_page_carries_the_banner(archive):
    pages = _pages(archive)
    assert pages
    for path in pages:
        assert site.ARCHIVE_BANNER in path.read_text(encoding="utf-8"), path.name


def test_every_archive_page_offers_the_way_back(archive):
    """The reader has to be able to get out, from any depth."""
    for path in _pages(archive):
        text = path.read_text(encoding="utf-8")
        depth = len(path.relative_to(archive).parts) - 1
        assert f'href="{"../" * (depth + 1)}index.html">← The live game' in text, path.name


def test_the_archive_has_no_scrubber(archive):
    for path in _pages(archive):
        assert 'id="season"' not in path.read_text(encoding="utf-8"), path.name


def test_the_archive_does_not_link_itself(archive):
    index = (archive / "index.html").read_text(encoding="utf-8")
    assert f'href="{site.ARCHIVE_DIRNAME}/index.html"' not in index


def test_the_live_site_links_the_archive(tmp_path):
    conn = load_seed.build(tmp_path / "live.db", seed=scenario.seed_dir("legacy"))
    site.write_site(conn, out_dir=tmp_path)
    site_dir = tmp_path / site.SITE_DIRNAME

    index = (site_dir / "index.html").read_text(encoding="utf-8")
    assert f'href="{site.ARCHIVE_DIRNAME}/index.html">Archive</a>' in index

    about = (site_dir / "about.html").read_text(encoding="utf-8")
    assert f'{site.ARCHIVE_DIRNAME}/index.html' in about


def test_archive_mode_does_not_leak_into_the_next_render(tmp_path):
    """The mode is module state, so a render after the archive must come back
    clean — otherwise every export would ship a live site wearing the banner."""
    build_archive.build_archive(out_dir=tmp_path)

    conn = load_seed.build(tmp_path / "after.db", seed=scenario.seed_dir("legacy"))
    site.write_site(conn, out_dir=tmp_path)
    index = (tmp_path / site.SITE_DIRNAME / "index.html").read_text(encoding="utf-8")

    assert site.ARCHIVE_BANNER not in index
    assert "← The live game" not in index


def test_switching_scenarios_sweeps_the_previous_games_house_pages(tmp_path):
    """Regression: rendering a different game into the same directory used to
    leave the old game's houses standing in the live site — readable, linkable
    and wrong. Only the archive is allowed to hold the old world."""
    legacy = load_seed.build(tmp_path / "legacy.db", seed=scenario.seed_dir("legacy"))
    site.write_site(legacy, out_dir=tmp_path)
    houses_dir = tmp_path / site.SITE_DIRNAME / "houses"
    assert len(list(houses_dir.glob("*.html"))) > 30
    legacy.close()

    from hoc import sim

    fresh = load_seed.build(tmp_path / "fresh.db", seed=scenario.seed_dir("new"))
    world = sim.World(fresh, world_seed=1867)
    world.initialise(1867)
    site.write_site(fresh, out_dir=tmp_path)

    remaining = {path.stem for path in houses_dir.glob("*.html")}
    expected = {
        site.slugify(row["house"])
        for row in fresh.execute("SELECT house FROM houses")
    }
    assert remaining == expected
    assert len(remaining) == 1
