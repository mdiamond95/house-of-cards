// Standings (docs/STORY_DESIGN.md §3.3).
//
// Phase A's standing is provisional and the story layer's own: per_holding ×
// ridings held + per_rank × rank index (weights.json `standing`), folded from
// beats. It is never read by either engine. From Phase C the engine's prestige
// replaces it.
//
// A board is { owners: {fed_id: house}, ranks: {house: rank index},
// removed: [house] } — plain data, so it can be shipped, stored and compared.
// Pure functions: nothing here mutates its arguments.

import { compareText } from './beats.js';

export function emptyBoard() {
  return { owners: {}, ranks: {}, removed: [] };
}

export function copyBoard(board) {
  return {
    owners: { ...(board.owners || {}) },
    ranks: { ...(board.ranks || {}) },
    removed: [...(board.removed || [])],
  };
}

// The board after `beats`, in their order.
export function applyBeats(board, beats) {
  const next = copyBoard(board);
  const removed = new Set(next.removed);
  for (const beat of beats) {
    for (const [fed, house] of Object.entries(beat.owners || {})) {
      if (house === null) delete next.owners[fed];
      else next.owners[fed] = house;
    }
    for (const [house, rank] of Object.entries(beat.ranks || {})) next.ranks[house] = rank;
    for (const house of beat.removed || []) removed.add(house);
  }
  next.removed = [...removed].sort(compareText);
  return next;
}

// Every house still standing, best first: score, then ridings, then name.
// A house is standing once the board knows its rank and until it is removed.
export function table(board, weights) {
  const per = weights.standing;
  const holdings = new Map();
  for (const house of Object.values(board.owners)) {
    holdings.set(house, (holdings.get(house) || 0) + 1);
  }
  const removed = new Set(board.removed);
  const rows = [];
  for (const [house, rank] of Object.entries(board.ranks)) {
    if (removed.has(house)) continue;
    const held = holdings.get(house) || 0;
    rows.push({ house, holdings: held, rank, score: per.per_holding * held + per.per_rank * rank });
  }
  rows.sort((a, b) => b.score - a.score || b.holdings - a.holdings || compareText(a.house, b.house));
  return rows.map((row, i) => ({ ...row, place: i + 1 }));
}

export function cast(rows, weights) {
  return rows.slice(0, weights.cast_size);
}

// The top `cast_size` with movement since `before` (the previous turn's table):
// 'up', 'down', 'same', or 'new' for a house that was not in the cast before.
export function movement(before, after, weights) {
  const was = new Map(cast(before, weights).map((row) => [row.house, row.place]));
  return cast(after, weights).map((row) => {
    if (!was.has(row.house)) return { ...row, move: 'new', was: null };
    const prior = was.get(row.house);
    const move = row.place < prior ? 'up' : row.place > prior ? 'down' : 'same';
    return { ...row, move, was: prior };
  });
}
