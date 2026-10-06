// The play page's beat input, from the JavaScript engine's in-memory tables.
//
//     node tests/js/story_engine_inputs.mjs --seed 1867 --seasons 40 [--seat NAME] [--rules-version V]
//
// Plays a world with web/engine/ and, after each season, builds that season's
// beat input with web/story/beats.js inputFromState — exactly what play.js does
// — and prints {inputs, beats} as JSON. tests/test_story.py compares it with
// hoc/export/beats.py's input for the same world played by the Python engine.
//
// This harness imports both the engine and the story layer; neither of those
// imports the other (tests/test_story.py checks).

import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { newWorld, loadWorldData, REFERENCE_TABLES, WORLD_TABLES } from '../../web/engine/index.js';
import { inputFromState, typeTurn } from '../../web/story/beats.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const args = { seed: 1867, seasons: 10, seat: null, reference: 'data/reference', 'rules-version': null };
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i += 2) {
  const key = argv[i].replace(/^--/, '');
  args[key] = ['seat', 'reference', 'rules-version'].includes(key) ? argv[i + 1] : parseInt(argv[i + 1], 10);
}

const read = (relative) => readFileSync(path.join(ROOT, relative), 'utf8');
const tables = REFERENCE_TABLES.concat(
  WORLD_TABLES.filter((name) => existsSync(path.join(ROOT, args.reference, name))),
);
const data = loadWorldData(read, args['rules-version'], { dir: args.reference, tables });
const { world } = newWorld(read, args.seed, args.seat, { data, version: args['rules-version'] });
const inputs = [inputFromState(world.state, 1)];
for (let season = 2; season <= args.seasons; season += 1) {
  world.runSeason();
  inputs.push(inputFromState(world.state, season));
}
process.stdout.write(JSON.stringify({ inputs, beats: inputs.map(typeTurn) }));
