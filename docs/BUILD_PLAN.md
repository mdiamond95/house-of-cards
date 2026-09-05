# Build plan (condensed)

Full narrative version lives with the director. Phases and exit criteria:

0. Repository and cloud environment — repo exists, GitHub App connected, environment created, seed files merged. (This scaffold session.)
1. Freeze and extract — `scripts/extract.py` reads the baseline workbook into `data/extract/*.json` with a reconciliation report (expect 33 active + 2 removed houses, ~145 ridings). Exit: director resolves unclassified cells.
2. Reference data — `ridings` (343, 2023 Representation Order) and `adjacency` (land vs water-only) from Elections Canada boundaries; simplified geometry retained. Exit: every tracker riding resolves to exactly one reference row.
3. Schema — `hoc/schema.sql` with houses, holders, holdings (seat_order), colours view, clocks, events, relations, climate, watch/threads/handoff; `hoc.db` committed. Exit: extract loads with zero constraint violations.
4. Rules engine — `hoc/rules.py`: validate_expansion, primary_colour, advance/sync clocks, succeed, climate_shift, cohort_fit, elevate; tests from real logged cases. Exit: suite green.
5. Turn runner — `python -m hoc turn "..."`: transaction, rules, event+narrative, commit/rollback, exporters. Exit: one historical turn replays correctly.
6. Exporters — workbook in current layout, CSV/JSON dump, riding map SVG. Exit: generated workbook diffs cleanly against baseline.
7. Parity run and cutover — next real turn run both ways, diff, retire manual edits.

Backlog: nine TBD secondary colours; full climate replay from 1867; per-house timeline SVG; routine to regenerate outputs on push.
