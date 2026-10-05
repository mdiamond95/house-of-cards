#!/usr/bin/env node
// The play page's save, run headlessly with the network mocked.
//
//     node web/engine/savecheck.js --seed 1867 --seasons 5
//
// Phase 10-3. A save commits the seasons a browser played, and the whole
// arrangement rests on those files being byte-for-byte what the engine wrote:
// the referee replays them in Python and refuses anything else. This plays a
// game, builds the Git Data API payload the page would send with the same
// `web/engine/record.js` the page uses, and checks two things about it:
//
//   * the paths are the record's paths and nothing else — no hoc.db, no
//     outputs/, no world.json; and
//   * every blob it would post hashes to the same git object as the file
//     `cli.js` wrote to disk, so what is committed is what was played.
//
// It also checks the refusal: a frozen scenario (every one in scenarios/ that is
// not live, and a scenario that is missing) must make `recordFiles` and
// `commitRecord` throw before any file is built or any request is made.
//
// `api` is a mock. Nothing here reaches the network, and no token is needed.
// It exits 0 when everything agrees and 1 when it does not; a difference is
// printed with the path it belongs to.

import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import { newWorld } from './index.js';
import {
  recordFiles, commitRecord, scenarioPaths, FrozenScenarioError,
} from './record.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = path.resolve(HERE, '..', '..');

function parseArgs(argv) {
  const args = { seed: 1867, seasons: 5, seat: 'Kingston and the Islands', root: DEFAULT_ROOT };
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

// A git blob's object id: the hash of "blob <bytes>\0" followed by the content.
// This is what the Git Data API returns for a blob it has stored, so comparing
// it against the file on disk compares the committed bytes with the played ones
// without needing either a network or a repository.
function blobSha(content) {
  const body = Buffer.from(content, 'utf8');
  return createHash('sha1')
    .update(Buffer.concat([Buffer.from(`blob ${body.length}\0`, 'utf8'), body]))
    .digest('hex');
}

// Everything the page would have sent, recorded instead. The shapes match what
// the real endpoints return, because the page reads them.
function mockApi(calls) {
  return async (endpoint, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({ endpoint, method: options.method || 'GET', body });
    if (endpoint === '/git/blobs') return { sha: blobSha(body.content) };
    if (endpoint.startsWith('/git/commits/')) return { tree: { sha: 'base-tree-sha' } };
    if (endpoint === '/git/trees') return { sha: 'new-tree-sha' };
    if (endpoint === '/git/commits') return { sha: 'new-commit-sha' };
    if (endpoint.startsWith('/git/refs/heads/')) return { object: { sha: 'new-commit-sha' } };
    throw new Error(`the page called an endpoint this check does not mock: ${endpoint}`);
  };
}

// The scenario a save is checked against: a made-up live one, so that the check
// does not depend on whether the repository has a live game at the moment.
const SCENARIO = { name: 'savecheck', title: 'Savecheck', status: 'live' };

// Every way a write to a game that is not live could be attempted.
async function checkRefusals(root, failures) {
  const calls = [];
  const frozen = [
    { name: 'frozen-case', title: 'Frozen case', status: 'frozen' },
    { name: 'no-status', title: 'No status' },
    undefined,
  ];
  const scenariosDir = path.join(root, 'scenarios');
  for (const entry of readdirSync(scenariosDir, { withFileTypes: true })) {
    const manifest = path.join(scenariosDir, entry.name, 'scenario.json');
    if (!entry.isDirectory() || !existsSync(manifest)) continue;
    const data = JSON.parse(readFileSync(manifest, 'utf8'));
    // A missing status reads as frozen — the page is handed whatever the manifest says.
    if (data.status !== 'live') {
      frozen.push({ name: entry.name, title: data.title, status: data.status });
    }
  }
  for (const scenario of frozen) {
    const label = scenario ? scenario.name : 'no scenario';
    let built = null;
    try {
      built = recordFiles({ scenario, records: [{ season: 1 }], committedSeason: 0 });
    } catch (error) {
      if (!(error instanceof FrozenScenarioError)) failures.push(`${label}: recordFiles threw ${error.name}`);
    }
    if (built !== null) failures.push(`recordFiles built files for ${label}, which is not live`);

    let committed = false;
    try {
      await commitRecord(async (endpoint) => { calls.push(endpoint); return {}; }, {
        scenario, baseSha: 'x', files: [{ path: 'scenarios/x/seasons/0001.json', content: '{}' }], message: 'm',
      });
      committed = true;
    } catch (error) {
      if (!(error instanceof FrozenScenarioError)) failures.push(`${label}: commitRecord threw ${error.name}`);
    }
    if (committed) failures.push(`commitRecord committed to ${label}, which is not live`);
  }
  if (calls.length > 0) failures.push(`a refused save still made ${calls.length} request(s)`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const read = (relative) => readFileSync(path.join(args.root, relative), 'utf8');
  const failures = [];

  // Play the seasons twice over: once into files, exactly as a committed record
  // looks, and once in memory, as the browser holds them.
  const out = mkdtempSync(path.join(tmpdir(), 'hoc-savecheck-'));
  try {
    execFileSync('node', [
      path.join(HERE, 'cli.js'),
      '--seed', String(args.seed), '--seat', args.seat,
      '--seasons', String(args.seasons), '--out', out, '--root', args.root,
    ], { stdio: 'pipe' });

    const { world, record } = newWorld(read, args.seed, args.seat);
    const records = [record];
    for (let season = 2; season <= args.seasons; season += 1) {
      records.push(world.runSeason());
    }

    const files = recordFiles({ scenario: SCENARIO, records, committedSeason: 0 });
    if (files.length !== args.seasons) {
      failures.push(`built ${files.length} file(s) for ${args.seasons} season(s)`);
    }

    const calls = [];
    const commit = await commitRecord(mockApi(calls), {
      scenario: SCENARIO,
      baseSha: 'base-commit-sha',
      files,
      message: `Play: seasons 1–${args.seasons} (browser engine)`,
    });

    // Paths: the record and nothing else.
    for (const file of files) {
      if (!file.path.startsWith(`${scenarioPaths(SCENARIO.name).seasonsPath}/`)) {
        failures.push(`a save would write outside the record: ${file.path}`);
      }
    }

    // Content: every blob is the file the engine wrote.
    const blobs = calls.filter((call) => call.endpoint === '/git/blobs');
    if (blobs.length !== files.length) {
      failures.push(`posted ${blobs.length} blob(s) for ${files.length} file(s)`);
    }
    for (let i = 0; i < files.length; i += 1) {
      const name = path.basename(files[i].path);
      const onDisk = readFileSync(path.join(out, name), 'utf8');
      if (blobSha(blobs[i].body.content) !== blobSha(onDisk)) {
        failures.push(`${files[i].path} is not the file the engine wrote to ${name}`);
      }
      if (blobs[i].body.encoding !== 'utf-8') {
        failures.push(`${files[i].path} would be posted as ${blobs[i].body.encoding}`);
      }
    }

    // The commit itself: one tree on the base, one commit on the head, one
    // fast-forward of the ref.
    const tree = calls.find((call) => call.endpoint === '/git/trees');
    if (!tree || tree.body.base_tree !== 'base-tree-sha') {
      failures.push('the tree was not built on the base commit\u2019s tree');
    }
    if (tree && tree.body.tree.some((entry) => entry.mode !== '100644' || entry.type !== 'blob')) {
      failures.push('a tree entry is not a plain file blob');
    }
    const made = calls.find((call) => call.endpoint === '/git/commits' && call.method === 'POST');
    if (!made || made.body.parents.length !== 1 || made.body.parents[0] !== 'base-commit-sha') {
      failures.push('the commit does not have the base as its only parent');
    }
    const ref = calls.find((call) => call.endpoint.startsWith('/git/refs/heads/'));
    if (!ref || ref.method !== 'PATCH' || ref.body.force !== false) {
      failures.push('the ref update is not an unforced fast-forward');
    }
    if (commit.sha !== 'new-commit-sha') failures.push('the commit was not returned');
  } finally {
    rmSync(out, { recursive: true, force: true });
  }

  await checkRefusals(args.root, failures);

  if (failures.length > 0) {
    for (const failure of failures) console.error(`savecheck: ${failure}`);
    process.exitCode = 1;
    return;
  }
  console.log(
    `savecheck: ${args.seasons} season(s) would be committed exactly as played;`
    + ' a frozen scenario is refused',
  );
}

main().catch((error) => {
  console.error(error.stack || String(error));
  process.exitCode = 1;
});
