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
  // Rules 1.0: the succession watch's two events, and a house with nothing to do.
  'heir_wanted', 'heir_of_age', 'bide',
  // Rules 1.0 (Phase C2): schemes, the allies a contest calls, contests, and a
  // house that falls to the house that took its seat.
  'scheme_begun', 'scheme_step', 'scheme_answered', 'scheme_abandoned', 'scheme_resolved',
  'ally_joins', 'ally_declines', 'contest_won', 'contest_lost', 'fallen',
  // Rules 1.0 (Phase D1): a crisis, land opened, a year of an event still
  // running, and the reckoning after the last turn.
  'crisis', 'accession', 'event_continues', 'reckoning',
];

// Rules 1.0 `world_calendar`: the world's own events, by their delta's `world`.
const WORLD_KINDS = {
  accession: 'accession', extension: 'accession', continues: 'event_continues', reckoning: 'reckoning',
};

// A scheme event's phase, as its beat kind (Phase C2).
const SCHEME_PHASES = {
  begun: 'scheme_begun',
  step: 'scheme_step',
  answered: 'scheme_answered',
  abandoned: 'scheme_abandoned',
  resolved: 'scheme_resolved',
};

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
  // Rules 1.0 `upkeep_phase`: a house with no legal action bides.
  Bide: 'bide',
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
      // Rules 1.0 `contested_claims`: a house left with no riding falls, and
      // the record names the house that took its seat.
      if (d.nature === 'extinction' && has(d, 'taken_by')) return { kind: 'fallen', outcome: d.taken_by };
      if (d.nature === 'extinction') return { kind: 'removed', outcome: d.reason ?? null };
      if (d.nature === 'disorderly') return { kind: 'succession_disorderly', outcome: d.cause ?? null };
      if (d.nature === 'clean') return { kind: 'succession_clean', outcome: d.cause ?? null };
      return { kind: 'other', outcome: null };
    case 'transfer':
      if (d.nature === 'absorption') return { kind: 'riding_passes', outcome: 'absorption' };
      if (houses.length >= 2) {
        // Rules 1.0 `schemes`: the weaker side's answer to a standing claim.
        if (has(d, 'under_claim')) return { kind: 'riding_passes', outcome: 'cession under claim' };
        return { kind: 'riding_passes', outcome: has(d, 'price') ? 'purchase' : (d.reason ?? null) };
      }
      return { kind: 'riding_lost', outcome: d.reason ?? null };
    case 'challenge':
      // Rules 1.0 `contested_claims`: a claim decided, or a rout that follows.
      if (has(d, 'contest')) {
        return d.contest === 'held'
          ? { kind: 'contest_lost', outcome: 'held' }
          : { kind: 'contest_won', outcome: d.contest };
      }
      if (d.outcome === 'won') return { kind: 'riding_passes', outcome: 'challenge' };
      return { kind: 'failed', outcome: 'Challenge (11b)' };
    case 'elevation':
      return { kind: 'elevation', outcome: d.to ?? null };
    case 'expansion':
      return { kind: 'expansion', outcome: null };
    case 'societal':
      // Rules 1.0 `crises`: one event for the whole crisis, both camps in it.
      if (d.crisis && typeof d.crisis === 'object') return { kind: 'crisis', outcome: d.crisis.carried ?? null };
      return d.magnitude === 'Major'
        ? { kind: 'major_response', outcome: d.response ?? null }
        : { kind: 'era_response', outcome: d.response ?? null };
    case 'relational': {
      if (d.outcome === 'won') return { kind: 'dispute_won', outcome: d.marker ?? null };
      if (d.outcome === 'lost') return { kind: 'failed', outcome: 'Dispute' };
      if (has(d, 'cause') && d.marker === GRIEVANCE) return { kind: 'quarrel', outcome: d.cause };
      if (has(d, 'ceded')) return { kind: 'reconciled', outcome: 'cession' };
      // Rules 1.0 `schemes`: the stronger side buys peace from a claimant.
      if (has(d, 'peace')) return { kind: 'reconciled', outcome: 'peace' };
      // Rules 1.0 `upkeep_phase`: an automatic letter says so in its delta.
      if (d.letter) return { kind: 'correspondence', outcome: d.marker ?? null };
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
      if (has(WORLD_KINDS, d.world)) return { kind: WORLD_KINDS[d.world], outcome: d.event ?? d.world };
      // Rules 1.0 `schemes` and `contested_claims`.
      if (d.scheme && typeof d.scheme === 'object' && has(SCHEME_PHASES, d.scheme.phase)) {
        return { kind: SCHEME_PHASES[d.scheme.phase], outcome: d.scheme.name ?? null };
      }
      if (d.ally && typeof d.ally === 'object') {
        return { kind: d.ally.joins ? 'ally_joins' : 'ally_declines', outcome: d.ally.side ?? null };
      }
      // Rules 1.0 `succession_watch`.
      if (d.watch === 'no_heir') return { kind: 'heir_wanted', outcome: null };
      if (d.watch === 'heir_of_age') return { kind: 'heir_of_age', outcome: null };
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
    if ((kind === 'removed' || kind === 'fallen') && houses.length) removed.push(houses[0]);

    // Rules 1.0 `schemes`: the scheme an event belongs to, and how long it ran.
    let scheme = null;
    let ran = null;
    if (d.scheme && typeof d.scheme === 'object') {
      scheme = d.scheme.id ?? null;
      if (kind === 'scheme_resolved') ran = d.scheme.ran ?? null;
    } else if (Number.isInteger(d.scheme)) {
      scheme = d.scheme;
    } else if (d.ally && typeof d.ally === 'object') {
      // Phase D1: an ally answers the call of one contest, told with it.
      scheme = d.ally.scheme ?? null;
    }
    if (kind === 'riding_passes' && outcome === 'absorption' && houses.length > 1) removed.push(houses[1]);
    const world = worldFacts(kind, d);
    // The land an accession opens, for the map to show.
    const shown = kind === 'accession' ? [...(d.fed_ids || [])].sort() : ridings;

    beats.push(makeBeat(input.turn, beats.length, {
      kind, houses, ridings: shown, outcome, line: event.line ?? null, owners, ranks, removed, scheme, ran, world,
      part: d.part ?? null,
    }));
  }

  // Rules 1.0 `round_record`: an action is written in its house's own turn, so
  // where the turn's playing order is known an action beat is that house's
  // part of the round.
  const roundKnown = input.order !== undefined && input.order !== null;
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
      part: roundKnown ? row.house : null,
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
  if (fields.scheme !== null && fields.scheme !== undefined) beat.scheme = fields.scheme;
  if (fields.ran !== null && fields.ran !== undefined) beat.ran = fields.ran;
  if (fields.world !== null && fields.world !== undefined) beat.world = fields.world;
  if (fields.part !== null && fields.part !== undefined) beat.part = fields.part;
  return beat;
}

// Rules 1.0 `world_calendar` and `crises`: what a world beat carries for its
// sentence and the pages (hoc/export/beats.py _world_facts).
function worldFacts(kind, d) {
  if (kind === 'crisis') {
    const c = d.crisis;
    const facts = { event: d.event ?? null, lead: c.lead, resist: c.resist, carried: c.carried };
    if (has(d, 'years')) facts.years = d.years;
    return facts;
  }
  if (kind === 'event_continues') return { event: d.event, year_of: d.year_of, years: d.years };
  if (kind === 'accession') return { jurisdiction: d.jurisdiction, status: d.status, change: d.world };
  return null;
}

// One season's input from the JavaScript engine's in-memory tables (web/engine/
// state.js WorldState, read by shape). Only seasons played in this page carry
// full deltas: a state restored from a snapshot keeps just the season number on
// its old events, so call this right after the season is played. `order` is
// the season record's (rules 1.0 `round_record`), where the page has it.
export function inputFromState(state, season, order = null) {
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
  const input = {
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
  if (order !== null) input.order = [...order];
  return input;
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

// ------------------------------------------------------------ one act ----
//
// The engine sometimes writes two or three events for what is one act. The
// story layer tells each act once: mergeActs folds such a group into a single
// beat that carries every part's facts — houses, ridings, board changes — with
// `merge` naming the act, `parts` the beats it was made from, and the kind of
// its principal part. The groups, all within one turn:
//
//   cession     a riding passing by cession, and the grievance it settles
//               (riding_passes 'cession' + reconciled 'cession', same houses)
//   partition   a cadet founded by partition, and the clean succession of the
//               parent that caused it (partition + succession_clean of the parent)
//   disorderly  a disorderly succession, the riding it loses to the Crown and
//               the neighbour it falls out with (succession_disorderly +
//               riding_lost 'disorderly succession' + quarrel 'disorderly succession')
//   collapse    a succession, and the removal of the same house it brings on
//               (succession_* or one of the above + removed)
//   contest     a contested expansion: the grievance, and either the winner's
//               expansion or the loser's failed Expand
//   claim       (rules 1.0) a claim decided: the contest, the rout that may
//               follow it, and the fall of a house left with no riding. The
//               allies each side called (ally_joins, ally_declines, the same
//               scheme) are carried as `allies` [{ house, party, joins }] rather
//               than as parts, so they are told in one sentence and take no
//               part in the contest's storylines (Phase D1)
//
// And before any of these, a scheme's resolution (scheme_resolved, which is
// ledger-only) folds into the act that resolved it — the beat carrying the same
// scheme id, else the nearest act of the scheme's house that turn — which then
// carries `ran` (how many turns the scheme ran) and `plan` (its name).
//
// Everything else passes through unchanged and in order.

function mergeGroup(merge, kind, parts) {
  const houses = [];
  const ridings = new Set();
  const owners = {};
  const ranks = {};
  const removed = [];
  for (const p of parts) {
    for (const h of p.houses || []) if (!houses.includes(h)) houses.push(h);
    for (const r of p.ridings || []) ridings.add(r);
    Object.assign(owners, p.owners || {});
    Object.assign(ranks, p.ranks || {});
    for (const h of p.removed || []) if (!removed.includes(h)) removed.push(h);
  }
  const principal = parts.find((p) => p.kind === kind) || parts[0];
  const beat = { turn: parts[0].turn, seq: parts[0].seq, kind, houses, merge, parts };
  // One act is played in one turn of the round (rules 1.0 `round_record`).
  if (principal.part !== undefined) beat.part = principal.part;
  for (const key of ['scheme', 'ran', 'plan']) {
    const carrier = parts.find((p) => p[key] !== undefined);
    if (carrier) beat[key] = carrier[key];
  }
  if (ridings.size) beat.ridings = [...ridings].sort(compareText);
  if (principal.outcome !== undefined) beat.outcome = principal.outcome;
  if (Object.keys(owners).length) beat.owners = owners;
  if (Object.keys(ranks).length) beat.ranks = ranks;
  if (removed.length) beat.removed = removed;
  return beat;
}

const SUCCESSIONS = ['succession_clean', 'succession_disorderly'];

// The acts a scheme can end in (Phase C2): what its resolution folds into.
const RESOLVING = [
  'expansion', 'contest_won', 'contest_lost', 'fallen', 'riding_passes', 'reconciled',
  'dispute_won', 'failed', 'marriage', 'compact', 'elevation', 'name_heir',
];

function foldResolutions(beats) {
  const attached = new Map();
  const dropped = new Set();
  beats.forEach((b, i) => {
    if (b.kind !== 'scheme_resolved') return;
    const free = (k) => !attached.has(k) && !dropped.has(k) && RESOLVING.includes(beats[k].kind);
    let j = -1;
    if (b.scheme !== undefined) {
      j = beats.findIndex((x, k) => k !== i && x.scheme === b.scheme && free(k));
    }
    const house = (b.houses || [])[0];
    for (let k = i - 1; j === -1 && k >= 0; k -= 1) {
      if (free(k) && (beats[k].houses || [])[0] === house) j = k;
    }
    for (let k = i + 1; j === -1 && k < beats.length; k += 1) {
      if (free(k) && (beats[k].houses || [])[0] === house) j = k;
    }
    if (j === -1) return;
    attached.set(j, { ran: b.ran, plan: b.outcome });
    dropped.add(i);
  });
  if (!dropped.size) return beats;
  return beats
    .map((b, i) => (attached.has(i) ? { ...b, ...attached.get(i) } : b))
    .filter((_, i) => !dropped.has(i));
}

const ALLY_KINDS = ['ally_joins', 'ally_declines'];
const DECIDED = ['contest_won', 'contest_lost'];

export function mergeActs(input) {
  const beats = foldResolutions(input);
  const used = new Set();
  const out = [];
  // The allies called to each contest decided this turn, by scheme.
  const alliesOf = new Map();
  const decided = new Set(beats.filter((b) => DECIDED.includes(b.kind) && b.outcome !== 'rout'
    && b.scheme !== undefined).map((b) => b.scheme));
  beats.forEach((b, i) => {
    if (!ALLY_KINDS.includes(b.kind) || b.scheme === undefined || !decided.has(b.scheme)) return;
    if (!alliesOf.has(b.scheme)) alliesOf.set(b.scheme, []);
    alliesOf.get(b.scheme).push({ house: b.houses[0], party: b.houses[1], joins: b.kind === 'ally_joins' });
    used.add(i);
  });
  const after = (i, test) => {
    for (let j = i + 1; j < beats.length; j += 1) {
      if (!used.has(j) && test(beats[j])) return j;
    }
    return -1;
  };
  for (let i = 0; i < beats.length; i += 1) {
    if (used.has(i)) continue;
    const b = beats[i];
    let merged = null;
    const [first, second] = b.houses || [];
    if (b.kind === 'riding_passes' && b.outcome === 'cession') {
      const j = after(i, (x) => x.kind === 'reconciled' && x.outcome === 'cession'
        && x.houses[0] === first && x.houses[1] === second);
      if (j !== -1) { used.add(j); merged = mergeGroup('cession', 'riding_passes', [b, beats[j]]); }
    } else if (b.kind === 'partition') {
      const j = after(i, (x) => x.kind === 'succession_clean' && x.houses[0] === first);
      if (j !== -1) { used.add(j); merged = mergeGroup('partition', 'partition', [b, beats[j]]); }
    } else if (b.kind === 'succession_disorderly') {
      const parts = [b];
      for (const [kind, outcome] of [['riding_lost', 'disorderly succession'], ['quarrel', 'disorderly succession']]) {
        const j = after(i, (x) => x.kind === kind && x.outcome === outcome && x.houses[0] === first);
        if (j !== -1) { used.add(j); parts.push(beats[j]); }
      }
      if (parts.length > 1) merged = mergeGroup('disorderly', 'succession_disorderly', parts);
    } else if ((b.kind === 'contest_won' || b.kind === 'contest_lost') && b.outcome !== 'rout') {
      const parts = [b];
      const rout = after(i, (x) => x.kind === 'contest_won' && x.outcome === 'rout' && x.scheme === b.scheme);
      if (rout !== -1) { used.add(rout); parts.push(beats[rout]); }
      const fall = after(i, (x) => x.kind === 'fallen' && x.houses[0] === second && x.houses[1] === first);
      if (fall !== -1) { used.add(fall); parts.push(beats[fall]); }
      const allies = b.scheme !== undefined ? alliesOf.get(b.scheme) : undefined;
      if (parts.length > 1 || allies) {
        merged = mergeGroup('claim', fall !== -1 ? 'fallen' : b.kind, parts);
        if (allies) merged.allies = allies;
      }
    } else if (b.kind === 'quarrel' && b.outcome === 'contested expansion') {
      let j = i + 1 < beats.length && !used.has(i + 1) && beats[i + 1].kind === 'expansion'
        && beats[i + 1].houses[0] === second ? i + 1 : -1;
      if (j === -1) j = after(i, (x) => x.kind === 'failed' && x.outcome === 'Expand' && x.houses[0] === first);
      if (j !== -1) { used.add(j); merged = mergeGroup('contest', 'quarrel', [b, beats[j]]); }
    }
    let current = merged || b;
    const house = (current.merge ? current.parts[0] : current).houses[0];
    if (SUCCESSIONS.includes(current.kind) || current.merge === 'partition' || current.merge === 'disorderly') {
      const j = after(i, (x) => x.kind === 'removed' && x.houses[0] === house);
      if (j !== -1) { used.add(j); current = mergeGroup('collapse', 'removed', [current, beats[j]]); }
    }
    out.push(current);
  }
  return out;
}
