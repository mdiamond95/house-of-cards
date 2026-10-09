# Determinism: how two engines play the same game

Phase 10-1. There are two implementations of the House of Cards engine — `hoc/sim.py`
in Python and `web/engine/sim.js` in JavaScript — and they are required to produce
**byte-identical season files** from the same seed. `scripts/crosscheck.py` runs both
and diffs them; `tests/test_crosscheck.py` fails the suite if they ever disagree.

This document is the contract. Anything in it that is not true of both engines is a bug
in one of them.

## Why this was needed

Until Phase 10-1 the engine drew from Python's `random.Random`: a Mersenne Twister with
19937 bits of state, CPython's own seeding routine, 53-bit floats, and float draw weights
compared against a float target. None of that is specified anywhere outside CPython. A
second implementation could have been *approximately* right and would have diverged within
a few dozen seasons, in a way no test would have localised.

So the requirement is not "the engine is random". It is: **every number the game turns on
is derived from one 32-bit generator, by an algorithm short enough to state completely on
this page.**

## The rules, in one list

1. Every random value comes from `next_u32()` and nothing else.
2. Every draw weight is a **non-negative integer**. No float weights, anywhere.
3. Every probability is an **integer per cent**, rolled as `rand_int(1, 100) <= pct` —
   except the founding roll, below.
4. The **only** floating-point computation in the engine is §10's founding probability,
   and the only float comparison is that probability against `rand_float()`.
5. Every iteration whose order can change an outcome is over an explicitly ordered
   sequence — a sorted list, or a rules file's own row order. Never a set, and never a
   mapping's iteration order.
6. Season files are written with `canonical_json`: sorted keys, `separators=(",", ":")`,
   `ensure_ascii=False`, one trailing newline.

## The generator

**splitmix32**, used only to expand a 32-bit seed into xoshiro's four state words
(xoshiro is a poor self-seeder — an all-zero state never leaves itself):

```
state = seed
next():
    state = (state + 0x9E3779B9) mod 2^32
    z = state
    z = ((z xor (z >>> 16)) * 0x21F0AAAD) mod 2^32
    z = ((z xor (z >>> 15)) * 0x735A2D97) mod 2^32
    return z xor (z >>> 15)
```

**xoshiro128\*\*** (Blackman & Vigna), the generator proper:

```
next_u32():
    result = rotl(s1 * 5, 7) * 9
    t  = s1 << 9
    s2 ^= s0;  s3 ^= s1;  s1 ^= s2;  s0 ^= s3
    s2 ^= t
    s3  = rotl(s3, 11)
    return result
```

Every product and shift is masked to 32 bits. In JavaScript the two products are
`Math.imul` and every result is closed with `>>> 0`; in Python every result is `& 0xFFFFFFFF`.

It is 32-bit throughout, which is the whole reason it was chosen: JavaScript can do it
exactly without BigInt. It is **not cryptographic** and must never be used as though it were.

## The season seed

```
season_seed(world_seed, season_no) = fnv1a32("<world_seed>:<season_no>")

fnv1a32(text):
    hash = 0x811C9DC5
    for each byte b of UTF-8(text):
        hash = hash xor b
        hash = (hash * 0x01000193) mod 2^32
```

Both numbers are written in ASCII decimal, unpadded, unsigned — what both languages print
for a non-negative integer by default. The string is therefore pure ASCII, so "UTF-8 bytes"
and "UTF-16 code units" are the same numbers and `charCodeAt` is safe. `web/engine/prng.js`
throws rather than guess if it is ever handed a non-ASCII string.

## The derived draws

```
rand_float()      = next_u32() / 2^32

rand_int(lo, hi)  span  = hi - lo + 1
                  if span == 1: return lo
                  limit = 2^32 - (2^32 mod span)
                  repeat:
                      r = next_u32()
                      if r < limit: return lo + (r mod span)

rand_d6()         = rand_int(1, 6)
rand_2d6()        = (rand_int(1, 6), rand_int(1, 6))     -- two draws, in that order
choice(seq)       = seq[rand_int(0, len(seq) - 1)]

weighted_choice(items, weights):     -- weights are integers; zero never comes up
    drop every pair whose weight <= 0, keeping order
    total   = sum(weights)
    target  = rand_int(1, total)
    running = 0
    for (item, weight) in pairs:
        running += weight
        if target <= running: return item
```

`rand_float` divides by a power of two, which in IEEE-754 only shifts the exponent — it is
exact, so both languages produce the same double from the same word.

`rand_int` rejects rather than taking a modulo, so there is no bias: `limit` trims the 2^32
outputs to a whole number of spans. The naive `lo + next_u32() % span` would favour the
first `2^32 mod span` values — for a d6 that is a bias of about one part in 700 million,
which does not matter to the game and matters entirely to the principle that nothing here
is left to chance twice. For every span the engine uses, rejection happens on well under
one draw in a million.

## The one float

§10's founding probability:

```
p_found(room, total, coefficient) = sqrt(room / total) * coefficient
```

with `total` the number of units on the map (343 on both riding sets; "The hex board" below) and `coefficient = 0.5` from `rules/founding.json`. It is written as a
**square root**, not as `(room/total) ** exponent`, because IEEE-754 requires `sqrt` to be
correctly rounded — `math.sqrt` and `Math.sqrt` must return the same double for the same
input — while a general `pow` carries no such guarantee and is free to differ in the last
bit. Division and multiplication are exact-or-correctly-rounded under the same standard, so
all three steps agree.

It is compared against `rand_float()`, and that comparison is the only place in the engine
where two floats are compared.

## Ordering

Sorting decides outcomes, so both engines must sort the same way.

- **Houses act** in `(founded_season, seat fed_id, house)` order — by seat *fed_id*, an
  ASCII code, rather than by riding name, whose accents and em-dashes would make the answer
  depend on SQLite's collation.
- **Rules rows** are walked in the file's own row order (`communities.csv`, `objectives.csv`).
- **Actions** are walked in sorted action-name order.
- **Regions** are walked in sorted region-name order, not `founding.json`'s key order.
- **House names** are sorted as strings. Every surname in the banks is in the Basic
  Multilingual Plane, where UTF-8 byte order (SQLite's `BINARY`), UTF-16 code-unit order
  (JavaScript's `<`) and code-point order all coincide. Nothing outside the BMP may enter
  the surname banks without revisiting this.
- **Sets are never iterated.** They are used for membership tests only.

## The palette

`hoc/palette.py` and `web/engine/palette.js` are integer-only: hues are whole degrees
(0–359), saturation and lightness whole per cent, the distance metric is squared and
scaled by 1000 so no square root is taken, and HSL→hex is the exact integer conversion
documented in `hsl_to_hex`. Ties in `farthest_hue` go to the lowest hue, because the scan
runs upward and only a strictly greater gap displaces the incumbent — that tie-break is
load-bearing.

Converting a v1 hex colour to integer HSL loses up to one point of saturation and lightness,
since the generator only ever draws whole per cent. Stored colours are never rewritten —
they are only read, to place new hues away from them — so the loss does not accumulate.

## Reference data from Meridian

The `meridian-v1.0.3` reference-data version (`data/reference/meridian/v1.0.3/`) is built
from Meridian's riding unit table, which is JSON full of decimal fractions — shares,
indices, areas. **Neither engine ever sees one of them.** `scripts/build_world_meridian.py`
converts every value a table carries into an integer, once, when the tables are built, by
this rule:

1. The table is parsed with every number as a `decimal.Decimal` (`parse_float=Decimal`):
   exactly the digits Meridian wrote, never a binary float.
2. A share in 0–1 becomes an **integer per mille**: `value × 1000`, rounded **half up**
   (`ROUND_HALF_UP`) to a whole number, in exact decimal arithmetic. `0.0237` is `24`;
   `0.0025` is `3`. A share outside 0–1 is refused.
3. Any other quantity carried as an integer (`land_area_km2`) is rounded half up to a
   whole number in the same exact arithmetic.
4. A **tier** (`wealth_tier`, `resource_tier`) is a quintile: the 343 ridings are ranked
   ascending by `(value, fed_id)` — `value` an exact `Decimal` or integer, so ties are
   broken by fed id and nothing else — and the riding at 0-based rank `r` is in tier
   `1 + (5 × r) // 343`. Tier 5 is the top fifth. Integer arithmetic only.
5. A date becomes a **year**: `from_year` is the year of the span's `from`; `to_year` is
   the next span's `from_year − 1`, empty for the span still in force. A span left empty
   by this (two changes in one year) is dropped and the later one kept.
6. A value nothing in the game reads (`jurisdictions[].share`, `score.exposure`) is not
   carried at all, rather than converted for no one.

7. A place's **`designation_ok`** (`places_by_riding.csv`) is decided by text tests on
   the name exactly as Meridian wrote it, never on a rewritten one. It is 1 only when all
   of these hold, else 0:
   - `spans_ridings` is 0 (the place's population does not exceed its riding's);
   - every character is a letter (Unicode `isalpha`, accented letters included), a space,
     a hyphen, an apostrophe (`'` or `’`) or a period — so no digit, comma, parenthesis
     or slash;
   - none of `Subd`, `Unorganized`, `Division`, `Part`, `Partie`, `Area`, `No`, `District`,
     `Region`, `Regional`, `Improvement`, `Special`, `County`, `Municipality`, `Municipal`,
     `Rural`, `Reserve`, `Settlement`, `Nation`, `Communauté` appears as a whole word
     (not preceded or followed by a word character; case as written);
   - the name does not end in a space and a single capital letter (`Cariboo I`);
   - splitting the name on the space character gives at most four parts.

   Both engines keep a place as a designation candidate only when it is 1, in the seat's
   own tier and its neighbours' tier alike; a set without the column (`ne-2026`) keeps every
   place. At v1.0.3 it is 1 for 3,353 of 4,830 places, in 194 ridings.

The CSVs are committed, so the rule runs once per reference-data version and both engines
read identical integers in identical row order.

## The hex board (the hex trial)

The `meridian-hex-v1.0.4` set (`data/reference/meridian/hex-v1.0.4/`, docs/hex-trial/) is
built by `scripts/build_world_hex.py` from Meridian v1.0.4's H3 resolution-4 hexagon table,
in the same table shapes as every set. Rules 1–6 above apply to it as they stand (the
quintiles rank 439 units, so a tier is `1 + (5 × r) // 439`). What it adds:

8. **Units** are the rows with population 5,000 or more: 439.
9. **A unit's id** is `PP × 1,000,000 + S`, eight digits: `PP` is the two-digit federal code
   of the row's `province` (NL 10, PE 11, NS 12, NB 13, QC 24, ON 35, MB 46, SK 47, AB 48,
   BC 59, YT 60, NT 61, NU 62), and `S` is the H3 index's 7-bit base cell and its four
   resolution digits (each 0–6, bits 42–31 of the index) read as one base-7 number,
   `((((base × 7) + d1) × 7 + d2) × 7 + d3) × 7 + d4`. The index must be a cell (mode 1) at
   resolution 4 with digits 5–15 all 7, or the build stops. Ids are fixed width, so string
   order is numeric order (the Ordering rule above), and the first two digits are the
   province, as a FED number's are.
10. **A unit's name.** Two type lists of `csdType` codes: towns (`C CY CV CÉ T TV V VL VN
    VC NV NVL SV RV HAM NH`) and general municipalities (`MÉ MU M MD DM RM TP CT CU P PE RGM
    MRM CM SM RCR ID LGD IM RMU CC CG COM SÉ SET`). Units are taken by population descending,
    ties by id. Pass 1: each takes the first of its own places, towns before municipalities,
    each list in the table's order (population descending), whose `name_key` no unit has
    taken. Pass 2, for the units pass 1 left: the hexagons at land-link distance 1 from the
    unit's, then 2, and so on (each ring in H3 order); in each ring, the place of the town
    list, then the municipal list, with the greatest population whose name is not taken,
    ties by hexagon then table order. A unit with no name after both passes stops the build.
    No name is ever rewritten.
11. **`designation_ok`** is 1 when the place's `csdType` is in either list and it does not
    span its unit; this replaces rule 7's name tests for this set.
12. **Territories.** Over the table's land links among all 6,011 hexagons, every unit is at
    distance 0 and, level by level, a hexagon first reached at distance d takes the lowest
    unit id among the hexagons at d − 1 that reach it. A hexagon no unit reaches by land has
    no unit.
13. **Links.** For two units whose territories meet along a land link (x, y), the length is
    the least `dist(x) + 1 + dist(y)`; ties by (x, y) in H3 order give the route drawn.
    Every land link of length 6 or less is kept. The others are taken by (length, a, b) and
    one is kept only when it joins two groups the kept land links leave apart (union by
    lowest id). Two units whose territories meet only along water links get a water link,
    of length measured the same way. A unit with no link after that gets one water link to
    the unit whose hexagon centre is nearest on the WGS84 ellipsoid (pyproj's geodesic,
    ties to the lower id), of length ⌈metres / 45,000⌉: the only floating-point measure in
    the build, taken once, and committed as the row it decides.

Nothing here reaches an engine but the six tables every set has, and none holds a float.
The founding roll's denominator (`p_found`, "The one float") is the map's unit count —
`World.total_units`, the JavaScript engine's `map.ridings.length` — which is 343 on both
riding sets, so their games are unchanged. Map geometry stays in decimal degrees,
because a map is drawn in them; it is computed in the same exact decimal arithmetic
(rounded half up to six places) and is read only by the site's map, never by an engine.

## Worked examples

All values below are produced by both engines. `tests/test_prng.py` pins them as literals.

**Seed derivation.** `season_seed(1867, 1) = fnv1a32("1867:1")`:

```
4018125158            (0xEF7FB966)
```

Two more, to show the hash actually mixes: `fnv1a32("1867:2") = 4001347539`,
`fnv1a32("2:1") = 1056972260`.

**State after seeding** `Prng(4018125158)` — the four splitmix32 outputs:

```
0x2624FCC3   0xD9C30FFD   0x00206683   0xDD1D0F5A
```

**The first ten `next_u32()` values for seed 1867, season 1:**

```
2766650784
 178856183
3621254264
 850972858
1308284850
1544645602
3752021905
3387998208
2676143205
2797899509
```

**The first three `rand_float()` values** from the same fresh generator (the first is
`2766650784 / 2^32`):

```
0.644161082804203
0.041643200209364295
0.8431389611214399
```

**The first ten `rand_int(1, 6)` values** from the same fresh generator:

```
1 6 3 5 1 5 2 1 4 6
```

**`p_found`**, at an empty map, a partly-settled one, and a full one:

```
p_found(343, 343, 0.5) = 0.5
p_found(300, 343, 0.5) = 0.46760976479141225
p_found(  0, 343, 0.5) = 0.0
```

## The round record

Rules 1.0's `round_record` (Phase V2, docs/STORY_DESIGN.md §3.6) writes down what both
engines already do, in two fields, and decides nothing.

- **`part`, on every engine event's mechanical delta.** The part of the round the event
  was recorded in:
  - `"world"` from the start of a season to the start of the house turns: ages, the
    world's turn (accessions, the years of running events, crises) and the borders'
    friction;
  - the house's key during that house's turn: upkeep, strain, the succession watch, its
    era events, its mortality and succession, its action and letter, its objectives and
    its debt check, whatever house the event names first;
  - `"close"` from the founding roll to the end of the season: the Crown's founding,
    enclosure, the quiet lines, prestige and the reckoning.

  Turn 1, the first founding alone, is `"close"`. A director's intervention, applied
  between seasons, carries none.
- **`order`, on every season record.** The houses the season's house turns were played
  for, in the order `active_houses()` gave when they began (the Ordering rule above),
  including a house removed before its turn came. Turn 1's is `[]`.

Neither is read by any decision, and both engines set them at the same three points of
the season loop. `tests/test_round_record.py` plays seeds 1867, 2 and 3 for 100 turns
under 1.0 with the flag on and off, and requires every season record and every event to
be identical once the two fields are taken out.

The database keeps `part` (in `events.mechanical_delta`) but not `order`, which lives in
the season record alone. The draft-rules preview writes no season file, so
`scripts/build_preview.py` hands the exporter its records' `order`;
`scripts/build_archive.py` reads it from the season files its replay writes.

The cross-check compares the events each engine recorded as well as its season files
(`scripts/crosscheck.py` `engine_events`): every engine event, in order, with its kind,
title, line, houses and delta, `part` included. An event's row id is not compared: a
director's intervention records a wrapper event, which the Python turn runner allocates
before the operations it carries and the JavaScript engine after them, so the numbering
after an intervention differs while the events, compared by position, do not.

## Keeping it true

`CLAUDE.md` carries the standing rule: **any change to `hoc/sim.py` must be mirrored in
`web/engine/sim.js` in the same pull request, and the cross-check must pass.** The
cross-check is not a formality — it is the only thing that can tell you the two engines
have drifted, and it will tell you the exact season and the exact field.
