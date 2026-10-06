// Rules 1.0 `schemes` and `contested_claims`: the scheme utility function and
// the contest totals, computed by the JavaScript engine on a world resumed from
// a snapshot hoc/export/world.py wrote. tests/test_rules10.py computes the same
// values with hoc/sim.py on the world the snapshot came from and requires them
// to agree, value for value — finer-grained than the cross-check, which says
// only *that* a season differs.
//
//     node tests/js/scheme_parity.mjs SNAPSHOT VERSION REFERENCE_DIR

import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  resumeWorld, loadWorldData, REFERENCE_TABLES, WORLD_TABLES,
} from '../../web/engine/index.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const [snapshotPath, version, reference] = process.argv.slice(2);
const read = (relative) => readFileSync(path.join(ROOT, relative), 'utf8');
const tables = REFERENCE_TABLES.concat(
  WORLD_TABLES.filter((name) => existsSync(path.join(ROOT, reference, name))),
);
const data = loadWorldData(read, version, { dir: reference, tables });
const snapshot = JSON.parse(readFileSync(snapshotPath, 'utf8'));
const world = resumeWorld(read, snapshot, { version, data });
const season = snapshot.season + 1;

const strip = (candidates) => candidates.map((c) => [c[0], c[1], c[2], c[3]]);
const out = { utilities: {}, answers: {}, contests: [] };
for (const row of world.activeHouses()) {
  world._turnCache = new Map();
  out.utilities[row.house] = strip(world.schemeCandidates(row.house, season));
}
const contest = new Set(world.contestSchemes());
for (const claim of world.state.schemes.filter((s) => s.status === 'active' && contest.has(s.scheme))) {
  world._turnCache = new Map();
  out.answers[String(claim.id)] = strip(world.schemeCandidates(claim.targetHouse, season, claim));
}
for (const row of world.activeHouses()) {
  for (const [other, fedId] of world.claimTargets(row.house).slice(0, 3)) {
    world._turnCache = new Map();
    out.contests.push([row.house, other, fedId,
      ...world.contestTotals(row.house, other, fedId, 23, 17, 1, 2, 7, 6)]);
  }
}
process.stdout.write(`${JSON.stringify(out)}\n`);
