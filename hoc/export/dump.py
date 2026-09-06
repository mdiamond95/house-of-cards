"""CSV and JSON dump of the whole database.

Ordering is deterministic everywhere so that a turn's diff shows only what the
turn changed.
"""

import csv
import json
from pathlib import Path

from hoc import db

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent.parent / "outputs"

__all__ = ["write_dump", "DEFAULT_OUT_DIR"]


def _tables(conn):
    return [
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def _order_by(conn, table):
    """Order by primary key where there is one, else by every column, so the
    row order never depends on insertion order."""
    columns = list(conn.execute(f"PRAGMA table_info({table})"))
    pk = [c["name"] for c in sorted(columns, key=lambda c: c["pk"]) if c["pk"]]
    keys = pk or [c["name"] for c in columns]
    return ", ".join(f'"{name}"' for name in keys)


def _write_tables(conn, dump_dir):
    written = []
    for table in _tables(conn):
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY {_order_by(conn, table)}").fetchall()
        path = dump_dir / f"{table}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if rows:
                writer.writerow(rows[0].keys())
                writer.writerows([tuple(row) for row in rows])
            else:
                writer.writerow([c["name"] for c in conn.execute(f"PRAGMA table_info({table})")])
        written.append(path)
    return written


def _block_sort_key(field):
    """Known headings in reading order, anything newly recovered after them."""
    order = db.HOUSE_BLOCK_FIELDS
    return (order.index(field), "") if field in order else (len(order), field)


def _state(conn):
    colours = {row["house"]: row for row in conn.execute("SELECT * FROM v_house_colours")}
    clocks = {row["house"]: row for row in conn.execute("SELECT * FROM clocks")}

    blocks_by_house = {}
    for row in conn.execute("SELECT * FROM house_blocks"):
        blocks_by_house.setdefault(row["house"], []).append(
            {"field": row["field"], "text": row["text"], "source": row["source"]}
        )
    for entries in blocks_by_house.values():
        entries.sort(key=lambda entry: _block_sort_key(entry["field"]))

    holdings_by_house = {}
    for row in conn.execute(
        "SELECT h.house, h.seat_order, h.hex, h.fed_id, r.name_en, r.province"
        " FROM holdings h JOIN ridings r ON r.fed_id = h.fed_id"
        " WHERE h.released_event_id IS NULL ORDER BY h.house, h.seat_order"
    ):
        holdings_by_house.setdefault(row["house"], []).append(
            {
                "seat_order": row["seat_order"],
                "fed_id": row["fed_id"],
                "riding": row["name_en"],
                "province": row["province"],
                "hex": row["hex"],
            }
        )

    holders_by_house = {}
    for row in conn.execute(
        "SELECT * FROM holders WHERE is_current = 1 ORDER BY house"
    ):
        holders_by_house[row["house"]] = {
            "name": row["name"],
            "generation": row["generation"],
            "acceded": row["acceded"],
            "bio_age_at_accession": row["bio_age_at_accession"],
            "predecessor": row["predecessor"],
            "heir_apparent": row["heir_apparent"],
            "source": row["source"],
            "confidence": row["confidence"],
        }

    houses = []
    for row in conn.execute("SELECT * FROM houses ORDER BY house"):
        house = row["house"]
        clock = clocks.get(house)
        houses.append(
            {
                "house": house,
                "peerage": row["peerage"],
                "rank": row["rank"],
                "status": row["status"],
                "primary_hex": colours[house]["primary_hex"] if house in colours else None,
                "secondary_hex": colours[house]["secondary_hex"] if house in colours else None,
                "notes": row["notes"],
                "holder": holders_by_house.get(house),
                "blocks": blocks_by_house.get(house, []),
                "holdings": holdings_by_house.get(house, []),
                "riding_count": len(holdings_by_house.get(house, [])),
                "clock": None if clock is None else {
                    "personal_year": clock["personal_year"],
                    "basis": clock["basis"],
                },
            }
        )

    climate = {}
    for row in conn.execute("SELECT * FROM climate ORDER BY era_cohort, seq"):
        climate.setdefault(row["era_cohort"], []).append(
            {
                "seq": row["seq"],
                "event": row["event"],
                "magnitude": row["magnitude"],
                "tag": row["tag"],
                "cumulative_after": row["cumulative_after"],
                "source": row["source"],
            }
        )
    current_climate = {
        row["era_cohort"]: row["cumulative_after"]
        for row in conn.execute("SELECT * FROM v_current_climate ORDER BY era_cohort")
    }

    events = []
    for row in conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT 50"):
        events.append(
            {
                "id": row["id"],
                "turn_id": row["turn_id"],
                "kind": row["kind"],
                "era_cohort": row["era_cohort"],
                "title": row["title"],
                "narrative": row["narrative"],
                "mechanical_delta": row["mechanical_delta"],
                "source": row["source"],
                "created_at": row["created_at"],
                "houses": [
                    {"house": h["house"], "role": h["role"], "personal_year": h["personal_year"]}
                    for h in conn.execute(
                        "SELECT house, role, personal_year FROM event_houses"
                        " WHERE event_id = ? ORDER BY house",
                        (row["id"],),
                    )
                ],
            }
        )

    return {
        "houses": houses,
        "climate": {"ledgers": climate, "current": current_climate},
        "events": events,
        "counts": {
            "houses_active": conn.execute("SELECT COUNT(*) FROM houses WHERE status = 'active'").fetchone()[0],
            "houses_removed": conn.execute("SELECT COUNT(*) FROM houses WHERE status = 'removed'").fetchone()[0],
            "ridings_total": conn.execute("SELECT COUNT(*) FROM ridings").fetchone()[0],
            "ridings_claimed": conn.execute(
                "SELECT COUNT(*) FROM holdings WHERE released_event_id IS NULL"
            ).fetchone()[0],
            "holders_unrecovered": conn.execute(
                "SELECT COUNT(*) FROM holders WHERE is_current = 1 AND name IS NULL"
            ).fetchone()[0],
        },
    }


def write_dump(conn, out_dir=DEFAULT_OUT_DIR):
    """Write outputs/dump/*.csv and outputs/dump/state.json. Returns the paths."""
    dump_dir = Path(out_dir) / "dump"
    dump_dir.mkdir(parents=True, exist_ok=True)

    written = _write_tables(conn, dump_dir)

    state_path = dump_dir / "state.json"
    state_path.write_text(
        json.dumps(_state(conn), indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    written.append(state_path)
    return written
