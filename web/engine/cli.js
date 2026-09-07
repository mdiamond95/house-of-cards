#!/usr/bin/env node
// Play the game with the JavaScript engine and write its season files.
//
//     node web/engine/cli.js --seed 1867 --seasons 120 --out DIR
//     node web/engine/cli.js --seed 1867 --seat "Kingston and the Islands" --seasons 5 --out DIR
//
// This exists so `scripts/crosscheck.py` can run both engines the same way and
// compare what they wrote. The bytes are canonical (sorted keys, tight
// separators, UTF-8 as-is, one trailing newline) — identical to what
// `hoc/sim.py` writes, which is what makes a plain byte comparison meaningful.
//
// `--phases` is a developer-only flag mirroring `python -m hoc sim run
// --phases`: it runs only the named phases of the §6 season loop, so the two
// engines can be compared a phase at a time while the port is being built. The
// default is every phase, and that is the only way the game is ever played.

import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { newWorld, canonicalJson, PHASES } from './index.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = path.resolve(HERE, '..', '..');

function parseArgs(argv) {
  const args = {
    seed: 1867, seasons: 1, seat: null, out: null,
    root: DEFAULT_ROOT, phases: null,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i];
    const value = argv[i + 1];
    switch (flag) {
      case '--seed': args.seed = parseInt(value, 10); i += 1; break;
      case '--seasons': args.seasons = parseInt(value, 10); i += 1; break;
      case '--seat': args.seat = value; i += 1; break;
      case '--out': args.out = value; i += 1; break;
      case '--root': args.root = path.resolve(value); i += 1; break;
      case '--phases':
        args.phases = value.split(',').map((p) => p.trim()).filter(Boolean);
        i += 1;
        break;
      default:
        throw new Error(`unknown argument ${flag}`);
    }
  }
  if (args.out === null) throw new Error('--out is required');
  if (!Number.isInteger(args.seed)) throw new Error('--seed must be an integer');
  if (!Number.isInteger(args.seasons) || args.seasons < 1) {
    throw new Error('--seasons must be a positive integer');
  }
  if (args.phases !== null) {
    const unknown = args.phases.filter((p) => !PHASES.includes(p));
    if (unknown.length > 0) {
      throw new Error(
        `unknown phase(s) ${unknown.join(', ')}; valid phases are ${PHASES.join(', ')}`,
      );
    }
  }
  return args;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const read = (relative) => readFileSync(path.join(args.root, relative), 'utf8');

  mkdirSync(args.out, { recursive: true });

  const { world, record } = newWorld(read, args.seed, args.seat, { phases: args.phases });
  const write = (season, value) => {
    const name = String(season).padStart(4, '0');
    writeFileSync(path.join(args.out, `${name}.json`), canonicalJson(value), 'utf8');
  };
  write(1, record);

  for (let season = 2; season <= args.seasons; season += 1) {
    write(season, world.runSeason());
  }
}

try {
  main();
} catch (error) {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exit(1);
}
