// The dispatch (docs/STORY_DESIGN.md §3.2): one turn, told.
//
// A turn on screen is a headline (its heaviest beat, the map zoomed to where it
// happened), up to `secondary_max` secondary beats at or above the secondary
// threshold, and a ledger line counting the rest. A turn with nothing at or
// above the quiet threshold is one quiet-turn line instead. The full record —
// every line the engine wrote that turn — travels with it, one tap away.
//
// `Story` steps through a game turn by turn: it keeps the board (standings.js)
// and the weighting context (weight.js) and returns each turn's dispatch. A
// game is replayed by stepping it from its baseline; following a different
// house means replaying with a different `follow`, which changes weights and
// never the game.
//
// Pure: no DOM, no engine, no clock, no randomness.

import { BOOKKEEPING } from './beats.js';
import { createContext, weighTurn, advance } from './weight.js';
import { emptyBoard, copyBoard, applyBeats, table, movement } from './standings.js';

const SMALL = [
  'no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
  'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen',
  'eighteen', 'nineteen', 'twenty',
];
const TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety'];

export function numberWord(n) {
  if (n <= 20) return SMALL[n];
  if (n < 100) return TENS[Math.floor(n / 10)] + (n % 10 ? `-${SMALL[n % 10]}` : '');
  return String(n);
}

function capitalise(text) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const FAILED = {
  Expand: 'tries to expand and fails',
  'Propose compact': 'proposes a compact and is refused',
  'Petition elevation': 'petitions the Crown for elevation and is refused',
  'Purchase riding': 'tries to buy a riding and fails',
  'Marriage alliance': 'seeks a marriage alliance and is refused',
  'Cede / swap': 'offers a cession and is refused',
  Reconcile: 'seeks a reconciliation and is refused',
  Dispute: 'presses a claim and is rebuffed',
  Absorb: 'tries to absorb a neighbour and fails',
  'Challenge (11b)': 'makes a challenge and fails',
};

const PLAIN = {
  invest: 'invests in its estates',
  cultivate: 'cultivates influence',
  consolidate: 'rests and consolidates',
  name_heir: 'names an heir',
};

// A beat's line: the engine's own where it wrote one (without the "Season N · "
// the dispatch's heading already says), else a sentence made only of the
// beat's typed facts.
export function describe(beat, nameOf = (house) => `House ${house}`) {
  if (beat.line) {
    const prefix = `Season ${beat.turn} · `;
    const line = beat.line.startsWith(prefix) ? beat.line.slice(prefix.length) : beat.line;
    return capitalise(line);
  }
  const who = beat.houses && beat.houses.length ? nameOf(beat.houses[0]) : 'A house';
  if (beat.kind === 'failed') return `${who} ${FAILED[beat.outcome] || 'tries and fails'}.`;
  if (beat.kind === 'correspondence' && beat.outcome === 'failed') {
    return `${who} writes, and no correspondence follows.`;
  }
  if (PLAIN[beat.kind]) return `${who} ${PLAIN[beat.kind]}.`;
  return `${who}: ${beat.kind.replace(/_/g, ' ')}.`;
}

function actors(beats) {
  const houses = new Set();
  for (const beat of beats) if (beat.houses && beat.houses.length) houses.add(beat.houses[0]);
  return houses.size;
}

function estates(n) {
  return n === 1 ? 'one house tended its estates' : `${numberWord(n)} houses tended their estates`;
}

// Choose a turn's headline, secondaries and the rest from its weighed beats.
export function select(beats, weighed, weights) {
  const t = weights.thresholds;
  const order = beats
    .map((beat, i) => ({ beat, weight: weighed[i].total, mods: weighed[i].mods }))
    .sort((a, b) => b.weight - a.weight || a.beat.seq - b.beat.seq);
  if (!order.length || order[0].weight < t.quiet) {
    return { quiet: true, headline: null, secondary: [], rest: order };
  }
  const [headline, ...others] = order;
  const secondary = others
    .filter((entry) => entry.weight >= t.secondary)
    .slice(0, weights.secondary_max);
  const shown = new Set(secondary);
  const rest = others.filter((entry) => !shown.has(entry));
  return { quiet: false, headline, secondary, rest };
}

export class Story {
  // `baseline` is the board before the first turn (standings.js); for an
  // engine-played game it is empty. `unit` names a turn: 'season' or 'turn'.
  // `seen` lists kinds whose firsts are already spent (weight.js createContext).
  constructor({ weights, baseline = emptyBoard(), follow = null, unit = 'season', seen = [] }) {
    this.weights = weights;
    this.follow = follow;
    this.unit = unit;
    this.board = copyBoard(baseline);
    this.context = createContext(this.board.owners, seen);
    this.standings = table(this.board, weights);
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

  step(turn, beats, nameOf) {
    const w = this.weights;
    const before = this.standings;
    const cast = new Set(before.slice(0, w.cast_size).map((row) => row.house));
    const weighed = weighTurn(beats, this.context, { weights: w, cast, follow: this.follow });
    const chosen = select(beats, weighed, w);

    this.context = advance(this.context, beats, chosen.quiet ? null : chosen.headline.beat.kind, w);
    this.board = applyBeats(this.board, beats);
    this.standings = table(this.board, w);

    const told = (entry) => ({
      beat: entry.beat, weight: entry.weight, mods: entry.mods, text: describe(entry.beat, nameOf),
    });
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
    return {
      turn,
      quiet: chosen.quiet,
      headline: chosen.quiet ? null : told(chosen.headline),
      secondary: chosen.secondary.map(told),
      ledger,
      quietLine,
      pause: !chosen.quiet && chosen.headline.weight >= w.thresholds.pause,
      zoom: chosen.quiet ? [] : [...(chosen.headline.beat.ridings || [])],
      standings: movement(before, this.standings, w),
      record: beats.filter((beat) => beat.line).map((beat) => describe(beat, nameOf)),
    };
  }
}

// Every dispatch of a game: `turns` is [[turn, beats], ...] in order.
export function replay(turns, options) {
  const story = new Story(options);
  return turns.map(([turn, beats]) => story.step(turn, beats, options.nameOf));
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
