// Story weight (docs/STORY_DESIGN.md §3.1).
//
// Every beat gets an integer weight: its kind's base from weights.json, then
// the modifiers, in this order —
//   + top_eight   if a house of the cast (the top eight at the start of the
//                 turn) is among the beat's houses
//   + first       if it is the first beat of its kind in the game, or the first
//                 riding any house has held in its province (once, not twice)
//   + callback    if the same pair of houses shared a beat in the last
//                 `callback_window` turns
//   + repeat_headline (negative) if its kind headlined the previous turn
//   × follow_multiplier if the followed house is among its houses
// and never below zero. A beat whose base is zero takes no modifier: the four
// bookkeeping actions never headline, whoever is involved.
//
// What carries from turn to turn — kinds seen, provinces entered, which pairs
// met when, the last headline's kind — is a plain context object. weighTurn
// reads it and advance returns the next one; neither mutates it.

import { compareText } from './beats.js';

// `seenKinds` are kinds whose first has already happened: a page that picks a
// game up part-way through cannot know which firsts are spent, and passes every
// kind rather than announce a hundredth expansion as the first.
export function createContext(baselineOwners = {}, seenKinds = []) {
  const provinces = new Set();
  for (const fed of Object.keys(baselineOwners)) provinces.add(provinceOf(fed));
  return {
    kinds: [...new Set(seenKinds)].sort(compareText),
    provinces: [...provinces].sort(compareText),
    pairs: {},
    lastHeadline: null,
  };
}

// A riding's province is the two-digit prefix of its federal electoral
// district code (10 Newfoundland and Labrador ... 62 Nunavut).
export function provinceOf(fed) {
  return String(fed).slice(0, 2);
}

function pairKey(a, b) {
  return compareText(a, b) <= 0 ? `${a}\u0000${b}` : `${b}\u0000${a}`;
}

function pairsOf(houses) {
  const unique = [...new Set(houses)];
  const keys = [];
  for (let i = 0; i < unique.length; i += 1) {
    for (let j = i + 1; j < unique.length; j += 1) keys.push(pairKey(unique[i], unique[j]));
  }
  return keys;
}

function gainedProvinces(beat) {
  const out = [];
  for (const [fed, house] of Object.entries(beat.owners || {})) {
    if (house !== null) out.push(provinceOf(fed));
  }
  return out;
}

// Each beat's weight, as { total, base, mods: [[name, value]] }, in beat order.
// `cast` is the set of top-eight houses at the start of the turn; `follow` the
// followed house or null.
export function weighTurn(beats, context, { weights, cast = new Set(), follow = null } = {}) {
  const m = weights.modifiers;
  const kinds = new Set(context.kinds);
  const provinces = new Set(context.provinces);
  return beats.map((beat) => {
    const base = Object.prototype.hasOwnProperty.call(weights.kinds, beat.kind)
      ? weights.kinds[beat.kind] : 0;
    const mods = [];
    const houses = beat.houses || [];
    const firstKind = !kinds.has(beat.kind);
    const fresh = gainedProvinces(beat).filter((p) => !provinces.has(p));
    if (base > 0) {
      if (houses.some((h) => cast.has(h))) mods.push(['top_eight', m.top_eight]);
      if (firstKind || fresh.length) mods.push(['first', m.first]);
      const recent = pairsOf(houses).some((key) => {
        const last = context.pairs[key];
        return last !== undefined && beat.turn - last <= m.callback_window && beat.turn > last;
      });
      if (recent) mods.push(['callback', m.callback]);
      if (context.lastHeadline === beat.kind) mods.push(['repeat_headline', m.repeat_headline]);
    }
    // Firsts are spent by the beat that has them, so a second expansion into
    // a new province in the same turn is not also a first.
    if (base > 0) kinds.add(beat.kind);
    for (const p of gainedProvinces(beat)) provinces.add(p);
    let total = base + mods.reduce((sum, [, value]) => sum + value, 0);
    if (base > 0 && follow !== null && houses.includes(follow)) {
      mods.push(['follow', m.follow_multiplier]);
      total *= m.follow_multiplier;
    }
    return { total: Math.max(0, total), base, mods };
  });
}

// The context after a turn: its weighted kinds and provinces are spent, its
// pairs are remembered at this turn, and its headline kind (or null for a
// quiet turn) is the one the next turn is penalised for repeating.
export function advance(context, beats, headlineKind, weights) {
  const kinds = new Set(context.kinds);
  const provinces = new Set(context.provinces);
  const pairs = { ...context.pairs };
  for (const beat of beats) {
    const base = weights.kinds[beat.kind] || 0;
    for (const p of gainedProvinces(beat)) provinces.add(p);
    if (base <= 0) continue;
    kinds.add(beat.kind);
    for (const key of pairsOf(beat.houses || [])) pairs[key] = beat.turn;
  }
  return {
    kinds: [...kinds].sort(compareText),
    provinces: [...provinces].sort(compareText),
    pairs,
    lastHeadline: headlineKind,
  };
}
