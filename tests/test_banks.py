"""Tests for the Phase 9b-2 data banks (event deck, communities, names, places).

Transcription-and-validation only, same as tests/test_rules_data.py: nothing
here runs a season, because the engine that would (Phase 9c) doesn't exist yet.
"""

import csv
from collections import Counter, defaultdict
from pathlib import Path

from hoc.rules_data import load_rules

VALID_TAGS = {"Progressive", "Conservative", "Mixed", "Global"}
VALID_MAGNITUDES = {"Minor", "Significant", "Major"}


def _province_codes_in_ridings():
    path = Path("data/reference/ridings.csv")
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {row["province"] for row in rows}


def test_every_naming_tradition_has_both_genders():
    bundle = load_rules()
    genders_by_tradition = defaultdict(set)
    for name in bundle.given_names:
        genders_by_tradition[name.tradition].add(name.gender)

    for community in bundle.communities:
        tradition = community.naming_tradition
        genders = genders_by_tradition.get(tradition, set())
        assert "m" in genders and "f" in genders, (
            f"naming_tradition {tradition!r} (used by community"
            f" {community.community!r}) is missing an 'm' or 'f' entry in"
            " given_names.csv"
        )


def test_every_community_has_at_least_15_surnames():
    bundle = load_rules()
    counts = Counter(s.community for s in bundle.surnames)
    for community in bundle.communities:
        assert counts.get(community.community, 0) >= 15, (
            f"community {community.community!r} has only"
            f" {counts.get(community.community, 0)} surnames, needs at least 15"
        )


def test_no_surname_in_more_than_three_communities():
    bundle = load_rules()
    communities_by_surname = defaultdict(set)
    for s in bundle.surnames:
        communities_by_surname[s.surname].add(s.community)

    offenders = {
        surname: sorted(communities)
        for surname, communities in communities_by_surname.items()
        if len(communities) > 3
    }
    assert not offenders, (
        "surnames shared by more than three communities:"
        f" {offenders} (see rules/CHANGELOG.md 0.2)"
    )


def test_events_non_empty_for_each_era_band():
    bundle = load_rules()
    for era in bundle.eras:
        end = era.end_year if era.end_year is not None else float("inf")
        matching = [
            e for e in bundle.events if era.start_year <= e.personal_year <= end
        ]
        assert matching, f"era band {era.name!r} has no events"


def test_event_tags_and_magnitudes_and_years():
    bundle = load_rules()
    for event in bundle.events:
        assert event.tag in VALID_TAGS, (
            f"event {event.name!r}: tag {event.tag!r} is not one of {VALID_TAGS}"
        )
        assert event.magnitude in VALID_MAGNITUDES, (
            f"event {event.name!r}: magnitude {event.magnitude!r} is not one of"
            f" {VALID_MAGNITUDES}"
        )
        assert event.personal_year >= 1867, (
            f"event {event.name!r}: personal_year {event.personal_year} precedes 1867"
        )


def test_every_place_province_matches_ridings_and_has_at_least_8_places():
    bundle = load_rules()
    riding_provinces = _province_codes_in_ridings()

    counts = Counter(p.province for p in bundle.places)
    for province in counts:
        assert province in riding_provinces, (
            f"places.csv province {province!r} does not match any province"
            " code in data/reference/ridings.csv"
        )
    for province in riding_provinces:
        if province in counts:
            assert counts[province] >= 8, (
                f"province {province!r} has only {counts[province]} places,"
                " needs at least 8"
            )


def test_region_weights_positive_and_founding_regions_have_three_communities():
    bundle = load_rules()

    weight_by_region = defaultdict(float)
    community_count_by_region = Counter()
    for community in bundle.communities:
        weight_by_region[community.region] += community.weight
        community_count_by_region[community.region] += 1

    for region, total in weight_by_region.items():
        assert total > 0, f"region {region!r} has a non-positive total weight ({total})"

    founding_regions = bundle.founding["region_weights"]["initial"].keys()
    for region in founding_regions:
        count = community_count_by_region.get(region.lower(), 0)
        assert count >= 3, (
            f"founding region {region!r} has only {count} communities,"
            " needs at least 3"
        )
