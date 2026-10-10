// The reference map: 343 ridings and which of them touch.
//
// This is the one part of the engine's data that never changes during a game.
// It is loaded from the same CSVs the Python engine reads, from the
// reference-data set the scenario names: `ne-2026` (data/reference/, built from
// Elections Canada's 2023 Representation Order by `scripts/build_ridings.py`
// and `scripts/build_adjacency.py`) or `meridian-v1.0.3`
// (data/reference/meridian/v1.0.3/, built from Meridian's riding table by
// `scripts/build_world_meridian.py`) — never authored by hand, in either engine.

import { parseCsvDicts } from './csv.js';

// SQLite compares TEXT with its BINARY collation, which orders by UTF-8 bytes;
// JavaScript's `<` orders by UTF-16 code units. The two agree for every
// character in the Basic Multilingual Plane, which is all of this data — but
// comparing by code point is what both actually mean, so that is what this
// does, and it stays right if a name outside the BMP ever appears.
export function compareStrings(a, b) {
  if (a === b) return 0;
  const aPoints = Array.from(a);
  const bPoints = Array.from(b);
  const shared = Math.min(aPoints.length, bPoints.length);
  for (let i = 0; i < shared; i += 1) {
    const ca = aPoints[i].codePointAt(0);
    const cb = bPoints[i].codePointAt(0);
    if (ca !== cb) return ca < cb ? -1 : 1;
  }
  if (aPoints.length === bPoints.length) return 0;
  return aPoints.length < bPoints.length ? -1 : 1;
}

export class ReferenceMap {
  constructor(ridingRows, adjacencyRows, placeRows = [], tokenRows = [],
    statsRows = [], jurisdictionRows = []) {
    // Ridings in fed_id order, which is what every "ORDER BY r.fed_id" in the
    // Python engine produces. fed_ids are fixed-width digit strings, so this
    // ordering is both lexicographic and numeric.
    this.ridings = [...ridingRows].sort((a, b) => compareStrings(a.fed_id, b.fed_id));
    this.byFedId = new Map(this.ridings.map((r) => [r.fed_id, r]));
    this.byNameKey = new Map(this.ridings.map((r) => [r.name_key, r]));

    // Land neighbours, each list in fed_id order. The adjacency table stores
    // each pair once with fed_id_a < fed_id_b, so both directions are filled
    // here — the Python engine does the same expansion inside its SQL with a
    // CASE over which end matched.
    this.landNeighbours = new Map();
    this.waterNeighbours = new Map();
    for (const riding of this.ridings) {
      this.landNeighbours.set(riding.fed_id, []);
      this.waterNeighbours.set(riding.fed_id, []);
    }
    for (const row of adjacencyRows) {
      const target = row.adjacency_type === 'land' ? this.landNeighbours : this.waterNeighbours;
      if (!target.has(row.fed_id_a) || !target.has(row.fed_id_b)) {
        throw new Error(
          `adjacency names a riding that does not exist: ${row.fed_id_a}/${row.fed_id_b}`,
        );
      }
      target.get(row.fed_id_a).push(row.fed_id_b);
      target.get(row.fed_id_b).push(row.fed_id_a);
    }
    for (const list of this.landNeighbours.values()) list.sort(compareStrings);
    for (const list of this.waterNeighbours.values()) list.sort(compareStrings);

    // Rules 0.8's designation tiers, in the CSVs' own row order — the order
    // the draws depend on, and the reason both engines read the same two files
    // rather than each deriving them (hoc/places.py says why). A place marked
    // spans_ridings = 1 is bigger than the riding it is filed under and is
    // never a designation for it; where the set has a designation_ok column,
    // only a place marked 1 is a candidate at all, in the seat's own tier and
    // its neighbours' alike. Both dropped here, as hoc/places.py drops them; a
    // set without the columns (ne-2026) loses nothing.
    this.placesByRiding = new Map();
    for (const row of placeRows) {
      if (row.spans_ridings === '1') continue;
      if (row.designation_ok !== undefined && row.designation_ok !== '1') continue;
      if (!this.placesByRiding.has(row.fed_id)) this.placesByRiding.set(row.fed_id, []);
      this.placesByRiding.get(row.fed_id).push(row.place);
    }
    this.tokensByRiding = new Map();
    for (const row of tokenRows) {
      if (!this.tokensByRiding.has(row.fed_id)) this.tokensByRiding.set(row.fed_id, []);
      this.tokensByRiding.get(row.fed_id).push(row.token);
    }

    // Per-riding integers and jurisdictions by year, where the reference set
    // has them (meridian-v1.0.3). Held so both engines load them, in the same
    // shapes as hoc/places.py's riding_stats() and riding_jurisdictions();
    // nothing in the season loop reads them yet.
    this.ridingStats = new Map();
    for (const row of statsRows) {
      const values = {};
      for (const [key, value] of Object.entries(row)) {
        if (key !== 'fed_id') values[key] = parseIntStrict(value, `riding_stats ${key}`);
      }
      this.ridingStats.set(row.fed_id, values);
    }
    this.ridingJurisdictions = new Map();
    for (const row of jurisdictionRows) {
      if (!this.ridingJurisdictions.has(row.fed_id)) this.ridingJurisdictions.set(row.fed_id, []);
      this.ridingJurisdictions.get(row.fed_id).push({
        from_year: parseIntStrict(row.from_year, 'from_year'),
        to_year: row.to_year === '' ? null : parseIntStrict(row.to_year, 'to_year'),
        unit: row.unit,
        name: row.name,
        status: row.status,
        sovereign: row.sovereign,
      });
    }

    // Every riding that has at least one land neighbour — the denominator of
    // the enclosure test, and of §10's founding roll.
    this.hasLandNeighbour = new Set(
      [...this.landNeighbours.entries()].filter(([, list]) => list.length > 0).map(([id]) => id),
    );
  }

  land(fedId) {
    return this.landNeighbours.get(fedId) ?? [];
  }

  // Land neighbours, and under rules 1.0 `water_crossings` water neighbours
  // too, in fed_id order (hoc/sim.py's IN ('land', 'water') joins).
  linked(fedId, water) {
    const land = this.land(fedId);
    if (!water) return land;
    const both = new Set([...land, ...(this.waterNeighbours.get(fedId) ?? [])]);
    return [...both].sort(compareStrings);
  }

  places(fedId) {
    return this.placesByRiding.get(fedId) ?? [];
  }

  tokens(fedId) {
    return this.tokensByRiding.get(fedId) ?? [];
  }

  riding(fedId) {
    return this.byFedId.get(fedId);
  }

  province(fedId) {
    const riding = this.byFedId.get(fedId);
    return riding ? riding.province : undefined;
  }

  nameEn(fedId) {
    const riding = this.byFedId.get(fedId);
    return riding ? riding.name_en : fedId;
  }

  // Resolve a riding by name, through the same normalisation the seed CSVs and
  // the loader use (hoc/names.py name_key).
  resolve(nameKeyValue) {
    const riding = this.byNameKey.get(nameKeyValue);
    return riding ? riding.fed_id : null;
  }
}

function parseIntStrict(text, what) {
  if (!/^-?[0-9]+$/.test(text)) throw new Error(`${what}: ${JSON.stringify(text)} is not an integer`);
  return parseInt(text, 10);
}

// The tables every reference-data set has, and the two only some have. Which
// set, and so which directory, is the caller's to say: a scenario's manifest
// names it (hoc/scenario.py REFERENCE_SETS), and the site ships the live
// scenario's set under data/reference/ whichever it is.
export const REFERENCE_TABLES = [
  'ridings.csv', 'adjacency.csv', 'places_by_riding.csv', 'riding_tokens.csv',
];
export const WORLD_TABLES = ['riding_stats.csv', 'riding_jurisdictions.csv'];

// `read(relativePath)` returns file text, exactly as web/engine/rules.js takes it.
// `tables` lists the files the set has; a WORLD_TABLES file not in it is not read.
export function loadReferenceMap(read, dir = 'data/reference', tables = REFERENCE_TABLES) {
  const table = (name) => parseCsvDicts(read(`${dir}/${name}`));
  const optional = (name) => (tables.includes(name) ? table(name) : []);
  return new ReferenceMap(
    table('ridings.csv'),
    table('adjacency.csv'),
    table('places_by_riding.csv'),
    table('riding_tokens.csv'),
    optional('riding_stats.csv'),
    optional('riding_jurisdictions.csv'),
  );
}
