// Rules 1.0 `crises`: one crisis resolved by the JavaScript engine on a world
// resumed from a snapshot hoc/export/world.py wrote — the camps, which camp
// carried it, and every house's influence and every border's friction after.
// tests/test_rules10.py resolves the same crisis with hoc/sim.py on the world
// the snapshot came from and requires the two to agree, value for value.
//
//     node tests/js/crisis_parity.mjs SNAPSHOT VERSION REFERENCE_DIR EVENT

import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  resumeWorld, loadWorldData, REFERENCE_TABLES, WORLD_TABLES,
} from '../../web/engine/index.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const [snapshotPath, version, reference, eventName] = process.argv.slice(2);
const read = (relative) => readFileSync(path.join(ROOT, relative), 'utf8');
const tables = REFERENCE_TABLES.concat(
  WORLD_TABLES.filter((name) => existsSync(path.join(ROOT, reference, name))),
);
const data = loadWorldData(read, version, { dir: reference, tables });
const snapshot = JSON.parse(readFileSync(snapshotPath, 'utf8'));
const world = resumeWorld(read, snapshot, { version, data });
const season = snapshot.season + 1;
const event = world.rules.events.find((e) => e.name === eventName);
world._playingSeason = season;
world._turnCache = new Map();
world.crisis(event, season, world.rngFor(season), world.yearNow());
const recorded = world.state.events[world.state.events.length - 1];
const influence = {};
for (const row of world.activeHouses()) influence[row.house] = world.houseRow(row.house).influence;
const friction = world.state.borderingPairs().map(([a, b]) => [a, b, world.frictionBetween(a, b)]);
process.stdout.write(`${JSON.stringify({ crisis: recorded.mechanicalDelta.crisis, influence, friction })}\n`);
