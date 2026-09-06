"""The season history the site reads: timeline.json and the pages built on it.

One world is played once for the whole module and every test reads it, because
playing seasons is the expensive part and none of these tests needs its own.
"""

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import load_seed  # noqa: E402

from hoc import scenario, sim  # noqa: E402
from hoc.export import site, timeline  # noqa: E402

SEASONS = 40


@pytest.fixture(scope="module")
def played(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("timeline")
    conn = load_seed.build(tmp / "played.db", seed=scenario.seed_dir("new"))
    world = sim.World(conn, world_seed=17)
    world.initialise(17)
    for _ in range(SEASONS - 1):
        world.run_season()
    return world


@pytest.fixture(scope="module")
def rendered(played, tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    site.write_site(played.conn, out_dir=out)
    return out / "site"


# ---------------------------------------------------------------- the data --


def test_timeline_is_written_and_small(rendered):
    path = rendered / "data" / "timeline.json"
    assert path.exists()
    assert path.stat().st_size < timeline.SIZE_BUDGET


def test_timeline_replays_to_the_current_map(played):
    """The whole point of a diff format: walking every frame has to land exactly
    on the map the database holds now, or the scrubber lies at its default
    position — which is the one every reader sees first."""
    data = timeline.build_timeline(played.conn)

    owners = {}
    for season in sorted(data["changes"], key=int):
        for fed_id, house in data["changes"][season].items():
            owners[fed_id] = house
    replayed = {fed: house for fed, house in owners.items() if house is not None}

    actual = {
        row["fed_id"]: row["house"]
        for row in played.conn.execute(
            "SELECT fed_id, house FROM holdings WHERE released_event_id IS NULL"
        )
    }
    assert replayed == actual


def test_timeline_covers_every_season_and_house(played):
    data = timeline.build_timeline(played.conn)
    assert data["latest"] == SEASONS
    assert len(data["counts"]) == SEASONS

    active = {
        row["house"]
        for row in played.conn.execute("SELECT house FROM houses")
    }
    assert set(data["houses"]) == active
    for entry in data["houses"].values():
        assert entry["primary"], "a house with no colour cannot be drawn"


def test_snapshots_are_periodic_not_per_season(played):
    data = timeline.build_timeline(played.conn)
    seasons = sorted(int(s) for s in data["snapshots"])
    assert seasons, "the engine should have written snapshots"
    assert len(seasons) < SEASONS, "snapshots every season would blow the size budget"
    for season in seasons:
        assert season == 1 or season % sim.SNAPSHOT_EVERY == 0


# --------------------------------------------------------------- the pages --


def test_index_carries_a_scrubber(rendered):
    index = (rendered / "index.html").read_text(encoding="utf-8")
    assert 'id="season"' in index
    assert 'id="play"' in index
    assert f'max="{SEASONS}"' in index
    assert f'value="{SEASONS}"' in index, "the scrubber should open at the latest season"
    assert 'data-fed=' in index, "the scrubber recolours by fed_id"


def test_a_one_season_world_has_no_scrubber(tmp_path):
    """Nothing to scrub through yet, so the control would only be noise."""
    conn = load_seed.build(tmp_path / "fresh.db", seed=scenario.seed_dir("new"))
    world = sim.World(conn, world_seed=2)
    world.initialise(2)
    site.write_site(conn, out_dir=tmp_path)

    index = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert 'id="season"' not in index


def test_chronicle_is_grouped_by_season_newest_first(rendered):
    chronicle = (rendered / "chronicle.html").read_text(encoding="utf-8")
    seasons = [int(n) for n in re.findall(r'<article class="season" id="season-(\d+)"', chronicle)]
    assert seasons == sorted(seasons, reverse=True)
    assert 'id="jump-season"' in chronicle


def test_chronicle_lines_link_their_houses_and_stay_well_formed(rendered):
    chronicle = (rendered / "chronicle.html").read_text(encoding="utf-8")
    lines = re.findall(r'<li class="[a-z]+">(.*?)</li>', chronicle)
    assert lines
    for line in lines:
        assert line.count("<a ") == line.count("</a>"), line
    assert any("<a href=\"houses/" in line for line in lines)


def test_house_pages_show_the_engine_state(rendered, played):
    house = played.active_houses()[0]["house"]
    slug = site.slugify(house)
    text = (rendered / "houses" / f"{slug}.html").read_text(encoding="utf-8")

    assert text.count('class="spark"') == 3  # capital, influence, cohesion
    assert "<h2>Objectives</h2>" in text
    assert "<h2>Actions" in text
    assert "<h2>People</h2>" in text
    assert "<h2>State</h2>" in text


def test_climate_page_charts_every_band_that_has_moved(rendered, played):
    """A band whose ledger holds only its opening zero has no line to draw, and
    says so rather than drawing a flat one. Most houses sit in the Confederation
    band at any moment, so the later bands often have exactly that."""
    climate = (rendered / "climate.html").read_text(encoding="utf-8")
    movers = [
        row["era_cohort"]
        for row in played.conn.execute(
            "SELECT era_cohort, COUNT(*) AS n FROM climate GROUP BY era_cohort HAVING n > 1"
        )
    ]
    assert movers, "the run should have moved at least one ledger"
    assert climate.count('class="chart"') == len(movers)
    for band in movers:
        assert band in climate


def test_a_director_scenario_renders_without_engine_sections(tmp_path):
    """The legacy game has no seasons, so the scrubber, the season chronicle and
    the state block should simply not be there — not be there and empty."""
    conn = load_seed.build(tmp_path / "legacy.db", seed=scenario.seed_dir("legacy"))
    site.write_site(conn, out_dir=tmp_path)
    site_dir = tmp_path / "site"

    index = (site_dir / "index.html").read_text(encoding="utf-8")
    assert 'id="season"' not in index

    data = json.loads((site_dir / "data" / "timeline.json").read_text(encoding="utf-8"))
    assert data["latest"] == 0

    house = conn.execute("SELECT house FROM houses ORDER BY house LIMIT 1").fetchone()["house"]
    text = (site_dir / "houses" / f"{site.slugify(house)}.html").read_text(encoding="utf-8")
    assert "<h2>State</h2>" not in text
    assert "<h2>House block</h2>" in text
