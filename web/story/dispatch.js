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
//   * a dispatch pauses Auto (Phase C1) only when a storyline of at least
//     `storylines.pause_closing_beats` beats involving a cast or followed house
//     closes, a house is removed, a riding passes between two cast houses, or
//     the followed house is in a headline at or above the pause threshold.
//     Storyline openings, climaxes and rises and declines are shown, not paused on.
//
// Phase C2 adds schemes. A headline that resolves one says how many turns it
// ran; a claim decided between two houses of the cast pauses Auto as a riding
// passing between them does; and, for a game whose record carries schemes,
// `plansAfoot` lists every public scheme of a cast or followed house.
//
// `Story` steps through a game turn by turn: it keeps the board (standings.js),
// the weighting context (weight.js) and the storylines, and returns each turn's
// dispatch. Following a different house means replaying with a different
// `follow`, which changes weights and never the game.
//
// Phase D1 adds the world calendar. For a game played with one (`calendar`,
// from game.json by way of the beat index), a turn is a year: the dispatch
// carries its `year`, and kickers, plans and quiet lines count years. A crisis
// is one beat naming both camps, the cast first. At the end of each chapter the
// dispatch carries an interstitial (`chapter`) — its title and years, the
// standings with their movement over the chapter, the storylines it closed and
// those left open — and Auto always pauses there; after the last turn it
// carries the reckoning (reckoning.js) and pauses there too.
//
// Pure: no DOM, no engine, no clock, no randomness.

import { BOOKKEEPING, compareText, mergeActs } from './beats.js';
import { reckoningView } from './reckoning.js';
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

// The storyline a beat is best told as part of: the longest it belongs to,
// other than a frontier — a frontier names a headline only when the headline
// belongs to nothing else.
function mainStoryline(roles, lines) {
  let best = null;
  let frontier = null;
  for (const { id } of roles || []) {
    const s = lines.of(id);
    if (!s) continue;
    if (s.type === 'frontier') {
      if (frontier === null || s.beats.length > frontier.beats.length) frontier = s;
    } else if (best === null || s.beats.length > best.beats.length) best = s;
  }
  return best || frontier;
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
    styleOf = () => null, ridings = {}, watch = false, calendar = null, reckoning = null,
  }) {
    this.weights = weights;
    this.follow = follow;
    // Rules 1.0 `world_calendar`: one turn is one year.
    this.calendar = calendar;
    this.reckoningFacts = reckoning;
    this.unit = calendar ? 'year' : unit;
    this.styleOf = styleOf;
    this.ridings = ridings;
    this.board = copyBoard(baseline);
    this.context = createContext(this.board.owners, seen);
    this.standings = table(this.board, weights);
    this.turn = 0;
    // Rules 1.0 `schemes`: every public scheme at the end of the last turn,
    // for a record that carries them; null for one that does not.
    this.plans = null;
    this.lines = new Storylines({
      weights,
      provinceTotals: provinceTotals(ridings),
      held: Object.keys(this.board.owners).map(provinceOf),
      watch,
    });
    // The standings as the current chapter began, for its interstitial.
    this.chapterStart = { turn: 1, table: this.standings };
  }

  // The world year of a turn, or null for a game without a calendar.
  yearOf(turn) {
    return this.calendar ? this.calendar.start_year + turn - 1 : null;
  }

  // When a turn happened, as the pages say it: its year, or "season N".
  when(turn) {
    return this.calendar ? String(this.yearOf(turn)) : `${this.unit} ${turn}`;
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

  // `prestige`, for a record that carries it (rules 1.0), is each house's
  // prestige at the end of this turn: the standings use it.
  step(turn, rawBeats, { prestige = null, plans = null } = {}) {
    const w = this.weights;
    const beats = mergeActs(rawBeats);
    const before = this.standings;
    const boardBefore = this.board;
    const cast = this.cast();
    const boardAfter = applyBeats(boardBefore, beats);
    const after = table(boardAfter, w, prestige);
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
    if (plans !== null) this.plans = plans;

    const namer = this.namer(boardAfter.ranks);
    // A crisis names its camps' houses in standings order, the cast first.
    const placeOf = new Map(after.map((row) => [row.house, row.place]));
    const order = (houses) => [...houses].sort((a, b) => (placeOf.get(a) ?? Infinity) - (placeOf.get(b) ?? Infinity)
      || compareText(a, b));
    const told = (entry) => ({
      beat: entry.beat, weight: entry.weight, mods: entry.mods,
      text: sentence(entry.beat, namer, (fed) => this.ridingName(fed), { order }),
    });

    let headline = null;
    let kicker = null;
    let previously = null;
    let related = [];
    if (!chosen.quiet) {
      headline = told(chosen.headline);
      const ran = chosen.headline.beat.ran;
      if (Number.isInteger(ran) && ran > 0) {
        headline.ran = ran;
        headline.text = `${headline.text} The scheme (${chosen.headline.beat.plan}) ran`
          + ` ${numberWord(ran)} ${this.unit}${ran === 1 ? '' : 's'}.`;
      }
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
          previously = {
            turn: last.turn, year: this.yearOf(last.turn),
            text: sentence(last.beat, namer, (fed) => this.ridingName(fed), { order }),
          };
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

    // Storyline moments to show: a cast or followed storyline that opened,
    // reached its climax or closed.
    const watched = new Set([...cast, ...this.cast()]);
    if (this.follow) watched.add(this.follow);
    const moments = changes
      .map(({ id, change }) => ({ storyline: this.lines.of(id), change }))
      .filter(({ storyline }) => storyline.houses.some((h) => watched.has(h)))
      .map(({ storyline, change }) => ({
        id: storyline.id, name: this.name(storyline), change, type: storyline.type,
        beats: storyline.beats.length,
      }));
    const heavy = !chosen.quiet && chosen.headline.weight >= w.thresholds.pause;

    // What stops Auto (Phase C1): a long cast storyline closing, a removal, a
    // riding passing between two cast houses, or a heavy headline about the
    // followed house.
    const stops = [];
    const castEither = new Set([...cast, ...this.cast()]);
    // A storyline involves the cast if any of its houses was in the top eight
    // at any turn while it ran, so one whose house has just fallen out of the
    // cast still counts when it closes.
    for (const s of this.lines.all) {
      if (s.state !== 'closed' || s.closed === turn) {
        if (s.houses.some((h) => castEither.has(h))) s.cast = true;
      }
    }
    for (const { id, change } of changes) {
      const s = this.lines.of(id);
      const involved = s.cast || (this.follow && s.houses.includes(this.follow));
      if (change === 'closed' && involved && s.beats.length >= w.storylines.pause_closing_beats) {
        stops.push(`${this.name(s)} closes`);
      }
    }
    for (const beat of beats) {
      for (const house of beat.removed || []) stops.push(`${this.namer(boardAfter.ranks).style(house)} is removed`);
      if (beat.kind === 'riding_passes' || beat.kind === 'contest_won' || beat.kind === 'fallen') {
        const [from, to] = beat.kind === 'riding_passes' ? beat.houses : [beat.houses[1], beat.houses[0]];
        if (castEither.has(from) && castEither.has(to)) stops.push('a riding passes between two houses of the cast');
      }
    }
    if (heavy && this.follow && chosen.headline.beat.houses.includes(this.follow)) {
      stops.push(`a headline of weight ${chosen.headline.weight} about the followed house`);
    }

    // Phase D1: the end of a chapter, and the reckoning after the last turn.
    const year = this.yearOf(turn);
    let chapter = null;
    let reckoning = null;
    if (this.calendar) {
      const ch = this.calendar.chapters.find((c) => c.end_year === year);
      if (ch) {
        chapter = this.interstitial(ch, turn);
        stops.push(`the end of Chapter ${ch.numeral}, ${ch.name}`);
        this.chapterStart = { turn: turn + 1, table: this.standings };
      }
      if (this.reckoningFacts && turn === this.calendar.turns) {
        reckoning = reckoningView(this.reckoningFacts, { styleOf: this.styleOf });
        stops.push(`the reckoning of ${reckoning.year}`);
      }
    }

    return {
      turn,
      year,
      chapter,
      reckoning,
      quiet: chosen.quiet,
      headline,
      kicker,
      previously,
      related,
      secondary,
      ledger,
      quietLine,
      pause: stops.length > 0,
      stops: [...new Set(stops)],
      heavy,
      moments,
      zoom: chosen.quiet ? [] : [...(chosen.headline.beat.ridings || [])],
      standings: movement(before, this.standings, w),
      record: rawBeats.filter((beat) => beat.line)
        .map((beat) => sentence(beat, this.namer(boardAfter.ranks), (fed) => this.ridingName(fed), { order })),
      headlineOpens: !chosen.quiet && chosen.headline.roles.some((r) => r.role === 'open')
        && !chosen.headline.roles.some((r) => r.role !== 'open'),
      inStoryline: !chosen.quiet && chosen.headline.roles.length > 0,
    };
  }

  // A chapter's interstitial (Phase D1): its title and years, the standings
  // with their movement since the chapter began, the storylines of the cast it
  // closed, and those of the cast still open, longest first.
  interstitial(ch, turn) {
    const cfg = this.weights.storylines;
    const from = this.chapterStart.turn;
    const castOf = (s) => s.cast || (this.follow && s.houses.includes(this.follow));
    const longest = (a, b) => b.beats.length - a.beats.length || compareText(a.id, b.id);
    const closed = this.lines.all
      .filter((s) => s.state === 'closed' && s.closed >= from && s.closed <= turn && castOf(s))
      .sort(longest).slice(0, cfg.afoot_max)
      .map((s) => this.summary(s));
    const open = this.lines.open.filter(castOf).sort(longest).slice(0, cfg.afoot_max)
      .map((s) => this.summary(s));
    return {
      numeral: ch.numeral,
      name: ch.name,
      start_year: ch.start_year,
      end_year: ch.end_year,
      standings: movement(this.chapterStart.table, this.standings, this.weights),
      closed,
      open,
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

  // Plans afoot (Phase C2): every public scheme of a cast or followed house,
  // its target and its turns remaining, followed house first, then in the
  // order the schemes were begun. Null for a record without schemes.
  plansAfoot() {
    if (this.plans === null) return null;
    const cast = this.cast();
    const mine = (p) => (this.follow && p.house === this.follow ? 0 : 1);
    return this.plans
      .filter((p) => cast.has(p.house) || (this.follow && p.house === this.follow))
      .map((p) => ({ p, rank: mine(p) }))
      .sort((a, b) => a.rank - b.rank || a.p.id - b.p.id)
      .map(({ p }) => ({
        id: p.id,
        house: p.house,
        name: this.placeOf(p.house),
        scheme: p.scheme,
        target: p.target_house ? this.placeOf(p.target_house) : null,
        riding: p.riding || null,
        turnsRemaining: p.turns_remaining,
        followed: Boolean(this.follow && p.house === this.follow),
      }));
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
    if (d.pause) paused += 1;
    if (d.quiet) { quiet += 1; continue; }
    headlines += 1;
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
