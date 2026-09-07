"""Where a riding's territorial designations can come from (rules 0.8).

Rules 0.7 drew a house's designation from a province-wide bank, so a Baron
seated in Halifax could be styled "of Kamloops" as readily as "of Dartmouth" —
the bank knew the province and nothing else. Rules 0.8 draws from the seat's own
ground instead, and this module is the data that makes that possible.

Two tables, both built by `scripts/build_places.py` and committed:

* `places_by_riding.csv` — Natural Earth's Canadian populated places, each
  assigned to the riding whose polygon covers it, largest population first.
  There are 255 of them across 111 of the 343 ridings, which is thin — hence
  the tiers rather than a single source.
* `riding_tokens.csv` — the usable words in a riding's own name, in name order.
  Every riding has at least one, which is what makes the draw always able to
  answer.

Read from the CSVs rather than from `hoc.db`, deliberately: `web/engine/` reads
the same two files, so both engines see identical bytes in identical order and
the row ordering the draws depend on cannot diverge between them
(docs/DETERMINISM.md).
"""

import csv
from pathlib import Path

__all__ = ["places_by_riding", "tokens_by_riding", "PLACES_PATH", "TOKENS_PATH"]

REFERENCE_DIR = Path(__file__).resolve().parent.parent / "data" / "reference"
PLACES_PATH = REFERENCE_DIR / "places_by_riding.csv"
TOKENS_PATH = REFERENCE_DIR / "riding_tokens.csv"

_places = None
_tokens = None


def _load(path, key, value):
    """{fed_id: [value, ...]} in file order — the order the draws depend on."""
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.setdefault(row[key], []).append(row[value])
    return out


def places_by_riding():
    """fed_id -> place names, largest population first (the file's own order)."""
    global _places
    if _places is None:
        _places = _load(PLACES_PATH, "fed_id", "place")
    return _places


def tokens_by_riding():
    """fed_id -> the usable words of the riding's name, in name order."""
    global _tokens
    if _tokens is None:
        _tokens = _load(TOKENS_PATH, "fed_id", "token")
    return _tokens
