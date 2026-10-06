// Story weight (docs/STORY_DESIGN.md §3.1, with §3.4's weight by position).
//
// Every beat gets an integer weight: its kind's base from weights.json, then
// the modifiers, in this order —
//   + top_eight   if a house of the cast (the top eight at the start of the
//                 turn) is among the beat's houses
//   + first       if it is the first beat of its kind in the game, or the first
//                 riding any house has held in its province (once, not twice)
//   + storyline   by the beat's place in the storylines it belongs to
//                 (storylines.js): none for the beat that opens one; for a beat
//                 that escalates one, escalate_per_beat for each earlier beat in
//                 it, up to escalate_max — except a frontier, whose beats take
//                 no escalation bonus; close for the beat that closes one. A
//                 beat in several storylines takes the largest.
//   + repeat_headline (negative) if its kind headlined the previous turn
//   × follow_multiplier if the followed house is among its houses
// and never below zero. A quarrel that opens a rivalry between two houses
// outside the cast starts from `storylines.quarrel_outside_cast` instead of the
// quarrel's base, and a contest decided between houses outside the cast
// (contest_won, contest_lost, fallen) from its base times the share
// `storylines.contest_outside_cast` (Phase D1). A beat whose base is zero takes no modifier: the four
// bookkeeping actions never headline, whoever is involved.
//
// What carries from turn to turn — kinds seen, provinces entered, the last
// headline's kind — is a plain context object. weighTurn reads it and advance
// returns the next one; neither mutates it.

import { compareText } from './beats.js';

const CONTEST_KINDS = ['contest_won', 'contest_lost', 'fallen'];

// `seenKinds` are kinds whose first has already happened: a page that picks a
// game up part-way through cannot know which firsts are spent, and passes every
// kind rather than announce a hundredth expansion as the first.
export function createContext(baselineOwners = {}, seenKinds = []) {
  const provinces = new Set();
  for (const fed of Object.keys(baselineOwners)) provinces.add(provinceOf(fed));
  return {
    kinds: [...new Set(seenKinds)].sort(compareText),
    provinces: [...provinces].sort(compareText),
    lastHeadline: null,
  };
}

// A riding's province is the two-digit prefix of its federal electoral
// district code (10 Newfoundland and Labrador ... 62 Nunavut).
export function provinceOf(fed) {
  return String(fed).slice(0, 2);
}

function gainedProvinces(beat) {
  const out = [];
  for (const [fed, house] of Object.entries(beat.owners || {})) {
    if (house !== null) out.push(provinceOf(fed));
  }
  return out;
}

// What a beat's storyline roles add (§3.4): the largest of them.
export function storylineBonus(roles, cfg) {
  let bonus = 0;
  for (const { role, earlier, type } of roles || []) {
    if (role === 'close') bonus = Math.max(bonus, cfg.close);
    else if (role === 'escalate' && type !== 'frontier') {
      bonus = Math.max(bonus, Math.min(cfg.escalate_max, cfg.escalate_per_beat * earlier));
    }
  }
  return bonus;
}

// Each beat's weight, as { total, base, mods: [[name, value]] }, in beat order.
// `cast` is the set of top-eight houses at the start of the turn; `follow` the
// followed house or null; `roles[i]` beat i's storyline roles.
export function weighTurn(beats, context, { weights, cast = new Set(), follow = null, roles = [] } = {}) {
  const m = weights.modifiers;
  const cfg = weights.storylines;
  const kinds = new Set(context.kinds);
  const provinces = new Set(context.provinces);
  return beats.map((beat, i) => {
    let base = Object.prototype.hasOwnProperty.call(weights.kinds, beat.kind)
      ? weights.kinds[beat.kind] : 0;
    const mods = [];
    const houses = beat.houses || [];
    const mine = roles[i] || [];
    const inCast = houses.some((h) => cast.has(h));
    if (beat.kind === 'quarrel' && !inCast && mine.some((r) => r.role === 'open')) {
      base = cfg.quarrel_outside_cast;
    }
    if (CONTEST_KINDS.includes(beat.kind) && !inCast && cfg.contest_outside_cast) {
      const [num, den] = cfg.contest_outside_cast;
      base = Math.floor((base * num) / den);
    }
    const firstKind = !kinds.has(beat.kind);
    const fresh = gainedProvinces(beat).filter((p) => !provinces.has(p));
    if (base > 0) {
      if (inCast) mods.push(['top_eight', m.top_eight]);
      if (firstKind || fresh.length) mods.push(['first', m.first]);
      const bonus = storylineBonus(mine, cfg);
      if (bonus) mods.push(['storyline', bonus]);
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

// The context after a turn: its weighted kinds and provinces are spent, and
// its headline kind (or null for a quiet turn) is the one the next turn is
// penalised for repeating.
export function advance(context, beats, headlineKind, weights) {
  const kinds = new Set(context.kinds);
  const provinces = new Set(context.provinces);
  for (const beat of beats) {
    const base = weights.kinds[beat.kind] || 0;
    for (const p of gainedProvinces(beat)) provinces.add(p);
    if (base > 0) kinds.add(beat.kind);
  }
  return {
    kinds: [...kinds].sort(compareText),
    provinces: [...provinces].sort(compareText),
    lastHeadline: headlineKind,
  };
}
