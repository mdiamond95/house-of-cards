#!/usr/bin/env node
// A headless run of exactly what the play page does, with no browser.
//
//     node web/engine/playtest.js --site outputs/site --seasons 300 --out DIR
//
// The page fetches the rules and the reference map, fetches world.json, loads
// it into the engine and plays seasons. This does the same thing with
// readFileSync in place of fetch, so `tests/test_site.py` can prove the page's
// path through the engine works — and produces the seasons the Python engine
// produces — without driving a browser.
//
// It deliberately reads the *exported site*, not the repository: if an export
// forgot to copy a module or a rules table, this fails, which is the point.

import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));

function parseArgs(argv) {
  const args = { site: null, seasons: 10, out: null };
  for (let i = 0; i < argv.length; i += 1) {
    const value = argv[i + 1];
    switch (argv[i]) {
      case '--site': args.site = path.resolve(value); i += 1; break;
      case '--seasons': args.seasons = parseInt(value, 10); i += 1; break;
      case '--out': args.out = path.resolve(value); i += 1; break;
      default: throw new Error(`unknown argument ${argv[i]}`);
    }
  }
  if (args.site === null) throw new Error('--site is required');
  return args;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  // The page imports the engine from engine/ inside the site; so does this, so
  // a module missing from the export is a failure here rather than a surprise
  // in someone's browser.
  const engine = path.join(args.site, 'engine');
  const { loadRules } = await import(path.join(engine, 'rules.js'));
  const { loadReferenceMap } = await import(path.join(engine, 'adjacency.js'));
  const { WorldState } = await import(path.join(engine, 'state.js'));
  const { World, canonicalJson, RULES_VERSION } = await import(path.join(engine, 'sim.js'));

  // The same path mapping play.js uses: the engine asks for repository paths,
  // the site serves the rules one directory down.
  const read = (logical) => {
    const relative = logical.startsWith('rules/') ? `data/${logical}` : logical;
    return readFileSync(path.join(args.site, relative), 'utf8');
  };

  const committed = JSON.parse(readFileSync(path.join(args.site, 'data', 'world.json'), 'utf8'));
  if (committed.rules_version !== RULES_VERSION) {
    throw new Error(
      `world.json is rules ${committed.rules_version} and the exported engine is ${RULES_VERSION}`,
    );
  }

  const world = new World({
    state: WorldState.load(committed, loadReferenceMap(read)),
    rules: loadRules(read),
    worldSeed: committed.world_seed,
  });

  const started = Date.now();
  const records = [];
  const first = (committed.season || 0) + 1;
  const last = (committed.season || 0) + args.seasons;
  for (let season = first; season <= last; season += 1) records.push(world.runSeason());
  const elapsed = (Date.now() - started) / 1000;

  if (args.out !== null) {
    mkdirSync(args.out, { recursive: true });
    for (const record of records) {
      writeFileSync(
        path.join(args.out, `${String(record.season).padStart(4, '0')}.json`),
        canonicalJson(record),
        'utf8',
      );
    }
  }

  // A round trip through the snapshot the page autosaves with, so that path is
  // exercised too rather than merely present.
  const saved = world.state.toSnapshot(world);
  const reloaded = WorldState.load(JSON.parse(JSON.stringify(saved)), world.state.map);

  process.stdout.write(JSON.stringify({
    from: committed.season,
    to: world.seasonNo,
    seasons: records.length,
    seconds: Number(elapsed.toFixed(3)),
    seasons_per_second: Number((records.length / Math.max(elapsed, 1e-9)).toFixed(1)),
    houses: world.state.activeHouses().length,
    ridings: world.state.totalCurrentHoldings(),
    snapshot_round_trips: reloaded.activeHouses().length === world.state.activeHouses().length,
    chronicle_lines: records.reduce((n, r) => n + r.chronicle.length, 0),
  }));
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exit(1);
});
