# `web/engine/` — the game engine in JavaScript

The second implementation of the House of Cards engine. It exists so the game
can be played in a browser (Phase 10-2) and, eventually, committed back from one
(Phase 10-3). Its whole value is that it agrees with `hoc/sim.py` exactly:
**both engines must write byte-identical season files from the same seed.**

Read `docs/DETERMINISM.md` before changing anything here. It is the contract.

## Constraints

- **Plain ES modules.** No build step, no bundler, no packages — the static site
  loads these with `<script type="module">` and nothing else. `tests/test_js_syntax.py`
  fails any import that is not a relative path or a `node:` builtin.
- **No floats, ever**, except §10's founding probability. No `Math.random`. No
  locale-dependent anything. No relying on object key order or `Array.sort`'s
  default comparator.
- Anything mirrored from Python must be mirrored in the same pull request, and
  the cross-check must pass (`CLAUDE.md`, "Two engines").

## State as of Phase 10-1b

The port is complete. Both engines play the same game.

| module | mirrors | state |
| --- | --- | --- |
| `prng.js` | `hoc/prng.py` | done, verified value-for-value |
| `csv.js` | Python's `csv` module | done, verified on all 11 CSVs in the repo |
| `palette.js` | `hoc/palette.py` | done, verified over 81,120 conversions |
| `names.js` | `hoc/names.py` | done, verified over 2,673 bank strings |
| `rules.js` | `hoc/rules_data.py` (loading half) | done, verified table by table |
| `adjacency.js` | the `ridings`/`adjacency` tables | done, verified against SQLite |
| `state.js` | the mutable tables + sim.py's queries | done, verified against SQLite |
| `sim.js` | `hoc/sim.py` | done, cross-checked to 300 seasons |
| `index.js` | — | done |
| `cli.js` | — | done |
| `selftest.js` | — | done, drives `tests/test_js_engine_parity.py` |

`tests/test_crosscheck.py` runs seeds 1867, 2 and 3 for 120 seasons each and
asserts zero differences. Seeds 1867, 2 and 3 have also been checked at 300
seasons, and seeds 7, 11 and 42 at 120.

## What is left

Only Phase 10-2 (the live UI in the browser) and Phase 10-3 (committing a game
played in the page back to the repository). Nothing in this directory is
unfinished.

## Two things the port had to get right that are easy to miss

**Floats.** JavaScript has one number type. Python distinguishes `0` from `0.0`
and `json.dumps` writes them differently, so a season record's genuine floats —
§10's founding probability and the `rand_float()` it is compared against — are
boxed in `FloatValue` and rendered by `encodeFloat`, which reproduces Python's
`repr`: always a decimal point, exponential below 1e-4 and at 1e16 (JavaScript
switches at 1e-6 and 1e21), and a two-digit exponent. `encodeNumber` refuses any
other non-integer rather than guessing. This was the port's one real divergence
and it surfaced only at season 220, when the map filled and `p_found` reached
zero.

**Draw for draw.** Every call into the RNG must happen in the same order, the
same number of times, with the same `purpose` string. Python's
`any(... for _ in range(rolls))` in `_mortality` short-circuits, so a house that
dies on its first roll never draws the second; `rand_int(lo, hi)` with `lo == hi`
consumes no word at all. Either one, ported carelessly, desynchronises the stream
and every later season with it.

## How to work on it

Port a slice, then run the cross-check at a small season count and grow it:

    python scripts/crosscheck.py --seed 1867 --seasons 1 --keep /tmp/xc
    python scripts/crosscheck.py --seed 1867 --seasons 20
    python -m pytest tests/test_crosscheck.py

The script prints the first differing season and a unified diff of the two
files. Because every draw is logged with its purpose, a divergence usually shows
up first in the `draws` array, and the purpose string names the method that
drew it.

When both `test_crosscheck.py` and `test_js_engine_parity.py` fail, fix the
parity test first: it names the primitive, where the cross-check only names the
season.

**Never fix a divergence by loosening the comparison.** The ignore list is one
field long and a test asserts it stays that way.
