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

with `total = 343` and `coefficient = 0.5` from `rules/founding.json`. It is written as a
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

## Keeping it true

`CLAUDE.md` carries the standing rule: **any change to `hoc/sim.py` must be mirrored in
`web/engine/sim.js` in the same pull request, and the cross-check must pass.** The
cross-check is not a formality — it is the only thing that can tell you the two engines
have drifted, and it will tell you the exact season and the exact field.
