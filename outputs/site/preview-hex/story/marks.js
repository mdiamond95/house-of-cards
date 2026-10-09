// The map view's marks (docs/STORY_DESIGN.md §3.6, Phase V): where a dispatch
// happened on the map, and how it is drawn there.
//
// `marksFor(dispatch, context)` turns one turn's dispatch (dispatch.js
// Story.step) into the things the map draws over itself:
//
//   marks    the headline's mark first, then at most `cap` others by story
//            weight. Each is one of a small vocabulary (MARK_TYPES):
//              transfer   a riding changing hands (its fill moves from the old
//                         colour to the new; the mark sits on the riding)
//              claim      a claim or contest: the target riding outlined and
//                         pulsing, a line from the claimant's seat, and the
//                         result (`taken` or `held`) once it resolves
//              scheme     a scheme begun or given up: an arrow from the seat to
//                         its target
//              seat       a founding, succession, elevation or fall, at the seat
//              bond       a match, compact or peace: a solid line between seats
//              strife     a quarrel or dispute: a broken line between seats
//              crisis     every standing house's camp (lead, resist, aside):
//                         the page tints each camp's holdings with a pattern
//                         (Phase V2); the camera takes the whole table
//              accession  land coming under Canada: its ridings, opened
//   schemes  the public schemes afoot of the cast and the followed house that
//            have a target, as faint arrows (intent, before it resolves)
//   chips    standing chips: an event still running ("The Great War, year 3
//            of 5"), and "a quiet year"
//   banner   the headline's sentence, when the headline names no place
//   more     how many beats worth telling were left off the map (the drawer
//            lists them)
//   frame    the ground the camera frames for the headline: the ridings it
//            names, else its scheme's target, else the seats of its houses
//
// A quiet turn has no marks and no scheme arrows, only its chip.
//
// Where a house is, is its seat: its principal riding (hard rule 4), from the
// seat history hoc/export/beats.py ships (`seatsAt`). Nothing here reads the
// page, the geometry or either engine: a mark names ridings by fed_id, and the
// page puts them on the map.
//
// Pure: no DOM, no engine, no clock, no randomness.

import { compareText } from './beats.js';

export const MARK_TYPES = ['transfer', 'claim', 'scheme', 'seat', 'bond', 'strife', 'crisis', 'accession'];

// The headline, and at most this many other marks a turn.
export const MARK_CAP = 5;

// At most this many faint scheme arrows a turn.
export const SCHEME_CAP = 8;

// What each kind of beat is drawn as, with its glyph and its one-word label.
// A glyph is a shape the page draws (never a colour alone); the label sits
// under it, so a mark is legible on a phone without its card.
const SEAT_KINDS = {
  founding: ['found', 'founded'],
  partition: ['found', 'founded'],
  succession_clean: ['succeed', 'succeeds'],
  succession_disorderly: ['succeed', 'disorder'],
  heir_wanted: ['succeed', 'no heir'],
  heir_of_age: ['succeed', 'heir of age'],
  elevation: ['elevate', 'elevated'],
  removed: ['fall', 'fails'],
  fallen: ['fall', 'falls'],
  failed: ['failed', 'fails'],
  endowment: ['dot', 'endows'],
  name_heir: ['succeed', 'heir named'],
};

const BOND_KINDS = { marriage: 'match', compact: 'compact', reconciled: 'peace', ally_joins: 'stands with' };
const STRIFE_KINDS = { quarrel: 'quarrel', dispute_won: 'dispute', ally_declines: 'declines' };
const TRANSFER_LABELS = {
  expansion: 'expands', riding_passes: 'changes hands', riding_lost: 'to the Crown',
};
// A scheme's label on the map, by its name in schemes.csv.
export const SCHEME_LABELS = {
  'Claim a riding': 'claim',
  'Counter-claim': 'counter-claim',
  Fortify: 'fortifies',
  'Open the frontier': 'frontier',
  'Buy out a neighbour': 'buy-out',
  'Break a rival': 'to break',
  'Dynastic match': 'courtship',
  'Win elevation': 'suit',
  'Seek a protector': 'protector',
  'Secure the line': 'the line',
  'Make peace': 'overture',
  'Sue for peace': 'sues for peace',
};

// Beats that are the world's, not any house's: told as chips or a banner.
const PLACELESS = ['event_continues', 'reckoning'];

// ------------------------------------------------------------- seats ----

// A house's seat at the end of `turn`, from the seat history: { house:
// [[turn, fed_id or null], ...] } in turn order, turn 0 the board before the
// first turn. Returns a Map house -> fed_id of every house with a seat.
export function seatsAt(history, turn) {
  const out = new Map();
  for (const [house, changes] of Object.entries(history || {})) {
    let seat = null;
    for (const [t, fed] of changes) {
      if (t > turn) break;
      seat = fed;
    }
    if (seat !== null && seat !== undefined) out.set(house, seat);
  }
  return out;
}

// A seat for a house that may have none, from a Board's owners: the riding it
// holds with the lowest fed_id. Only for a house the seat history does not
// know (a page told without one); never preferred to the history.
function ownedBy(owners, house) {
  let best = null;
  for (const [fed, owner] of Object.entries(owners || {})) {
    if (owner === house && (best === null || compareText(fed, best) < 0)) best = fed;
  }
  return best;
}

// --------------------------------------------------------------- marks ----

function uniq(list) {
  const out = [];
  for (const item of list) if (item !== null && item !== undefined && !out.includes(item)) out.push(item);
  return out;
}

// The scheme a beat belongs to, from the plans of this turn or the last (a
// scheme that ended this turn is only in the last).
function planOf(beat, plans, plansBefore) {
  if (beat.scheme === undefined || beat.scheme === null) return null;
  for (const list of [plans, plansBefore]) {
    const p = (list || []).find((x) => x.id === beat.scheme);
    if (p) return p;
  }
  return null;
}

function isClaim(beat, claimSchemes) {
  if (['contest_won', 'contest_lost'].includes(beat.kind) || beat.merge === 'claim') return true;
  if (beat.kind === 'scheme_begun' || beat.kind === 'scheme_answered' || beat.kind === 'scheme_abandoned') {
    return claimSchemes.includes(beat.outcome) || beat.outcome === 'Fortify';
  }
  return false;
}

// The parts a merged beat was made from, or the beat itself.
function partsOf(beat) {
  return beat.merge ? beat.parts : [beat];
}

function partOf(beat, kind) {
  return partsOf(beat).find((p) => p.kind === kind) || null;
}

export class MarkContext {
  // `seats` and `seatsBefore` are Maps house -> fed_id at the end of the turn
  // and before it; `plans`/`plansBefore` the public schemes then (or null);
  // `ridingIds` maps a riding's name to its fed_id; `standing` lists every
  // house still standing after the turn; `owners`/`ownersBefore` the board.
  constructor({
    seats = new Map(), seatsBefore = new Map(), plans = null, plansBefore = null,
    ridingIds = {}, standing = [], owners = {}, ownersBefore = {}, claimSchemes = [],
    cast = new Set(), follow = null,
  } = {}) {
    Object.assign(this, {
      seats, seatsBefore, plans, plansBefore, ridingIds, standing, owners, ownersBefore,
      claimSchemes, cast, follow,
    });
  }

  // A house's seat now, or, for a house gone this turn, the seat it had.
  seat(house) {
    if (house === undefined || house === null) return null;
    return this.seats.get(house) ?? this.seatsBefore.get(house)
      ?? ownedBy(this.owners, house) ?? ownedBy(this.ownersBefore, house);
  }

  riding(name) {
    if (!name) return null;
    return Object.prototype.hasOwnProperty.call(this.ridingIds, name) ? this.ridingIds[name] : null;
  }
}

// The mark for one told beat ({ beat, weight, text, alone }), or null for a
// beat with no place on the map.
export function markOf(entry, ctx, { headline = false } = {}) {
  const b = entry.beat;
  const houses = b.houses || [];
  const ridings = [...(b.ridings || [])];
  const mark = {
    type: null, kind: b.kind, glyph: null, label: null, headline, weight: entry.weight,
    text: entry.alone || entry.text, houses: [...houses], ridings, at: null, from: null, to: null,
    result: null, fall: null, camps: null, ground: [], groundKind: null,
    scheme: b.scheme ?? null,
  };
  const seatOf = (h) => ctx.seat(h);

  if (PLACELESS.includes(b.kind)) return null;

  if (b.kind === 'crisis' && b.world) {
    const lead = uniq((b.world.lead || []).map(seatOf));
    const resist = uniq((b.world.resist || []).map(seatOf));
    const sided = new Set([...(b.world.lead || []), ...(b.world.resist || [])]);
    const aside = uniq(ctx.standing.filter((h) => !sided.has(h)).map(seatOf));
    Object.assign(mark, {
      type: 'crisis', glyph: 'crisis', label: b.world.carried === 'lead' ? 'led' : b.world.carried === 'resist' ? 'resisted' : 'divided',
      camps: { lead, resist, aside, carried: b.world.carried || null },
      // Phase V2: each camp's houses, whose holdings the page tints by camp.
      campHouses: {
        lead: [...(b.world.lead || [])],
        resist: [...(b.world.resist || [])],
        aside: ctx.standing.filter((h) => !sided.has(h)),
      },
    });
    mark.ground = uniq([...lead, ...resist, ...aside]);
    mark.groundKind = 'table';
    return mark.ground.length ? mark : null;
  }

  if (b.kind === 'accession') {
    Object.assign(mark, { type: 'accession', glyph: 'open', label: 'opens', at: null });
    mark.ground = ridings;
    mark.groundKind = 'ridings';
    return ridings.length ? mark : null;
  }

  if (isClaim(b, ctx.claimSchemes)) {
    const contest = partOf(b, 'contest_won') || partOf(b, 'contest_lost') || (b.kind === 'fallen' ? b : null);
    const plan = planOf(b, ctx.plans, ctx.plansBefore);
    const scheme = plan ? plan.scheme : b.outcome;
    let claimant = houses[0];
    let defender = houses[1];
    if (scheme === 'Fortify' && plan) {
      // A defence: the threat runs from the claimant's seat to the defended riding.
      claimant = plan.target_house;
      defender = plan.house;
    }
    const target = ridings.find((fed) => ctx.owners[fed] === claimant)
      || (plan && ctx.riding(plan.riding)) || ridings[0] || null;
    let result = null;
    if (contest) result = contest.kind === 'contest_lost' ? 'held' : 'taken';
    const fallen = partOf(b, 'fallen');
    Object.assign(mark, {
      type: 'claim',
      glyph: result === 'taken' ? 'taken' : result === 'held' ? 'held' : 'claim',
      label: result === 'taken' ? 'taken' : result === 'held' ? 'held'
        : b.kind === 'scheme_abandoned' ? 'gives up' : SCHEME_LABELS[scheme] || 'claim',
      at: target, from: seatOf(claimant), to: target, result,
      fall: fallen ? ctx.seatsBefore.get(fallen.houses[0]) ?? null : null,
    });
    mark.ridings = uniq([target, ...ridings]);
    if (!target) {
      // A claim whose riding the record does not name: a line between the seats.
      mark.to = seatOf(defender);
      mark.at = mark.to;
    }
    mark.ground = target ? uniq([target, ...ridings]) : uniq([mark.from, mark.to]);
    mark.groundKind = ridings.length ? 'ridings' : target ? 'target' : 'seats';
    return mark.at || mark.from ? mark : null;
  }

  if (b.kind === 'scheme_begun' || b.kind === 'scheme_abandoned' || b.kind === 'scheme_answered') {
    const plan = planOf(b, ctx.plans, ctx.plansBefore);
    const from = seatOf(houses[0]);
    const to = (plan && ctx.riding(plan.riding)) || (plan && plan.target_house ? seatOf(plan.target_house) : null)
      || (houses[1] !== undefined ? seatOf(houses[1]) : null);
    if (plan && plan.scheme === 'Sue for peace') {
      Object.assign(mark, { type: 'bond', glyph: 'peace', label: 'sues for peace', from, to, at: from });
    } else {
      Object.assign(mark, {
        type: 'scheme', glyph: to ? 'scheme' : 'dot',
        label: b.kind === 'scheme_abandoned' ? 'gives up' : SCHEME_LABELS[plan ? plan.scheme : b.outcome] || 'scheme',
        from, to, at: to || from,
      });
    }
    if (plan && ctx.riding(plan.riding)) mark.ridings = [ctx.riding(plan.riding)];
    mark.ground = mark.ridings.length ? [...mark.ridings] : uniq([from, to]);
    mark.groundKind = mark.ridings.length ? 'target' : 'seats';
    return from || to ? mark : null;
  }

  const strife = STRIFE_KINDS[b.kind] || (b.merge === 'contest' ? 'contested' : null)
    || (b.kind === 'failed' && b.outcome === 'Dispute' ? 'dispute' : null);
  const bond = BOND_KINDS[b.kind];
  if ((strife || bond) && b.merge !== 'cession') {
    const [a, c] = b.kind === 'ally_joins' || b.kind === 'ally_declines' ? houses : (() => {
      const q = partOf(b, 'quarrel');
      return q ? q.houses : houses;
    })();
    Object.assign(mark, {
      type: strife ? 'strife' : 'bond', glyph: strife ? 'strife' : b.kind === 'marriage' ? 'match' : 'bond',
      label: strife || bond, from: seatOf(a), to: seatOf(c),
    });
    mark.at = ridings[0] || mark.from;
    mark.ground = ridings.length ? ridings : uniq([mark.from, mark.to]);
    mark.groundKind = ridings.length ? 'ridings' : 'seats';
    return mark.from || mark.to ? mark : null;
  }

  const seatKind = SEAT_KINDS[b.kind] || (b.merge === 'collapse' ? SEAT_KINDS.removed : null)
    || (b.merge === 'disorderly' ? SEAT_KINDS.succession_disorderly : null);
  if (seatKind && b.merge !== 'cession') {
    // A founding is at the new house's seat; a partition's at the cadet's.
    const subject = b.kind === 'partition' || b.merge === 'partition'
      ? (partOf(b, 'partition') || b).houses[1] : (partsOf(b)[0].houses || [])[0];
    const gone = ['removed', 'fallen'].includes(b.kind) || b.merge === 'collapse';
    const at = gone ? (ctx.seatsBefore.get(subject) ?? seatOf(subject)) : seatOf(subject);
    Object.assign(mark, { type: 'seat', glyph: seatKind[0], label: seatKind[1], at });
    mark.ground = ridings.length ? ridings : uniq(houses.map(seatOf));
    mark.groundKind = ridings.length ? 'ridings' : 'seats';
    if (!mark.ground.length && at) mark.ground = [at];
    return at ? mark : null;
  }

  // A riding changing hands, by any road: its fill moves, and the mark sits on it.
  if (ridings.length) {
    const label = b.merge === 'cession' ? 'ceded' : TRANSFER_LABELS[b.kind] || 'changes hands';
    Object.assign(mark, { type: 'transfer', glyph: b.kind === 'expansion' ? 'expand' : 'transfer', label, at: ridings[0] });
    mark.ground = ridings;
    mark.groundKind = 'ridings';
    return mark;
  }

  // Anything else a house did: a mark at its seat.
  const at = seatOf(houses[0]);
  if (!at) return null;
  Object.assign(mark, { type: 'seat', glyph: 'dot', label: b.kind.replace(/_/g, ' '), at });
  mark.ground = uniq(houses.map(seatOf));
  mark.groundKind = 'seats';
  return mark;
}

// The faint arrows of the schemes afoot: every public scheme of a cast or
// followed house that has a target, followed house first, then the order the
// schemes were begun; none already drawn as a mark this turn.
export function schemeArrows(ctx, drawn = new Set(), cap = SCHEME_CAP) {
  if (!ctx.plans) return [];
  const mine = (p) => (ctx.follow && p.house === ctx.follow ? 0 : 1);
  return ctx.plans
    .filter((p) => (ctx.cast.has(p.house) || (ctx.follow && p.house === ctx.follow)) && !drawn.has(p.id))
    .map((p) => ({
      p,
      from: ctx.seat(p.house),
      to: ctx.riding(p.riding) || (p.target_house ? ctx.seat(p.target_house) : null),
    }))
    .filter(({ from, to }) => from && to && from !== to)
    .sort((a, b) => mine(a.p) - mine(b.p) || a.p.id - b.p.id)
    .slice(0, cap)
    .map(({ p, from, to }) => ({
      id: p.id, house: p.house, scheme: p.scheme, from, to, target: p.target_house || null,
      riding: p.riding || null, turnsRemaining: p.turns_remaining,
    }));
}

// The chips a turn shows: each event still running, and a quiet year.
export function chipsFor(d, unit = 'year') {
  const chips = (d.running || []).map((r) => ({
    kind: 'event', text: `${r.event}, ${unit} ${r.year} of ${r.years}`,
  }));
  if (d.quiet) chips.push({ kind: 'quiet', text: `a quiet ${unit}` });
  return chips;
}

// One turn on the map. See the head of this file.
export function marksFor(d, ctx, { cap = MARK_CAP, unit = 'year' } = {}) {
  const out = {
    quiet: Boolean(d.quiet), marks: [], schemes: [], chips: chipsFor(d, unit), banner: null,
    more: 0, frame: [], frameKind: null,
  };
  if (d.quiet || !d.headline) return out;
  const head = markOf(d.headline, ctx, { headline: true });
  if (head) {
    out.marks.push(head);
    out.frame = [...head.ground];
    out.frameKind = head.groundKind;
  } else {
    out.banner = d.headline.text;
  }
  const rest = [...(d.related || []), ...(d.secondary || []), ...(d.others || [])]
    .sort((a, b) => b.weight - a.weight || a.beat.seq - b.beat.seq);
  let crisis = head && head.type === 'crisis';
  let shown = 0;
  for (const entry of rest) {
    const mark = markOf(entry, ctx);
    // One crisis's camps a turn: a second would mark every seat again.
    if (!mark || shown >= cap || (mark.type === 'crisis' && crisis)) {
      out.more += 1;
      continue;
    }
    if (mark.type === 'crisis') crisis = true;
    out.marks.push(mark);
    shown += 1;
  }
  out.marks.forEach((m, i) => { m.id = `m${i + 1}`; });
  // A headline with no place (a banner): the camera frames the turn's marks.
  if (!head && out.marks.length) {
    out.frame = uniq(out.marks.flatMap((m) => m.ground));
    out.frameKind = 'marks';
  }
  out.schemes = schemeArrows(ctx, new Set(out.marks.map((m) => m.scheme).filter((s) => s !== null)));
  return out;
}
