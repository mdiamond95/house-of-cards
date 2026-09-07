// The portable random number generator: xoshiro128** on unsigned 32-bit words.
//
// A line-for-line mirror of hoc/prng.py. Read that file for why each algorithm
// is the one it is; read docs/DETERMINISM.md for worked examples. If you change
// anything here, change it there in the same commit and run
// `python scripts/crosscheck.py` — the two engines are only worth having
// because they agree.
//
// JavaScript has no 32-bit integer type, but it has three operators that behave
// as though it did:
//   * `Math.imul(a, b)` is 32-bit multiplication with the same wrapping as
//     `(a * b) & 0xFFFFFFFF` in Python.
//   * `>>> 0` reinterprets a 32-bit result as unsigned, which is what turns
//     JavaScript's signed bitwise operators back into Python's.
//   * `<<`, `>>>` and `^` are already 32-bit.
// Every operation below ends in one of those, so no value ever escapes 32 bits
// and BigInt is never needed.

export const MASK32 = 0xffffffff;
export const TWO_POW_32 = 4294967296;

const SPLITMIX_GAMMA = 0x9e3779b9;
const SPLITMIX_MIX_1 = 0x21f0aaad;
const SPLITMIX_MIX_2 = 0x735a2d97;

const FNV_OFFSET_BASIS = 0x811c9dc5;
const FNV_PRIME = 0x01000193;

function rotl32(value, bits) {
  return ((value << bits) | (value >>> (32 - bits))) >>> 0;
}

// The splitmix32 stream, as a stateful stepper. Python yields from a generator;
// this returns a closure, which is the same thing with a different spelling.
export function splitmix32(seed) {
  let state = seed >>> 0;
  return function next() {
    state = (state + SPLITMIX_GAMMA) >>> 0;
    let z = state;
    z = Math.imul(z ^ (z >>> 16), SPLITMIX_MIX_1) >>> 0;
    z = Math.imul(z ^ (z >>> 15), SPLITMIX_MIX_2) >>> 0;
    return (z ^ (z >>> 15)) >>> 0;
  };
}

// FNV-1a over the UTF-8 bytes of `text`.
//
// The strings this hashes are "<int>:<int>" — ASCII digits and a colon — so
// every code unit is a single byte and charCodeAt gives that byte directly.
// The guard rejects anything else rather than silently hashing UTF-16 code
// units where Python would hash UTF-8 bytes, which is exactly the kind of
// difference that would show up a hundred seasons later as an unexplained
// divergence.
export function fnv1a32(text) {
  let digest = FNV_OFFSET_BASIS;
  for (let i = 0; i < text.length; i += 1) {
    const code = text.charCodeAt(i);
    if (code > 0x7f) {
      throw new Error(`fnv1a32 expects ASCII, got ${JSON.stringify(text)}`);
    }
    digest = (digest ^ code) >>> 0;
    digest = Math.imul(digest, FNV_PRIME) >>> 0;
  }
  return digest >>> 0;
}

// This season's 32-bit seed: fnv1a32("<world_seed>:<season_no>").
export function seasonSeed(worldSeed, seasonNo) {
  return fnv1a32(`${Math.trunc(worldSeed)}:${Math.trunc(seasonNo)}`);
}

export class Prng {
  constructor(seed) {
    const stream = splitmix32(seed);
    this.s = [stream(), stream(), stream(), stream()];
  }

  // One step of xoshiro128** (Blackman & Vigna). See hoc/prng.py.
  nextU32() {
    const [s0, s1, s2, s3] = this.s;
    const result = Math.imul(rotl32(Math.imul(s1, 5) >>> 0, 7), 9) >>> 0;

    const t = (s1 << 9) >>> 0;
    let n2 = (s2 ^ s0) >>> 0;
    const n3 = (s3 ^ s1) >>> 0;
    const n1 = (s1 ^ n2) >>> 0;
    const n0 = (s0 ^ n3) >>> 0;
    n2 = (n2 ^ t) >>> 0;

    this.s = [n0, n1, n2, rotl32(n3, 11)];
    return result;
  }

  // A float in [0, 1). Dividing by a power of two is exact in IEEE-754, so this
  // is the same double Python produces from the same word.
  randFloat() {
    return this.nextU32() / TWO_POW_32;
  }

  // A uniform integer in [lo, hi] inclusive, by rejection sampling. The
  // arithmetic below stays exact: `span` is at most 2^32, and both
  // `TWO_POW_32 % span` and `value % span` are integer-valued doubles well
  // inside the 2^53 range where `%` is exact.
  randInt(lo, hi) {
    const span = hi - lo + 1;
    if (span <= 0) throw new Error(`empty range: randInt(${lo}, ${hi})`);
    if (span === 1) return lo;
    const limit = TWO_POW_32 - (TWO_POW_32 % span);
    for (;;) {
      const value = this.nextU32();
      if (value < limit) return lo + (value % span);
    }
  }

  randD6() {
    return this.randInt(1, 6);
  }

  // Two dice, drawn in order. Returned as a pair because a natural 2 is a rule.
  rand2d6() {
    const a = this.randInt(1, 6);
    const b = this.randInt(1, 6);
    return [a, b];
  }

  choice(seq) {
    const items = Array.from(seq);
    if (items.length === 0) throw new Error('cannot choose from an empty sequence');
    return items[this.randInt(0, items.length - 1)];
  }

  // Pick from `items` in proportion to integer `weights`, by cumulative scan
  // against randInt(1, total). Returns null when nothing has a positive weight.
  weightedChoice(items, weights) {
    const pairs = [];
    for (let i = 0; i < items.length; i += 1) {
      const weight = Math.trunc(weights[i]);
      if (weight > 0) pairs.push([items[i], weight]);
    }
    if (pairs.length === 0) return null;
    let total = 0;
    for (const [, weight] of pairs) total += weight;
    const target = this.randInt(1, total);
    let running = 0;
    for (const [item, weight] of pairs) {
      running += weight;
      if (target <= running) return item;
    }
    return pairs[pairs.length - 1][0];
  }

  // Reserved for the founding roll; see pFound below.
  chanceFloat(probability) {
    return this.randFloat() < probability;
  }
}

// §10's founding probability: sqrt(room / total) * coefficient. Written as a
// square root because IEEE-754 requires sqrt to be correctly rounded, while a
// general pow does not — see hoc/prng.py for the full argument.
export function pFound(room, totalRidings, coefficient) {
  return Math.sqrt(room / totalRidings) * coefficient;
}
