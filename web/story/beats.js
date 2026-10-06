// Beats: the typed happenings of one turn (docs/STORY_DESIGN.md §3.1).
//
// A beat is { turn, seq, kind, houses, ridings, outcome, line, owners, ranks,
// removed } — what happened, to whom, where, how it came out, and the chronicle
// line the engine wrote for it. `owners` (fed_id -> house, or null when a riding
// returns to the Crown), `ranks` (house -> rank index) and `removed` are what the
// beat did to the board, so standings can be folded from beats alone (§3.3).
//
// Beats are typed from the engine's *structured* record and never from its
// prose: an event's kind, its houses in the order the engine named them, its
// mechanical delta, the holdings it moved, and — where an event's delta cannot
// say which action produced it — the acting house's own action that season.
// Correspondence, a compact, a reconciliation and a marriage all write a bare
// relation marker, and a letter between kin writes the same marker a marriage
// does, so only the action tells them apart.
//
// Two sources feed the same typing:
//   * hoc/export/beats.py builds the turn input from hoc.db for exported and
//     archived games, types it with its own copy of these rules, and ships the
//     beats as data. tests/test_story.py runs typeTurn here over the same input
//     and requires the two to agree beat for beat.
//   * inputFromState builds the input from the JavaScript engine's in-memory
//     tables, for the play page. It reads the state by shape; nothing here
//     imports the engine, and the engine never imports this.
//
// Pure functions. No DOM, no engine, no dependencies.

// The rank ladder, low to high, with every form a peerage uses (hoc/rules.py
// RANK_LADDER). A rank index is a position on it; an unknown form reads as 0.
export const RANK_LADDER = [
  ['Baron', 'Baroness'],
  ['Viscount', 'Viscountess'],
  ['Earl', 'Countess'],
  ['Marquis', 'Marchioness'],
  ['Duke', 'Duchess'],
];

// Text order by UTF-16 code unit, which for every house name in this game is
// the order SQLite and Python sort in (docs/DETERMINISM.md, Ordering).
export function compareText(a, b) {
  if (a < b) return -1;
  return a > b ? 1 : 0;
}

export function rankIndex(rank) {
  for (let i = 0; i < RANK_LADDER.length; i += 1) {
    if (RANK_LADDER[i].includes(rank)) return i;
  }
  return 0;
}

// Every kind a beat can have. The first block is §3.1's table; the second is
// what the record holds that §3.1 does not name (see weights.json's notes).
export const BEAT_KINDS = [
  'removed', 'riding_passes', 'partition', 'elevation', 'succession_disorderly',
  'quarrel', 'marriage', 'dispute_won', 'reconciled', 'founding', 'succession_clean',
  'major_response', 'compact', 'expansion', 'failed', 'correspondence',
  'invest', 'cultivate', 'consolidate', 'name_heir',
  'riding_lost', 'endowment', 'era_response', 'other',
];

// The four bookkeeping actions. They never headline (§3.1: weight 0, and no
// modifier lifts a zero).
export const BOOKKEEPING = ['invest', 'cultivate', 'consolidate', 'name_heir'];

const GRIEVANCE = 'Sig−';

// Actions whose failure leaves no event behind: the house tried, nothing moved.
// Dispute, Challenge and Absorb record their failures as events and are typed
// there; a failed Correspond is typed below, unless its letter gave offence.
export const SILENT_FAILURES = [
  'Cede / swap', 'Expand', 'Marriage alliance', 'Petition elevation',
  'Propose compact', 'Purchase riding', 'Reconcile',
];

const BOOKKEEPING_ACTIONS = {
  Invest: 'invest',
  'Cultivate influence': 'cultivate',
  'Consolidate (rest)': 'consolidate',
};

function has(object, key) {
  return object !== null && object !== undefined
    && Object.prototype.hasOwnProperty.call(object, key);
}

// What one event is, as a beat kind and an outcome. `actionOf(house)` is the
// house's own action this turn, or null.
export function typeEvent(event, actionOf) {
  const d = event.delta || {};
  const houses = event.houses || [];
  switch (event.kind) {
    case 'founding':
      return d.nature === 'partition'
        ? { kind: 'partition', outcome: null }
        : { kind: 'founding', outcome: null };
    case 'succession':
      if (d.nature === 'extinction') return { kind: 'removed', outcome: d.reason ?? null };
      if (d.nature === 'disorderly') return { kind: 'succession_disorderly', outcome: d.cause ?? null };
      if (d.nature === 'clean') return { kind: 'succession_clean', outcome: d.cause ?? null };
      return { kind: 'other', outcome: null };
    case 'transfer':
      if (d.nature === 'absorption') return { kind: 'riding_passes', outcome: 'absorption' };
      if (houses.length >= 2) {
        return { kind: 'riding_passes', outcome: has(d, 'price') ? 'purchase' : (d.reason ?? null) };
      }
      return { kind: 'riding_lost', outcome: d.reason ?? null };
    case 'challenge':
      if (d.outcome === 'won') return { kind: 'riding_passes', outcome: 'challenge' };
      return { kind: 'failed', outcome: 'Challenge (11b)' };
    case 'elevation':
      return { kind: 'elevation', outcome: d.to ?? null };
    case 'expansion':
      return { kind: 'expansion', outcome: null };
    case 'societal':
      return d.magnitude === 'Major'
        ? { kind: 'major_response', outcome: d.response ?? null }
        : { kind: 'era_response', outcome: d.response ?? null };
    case 'relational': {
      if (d.outcome === 'won') return { kind: 'dispute_won', outcome: d.marker ?? null };
      if (d.outcome === 'lost') return { kind: 'failed', outcome: 'Dispute' };
      if (has(d, 'cause') && d.marker === GRIEVANCE) return { kind: 'quarrel', outcome: d.cause };
      if (has(d, 'ceded')) return { kind: 'reconciled', outcome: 'cession' };
      const action = houses.length ? actionOf(houses[0]) : null;
      switch (action) {
        case 'Correspond': return { kind: 'correspondence', outcome: d.marker ?? null };
        case 'Propose compact': return { kind: 'compact', outcome: null };
        case 'Reconcile': return { kind: 'reconciled', outcome: null };
        case 'Marriage alliance': return { kind: 'marriage', outcome: null };
        case 'Absorb': return { kind: 'failed', outcome: 'Absorb' };
        default: return { kind: 'other', outcome: null };
      }
    }
    case 'other': {
      const action = houses.length ? actionOf(houses[0]) : null;
      if (action === 'Name heir') return { kind: 'name_heir', outcome: d.role ?? null };
      if (action === 'Endow') return { kind: 'endowment', outcome: null };
      return { kind: 'other', outcome: null };
    }
    default:
      return { kind: 'other', outcome: null };
  }
}

// One turn's beats from its input:
//   { turn,
//     events:   [{ id, kind, houses, delta, line }]            in id order
//     actions:  [{ house, action, success }]                   in the order taken
//     holdings: [{ event, fed, house, change }]                'acquired' | 'released', in holding-id order
//     ranks:    { house: rank }                                each house founded this turn, at founding }
export function typeTurn(input) {
  const actions = new Map();
  for (const row of input.actions || []) actions.set(row.house, row.action);
  const actionOf = (house) => (actions.has(house) ? actions.get(house) : null);

  const moves = new Map();
  for (const row of input.holdings || []) {
    if (!moves.has(row.event)) moves.set(row.event, []);
    moves.get(row.event).push(row);
  }

  const beats = [];
  const offended = new Set();
  for (const event of input.events || []) {
    const { kind, outcome } = typeEvent(event, actionOf);
    const houses = [...(event.houses || [])];
    const d = event.delta || {};
    if (kind === 'quarrel' && d.cause === 'correspondence' && houses.length) offended.add(houses[0]);

    // Releases first, then acquisitions: a riding that changes hands within
    // one event ends with its new house.
    const owners = {};
    const rows = moves.get(event.id) || [];
    for (const row of rows) if (row.change === 'released') owners[row.fed] = null;
    for (const row of rows) if (row.change === 'acquired') owners[row.fed] = row.house;
    const ridings = Object.keys(owners).sort();

    const ranks = {};
    if (kind === 'founding' || kind === 'partition') {
      const founded = kind === 'founding' ? houses[0] : houses[1];
      if (founded !== undefined && has(input.ranks, founded)) {
        ranks[founded] = rankIndex(input.ranks[founded]);
      }
    }
    if (kind === 'elevation' && houses.length && has(d, 'to')) ranks[houses[0]] = rankIndex(d.to);

    const removed = [];
    if (kind === 'removed' && houses.length) removed.push(houses[0]);
    if (kind === 'riding_passes' && outcome === 'absorption' && houses.length > 1) removed.push(houses[1]);

    beats.push(makeBeat(input.turn, beats.length, {
      kind, houses, ridings, outcome, line: event.line ?? null, owners, ranks, removed,
    }));
  }

  for (const row of input.actions || []) {
    let kind = null;
    let outcome = row.success ? 'success' : 'failed';
    if (has(BOOKKEEPING_ACTIONS, row.action)) {
      kind = BOOKKEEPING_ACTIONS[row.action];
    } else if (!row.success && SILENT_FAILURES.includes(row.action)) {
      kind = 'failed';
      outcome = row.action;
    } else if (!row.success && row.action === 'Correspond' && !offended.has(row.house)) {
      kind = 'correspondence';
    }
    if (kind === null) continue;
    beats.push(makeBeat(input.turn, beats.length, {
      kind, houses: [row.house], ridings: [], outcome, line: null, owners: {}, ranks: {}, removed: [],
    }));
  }
  return beats;
}

// The canonical shape: empty fields are left out, so a beat shipped as JSON and
// a beat built in the browser compare equal.
function makeBeat(turn, seq, fields) {
  const beat = { turn, seq, kind: fields.kind, houses: fields.houses };
  if (fields.ridings.length) beat.ridings = fields.ridings;
  if (fields.outcome !== null && fields.outcome !== undefined) beat.outcome = fields.outcome;
  if (fields.line !== null && fields.line !== undefined) beat.line = fields.line;
  if (Object.keys(fields.owners).length) beat.owners = fields.owners;
  if (Object.keys(fields.ranks).length) beat.ranks = fields.ranks;
  if (fields.removed.length) beat.removed = fields.removed;
  return beat;
}

// One season's input from the JavaScript engine's in-memory tables (web/engine/
// state.js WorldState, read by shape). Only seasons played in this page carry
// full deltas: a state restored from a snapshot keeps just the season number on
// its old events, so call this right after the season is played.
export function inputFromState(state, season) {
  const events = state.events
    .filter((e) => e.mechanicalDelta && e.mechanicalDelta.season === season)
    .sort((a, b) => a.id - b.id);
  const ids = new Set(events.map((e) => e.id));
  const holdings = [];
  for (const h of [...state.holdings].sort((a, b) => a.id - b.id)) {
    if (ids.has(h.acquiredEventId)) holdings.push({ event: h.acquiredEventId, fed: h.fedId, house: h.house, change: 'acquired' });
    if (h.releasedEventId !== null && ids.has(h.releasedEventId)) {
      holdings.push({ event: h.releasedEventId, fed: h.fedId, house: h.house, change: 'released' });
    }
  }
  const ranks = {};
  for (const e of events) {
    if (e.kind !== 'founding') continue;
    const founded = e.mechanicalDelta.nature === 'partition' ? e.houses[1] : e.houses[0];
    const row = founded === undefined ? undefined : state.houses.get(founded);
    if (row && row.rank) ranks[founded] = row.rank;
  }
  return {
    turn: season,
    events: events.map((e) => ({
      id: e.id,
      kind: e.kind,
      houses: [...e.houses],
      delta: e.mechanicalDelta,
      line: e.narrative ?? e.title ?? null,
    })),
    actions: state.houseActions
      .filter((a) => a.seasonNo === season)
      .sort((a, b) => a.id - b.id)
      .map((a) => ({ house: a.house, action: a.action, success: a.success ? 1 : 0 })),
    holdings: holdings.sort((a, b) => a.event - b.event),
    ranks,
  };
}

// The board as the in-memory engine holds it now, in the shape standings.js
// folds beats onto (its baseline): who holds each riding, each house's rank,
// and who is gone.
export function baselineFromState(state) {
  const owners = {};
  for (const h of state.holdings) if (h.releasedEventId === null) owners[h.fedId] = h.house;
  const ranks = {};
  const removed = [];
  for (const [name, row] of state.houses) {
    ranks[name] = rankIndex(row.rank);
    if (row.status !== 'active') removed.push(name);
  }
  return { owners, ranks, removed };
}
