# House of Cards

Collaborative alternate-history worldbuilding game set in an alternate 1867 Canadian Confederation. Fictional noble houses hold peerages mapped onto the 343 real federal electoral districts of the 2023 Representation Order.

Source of truth: `hoc.db` (SQLite). The Excel workbook, CSV/JSON dumps and riding map in `outputs/` are generated views, never edited by hand.

Run a turn (after Phase 5 of the build plan):

    python -m hoc turn "directive text"

Run tests:

    python -m pytest

## Rebuilding the database

    python scripts/rebuild.py

`scripts/rebuild.py` is the reproducible path: it loads the seed and then replays every `turns/*.json` in turn order, so the database is reconstructed from files under version control. `hoc.db` is committed as a convenience — the seed CSVs plus the turn files are the record, and the database is what they produce.

To load the seed alone, without replaying any turns:

    python scripts/load_seed.py

`hoc.db` is a derived artefact. The loader deletes and rebuilds it from scratch out of `data/reference/*.csv` (343 ridings and their land adjacency, from the 2023 Representation Order boundaries) and `data/seed/*.csv` (the reconstructed houses, holdings, holders, successions, climate ledgers and relations), then prints a row count per table. Run it after any reconstruction commit that changes the seed. The reference CSVs themselves are rebuilt from the raw boundary file by `scripts/build_ridings.py`, `scripts/build_adjacency.py` and `scripts/build_geometry.py` — see `data/reference/raw/SOURCE.md` for provenance.

See `CLAUDE.md` for game rules and working conventions, `docs/RECONSTRUCTION.md` for what is reconstructed and what is still missing, and `docs/BUILD_PLAN.md` for the migration phases.
