"""Tests for the Phase 9b rules-table loader (hoc/rules_data.py).

This is a transcription-and-validation pass only: nothing here runs a season,
because the engine that would (Phase 9c) doesn't exist yet.
"""

from hoc.rules_data import load_rules, probability_for_age

# One row per action in docs/ENGINE_DESIGN.md §7, counted by hand from the
# table there: Expand, Invest, Cultivate influence, Correspond, Propose
# compact, Name heir, Endow, Petition elevation, Dispute, Challenge (11b),
# Reconcile, Consolidate (rest), Purchase riding, Marriage alliance, Absorb,
# Cede / swap, Partition.
EXPECTED_ACTION_COUNT = 17


def test_load_rules_succeeds():
    bundle = load_rules()
    assert bundle.actions
    assert bundle.objectives
    assert bundle.mortality
    assert bundle.eras
    assert bundle.founding
    assert bundle.succession
    assert bundle.responses


def test_action_count_matches_design_document_section_7():
    bundle = load_rules()
    assert len(bundle.actions) == EXPECTED_ACTION_COUNT


def test_mortality_table_matches_the_design_document():
    bundle = load_rules()
    assert probability_for_age(bundle.mortality, 45) == 0.01
    assert probability_for_age(bundle.mortality, 95) == 0.20


def test_eras_cover_1867_onward_with_no_gap():
    bundle = load_rules()
    eras = sorted(bundle.eras, key=lambda e: e.start_year)

    assert eras[0].start_year == 1867
    for previous, current in zip(eras, eras[1:]):
        assert previous.end_year is not None
        assert current.start_year == previous.end_year + 1
    assert eras[-1].end_year is None  # open-ended: the era structure never runs out
