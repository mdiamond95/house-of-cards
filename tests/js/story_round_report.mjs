// Replays a game's exported beats round by round (docs/STORY_DESIGN.md §3.6,
// Phase V2) and reports how the round tells it.
//
//     node tests/js/story_round_report.mjs <site>/data/beats [--follow HOUSE]
//
// Prints JSON: whether every beat has a part of the round and every part is in
// the round (`stray`), whether each round's house turns come out in the
// playing order, how many turns are of each pace, and how long Auto runs at
// 1x with quiet turns shown and skipped (round.js autoLength), with the stops
// a reader presses on through.
import { readFileSync } from 'node:fs';
import path from 'node:path';

import { Story } from '../../web/story/dispatch.js';
import { autoLength } from '../../web/story/round.js';
import { houseStyle } from '../../web/story/text.js';

const args = process.argv.slice(2);
const dir = args[0];
const option = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i === -1 ? fallback : args[i + 1];
};
const weights = JSON.parse(readFileSync(new URL('../../web/story/weights.json', import.meta.url), 'utf8'));
const index = JSON.parse(readFileSync(path.join(dir, 'index.json'), 'utf8'));
const body = { turns: {}, prestige: {}, plans: {}, order: {}, deck: {} };
for (const chunk of index.chunks) {
  const part = JSON.parse(readFileSync(path.join(dir, chunk.file), 'utf8'));
  for (const key of Object.keys(body)) Object.assign(body[key], part[key] || {});
}
const styles = {};
for (const [house, info] of Object.entries(index.houses)) styles[house] = houseStyle({ house, ...info });
const follow = option('follow', null);
const story = new Story({
  weights, baseline: index.baseline, follow, unit: index.unit,
  styleOf: (h) => styles[h] || null, ridings: index.ridings || {},
  watch: Boolean(index.succession_watch),
  calendar: index.calendar || null, reckoning: index.reckoning || null,
});

let beats = 0;
let withPart = 0;
let stray = 0;
let inOrder = true;
let housePartsTwice = 0;
const rounds = [];
for (let turn = 1; turn <= index.turns; turn += 1) {
  const raw = body.turns[String(turn)] || [];
  beats += raw.length;
  withPart += raw.filter((b) => typeof b.part === 'string').length;
  const playing = body.order[String(turn)] || [];
  const d = story.step(turn, raw, {
    prestige: body.prestige[String(turn)] || null,
    plans: index.schemes ? (body.plans[String(turn)] || []) : null,
    playing,
    deck: body.deck[String(turn)] || [],
  });
  stray += d.round.stray.length;
  const houses = d.round.parts.filter((p) => p.kind === 'house').map((p) => p.house);
  if (houses.join('\u0000') !== playing.join('\u0000')) inOrder = false;
  if (new Set(houses).size !== houses.length) housePartsTwice += 1;
  rounds.push(d.round);
}
const minutes = (ms) => Math.round(ms / 600) / 100;
const hold = weights.pace.hold_ms;
const shown = autoLength(rounds, { hold, skipQuiet: false, follow });
const skipped = autoLength(rounds, { hold, skipQuiet: true, follow });
process.stdout.write(JSON.stringify({
  turns: index.turns,
  round: Boolean(index.round),
  beats,
  withPart,
  stray,
  inOrder,
  housePartsTwice,
  parts: rounds.reduce((n, r) => n + r.parts.length, 0),
  byPace: shown.byPace,
  stops: shown.stops,
  autoShown: { ms: shown.ms, minutes: minutes(shown.ms), shown: shown.shown },
  autoSkipped: { ms: skipped.ms, minutes: minutes(skipped.ms), shown: skipped.shown },
}, null, 1));
