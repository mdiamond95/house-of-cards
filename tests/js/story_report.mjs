// Replays a game's exported beats as dispatches and reports what headlined:
// the tuning tool for web/story/weights.json (docs/STORY_DESIGN.md §3.1).
//
//     node tests/js/story_report.mjs <site>/data/beats [--weights FILE] [--follow HOUSE] [--lines N]
//
// Prints JSON: summarise() over every dispatch, the board after the last turn,
// and whether every quiet turn rendered as a single quiet line.
import { readFileSync } from 'node:fs';
import path from 'node:path';

import { replay, summarise } from '../../web/story/dispatch.js';
import { applyBeats } from '../../web/story/standings.js';

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

const dispatches = replay(turns, {
  weights, baseline: index.baseline, follow: option('follow', null), unit: index.unit,
});
const quietAreOneLine = dispatches.every((d) => !d.quiet
  || (d.headline === null && d.secondary.length === 0 && d.ledger === null && typeof d.quietLine === 'string'));

// The board again, folded the same way the Story did, for comparison with hoc.db.
let board = index.baseline;
for (const [, beats] of turns) board = applyBeats(board, beats);

const lines = Number(option('lines', 0));
process.stdout.write(JSON.stringify({
  summary: summarise(dispatches),
  quietAreOneLine,
  board,
  sample: dispatches.slice(0, lines).map((d) => (d.quiet ? d.quietLine : `${d.headline.weight} ${d.headline.beat.kind}: ${d.headline.text}`)),
}, null, 1));
