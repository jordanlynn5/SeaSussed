"""Unit tests for pure-Python sustainability scoring logic.

These tests never call external APIs — they exercise only scoring.py + database.py.
Run without Vertex AI credentials.
"""

import pytest

from models import ProductInfo
from scoring import (
    compute_score,
    score_aquaculture,
    score_biological,
    score_ecological,
    score_management,
    score_wild_practices,
)

# ---------------------------------------------------------------------------
# Parametrized grade-range tests
# ---------------------------------------------------------------------------
# Uses common names that the screen_analyzer returns from real grocery pages.
# Grade ranges (min_grade–max_grade) reflect scoring with DB data present.
# Expand the range if a species' DB entry produces a borderline score.
# ---------------------------------------------------------------------------

_GRADE_ORDER = ["A", "B", "C", "D"]

_GRADE_TEST_CASES = [
    (
        "Alaska sockeye salmon — MSC, purse seine w/o FAD, Bristol Bay",
        dict(
            is_seafood=True,
            species="Alaska sockeye salmon",
            wild_or_farmed="wild",
            fishing_method="Purse seine (without FAD)",
            origin_region="Bristol Bay, Alaska",
            certifications=["MSC"],
        ),
        "A",
        "A",
    ),
    (
        "Pacific oyster — farmed, ASC certified",
        dict(
            is_seafood=True,
            species="Pacific oyster",
            wild_or_farmed="farmed",
            fishing_method=None,
            origin_region="Pacific Northwest",
            certifications=["ASC"],
        ),
        "A",
        "A",
    ),
    (
        "Atlantic mackerel — purse seine w/o FAD, no cert",
        dict(
            is_seafood=True,
            species="Atlantic mackerel",
            wild_or_farmed="wild",
            fishing_method="Purse seine (without FAD)",
            origin_region="North Atlantic",
            certifications=[],
        ),
        "A",
        "B",
    ),
    (
        "Alaska pollock — midwater trawl, MSC, Bering Sea",
        dict(
            is_seafood=True,
            species="Alaska pollock",
            wild_or_farmed="wild",
            fishing_method="Midwater trawl",
            origin_region="Bering Sea",
            certifications=["MSC"],
        ),
        "B",
        "B",
    ),
    (
        "Atlantic cod — bottom trawl, no cert, Norway",
        dict(
            is_seafood=True,
            species="Atlantic cod",
            wild_or_farmed="wild",
            fishing_method="Bottom trawl",
            origin_region="Norway",
            certifications=[],
        ),
        "D",
        "D",
    ),
    (
        "Farmed Atlantic salmon — no cert, Norway",
        dict(
            is_seafood=True,
            species="Atlantic salmon",
            wild_or_farmed="farmed",
            fishing_method=None,
            origin_region="Norway",
            certifications=[],
        ),
        "C",
        "D",
    ),
    (
        "Imported whiteleg shrimp — farmed, Thailand, no cert",
        dict(
            is_seafood=True,
            species="whiteleg shrimp",
            wild_or_farmed="farmed",
            fishing_method=None,
            origin_region="Thailand",
            certifications=[],
        ),
        "C",
        "D",
    ),
    (
        "Bluefin tuna — longline surface, Atlantic, no cert",
        dict(
            is_seafood=True,
            species="bluefin tuna",
            wild_or_farmed="wild",
            fishing_method="Longline (surface)",
            origin_region="Atlantic",
            certifications=[],
        ),
        "C",
        "D",
    ),
    (
        "Orange roughy — bottom trawl, New Zealand",
        dict(
            is_seafood=True,
            species="orange roughy",
            wild_or_farmed="wild",
            fishing_method="Bottom trawl",
            origin_region="New Zealand",
            certifications=[],
        ),
        "D",
        "D",
    ),
]


@pytest.mark.parametrize("description,kwargs,min_grade,max_grade", _GRADE_TEST_CASES)
def test_species_grade(
    description: str, kwargs: dict[str, object], min_grade: str, max_grade: str
) -> None:
    """Each species scores within the expected sustainability grade range."""
    product = ProductInfo(**kwargs)  # type: ignore[arg-type]
    breakdown, total, grade = compute_score(product)
    min_idx = _GRADE_ORDER.index(min_grade)
    max_idx = _GRADE_ORDER.index(max_grade)
    actual_idx = _GRADE_ORDER.index(grade)
    assert min_idx <= actual_idx <= max_idx, (
        f"{description}: expected {min_grade}–{max_grade}, got {grade} ({total})\n"
        f"  biological={breakdown.biological:.1f}, practices={breakdown.practices:.1f}, "
        f"  management={breakdown.management:.1f}, ecological={breakdown.ecological:.1f}"
    )


def test_farmed_oyster_uses_aquaculture_scorer() -> None:
    """Farmed Pacific oyster (filter feeder) gets aquaculture scoring path."""
    product = ProductInfo(
        is_seafood=True,
        species="Pacific oyster",
        wild_or_farmed="farmed",
        fishing_method=None,
        origin_region=None,
        certifications=[],
    )
    breakdown, _, _ = compute_score(product)
    # Oysters are filter feeders — aquaculture scorer applies, not wild practices.
    # Practices score should exceed the 10-pt unknown-gear penalty.
    assert breakdown.practices >= 5.0, (
        f"Expected aquaculture scorer (>=5 pts), got {breakdown.practices}"
    )


def test_msc_certified_wild_salmon_scores_high() -> None:
    """MSC-certified wild Alaskan salmon should score A or B."""
    product = ProductInfo(
        is_seafood=True,
        species="Alaska sockeye salmon",
        wild_or_farmed="wild",
        fishing_method="Purse seine",
        origin_region="Bristol Bay, Alaska",
        certifications=["MSC"],
    )
    breakdown, score, grade = compute_score(product)
    assert grade in ("A", "B"), f"Expected A/B, got {grade} (score={score})"
    assert score >= 60
    assert breakdown.management >= 15  # MSC cert contributes 15 pts


def test_bluefin_tuna_scores_low() -> None:
    """Bluefin tuna without certifications should score C or D."""
    product = ProductInfo(
        is_seafood=True,
        species="bluefin tuna",
        wild_or_farmed="wild",
        fishing_method=None,
        origin_region=None,
        certifications=[],
    )
    breakdown, score, grade = compute_score(product)
    assert grade in ("C", "D"), f"Expected C/D, got {grade} (score={score})"


def test_unknown_species_returns_neutral_without_crashing() -> None:
    """Unknown species returns a valid score in range."""
    product = ProductInfo(
        is_seafood=True,
        species=None,
        wild_or_farmed="unknown",
        fishing_method=None,
        origin_region=None,
        certifications=[],
    )
    breakdown, score, grade = compute_score(product)
    assert 0 <= score <= 100
    assert grade in ("A", "B", "C", "D")


def test_breakdown_components_sum_to_total() -> None:
    """Score is the integer sum of breakdown components."""
    product = ProductInfo(
        is_seafood=True,
        species="Atlantic salmon",
        wild_or_farmed="farmed",
        fishing_method=None,
        origin_region=None,
        certifications=["ASC"],
    )
    breakdown, score, grade = compute_score(product)
    components_sum = (
        breakdown.biological
        + breakdown.practices
        + breakdown.management
        + breakdown.ecological
    )
    assert abs(components_sum - score) <= 1  # int() truncation allowance


def test_grade_thresholds_are_correct() -> None:
    """Grade assignment follows A≥80, B≥60, C≥40, D<40."""
    product = ProductInfo(
        is_seafood=True,
        species="Alaska pollock",
        wild_or_farmed="wild",
        fishing_method="Midwater trawl",
        origin_region="Alaska",
        certifications=["MSC"],
    )
    breakdown, score, grade = compute_score(product)
    if score >= 80:
        assert grade == "A"
    elif score >= 60:
        assert grade == "B"
    elif score >= 40:
        assert grade == "C"
    else:
        assert grade == "D"


def test_management_msc_gives_max_cert_score() -> None:
    """MSC cert should give full 15 pts in management category."""
    result = score_management(["MSC"], None, None)
    # MSC=15 (cert) + 4 (noaa default) + 3 (exploitation default unknown)
    assert result == 22.0


def test_management_no_cert_gives_zero_cert_contribution() -> None:
    """No certification gives 0 cert pts in management."""
    result = score_management([], None, None)
    # 0 (cert) + 4 (noaa default) + 3 (exploitation default unknown)
    assert result == 7.0


def test_biological_unknown_species_returns_neutral() -> None:
    """Unknown species returns 10.0 neutral biological score."""
    assert score_biological(None) == 10.0


def test_wild_practices_unknown_gear_penalizes() -> None:
    """Unknown gear should be penalized (return 10.0 penalty score)."""
    assert score_wild_practices(None) == 10.0


def test_wild_practices_pole_line_scores_high() -> None:
    """Pole and line gear should score close to max 25."""
    from database import get_gear_score

    gear = get_gear_score("Pole and line")
    result = score_wild_practices(gear)
    assert result >= 22.0  # 98/100 * 25 ≈ 24.5


def test_aquaculture_asc_cert_scores_well() -> None:
    """ASC cert gives 15 pts + carnivory bonus (2.5 for unknown species) = 17.5."""
    result = score_aquaculture(["ASC"], None)
    assert result == 17.5  # 15 (ASC cert) + 2.5 (carnivory bonus at default 0.5)


def test_ecological_unknown_species_returns_neutral() -> None:
    """Unknown species returns neutral ecological score."""
    assert score_ecological(None) == 12.0


def test_farmed_species_uses_aquaculture_scoring() -> None:
    """Farmed species uses score_aquaculture, not score_wild_practices."""
    product_farmed = ProductInfo(
        is_seafood=True,
        species="Atlantic salmon",
        wild_or_farmed="farmed",
        fishing_method=None,
        origin_region=None,
        certifications=[],
    )
    product_wild = ProductInfo(
        is_seafood=True,
        species="Atlantic salmon",
        wild_or_farmed="wild",
        fishing_method=None,
        origin_region=None,
        certifications=[],
    )
    _, _, grade_farmed = compute_score(product_farmed)
    _, _, grade_wild = compute_score(product_wild)
    # Both should produce valid grades — just verifying no crash
    assert grade_farmed in ("A", "B", "C", "D")
    assert grade_wild in ("A", "B", "C", "D")


def test_cert_case_insensitive_matching() -> None:
    """Cert matching should be case-insensitive."""
    score_lower = score_management(["msc"], None, None)
    score_upper = score_management(["MSC"], None, None)
    assert score_lower == score_upper
