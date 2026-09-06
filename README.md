# House of Cards

Collaborative alternate-history worldbuilding game set in an alternate 1867 Canadian Confederation. Fictional noble houses hold peerages mapped onto the 343 real federal electoral districts of the 2023 Representation Order.

Source of truth: `hoc.db` (SQLite). The Excel workbook, CSV/JSON dumps and riding map in `outputs/` are generated views, never edited by hand.

Run a turn (after Phase 5 of the build plan):

    python -m hoc turn "directive text"

Run tests:

    python -m pytest

See `CLAUDE.md` for game rules and working conventions, and `docs/BUILD_PLAN.md` for the migration phases.
