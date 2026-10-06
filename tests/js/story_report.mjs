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
for (const chunk of index.chunks) {
  Object.assign(byTurn, JSON.parse(readFileSync(path.join(dir, chunk.file), 'utf8')).turns);
}
const turns = [];
for (let turn = 1; turn <= index.turns; turn += 1) turns.push([turn, byTurn[String(turn)] || []]);

const styles = {};
for (const [house, info] of Object.entries(index.houses)) styles[house] = houseStyle({ house, ...info });
const story = new Story({
  weights, baseline: index.baseline, follow: option('follow', null), unit: index.unit,
  styleOf: (h) => styles[h] || null, ridings: index.ridings || {},
});
const dispatches = turns.map(([turn, beats]) => story.step(turn, beats));
const quietAreOneLine = dispatches.every((d) => !d.quiet
  || (d.headline === null && d.secondary.length === 0 && d.ledger === null && typeof d.quietLine === 'string'));

let board = index.baseline;
for (const [, beats] of turns) board = applyBeats(board, beats);

const lines = Number(option('lines', 0));
const show = (d) => {
  if (d.quiet) return `${d.turn} ${d.quietLine}`;
  const out = [`${d.turn} [${d.headline.weight} ${d.headline.beat.kind}] ${d.headline.text}`];
  if (d.kicker) out.push(`    kicker: ${d.kicker.text}`);
  for (const r of d.related) out.push(`    + ${r.text}`);
  if (d.previously) out.push(`    previously (${d.previously.turn}): ${d.previously.text}`);
  for (const s of d.secondary) out.push(`    - [${s.weight} ${s.beat.kind}] ${s.text}`);
  if (d.ledger) out.push(`    ${d.ledger}`);
  if (d.moments.length) out.push(`    moments: ${d.moments.map((m) => `${m.name} ${m.change}`).join('; ')}`);
  return out.join('\n');
};
process.stdout.write(JSON.stringify({
  summary: summarise(dispatches),
  storylines: summariseStorylines(story, dispatches),
  quietAreOneLine,
  board,
  sample: dispatches.slice(0, lines).map(show),
}, null, 1));
