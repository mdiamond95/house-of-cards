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

## State as of Phase 10-1

| module | mirrors | state |
| --- | --- | --- |
| `prng.js` | `hoc/prng.py` | **done**, verified value-for-value |
| `csv.js` | Python's `csv` module | **done**, verified on all 11 CSVs in the repo |
| `palette.js` | `hoc/palette.py` | **done**, verified over 81,120 conversions |
| `names.js` | `hoc/names.py` | **done**, verified over 2,673 bank strings |
| `rules.js` | `hoc/rules_data.py` (loading half) | **done**, verified table by table |
| `adjacency.js` | the `ridings`/`adjacency` tables | **done**, verified against SQLite |
| `state.js` | the mutable tables + sim.py's queries | **done**, verified against SQLite |
| `selftest.js` | — | **done**, drives `tests/test_js_engine_parity.py` |
| `sim.js` | `hoc/sim.py` | **not written** |
| `index.js` | — | **not written** |
| `cli.js` | — | **not written** |

`tests/test_crosscheck.py` skips, saying so, until `cli.js` exists. A skip there
is not a pass.

## What `sim.js` still has to port

Roughly 1,700 lines of `hoc/sim.py`, in this order of dependency. The order
matters: every one of these draws from the shared generator, so a handler ported
out of order — or one that draws a different number of times than its Python
counterpart — desynchronises the stream and every later season with it.

1. **`World` construction and the season spine** — `run_season`'s §6 order,
   which is: age everyone, run friction, then for each active house in
   `activeHouses()` order (era event → mortality/succession → action →
   objectives → debt check), then the founding roll, then the enclosure
   recompute, then the season record. `hoc/sim.py` `run_season`.
2. **`LoggingRandom`** — the same façade over `Prng`, appending
   `{purpose, result}` to the season log in the same order with the same purpose
   strings. The purpose strings are compared by the cross-check, so they are
   part of the contract, not decoration.
3. **Founding** — `found_house`, `_draw_region` (integer drift), `_draw_seat`,
   `_draw_tag`, `_draw_founding_objectives`, `_unique_house_name`.
4. **Mortality and succession** — `_mortality`, `_succeed`, `_partition`,
   `_outer_holdings` (a BFS over land adjacency restricted to the house's own
   holdings), `_check_extinction`, `_remove_house`, `_lose_riding`.
5. **The event deck** — `_era_event`, `_fired_events`, `_response_for`,
   `_shift_climate`, `_in_scope`, `_apply_direct_effects`, `_sell_riding`.
6. **Relations and friction** — the relation helpers, `province_distance`,
   `housesWithinReach`, `_run_friction`, `_lapse_grievances`,
   `_grievance_template`.
7. **Actions** — `legal_actions`, `action_weights` (integer fixed point at
   `WEIGHT_SCALE = 100`), `take_action`, `resolve_action`, and the seventeen
   `_do_*` handlers. **Their chronicle strings must match character for
   character**, including the `·` separator and the non-breaking spacing of the
   peerage titles.
8. **Objectives, enclosure, debt** — `_check_objectives`, `_satisfy_objective`,
   `_contiguous_holdings`, `_recompute_enclosure`, `_debt_check`,
   `_seasons_since_loss`.
9. **The season record** — `_write_season`, `_snapshot`, `_interventions_since`,
   and `canonical_json` (sorted keys, `separators=(",", ":")`, UTF-8 as-is, one
   trailing newline). The record carries `engine: {impl: "javascript", ...}` —
   the one field the cross-check ignores.

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
