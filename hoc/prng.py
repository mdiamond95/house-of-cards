"""The portable random number generator: xoshiro128** on unsigned 32-bit words.

Phase 10-1. The engine used to run on `random.Random`, which is a Mersenne
Twister with 19937 bits of state, 53-bit floats and a seeding routine that is
CPython's business and nobody else's. Nothing about it is reproducible outside
CPython, so a second engine — the JavaScript one in `web/engine/` — could never
have agreed with it. This module replaces it with an algorithm small enough to
state completely and mechanical enough to reimplement exactly:

* every value is an unsigned 32-bit integer, masked after every operation;
* the state is four such words, seeded by splitmix32 from one 32-bit seed;
* every derived draw (floats, dice, ranges, weighted picks) is defined here in
  terms of `next_u32` and nowhere else.

`web/engine/prng.js` is a line-for-line mirror of this file. The two are held
together by `scripts/crosscheck.py`, and by `tests/test_prng.py`, which pins the
first ten values for seed 1867 season 1 as literals: if either engine drifts,
those literals fail before anything subtler does.

Everything here is documented with worked examples in docs/DETERMINISM.md.

Why xoshiro128** and not something better known: it is 32-bit throughout, so
JavaScript can implement it exactly with `Math.imul` and `>>> 0` without
touching BigInt; it needs four words of state, so a season's seeding is cheap;
and its output is good enough for a board game that draws a few thousand times
a season. It is not cryptographic and must never be used as though it were.
"""

import math

__all__ = [
    "MASK32",
    "Prng",
    "fnv1a32",
    "splitmix32",
    "season_seed",
    "TWO_POW_32",
]

MASK32 = 0xFFFFFFFF
TWO_POW_32 = 1 << 32  # 4294967296

# splitmix32's constants (Steele/Lea/Flood, as adapted to 32 bits).
_SPLITMIX_GAMMA = 0x9E3779B9
_SPLITMIX_MIX_1 = 0x21F0AAAD
_SPLITMIX_MIX_2 = 0x735A2D97

# FNV-1a, 32-bit.
_FNV_OFFSET_BASIS = 0x811C9DC5
_FNV_PRIME = 0x01000193


def _rotl32(value, bits):
    """Rotate a 32-bit word left. JS: ((v << b) | (v >>> (32 - b))) >>> 0."""
    value &= MASK32
    return ((value << bits) | (value >> (32 - bits))) & MASK32


def splitmix32(seed):
    """Yield the splitmix32 stream from a 32-bit seed, forever.

    Used only to fill xoshiro128**'s four state words: xoshiro is a poor
    self-seeder (an all-zero state is a fixed point that never leaves), and
    splitmix32 turns any 32-bit integer, zero included, into four well-mixed
    words in four steps.

        state = seed
        loop:
            state = (state + 0x9E3779B9) mod 2^32
            z = state
            z = ((z xor (z >>> 16)) * 0x21F0AAAD) mod 2^32
            z = ((z xor (z >>> 15)) * 0x735A2D97) mod 2^32
            yield z xor (z >>> 15)
    """
    state = seed & MASK32
    while True:
        state = (state + _SPLITMIX_GAMMA) & MASK32
        z = state
        z = ((z ^ (z >> 16)) * _SPLITMIX_MIX_1) & MASK32
        z = ((z ^ (z >> 15)) * _SPLITMIX_MIX_2) & MASK32
        yield (z ^ (z >> 15)) & MASK32


def fnv1a32(text):
    """FNV-1a over the UTF-8 bytes of `text`, as an unsigned 32-bit integer.

        hash = 0x811C9DC5
        for each byte b:
            hash = hash xor b
            hash = (hash * 0x01000193) mod 2^32

    Used to turn "world_seed:season_no" into this season's 32-bit seed. The
    strings this hashes are ASCII decimal digits and a colon, so "UTF-8 bytes"
    and "ASCII bytes" are the same bytes; JS can hash `charCodeAt` directly.
    """
    digest = _FNV_OFFSET_BASIS
    for byte in text.encode("utf-8"):
        digest ^= byte
        digest = (digest * _FNV_PRIME) & MASK32
    return digest


def season_seed(world_seed, season_no):
    """This season's 32-bit seed: fnv1a32("<world_seed>:<season_no>").

    The old engine digested the same pair with blake2b, which was portable in
    principle and unavailable in JavaScript in practice. Both numbers are
    written in ASCII decimal with no padding and no sign, which is what both
    languages produce for a non-negative int by default.
    """
    return fnv1a32(f"{int(world_seed)}:{int(season_no)}")


class Prng:
    """xoshiro128** seeded by splitmix32, plus the draws the engine actually uses.

    Every method here is defined purely in terms of `next_u32`, so the JS port
    only has to get one function right to get all of them right.
    """

    __slots__ = ("s",)

    def __init__(self, seed):
        """Seed the four state words from one 32-bit integer via splitmix32."""
        stream = splitmix32(seed)
        self.s = [next(stream) for _ in range(4)]

    # -- the generator itself --

    def next_u32(self):
        """One step of xoshiro128** (Blackman & Vigna).

            result = rotl(s1 * 5, 7) * 9
            t  = s1 << 9
            s2 ^= s0;  s3 ^= s1;  s1 ^= s2;  s0 ^= s3
            s2 ^= t
            s3  = rotl(s3, 11)
            return result

        Every product and shift is masked to 32 bits. In JS the two products
        are `Math.imul`, which is 32-bit multiplication with the same wrapping.
        """
        s0, s1, s2, s3 = self.s
        result = (_rotl32((s1 * 5) & MASK32, 7) * 9) & MASK32

        t = (s1 << 9) & MASK32
        s2 ^= s0
        s3 ^= s1
        s1 ^= s2
        s0 ^= s3
        s2 ^= t
        s3 = _rotl32(s3, 11)

        self.s = [s0 & MASK32, s1 & MASK32, s2 & MASK32, s3 & MASK32]
        return result

    # -- derived draws --

    def rand_float(self):
        """A float in [0, 1): `next_u32() / 2**32`.

        Dividing by a power of two is exact in IEEE-754 — it only shifts the
        exponent — so Python and JavaScript produce bit-identical doubles from
        the same word. Nothing else in the engine may invent a float.
        """
        return self.next_u32() / TWO_POW_32

    def rand_int(self, lo, hi):
        """A uniform integer in [lo, hi], inclusive, with no modulo bias.

        Rejection sampling, stated exactly so JS can mirror it:

            span  = hi - lo + 1
            if span == 1: return lo
            limit = 2**32 - (2**32 mod span)     # the largest multiple of
                                                 # span that fits in 32 bits
            repeat:
                r = next_u32()
                if r < limit: return lo + (r mod span)

        `limit` cuts the 2^32 outputs down to a whole number of spans, so every
        value in [lo, hi] is drawn with exactly the same probability. The naive
        `lo + next_u32() % span` would favour the first `2**32 mod span` values,
        which for a d6 is a bias of about one part in 700 million — small, but
        the point of this module is that nothing is left to chance twice.

        The loop terminates with probability 1 and, for every span the engine
        uses (at most a few thousand), rejects on well under one draw in a
        million.
        """
        span = hi - lo + 1
        if span <= 0:
            raise ValueError(f"empty range: rand_int({lo}, {hi})")
        if span == 1:
            return lo
        limit = TWO_POW_32 - (TWO_POW_32 % span)
        while True:
            value = self.next_u32()
            if value < limit:
                return lo + (value % span)

    def rand_d6(self):
        return self.rand_int(1, 6)

    def rand_2d6(self):
        """Two dice, drawn in order, returned as (a, b). The engine logs both:
        a natural 2 is a rule (rules/friction.json, correspond_fumble), so the
        dice have to be visible in the record and not just their total."""
        a = self.rand_int(1, 6)
        b = self.rand_int(1, 6)
        return a, b

    def choice(self, seq):
        """`seq[rand_int(0, len(seq) - 1)]`. The caller owns the ordering of
        `seq`: pass a list in a defined order, never a set."""
        items = list(seq)
        if not items:
            raise ValueError("cannot choose from an empty sequence")
        return items[self.rand_int(0, len(items) - 1)]

    def weighted_choice(self, items, weights):
        """Pick from `items` in proportion to `weights`, which must be integers.

            total  = sum(weights)                # every weight >= 0
            target = rand_int(1, total)          # 1..total inclusive
            running = 0
            for item, weight in zip(items, weights):
                running += weight
                if target <= running: return item

        Integer weights and an integer target are what make this portable: the
        old engine multiplied a float by a float total and compared, which is
        three roundings deep and cannot be relied on to land the same way twice
        in two languages. Weights of zero never come up, since `target` starts
        at 1 and a zero weight never advances `running` past it.

        Returns None when every weight is zero or there is nothing to pick.
        """
        pairs = [(item, int(weight)) for item, weight in zip(items, weights) if int(weight) > 0]
        if not pairs:
            return None
        total = sum(weight for _, weight in pairs)
        target = self.rand_int(1, total)
        running = 0
        for item, weight in pairs:
            running += weight
            if target <= running:
                return item
        return pairs[-1][0]  # unreachable while the weights are non-negative

    # -- the one permitted float comparison --

    def chance_float(self, probability):
        """True with probability `probability`, compared against rand_float().

        Reserved for the founding roll (§10), whose probability is a genuine
        continuous function of how much land is left. Every other probability in
        the game is an integer percentage and goes through `chance_percent`.
        """
        return self.rand_float() < probability


def p_found(room, total_ridings, coefficient):
    """§10's founding probability: sqrt(room / total) * coefficient.

    The one floating-point computation the engine is allowed. It is written as a
    square root rather than `(room / total) ** exponent` because IEEE-754
    requires `sqrt` to be correctly rounded — Python's `math.sqrt` and
    JavaScript's `Math.sqrt` must return the same double for the same input —
    while a general `pow` carries no such guarantee and is free to differ in the
    last bit between the two runtimes. Division and multiplication are exact
    operations under the same standard, so all three steps agree bit for bit.
    """
    return math.sqrt(room / total_ridings) * coefficient
