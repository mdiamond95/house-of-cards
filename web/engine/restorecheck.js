#!/usr/bin/env node
// The play page's autosave and its rebuild, run headlessly.
//
//     node web/engine/restorecheck.js --seasons 40
//
// Two things the page has to get right about a browser that is reloaded
// mid-game, checked here without a browser:
//
//   1. **Restore.** The autosave carries the season records and the
//      interventions alongside the state, and a restore brings them back. A
//      restored game that knows it is 38 seasons ahead of the repository and
//      cannot name one of them is the bug this exists to stop: the chronicle
//      renders empty and the save has nothing to commit.
//
//   2. **Rebuild.** With the records gone — the autosave bounds what it stores,
//      and storage can be cleared under a page — the save path replays them
//      from the committed base and checks the result against the live state.
//      The rebuilt records must equal the originals byte for byte, or the
//      browser would be committing a game it did not play.
//
// It also checks the rebuild *fails* when it should: a world that did not come
// from the base cannot be reconstructed from it, and `rebuiltMatches` must say
// so rather than waving through records nobody can reproduce.
//
// No browser, no network, no token. Exits 0 when everything agrees, 1 when it
// does not, naming what differed.

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { newWorld, resumeWorld, canonicalJson, World, WorldState, loadWorldData } from './index.js';
import {
  boundRecords, missingSeasons, replayRecords, replayRecordsStepwise, rebuiltMatches,
  reviveRecords,
  MAX_STORED_BYTES, MAX_STORED_RECORDS,
} from './record.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = path.resolve(HERE, '..', '..');

function parseArgs(argv) {
  const args = { seed: 1867, seasons: 40, seat: 'Kingston and the Islands', root: DEFAULT_ROOT };
  for (let i = 0; i < argv.length; i += 1) {
    const value = argv[i + 1];
    switch (argv[i]) {
      case '--seed': args.seed = parseInt(value, 10); i += 1; break;
      case '--seasons': args.seasons = parseInt(value, 10); i += 1; break;
      case '--seat': args.seat = value; i += 1; break;
      case '--root': args.root = path.resolve(value); i += 1; break;
      default: throw new Error(`unknown argument ${argv[i]}`);
    }
  }
  return args;
}

// What hoc/export/play_js.py's autosave() stores, built the same way: the state
// plus the bounded records plus the interventions. Round-tripped through JSON
// because IndexedDB stores a structured clone, not the live objects.
function autosavePayload(world, records, interventions, committedSeason) {
  return JSON.parse(JSON.stringify({
    savedAt: '1867-07-01T00:00:00.000Z',
    committedSeason,
    committedSha: 'base-sha',
    season: world.seasonNo,
    snapshot: world.state.toSnapshot(world),
    records: boundRecords(records),
    interventions,
    savedThrough: committedSeason,
  }));
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const read = (relative) => readFileSync(path.join(args.root, relative), 'utf8');
  const data = loadWorldData(read);
  const failures = [];
  const check = (ok, message) => { if (!ok) failures.push(message); };

  // The committed base: season 1, as world.json holds it.
  const founded = newWorld(read, args.seed, args.seat, { data });
  const base = JSON.parse(canonicalJson(founded.world.state.toSnapshot(founded.world)));
  const committedSeason = founded.world.seasonNo;

  // Play on to `seasons`, exactly as the page does.
  const live = resumeWorld(read, base, { data });
  const played = [];
  while (live.seasonNo < args.seasons) played.push(live.runSeason());
  check(
    played.length === args.seasons - committedSeason,
    `played ${played.length} season(s), expected ${args.seasons - committedSeason}`,
  );

  // ---- 1. autosave, then reload -------------------------------------------
  const stored = autosavePayload(live, played, [], committedSeason);

  check(Array.isArray(stored.records), 'the autosave stored no records array');
  check(
    stored.records.length === played.length,
    `the autosave stored ${stored.records.length} record(s) of ${played.length}`,
  );
  check(
    missingSeasons(stored.records, committedSeason, stored.season).length === 0,
    'the autosave left a gap in the seasons it stored',
  );

  // The reload: nothing survives but the payload, and what comes back has been
  // through a structured clone — so the records are revived, exactly as
  // hoc/export/play_js.py's boot does. Skipping that leaves bare floats where
  // the engine put boxed ones, and the save throws instead of committing.
  const restored = resumeWorld(read, stored.snapshot, { data });
  const restoredRecords = reviveRecords(stored.records);

  for (const record of restoredRecords) {
    try {
      canonicalJson(record);
    } catch (error) {
      failures.push(`restored season ${record.season} cannot be serialised: ${error.message}`);
      break;
    }
  }
  for (let i = 0; i < played.length; i += 1) {
    if (canonicalJson(restoredRecords[i]) !== canonicalJson(played[i])) {
      failures.push(`restored season ${played[i].season} differs from the one played`);
      break;
    }
  }
  check(
    restored.seasonNo === args.seasons,
    `the restored world is at season ${restored.seasonNo}, expected ${args.seasons}`,
  );
  check(
    canonicalJson(restored.state.toSnapshot(restored)) === canonicalJson(live.state.toSnapshot(live)),
    'the restored world is not the world that was autosaved',
  );

  // The chronicle the feed would draw. Empty here is the reported bug.
  const feedLines = restoredRecords.flatMap((record) => record.chronicle);
  check(restoredRecords.length > 0, 'a restored game holds no records at all');
  check(feedLines.length > 0, 'a restored game would render an empty chronicle');

  // The bound the autosave promises to stay inside, checked against what it
  // actually stored rather than against an assumed record size.
  const bytes = Buffer.byteLength(JSON.stringify(stored.records), 'utf8');
  const per = Math.round(bytes / Math.max(1, stored.records.length));
  check(
    bytes <= MAX_STORED_BYTES,
    `the autosave stored ${bytes} bytes, over the ${MAX_STORED_BYTES} budget`,
  );
  check(
    stored.records.length <= MAX_STORED_RECORDS,
    `the autosave stored ${stored.records.length} records, over the ${MAX_STORED_RECORDS} ceiling`,
  );

  // And that the bound bites: a budget smaller than one record's worth keeps
  // the newest and no more, which is what makes the rebuild necessary.
  const squeezed = boundRecords(played, { bytes: 1 });
  check(squeezed.length === 1, `a one-byte budget kept ${squeezed.length} record(s), expected 1`);
  check(
    squeezed.length === 0 || squeezed[0].season === played[played.length - 1].season,
    'a squeezed autosave kept the oldest record rather than the newest',
  );

  // ---- 2. the records are gone; rebuild them ------------------------------
  const gaps = missingSeasons([], committedSeason, restored.seasonNo);
  check(
    gaps.length === restoredRecords.length,
    `with no records, ${gaps.length} season(s) are missing of ${restoredRecords.length}`,
  );

  const rebuiltWorld = new World({
    state: WorldState.load(base, data.map),
    rules: data.rules,
    worldSeed: base.world_seed,
  });
  const rebuilt = replayRecords(rebuiltWorld, restored.seasonNo, []);
  check(
    rebuiltMatches(rebuiltWorld, restored),
    'the rebuilt world does not match the restored one, so the save would refuse',
  );
  check(
    rebuilt.length === restoredRecords.length,
    `rebuilt ${rebuilt.length} record(s), expected ${restoredRecords.length}`,
  );
  for (let i = 0; i < Math.min(rebuilt.length, restoredRecords.length); i += 1) {
    if (canonicalJson(rebuilt[i]) !== canonicalJson(restoredRecords[i])) {
      failures.push(`rebuilt season ${rebuilt[i].season} differs from the one played`);
      break;
    }
  }

  // ---- 3. the page's stepwise replay is the same replay -------------------
  //
  // The page yields to the event loop so it can paint its progress; the two
  // loops must otherwise be identical, or a rebuild in a browser would differ
  // from a rebuild anywhere else.
  const stepwiseWorld = new World({
    state: WorldState.load(base, data.map),
    rules: data.rules,
    worldSeed: base.world_seed,
  });
  const stepwise = await replayRecordsStepwise(stepwiseWorld, restored.seasonNo, []);
  check(
    stepwise.length === rebuilt.length,
    `the stepwise replay made ${stepwise.length} record(s) against ${rebuilt.length}`,
  );
  for (let i = 0; i < Math.min(stepwise.length, rebuilt.length); i += 1) {
    if (canonicalJson(stepwise[i]) !== canonicalJson(rebuilt[i])) {
      failures.push(`the stepwise replay differs at season ${rebuilt[i].season}`);
      break;
    }
  }

  // ---- 4. a game that did not come from the base must be refused ----------
  const stranger = resumeWorld(read, base, { data });
  while (stranger.seasonNo < args.seasons + 1) stranger.runSeason();
  check(
    !rebuiltMatches(rebuiltWorld, stranger),
    'a rebuild matched a world it did not reconstruct; the save would commit a game nobody played',
  );

  if (failures.length > 0) {
    for (const failure of failures) console.error(`restorecheck: ${failure}`);
    process.exitCode = 1;
    return;
  }
  console.log(
    `restorecheck: ${args.seasons} seasons autosave, restore and rebuild identically`
    + ` (${restoredRecords.length} records, ~${per} bytes each)`,
  );
}

main().catch((error) => {
  console.error(error.stack || String(error));
  process.exitCode = 1;
});
