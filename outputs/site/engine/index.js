// The JavaScript engine's public surface.
//
// Everything a caller needs to play a game and read its seasons, without
// knowing how the state is stored. `web/engine/cli.js` uses it under node; the
// live UI (Phase 10-2) will use it in the browser.
//
// `read(relativePath) -> string` is supplied by the caller, so this works
// unchanged with readFileSync under node and fetch in a page. There is no build
// step and no dependency: that is the point of the directory.

import { loadRules, currentVersion, feature } from './rules.js';
import { loadReferenceMap } from './adjacency.js';
import { WorldState } from './state.js';
import { World, canonicalJson, PHASES, RULES_VERSION, SimError } from './sim.js';

export { World, WorldState, canonicalJson, PHASES, RULES_VERSION, SimError };
export { loadRules, loadReferenceMap, currentVersion, feature };

// Load the rules and the reference map once. Both are immutable for the life of
// a game, so a caller playing several worlds should hold on to the result.
export function loadWorldData(read, version = null) {
  return { rules: loadRules(read, version), map: loadReferenceMap(read) };
}

// The rules bundle for a given version, cached against the map so a replay
// crossing a version boundary reloads only the tables. A game that runs long
// enough always crosses one.
export function rulesFor(read, version, data) {
  if (data && data.rules && data.rules.version === version) return data.rules;
  return loadRules(read, version);
}

// Found a new world and play its first season, exactly as
// `python -m hoc sim new --seed N --seat "..."` does.
//
// Returns { world, record } — the world to keep playing, and season 1's record.
export function newWorld(read, seed, seat = null, { phases = null, data = null, version = null } = {}) {
  const wanted = version || (data && data.rules && data.rules.version) || currentVersion(read);
  const { map } = data || loadWorldData(read, wanted);
  const rules = rulesFor(read, wanted, data);
  const state = new WorldState(map);
  const world = new World({ state, rules, worldSeed: seed, phases });
  const record = world.initialise(seed, seat);
  return { world, record };
}

// Resume the committed game from a snapshot written by hoc/export/world.py.
//
// This is how the browser picks the world up where the Python engine left it:
// the world's seed and season come out of the snapshot, so the very next season
// draws from the same seed the Python engine would have drawn from.
export function resumeWorld(read, snapshot, { phases = null, data = null, version = null } = {}) {
  // Which rules the *next* season is played under. A snapshot records the
  // version its last season was played under, which is not necessarily the
  // current one — a world at season 41 under rules 0.7 goes on to season 42
  // under 0.8, and that is exactly what shipping a new version means. What
  // must not happen is replaying season 41 itself under 0.8, and that is
  // `replaySeasons`' business, not this one's.
  const wanted = version || (data && data.rules && data.rules.version) || currentVersion(read);
  const { map } = data || loadWorldData(read, wanted);
  const rules = rulesFor(read, wanted, data);
  const state = WorldState.load(snapshot, map);
  return new World({ state, rules, worldSeed: snapshot.world_seed, phases });
}

/** Replay committed season records, each under the version it recorded.
 *
 * The mirror of hoc/sim.py's `World.replay`. A record that names a version this
 * checkout does not have is refused rather than replayed under another one:
 * that would produce a different game and call it the same one.
 */
export function replaySeasons(read, world, records, { data = null } = {}) {
  const produced = [];
  for (const record of records) {
    const version = record.rules_version;
    if (version && version !== world.rulesVersion) {
      world.rules = rulesFor(read, version, data);
      world.rulesVersion = world.rules.version;
      world.reindexRules();
    }
    produced.push(world.runSeason(record.season));
  }
  return produced;
}

// Play one more season. Returns that season's record.
export function runSeason(world) {
  return world.runSeason();
}

// The record for a season already played is the value runSeason returned; this
// re-reads the world's own bookkeeping for it, which is what a caller wants
// when it has the world but not the record it was handed.
export function seasonRecord(world, seasonNo) {
  const row = world.state.seasons.find((s) => s.seasonNo === seasonNo);
  if (row === undefined) return null;
  return {
    season: row.seasonNo,
    seed: row.seed,
    rules_version: row.rulesVersion,
    houses_after: row.housesAfter,
    ridings_after: row.ridingsAfter,
  };
}
