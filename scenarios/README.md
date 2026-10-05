# scenarios/

One directory per game. `current.txt` names the scenario `hoc.db` is built from; everything that loads, rebuilds or exports reads it through `hoc/scenario.py` rather than hard-coding a path.

- **legacy/** — the reconstructed 2026 playthrough, frozen. Its record is `seed/` (the audited reconstruction, changed only by a reconstruction commit as `RECONSTRUCTION.md` defines) plus `turns/*.json`, replayed in order by `scripts/rebuild.py`.
- **new/** — The First Dominion, an autoplay game frozen at season 150 and published in the Archive. Its seed CSVs hold headers only: the engine generates every house from a world seed. Its record is `seasons/NNNN.json`, one file per played season, replayed the same way.
- **dominion/** — The Dominion, the live autoplay game: the same layout as `new/`, on the `meridian-v1.0.3` world under rules 0.9 (`docs/ENGINE_DESIGN.md` §18). Seed 1867, its first house seated by the engine's own draw.

Switch with `python -m hoc scenario use <name>`, then rebuild. `python -m hoc scenario list` shows what exists and which is active.
