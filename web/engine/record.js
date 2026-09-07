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

import { canonicalJson } from './sim.js';

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
