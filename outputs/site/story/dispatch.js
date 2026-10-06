// The dispatch (docs/STORY_DESIGN.md §3.2): one turn, told.
//
// A turn on screen is a headline (its heaviest beat, the map zoomed to where it
// happened), up to `secondary_max` secondary beats at or above the secondary
// threshold, and a ledger line counting the rest. A turn with nothing at or
// above the quiet threshold is one quiet-turn line instead. The full record —
// every line the engine wrote that turn — travels with it, one tap away.
//
// Phase B adds the storylines (§3.4, storylines.js). A headline that belongs to
// one carries a kicker naming it, how long it has run and which beat this is,
// and a "previously" line — that storyline's last beat before this turn. Beats
// of the same storyline that would have been secondaries are listed under the
// headline instead. And:
//   * one act is one beat (beats.js mergeActs) before anything is weighed;
//   * at most one era response (major_response or era_response) appears in a
//     dispatch, and one headlines only when nothing else reaches the quiet
//     threshold;
//   * a dispatch pauses Auto at the pause threshold, and also when a storyline
//     of a cast or followed house opens, reaches its climax or closes.
//
// `Story` steps through a game turn by turn: it keeps the board (standings.js),
// the weighting context (weight.js) and the storylines, and returns each turn's
// dispatch. Following a different house means replaying with a different
// `follow`, which changes weights and never the game.
//
// Pure: no DOM, no engine, no clock, no randomness.

import { BOOKKEEPING, mergeActs } from './beats.js';
import { createContext, weighTurn, advance, provinceOf } from './weight.js';
import { emptyBoard, copyBoard, applyBeats, table, movement } from './standings.js';
import { Storylines, storylineName } from './storylines.js';
import { Namer, sentence } from './text.js';

const SMALL = [
  'no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
  'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen',
  'eighteen', 'nineteen', 'twenty',
];
const TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety'];
const ORDINALS = ['zeroth', 'first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh',
  'eighth', 'ninth', 'tenth', 'eleventh', 'twelfth'];

export function numberWord(n) {
  if (n <= 20) return SMALL[n];
  if (n < 100) return TENS[Math.floor(n / 10)] + (n % 10 ? `-${SMALL[n % 10]}` : '');
  return String(n);
}

export function ordinal(n) {
  if (n < ORDINALS.length) return ORDINALS[n];
  const tail = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
  return `${n}${tail}`;
}

export const ERA_KINDS = ['major_response', 'era_response'];

function actors(beats) {
  const houses = new Set();
  for (const beat of beats) if (beat.houses && beat.houses.length) houses.add(beat.houses[0]);
  return houses.size;
}

function estates(n) {
  return n === 1 ? 'one house tended its estates' : `${numberWord(n)} houses tended their estates`;
}

// The storyline a beat is best told as part of: the longest it belongs to.
function mainStoryline(roles, lines) {
  let best = null;
  for (const { id } of roles || []) {
    const s = lines.of(id);
    if (s && (best === null || s.beats.length > best.beats.length)) best = s;
  }
  return best;
}

// Choose a turn's headline, its storyline's other beats, the secondaries and
// the rest from its weighed beats. `roles[i]` are beat i's storyline roles.
export function select(beats, weighed, weights, roles = []) {
  const t = weights.thresholds;
  const order = beats
    .map((beat, i) => ({ beat, index: i, weight: weighed[i].total, mods: weighed[i].mods, roles: roles[i] || [] }))
    .sort((a, b) => b.weight - a.weight || a.beat.seq - b.beat.seq);
  const era = (entry) => ERA_KINDS.includes(entry.beat.kind);
  const headline = order.find((e) => e.weight >= t.quiet && !era(e))
    || order.find((e) => e.weight >= t.quiet);
  if (!headline) return { quiet: true, headline: null, related: [], secondary: [], rest: order };
  const ids = new Set(headline.roles.map((r) => r.id));
  const related = order.filter((e) => e !== headline && e.weight >= t.secondary
    && e.roles.some((r) => ids.has(r.id)));
  let eraShown = era(headline);
  const secondary = [];
  for (const e of order) {
    if (secondary.length >= weights.secondary_max) break;
    if (e === headline || related.includes(e) || e.weight < t.secondary) continue;
    if (era(e)) {
      if (eraShown) continue;
      eraShown = true;
    }
    secondary.push(e);
  }
  const shown = new Set([headline, ...related, ...secondary]);
  return { quiet: false, headline, related, secondary, rest: order.filter((e) => !shown.has(e)) };
}

function provinceTotals(ridings) {
  const totals = {};
  for (const fed of Object.keys(ridings || {})) {
    const p = provinceOf(fed);
    totals[p] = (totals[p] || 0) + 1;
  }
  return totals;
}

export class Story {
  // `baseline` is the board before the first turn (standings.js); for an
  // engine-played game it is empty. `unit` names a turn: 'season' or 'turn'.
  // `seen` lists kinds whose firsts are already spent (weight.js createContext).
  // `styleOf(house)` gives a house's naming record (text.js houseStyle) and
  // `ridings` maps every fed_id to its riding's name.
  constructor({
    weights, baseline = emptyBoard(), follow = null, unit = 'season', seen = [],
    styleOf = () => null, ridings = {},
  }) {
    this.weights = weights;
    this.follow = follow;
    this.unit = unit;
    this.styleOf = styleOf;
    this.ridings = ridings;
    this.board = copyBoard(baseline);
    this.context = createContext(this.board.owners, seen);
    this.standings = table(this.board, weights);
    this.turn = 0;
    this.lines = new Storylines({
      weights,
      provinceTotals: provinceTotals(ridings),
      held: Object.keys(this.board.owners).map(provinceOf),
    });
  }

  ridingName(fed) {
    return this.ridings[fed] || fed;
  }

  namer(ranks = this.board.ranks) {
    return new Namer(this.styleOf, (house) => ranks[house] || 0);
  }

  placeOf(house) {
    const s = this.styleOf(house);
    return s ? s.designation : house;
  }

  name(storyline) {
    return storylineName(storyline, (house) => this.placeOf(house));
  }

  // Replace the board, keeping what the story remembers: for a change the
  // story did not see as beats, such as a director's intervention.
  rebase(board) {
    this.board = copyBoard(board);
    this.standings = table(this.board, this.weights);
  }

  // The standings strip before any turn has been told: no movement yet.
  still() {
    return this.standings.slice(0, this.weights.cast_size)
      .map((row) => ({ ...row, move: 'same', was: row.place }));
  }

  cast() {
    return new Set(this.standings.slice(0, this.weights.cast_size).map((row) => row.house));
  }

  step(turn, rawBeats) {
    const w = this.weights;
    const beats = mergeActs(rawBeats);
    const before = this.standings;
    const boardBefore = this.board;
    const cast = this.cast();
    const boardAfter = applyBeats(boardBefore, beats);
    const after = table(boardAfter, w);
    const { roles, changes } = this.lines.step(turn, beats, {
      cast, boardBefore, boardAfter, tableBefore: before, tableAfter: after,
    });
    const weighed = weighTurn(beats, this.context, { weights: w, cast, follow: this.follow, roles });
    const chosen = select(beats, weighed, w, roles);

    // What each storyline beat weighed, for the Afoot panel's ranking, and the
    // ranks it was told with.
    for (const s of this.lines.all) {
      for (const entry of s.beats) {
        if (entry.turn !== turn || entry.weight !== undefined) continue;
        entry.weight = weighed[entry.index].total;
        entry.ranks = boardAfter.ranks;
      }
    }

    this.context = advance(this.context, beats, chosen.quiet ? null : chosen.headline.beat.kind, w);
    this.board = boardAfter;
    this.standings = after;
    this.turn = turn;

    const namer = this.namer(boardAfter.ranks);
    const told = (entry) => ({
      beat: entry.beat, weight: entry.weight, mods: entry.mods,
      text: sentence(entry.beat, namer, (fed) => this.ridingName(fed)),
    });

    let headline = null;
    let kicker = null;
    let previously = null;
    let related = [];
    if (!chosen.quiet) {
      headline = told(chosen.headline);
      const s = mainStoryline(chosen.headline.roles, this.lines);
      if (s) {
        const at = s.beats.findIndex((e) => e.turn === turn && e.index === chosen.headline.index);
        const runs = turn - s.opened;
        kicker = {
          id: s.id,
          type: s.type,
          name: this.name(s),
          beat: at + 1,
          runs,
          text: `${this.name(s)} · the ${ordinal(at + 1)} beat · `
            + (runs === 0 ? `opens this ${this.unit}` : `${numberWord(runs)} ${this.unit}${runs === 1 ? '' : 's'} running`),
        };
        related = chosen.related.map(told);
        const prior = s.beats.filter((e) => e.turn < turn);
        if (prior.length) {
          const last = prior[prior.length - 1];
          previously = { turn: last.turn, text: sentence(last.beat, namer, (fed) => this.ridingName(fed)) };
        }
      }
    }
    const secondary = chosen.secondary.map(told);

    const notable = chosen.rest.filter((entry) => entry.weight >= w.thresholds.secondary).length;
    let ledger = null;
    let quietLine = null;
    if (chosen.quiet) {
      const n = actors(beats);
      quietLine = n
        ? `A quiet ${this.unit}: ${estates(n)}.`
        : `A quiet ${this.unit}: nothing of note passed.`;
    } else if (chosen.rest.length) {
      ledger = `Elsewhere, ${estates(actors(chosen.rest.map((entry) => entry.beat)))}`
        + (notable ? `; ${numberWord(notable)} more ${notable === 1 ? 'matter is' : 'matters are'} in the full record.` : '.');
    }

    // Storyline moments worth stopping for: a cast or followed storyline that
    // opened, reached its climax or closed.
    const watched = new Set([...cast, ...this.cast()]);
    if (this.follow) watched.add(this.follow);
    const moments = changes
      .map(({ id, change }) => ({ storyline: this.lines.of(id), change }))
      .filter(({ storyline }) => storyline.houses.some((h) => watched.has(h)))
      .map(({ storyline, change }) => ({ id: storyline.id, name: this.name(storyline), change }));
    const heavy = !chosen.quiet && chosen.headline.weight >= w.thresholds.pause;

    return {
      turn,
      quiet: chosen.quiet,
      headline,
      kicker,
      previously,
      related,
      secondary,
      ledger,
      quietLine,
      pause: heavy || moments.length > 0,
      heavy,
      moments,
      zoom: chosen.quiet ? [] : [...(chosen.headline.beat.ridings || [])],
      standings: movement(before, this.standings, w),
      record: rawBeats.filter((beat) => beat.line)
        .map((beat) => sentence(beat, this.namer(boardAfter.ranks), (fed) => this.ridingName(fed))),
      headlineOpens: !chosen.quiet && chosen.headline.roles.some((r) => r.role === 'open')
        && !chosen.headline.roles.some((r) => r.role !== 'open'),
      inStoryline: !chosen.quiet && chosen.headline.roles.length > 0,
    };
  }

  // Open storylines worth showing (§3.4's Afoot panel): followed houses
  // first, then the cast's, then by weight over the last `afoot_window` turns.
  afoot() {
    const cfg = this.weights.storylines;
    const cast = this.cast();
    const rank = (s) => {
      if (this.follow && s.houses.includes(this.follow)) return 0;
      return s.houses.some((h) => cast.has(h)) ? 1 : 2;
    };
    const recent = (s) => s.beats
      .filter((e) => this.turn - e.turn < cfg.afoot_window)
      .reduce((sum, e) => sum + (e.weight || 0), 0);
    return this.lines.open
      .map((s) => ({ s, rank: rank(s), score: recent(s) }))
      .sort((a, b) => a.rank - b.rank || b.score - a.score || b.s.opened - a.s.opened
        || (a.s.id < b.s.id ? -1 : 1))
      .slice(0, cfg.afoot_max)
      .map(({ s, score }) => this.summary(s, score));
  }

  summary(s, score = null) {
    return {
      id: s.id, type: s.type, name: this.name(s), houses: [...s.houses], opened: s.opened,
      closed: s.closed, state: s.state, outcome: s.outcome, beats: s.beats.length, score,
    };
  }

  // A storyline told top to bottom: each beat with its turn, the houses named
  // by the dispatch rule within the storyline (full style first, then place).
  tell(id) {
    const s = this.lines.of(id);
    if (!s) return null;
    const namer = this.namer();
    return {
      ...this.summary(s),
      beats: s.beats.map((e) => ({
        turn: e.turn,
        weight: e.weight === undefined ? null : e.weight,
        text: sentence(e.beat, Object.assign(namer, { rankOf: (h) => (e.ranks || this.board.ranks)[h] || 0 }),
          (fed) => this.ridingName(fed)),
      })),
    };
  }
}

// Every dispatch of a game: `turns` is [[turn, beats], ...] in order. Returns
// the dispatches; `options.story`, if given, receives the Story.
export function replay(turns, options) {
  const story = new Story(options);
  const out = turns.map(([turn, beats]) => story.step(turn, beats));
  if (options.onStory) options.onStory(story);
  return out;
}

// What a run of dispatches headlined, for tuning weights.json: headline count
// by kind, the largest kind's share in per mille, the quiet turns, and whether
// any bookkeeping kind ever headlined.
export function summarise(dispatches) {
  const byKind = {};
  let headlines = 0;
  let quiet = 0;
  let paused = 0;
  for (const d of dispatches) {
    if (d.quiet) { quiet += 1; continue; }
    headlines += 1;
    if (d.pause) paused += 1;
    byKind[d.headline.beat.kind] = (byKind[d.headline.beat.kind] || 0) + 1;
  }
  const top = Object.values(byKind).reduce((a, b) => Math.max(a, b), 0);
  return {
    turns: dispatches.length,
    headlines,
    quiet,
    paused,
    byKind,
    largestSharePerMille: headlines ? Math.floor((1000 * top) / headlines) : 0,
    bookkeepingHeadlines: BOOKKEEPING.reduce((sum, kind) => sum + (byKind[kind] || 0), 0),
  };
}

// The Phase B gates (docs/STORY_DESIGN.md §7) over a replayed game: headlines
// after `from` that belong to a storyline and that open one (per mille),
// storylines with at least five beats, closed ones without an outcome, and the
// lapsed share of closed storylines (per mille).
export function summariseStorylines(story, dispatches, from = 20) {
  const later = dispatches.filter((d) => d.turn > from && !d.quiet);
  const inStory = later.filter((d) => d.inStoryline).length;
  const opening = later.filter((d) => d.headlineOpens).length;
  const all = story.lines.all;
  const closed = all.filter((s) => s.state === 'closed');
  const lapsed = closed.filter((s) => s.outcome === 'lapsed').length;
  const byType = {};
  const byOutcome = {};
  for (const s of all) {
    byType[s.type] = (byType[s.type] || 0) + 1;
    const key = s.state === 'closed' ? `${s.type}: ${s.outcome.endsWith(' removed') ? 'a house removed' : s.outcome}` : `${s.type}: open`;
    byOutcome[key] = (byOutcome[key] || 0) + 1;
  }
  const longest = [...all]
    .sort((a, b) => b.beats.length - a.beats.length || (a.id < b.id ? -1 : 1))
    .slice(0, 5)
    .map((s) => ({ name: story.name(s), beats: s.beats.length, opened: s.opened, closed: s.closed, outcome: s.outcome }));
  return {
    headlinesAfter: later.length,
    inStorylinePerMille: later.length ? Math.floor((1000 * inStory) / later.length) : 0,
    openingPerMille: later.length ? Math.floor((1000 * opening) / later.length) : 0,
    storylines: all.length,
    fivePlus: all.filter((s) => s.beats.length >= 5).length,
    closed: closed.length,
    closedWithoutOutcome: closed.filter((s) => !s.outcome).length,
    lapsedPerMille: closed.length ? Math.floor((1000 * lapsed) / closed.length) : 0,
    byType,
    byOutcome,
    longest,
  };
}
