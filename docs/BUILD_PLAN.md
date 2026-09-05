# Build plan (condensed)

Full narrative version lives with the director. Phases and exit criteria:

0. Repository and cloud environment — repo exists, GitHub App connected, environment created, seed files merged. (This scaffold session.)
1. Reconstruct — seed CSVs recovered from transcripts committed to `data/seed/` with provenance in docs/RECONSTRUCTION.md; `tests/test_seed.py` guards the counts. Further reconstruction (holders, clocks, matrix, climate, events) lands as additional seed files in later sessions. Exit: seed tests green; director accepts the reconstruction record.
2. Reference data — `ridings` (343, 2023 Representation Order) and `adjacency` (land vs water-only) from Elections Canada boundaries; simplified geometry retained. Exit: every tracker riding resolves to exactly one reference row.
3. Schema — `hoc/schema.sql` with houses, holders, holdings (seat_order), colours view, clocks, events, relations, climate, watch/threads/handoff; `hoc.db` committed. Exit: extract loads with zero constraint violations.
4. Rules engine — `hoc/rules.py`: validate_expansion, primary_colour, advance/sync clocks, succeed, climate_shift, cohort_fit, elevate; tests from real logged cases. Exit: suite green.
5. Turn runner — `python -m hoc turn "..."`: transaction, rules, event+narrative, commit/rollback, exporters. Exit: one historical turn replays correctly.
6. Exporters — workbook in current layout, CSV/JSON dump, riding map SVG. Exit: generated workbook diffs cleanly against baseline.

Backlog: nine TBD secondary colours; full climate replay from 1867; per-house timeline SVG; routine to regenerate outputs on push; recover per-riding settler/generation/notes and Section 5 house blocks from transcripts.
