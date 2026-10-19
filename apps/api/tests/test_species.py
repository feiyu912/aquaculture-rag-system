from __future__ import annotations

from app.species import GENERAL_SPECIES, detect_species, parse_species


def test_empty_species_is_general():
    assert parse_species("") == [GENERAL_SPECIES]
    assert parse_species(None) == [GENERAL_SPECIES]


def test_multiple_species_are_normalized_and_deduped():
    assert parse_species("中华绒螯蟹, 凡纳滨对虾、中华绒螯蟹") == [
        "中华绒螯蟹",
        "凡纳滨对虾",
    ]


def test_specific_species_wins_over_general_marker():
    assert parse_species("通用、凡纳滨对虾") == ["凡纳滨对虾"]


def test_detect_exact_species():
    options = [GENERAL_SPECIES, "中华绒螯蟹", "凡纳滨对虾"]
    assert detect_species("中华绒螯蟹的溶解氧要求", options) == "中华绒螯蟹"


def test_detect_ambiguous_species_returns_none():
    options = [GENERAL_SPECIES, "中华绒螯蟹", "凡纳滨对虾"]
    assert detect_species("中华绒螯蟹和凡纳滨对虾的盐度", options) is None


def test_detect_unique_suffix_alias():
    options = [GENERAL_SPECIES, "凡纳滨对虾"]
    assert detect_species("对虾养殖的盐度", options) == "凡纳滨对虾"
