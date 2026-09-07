// The reference map: 343 ridings and which of them touch.
//
// This is the one part of the engine's data that never changes during a game.
// It is loaded from the same two CSVs the Python engine reads
// (`data/reference/ridings.csv` and `data/reference/adjacency.csv`), which are
// built from Elections Canada's 2023 Representation Order by
// `scripts/build_ridings.py` and `scripts/build_adjacency.py` — never authored
// by hand, in either engine.

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
  constructor(ridingRows, adjacencyRows) {
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

    // Every riding that has at least one land neighbour — the denominator of
    // the enclosure test, and of §10's founding roll.
    this.hasLandNeighbour = new Set(
      [...this.landNeighbours.entries()].filter(([, list]) => list.length > 0).map(([id]) => id),
    );
  }

  land(fedId) {
    return this.landNeighbours.get(fedId) ?? [];
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

// `read(relativePath)` returns file text, exactly as web/engine/rules.js takes it.
export function loadReferenceMap(read) {
  return new ReferenceMap(
    parseCsvDicts(read('data/reference/ridings.csv')),
    parseCsvDicts(read('data/reference/adjacency.csv')),
  );
}
