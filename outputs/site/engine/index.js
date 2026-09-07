// The JavaScript engine's public surface.
//
// Everything a caller needs to play a game and read its seasons, without
// knowing how the state is stored. `web/engine/cli.js` uses it under node; the
// live UI (Phase 10-2) will use it in the browser.
//
// `read(relativePath) -> string` is supplied by the caller, so this works
// unchanged with readFileSync under node and fetch in a page. There is no build
// step and no dependency: that is the point of the directory.

import { loadRules } from './rules.js';
import { loadReferenceMap } from './adjacency.js';
import { WorldState } from './state.js';
import { World, canonicalJson, PHASES, RULES_VERSION, SimError } from './sim.js';

export { World, WorldState, canonicalJson, PHASES, RULES_VERSION, SimError };
export { loadRules, loadReferenceMap };

// Load the rules and the reference map once. Both are immutable for the life of
// a game, so a caller playing several worlds should hold on to the result.
export function loadWorldData(read) {
  return { rules: loadRules(read), map: loadReferenceMap(read) };
}

// Found a new world and play its first season, exactly as
// `python -m hoc sim new --seed N --seat "..."` does.
//
// Returns { world, record } — the world to keep playing, and season 1's record.
export function newWorld(read, seed, seat = null, { phases = null, data = null } = {}) {
  const { rules, map } = data || loadWorldData(read);
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
export function resumeWorld(read, snapshot, { phases = null, data = null } = {}) {
  const { rules, map } = data || loadWorldData(read);
  if (snapshot.rules_version !== RULES_VERSION) {
    throw new SimError(
      `this world was played under rules ${snapshot.rules_version} and the engine is`
      + ` ${RULES_VERSION}: replaying it would reinterpret seasons already played`,
    );
  }
  const state = WorldState.load(snapshot, map);
  return new World({ state, rules, worldSeed: snapshot.world_seed, phases });
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
