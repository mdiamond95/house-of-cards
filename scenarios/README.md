# scenarios/

One directory per game. `current.txt` names the scenario `hoc.db` is built from; everything that loads, rebuilds or exports reads it through `hoc/scenario.py` rather than hard-coding a path.

- **legacy/** — the reconstructed 2026 playthrough, frozen. Its record is `seed/` (the audited reconstruction, changed only by a reconstruction commit as `RECONSTRUCTION.md` defines) plus `turns/*.json`, replayed in order by `scripts/rebuild.py`.
- **new/** — the live autoplay game. Its seed CSVs hold headers only: the engine generates every house from a world seed. Its record is `seasons/NNNN.json`, one file per played season, replayed the same way.

Switch with `python -m hoc scenario use <name>`, then rebuild. `python -m hoc scenario list` shows what exists and which is active.
