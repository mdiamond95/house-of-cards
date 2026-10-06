// Replays a game's exported beats as dispatches and reports what headlined and
// how its storylines ran: the tuning tool for web/story/weights.json
// (docs/STORY_DESIGN.md §3.1, §3.4, §7).
//
//     node tests/js/story_report.mjs <site>/data/beats [--weights FILE] [--follow HOUSE] [--lines N]
//
// Prints JSON: summarise() and summariseStorylines() over every dispatch, the
// board after the last turn, whether every quiet turn rendered as a single
// quiet line, and the first N dispatches as text.
import { readFileSync } from 'node:fs';
import path from 'node:path';

import { Story, summarise, summariseStorylines } from '../../web/story/dispatch.js';
import { applyBeats } from '../../web/story/standings.js';
import { houseStyle } from '../../web/story/text.js';

const args = process.argv.slice(2);
const dir = args[0];
const option = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i === -1 ? fallback : args[i + 1];
};
const weightsPath = option('weights', new URL('../../web/story/weights.json', import.meta.url));
const weights = JSON.parse(readFileSync(weightsPath, 'utf8'));
const index = JSON.parse(readFileSync(path.join(dir, 'index.json'), 'utf8'));
const byTurn = {};
const prestige = {};
const plans = {};
for (const chunk of index.chunks) {
  const body = JSON.parse(readFileSync(path.join(dir, chunk.file), 'utf8'));
  Object.assign(byTurn, body.turns);
  Object.assign(prestige, body.prestige || {});
  Object.assign(plans, body.plans || {});
}
const turns = [];
for (let turn = 1; turn <= index.turns; turn += 1) turns.push([turn, byTurn[String(turn)] || []]);

const styles = {};
for (const [house, info] of Object.entries(index.houses)) styles[house] = houseStyle({ house, ...info });
const story = new Story({
  weights, baseline: index.baseline, follow: option('follow', null), unit: index.unit,
  styleOf: (h) => styles[h] || null, ridings: index.ridings || {},
  watch: Boolean(index.succession_watch),
  calendar: index.calendar || null, reckoning: index.reckoning || null,
});
const dispatches = turns.map(([turn, beats]) => story.step(turn, beats, {
  prestige: prestige[String(turn)] || null,
  plans: index.schemes ? (plans[String(turn)] || []) : null,
}));
const quietAreOneLine = dispatches.every((d) => !d.quiet
  || (d.headline === null && d.secondary.length === 0 && d.ledger === null && typeof d.quietLine === 'string'));

let board = index.baseline;
for (const [, beats] of turns) board = applyBeats(board, beats);

// What the trial harness (scripts/story_trial.py) reads besides the summaries:
// docs/STORY_DESIGN.md §6's measurable targets and the storyline breakdowns.
const pause = weights.thresholds.pause;
const heavy = dispatches.filter((d) => !d.quiet && d.headline.weight >= pause).length;
let quietRun = 0;
let maxQuietRun = 0;
for (const d of dispatches) {
  if (d.turn <= 10) continue;
  quietRun = d.quiet ? quietRun + 1 : 0;
  maxQuietRun = Math.max(maxQuietRun, quietRun);
}
const leaders = dispatches.map((d) => (d.standings.length ? d.standings[0].house : null));
let leadChanges = 0;
let longestLead = 0;
let run = 0;
for (let i = 0; i < leaders.length; i += 1) {
  if (i > 0 && leaders[i] !== leaders[i - 1] && leaders[i - 1] !== null && leaders[i] !== null) leadChanges += 1;
  run = i > 0 && leaders[i] === leaders[i - 1] ? run + 1 : 1;
  if (leaders[i] !== null) longestLead = Math.max(longestLead, run);
}
const headlineTypes = {};
for (const d of dispatches) {
  if (d.quiet) continue;
  const type = d.kicker ? d.kicker.type : 'none';
  headlineTypes[type] = (headlineTypes[type] || 0) + 1;
}
const all = story.lines.all;
const rivalries = all.filter((s) => s.type === 'rivalry');
const rivalryOutcomes = {};
for (const s of rivalries) {
  const key = s.state !== 'closed' ? 'open' : (s.outcome.endsWith(' removed') ? 'a house removed' : s.outcome);
  rivalryOutcomes[key] = (rivalryOutcomes[key] || 0) + 1;
}
const runs = rivalries.filter((s) => s.state === 'closed').map((s) => s.closed - s.opened).sort((x, y) => x - y);
const medianRivalryTurns = runs.length ? runs[Math.floor((runs.length - 1) / 2)] : null;
const fivePlusByType = {};
for (const s of all) if (s.beats.length >= 5) fivePlusByType[s.type] = (fivePlusByType[s.type] || 0) + 1;
// §5's chapters, as turns of a 100-turn game (1867-1885, 1886-1913,
// 1914-1929, 1930-1945, 1946-1966): in each after the first, did a house that
// began it in the top eight end it outside the top eight or removed?
const CHAPTERS = [[1, 19], [20, 47], [48, 63], [64, 79], [80, 100]];
const castAt = (turn) => {
  const d = dispatches[turn - 1];
  return d ? new Set(d.standings.map((r) => r.house)) : new Set();
};
const chapterChurn = CHAPTERS.slice(1).filter(([first, last]) => last <= dispatches.length).map(([first, last]) => {
  const began = castAt(first - 1);
  const ended = castAt(last);
  return [...began].some((h) => !ended.has(h));
});

// Phase C2: after turn 15, the share of turns with at least three public
// schemes involving a house of the cast (its own scheme, or one aimed at it).
let castSchemeShare = null;
if (index.schemes) {
  const later = dispatches.filter((d) => d.turn > 15);
  const busy = later.filter((d) => {
    const cast = new Set(d.standings.map((r) => r.house));
    return (plans[String(d.turn)] || []).filter((p) => cast.has(p.house) || cast.has(p.target_house)).length >= 3;
  }).length;
  castSchemeShare = later.length ? busy / later.length : 0;
}

const lines = Number(option('lines', 0));
const show = (d) => {
  const at = Number.isInteger(d.year) ? `${d.turn} (${d.year})` : `${d.turn}`;
  const tail = (d.pause ? [`    PAUSE: ${d.stops.join('; ')}`] : [])
    .concat(d.chapter ? [`    CHAPTER ${d.chapter.numeral}: ${d.chapter.standings.map((r) => `${r.place}.${r.house}(${r.move})`).join(' ')}`] : [])
    .concat(d.reckoning ? d.reckoning.epilogues.map((e) => `    EPILOGUE ${e.text}`) : []);
  if (d.quiet) return [`${at} ${d.quietLine}`, ...tail].join('\n');
  const out = [`${at} [${d.headline.weight} ${d.headline.beat.kind}] ${d.headline.text}`];
  if (d.kicker) out.push(`    kicker: ${d.kicker.text}`);
  for (const r of d.related) out.push(`    + ${r.text}`);
  if (d.previously) out.push(`    previously (${d.previously.turn}): ${d.previously.text}`);
  for (const s of d.secondary) out.push(`    - [${s.weight} ${s.beat.kind}] ${s.text}`);
  if (d.ledger) out.push(`    ${d.ledger}`);
  if (d.moments.length) out.push(`    moments: ${d.moments.map((m) => `${m.name} ${m.change}`).join('; ')}`);
  return out.concat(tail).join('\n');
};
process.stdout.write(JSON.stringify({
  summary: summarise(dispatches),
  storylines: summariseStorylines(story, dispatches),
  quietAreOneLine,
  trial: {
    turns: dispatches.length,
    heavyShare: dispatches.length ? heavy / dispatches.length : 0,
    maxQuietRunAfter10: maxQuietRun,
    leadChanges,
    longestLead,
    headlineTypes,
    rivalryOutcomes,
    medianRivalryTurns,
    fivePlusByType,
    chapterChurn,
    castSchemeShare,
    // Phase D1: the calendar's interstitials and the reckoning.
    chapters: dispatches.filter((d) => d.chapter).map((d) => [d.year, d.chapter.numeral, d.pause]),
    reckoning: dispatches.length ? Boolean(dispatches[dispatches.length - 1].reckoning) : false,
    years: dispatches.length ? [dispatches[0].year, dispatches[dispatches.length - 1].year] : null,
  },
  board,
  sample: dispatches.slice(0, lines).map(show),
}, null, 1));
