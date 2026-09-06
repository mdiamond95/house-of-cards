"""outputs/site/data/timeline.json — the map's history, for the season scrubber.

The site is static, so the scrubber cannot query anything: it has to be handed
the whole history up front and replay it in the browser. That makes size the
governing constraint, and the file is built as a diff rather than a series of
snapshots — for each season, only the ridings that changed hands, which over a
300-season game is a few hundred entries rather than a hundred thousand.

Stat histories are the exception: they are genuinely per-house series, so they
come from `stat_snapshots`, written every few seasons by the engine rather than
every season. `SIZE_BUDGET` is checked on write and the caller is told when a
game outgrows it.

Nothing here reads the season JSON logs. The database is canonical; the logs are
the audit trail.
"""

import json
from collections import defaultdict

__all__ = ["build_timeline", "write_timeline", "SIZE_BUDGET"]

# The director's ceiling for a 300-season game. Checked rather than assumed:
# write_timeline returns the size it wrote so the exporter can say so.
SIZE_BUDGET = 1_500_000


def _season_of(conn, event_id, cache):
    """Which season an event belongs to. Engine events carry it in their JSON
    delta; a director's turn has no season at all and reads as season 0, which
    puts the legacy scenario's whole map in the timeline's first frame."""
    if event_id is None:
        return 0
    if event_id in cache:
        return cache[event_id]
    row = conn.execute(
        "SELECT mechanical_delta FROM events WHERE id = ?", (event_id,)
    ).fetchone()
    season = 0
    if row is not None and row["mechanical_delta"]:
        try:
            season = int(json.loads(row["mechanical_delta"]).get("season", 0))
        except (ValueError, TypeError):
            season = 0
    cache[event_id] = season
    return season


def build_timeline(conn):
    """The timeline as a plain dict, ready to serialise."""
    latest = conn.execute("SELECT MAX(season_no) AS n FROM seasons").fetchone()["n"] or 0

    cache = {}
    # changes[season][fed_id] = house or None. A riding that changes hands twice
    # in one season keeps only where it ended up, which is all the map can show.
    changes = defaultdict(dict)
    for row in conn.execute(
        "SELECT fed_id, house, acquired_event_id, released_event_id FROM holdings"
        " ORDER BY id"
    ):
        acquired = _season_of(conn, row["acquired_event_id"], cache)
        changes[acquired][row["fed_id"]] = row["house"]
        if row["released_event_id"] is not None:
            released = _season_of(conn, row["released_event_id"], cache)
            # Only record the vacancy if nothing else claimed the riding that
            # same season; otherwise the later claim is the truth of the frame.
            changes[released].setdefault(row["fed_id"], None)

    # A riding released and re-taken in one season must read as taken.
    for season, entries in changes.items():
        for fed_id, house in list(entries.items()):
            if house is None:
                continue
            entries[fed_id] = house

    houses = {}
    for row in conn.execute(
        "SELECT h.house, h.peerage, h.rank, h.status, c.primary_hex, c.secondary_hex,"
        "       s.founded_season, s.removed_season, s.community, s.region, s.tag"
        " FROM houses h"
        " JOIN v_house_colours c ON c.house = h.house"
        " LEFT JOIN house_stats s ON s.house = h.house"
        " ORDER BY h.house"
    ):
        houses[row["house"]] = {
            "peerage": row["peerage"],
            "rank": row["rank"],
            "status": row["status"],
            "primary": row["primary_hex"],
            "secondary": row["secondary_hex"],
            "founded": row["founded_season"],
            "removed": row["removed_season"],
            "community": row["community"],
            "tag": row["tag"],
        }

    snapshots = defaultdict(dict)
    for row in conn.execute(
        "SELECT season_no, house, capital, influence, cohesion, ambition, holdings"
        " FROM stat_snapshots ORDER BY season_no, house"
    ):
        snapshots[row["season_no"]][row["house"]] = [
            row["capital"], row["influence"], row["cohesion"],
            row["ambition"], row["holdings"],
        ]

    counts = {
        row["season_no"]: [row["houses_after"], row["ridings_after"]]
        for row in conn.execute(
            "SELECT season_no, houses_after, ridings_after FROM seasons ORDER BY season_no"
        )
    }

    return {
        "latest": latest,
        "total_ridings": conn.execute("SELECT COUNT(*) AS n FROM ridings").fetchone()["n"],
        "stat_order": ["capital", "influence", "cohesion", "ambition", "holdings"],
        "houses": houses,
        # Keys are strings because JSON object keys always are; the browser
        # reads them back with Number().
        "changes": {str(season): changes[season] for season in sorted(changes)},
        "snapshots": {str(season): snapshots[season] for season in sorted(snapshots)},
        "counts": {str(season): counts[season] for season in sorted(counts)},
    }


def write_timeline(conn, data_dir):
    """Write timeline.json. Returns (path, size_in_bytes)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "timeline.json"
    payload = json.dumps(build_timeline(conn), separators=(",", ":"), ensure_ascii=False)
    path.write_text(payload, encoding="utf-8")
    return path, len(payload.encode("utf-8"))
