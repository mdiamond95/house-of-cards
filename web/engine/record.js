// The record a played game leaves behind, and how it is committed.
//
// Phase 10-3. A browser that has played seasons saves them by committing the
// same files the Python engine would have written — `scenarios/new/seasons/
// NNNN.json` for each season and `scenarios/new/interventions/NNNN.json` for
// each director's intervention — and nothing else. `hoc.db`, `outputs/` and the
// world snapshot are the referee's, written from its own replay.
//
// This module is what says so. The play page uses it, and so does
// `savecheck.js`, which builds the same payload headlessly and checks that
// every blob it would send hashes to the git object the file on disk already
// is. Keeping it here rather than inside the page's script is the point: there
// is one definition of the record's shape, and it can be run without a browser.
//
// Nothing here talks to the network. `commitRecord` is given an `api` function
// and calls it; the caller decides whether that reaches api.github.com.

import { canonicalJson, FloatValue } from './sim.js';

export const DEFAULT_SEASONS_PATH = 'scenarios/new/seasons';
export const DEFAULT_INTERVENTIONS_PATH = 'scenarios/new/interventions';

function padded(season) {
  return String(season).padStart(4, '0');
}

// A turn file is read by a person as often as by hoc/turn.py, so it is written
// the way the turn runner's own files are: indented, one trailing newline.
// A season file is machine-written and byte-compared, so it is canonical.
export function interventionJson(turnfile) {
  return `${JSON.stringify(turnfile, null, 2)}\n`;
}

/** The files a save must write, in commit order.
 *
 * `records` are season records as the engine produced them; `interventions` are
 * `{after_season, turnfile}` entries. Everything at or below `committedSeason`
 * is already in the repository and is left alone — a save adds to the record,
 * it never rewrites it.
 */
export function recordFiles({
  records = [],
  interventions = [],
  committedSeason = 0,
  seasonsPath = DEFAULT_SEASONS_PATH,
  interventionsPath = DEFAULT_INTERVENTIONS_PATH,
} = {}) {
  const files = [];
  for (const record of records) {
    if (record.season <= committedSeason) continue;
    files.push({
      path: `${seasonsPath}/${padded(record.season)}.json`,
      content: canonicalJson(record),
    });
  }
  for (const entry of interventions) {
    if (entry.after_season <= committedSeason) continue;
    files.push({
      path: `${interventionsPath}/${padded(entry.after_season)}.json`,
      content: interventionJson(entry.turnfile),
    });
  }
  return files;
}

/** One commit, through the Git Data API: blobs, tree, commit, fast-forward.
 *
 * `api(path, options)` is the caller's; it must resolve to the parsed body and
 * throw on a failure. The ref update is never forced — a save that cannot
 * fast-forward is a save built on a base the repository has moved past, and the
 * caller is expected to have refused it before reaching here.
 */
export async function commitRecord(api, {
  branch = 'main', baseSha, files, message, onProgress = () => {},
}) {
  const tree = [];
  for (let i = 0; i < files.length; i += 1) {
    onProgress(i, files.length);
    const blob = await api('/git/blobs', {
      method: 'POST',
      body: JSON.stringify({ content: files[i].content, encoding: 'utf-8' }),
    });
    tree.push({ path: files[i].path, mode: '100644', type: 'blob', sha: blob.sha });
  }

  const base = await api(`/git/commits/${baseSha}`);
  const newTree = await api('/git/trees', {
    method: 'POST',
    body: JSON.stringify({ base_tree: base.tree.sha, tree }),
  });
  const commit = await api('/git/commits', {
    method: 'POST',
    body: JSON.stringify({ message, tree: newTree.sha, parents: [baseSha] }),
  });
  await api(`/git/refs/heads/${branch}`, {
    method: 'PATCH',
    body: JSON.stringify({ sha: commit.sha, force: false }),
  });
  return commit;
}


// ---------------------------------------------- the record a browser holds --
//
// A browser's unsaved game is two things: the world's state, and the season
// records the engine produced on the way to it. The state alone is not enough
// to save — a save commits the *records*, byte for byte — so the autosave has
// to carry both, and anything that restores one has to restore the other.
//
// It is still only a cache. Everything below exists so that losing it is a
// delay rather than a loss: the records can always be rebuilt by replaying the
// committed base forward, and `rebuiltMatches` is what proves a rebuild landed
// on the game the browser is actually holding.

// What the autosave will store. Measured rather than assumed: a season record
// forty seasons into a game is about 4 KB, and it grows as the map fills, so a
// count on its own is not a bound on anything that matters. The budget is on
// bytes, with a count as a second ceiling.
//
// 2 MB is roughly five hundred seasons at that size — far beyond a session
// anyone plays by hand — and small enough that writing it once a season does
// not make the page stutter at twelve seasons a second. Past it the browser
// stops keeping history and relies on the rebuild, which is the whole reason
// dropping the oldest is safe.
export const MAX_STORED_BYTES = 2_000_000;
export const MAX_STORED_RECORDS = 1000;

/** A season record read back from storage, ready to be serialised again.
 *
 * `canonicalJson` refuses a bare non-integer, because Python and JavaScript
 * disagree about how to spell one unless it is boxed in `FloatValue`. The
 * engine boxes the two genuine floats a record carries — §10's founding
 * probability and the roll it is compared against — but IndexedDB stores a
 * structured clone and JSON stores text, and neither keeps a class. So a record
 * that has been through the autosave comes back with bare floats, and
 * committing it would throw rather than save.
 *
 * Re-boxing every non-integer number is the exact inverse: the record's
 * invariant is that a number in it is either an integer or one of those floats.
 */
export function reviveRecord(value) {
  if (Array.isArray(value)) return value.map(reviveRecord);
  if (value !== null && typeof value === 'object') {
    if (value instanceof FloatValue) return value;
    // Both a structured clone and a JSON round-trip lose the class but keep the
    // shape: a boxed float comes back as a plain object with one key, `value`,
    // holding a number. Nothing else in a record has that shape. This has to
    // catch an integer-valued one too — a p_found of 0 is still a float, and is
    // exactly the case Python spells `0.0` and JavaScript would spell `0`.
    const keys = Object.keys(value);
    if (keys.length === 1 && keys[0] === 'value' && typeof value.value === 'number') {
      return new FloatValue(value.value);
    }
    const out = {};
    for (const [key, inner] of Object.entries(value)) out[key] = reviveRecord(inner);
    return out;
  }
  // A bare non-integer can only be a float that lost its box some other way.
  if (typeof value === 'number' && !Number.isInteger(value)) return new FloatValue(value);
  return value;
}

/** Every record in a list, revived. */
export function reviveRecords(records) {
  return (records || []).map(reviveRecord);
}

/** The most recent records that fit the autosave's budget, in season order.
 *
 * Dropping the oldest is safe only because a save that finds a record missing
 * rebuilds it from the committed base and checks the rebuild against the live
 * state. If that ever stops being true, this has to stop dropping.
 *
 * One record is always kept, however large: storing nothing would be a worse
 * answer than storing something over budget.
 */
export function boundRecords(records, {
  limit = MAX_STORED_RECORDS, bytes = MAX_STORED_BYTES,
} = {}) {
  const kept = [];
  let total = 0;
  for (let i = records.length - 1; i >= 0; i -= 1) {
    if (kept.length >= limit) break;
    const size = JSON.stringify(records[i]).length;
    if (kept.length > 0 && total + size > bytes) break;
    total += size;
    kept.push(records[i]);
  }
  return kept.reverse();
}

/** The seasons in (from, to] that `records` does not account for. */
export function missingSeasons(records, from, to) {
  const have = new Set(records.map((record) => record.season));
  const gaps = [];
  for (let season = from + 1; season <= to; season += 1) {
    if (!have.has(season)) gaps.push(season);
  }
  return gaps;
}

/** A function that applies whatever interventions follow a given season.
 *
 * Shared by the two replay loops below so they cannot drift apart: a rewind and
 * a save's rebuild must produce the same game, and the interleaving is the part
 * that would be easy to get subtly different.
 */
function interventionApplier(world, interventions) {
  const byAfter = new Map();
  for (const entry of interventions || []) {
    const after = entry.after_season;
    if (!byAfter.has(after)) byAfter.set(after, []);
    byAfter.get(after).push(entry);
  }
  return (season) => {
    for (const entry of byAfter.get(season) || []) {
      const turnfile = entry.turnfile || {};
      const event = turnfile.event || {};
      world.intervene(
        turnfile.operations || [],
        event.title || "Director's intervention",
        event.kind || 'other',
      );
    }
  };
}

/** Play `world` forward to `target`, applying interventions between seasons.
 *
 * A director's intervention is recorded against the season it *follows*, so it
 * changes the state the next season starts from — which is why a replay that
 * ignored them would diverge from the moment the first one was applied. This is
 * the same interleaving `scripts/rebuild.py` does on the Python side.
 *
 * Returns the records produced, in season order.
 */
export function replayRecords(world, target, interventions = [], onProgress = () => {}) {
  const applyAt = interventionApplier(world, interventions);
  const records = [];
  applyAt(world.seasonNo);
  while (world.seasonNo < target) {
    records.push(world.runSeason());
    applyAt(world.seasonNo);
    onProgress(world.seasonNo, target);
  }
  return records;
}

/** The same replay, yielding to the event loop so a page can paint its progress.
 *
 * A three-hundred-season rebuild takes seconds, and a browser that never
 * returns to the event loop shows none of the progress it is reporting — the
 * director sees a frozen page and no reason for it. `yieldEvery` seasons the
 * loop hands control back; the default costs a few milliseconds over a long
 * rebuild and is the difference between a progress line and a hang.
 *
 * It must stay a mirror of `replayRecords`: same applier, same order.
 */
export async function replayRecordsStepwise(
  world, target, interventions = [], onProgress = () => {}, yieldEvery = 10,
) {
  const applyAt = interventionApplier(world, interventions);
  const records = [];
  applyAt(world.seasonNo);
  while (world.seasonNo < target) {
    records.push(world.runSeason());
    applyAt(world.seasonNo);
    onProgress(world.seasonNo, target);
    if (records.length % yieldEvery === 0) {
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
  }
  return records;
}

/** Does a rebuilt world hold the same game as the live one?
 *
 * The comparison is of canonical serialisations of the whole state, not of a
 * season number or a house count: a rebuild that agreed about the headline and
 * differed about a clock would produce season files the referee would refuse,
 * and the browser would have committed a game it was not playing.
 */
export function rebuiltMatches(rebuilt, live) {
  return canonicalJson(rebuilt.state.toSnapshot(rebuilt))
    === canonicalJson(live.state.toSnapshot(live));
}
