"""Tests for explanation and score_factors generation.

Tests without Gemini credentials verify the fallback path returns valid
structure. Tests requiring credentials (skipped in CI) verify the Gemini
honesty rule: explicitly states what was and was not visible on the page.
"""

import os

import pytest

from explanation import generate_content, generate_template_content
from models import ProductInfo, ScoreBreakdown

_HAS_CREDENTIALS = bool(os.environ.get("GOOGLE_CLOUD_PROJECT"))


def test_generate_content_returns_valid_structure() -> None:
    """generate_content always returns (str, list[ScoreFactor]) with 4 factors."""
    product = ProductInfo(
        is_seafood=True,
        species="Alaska sockeye salmon",
        wild_or_farmed="wild",
        fishing_method="Purse seine (without FAD)",
        origin_region="Bristol Bay, Alaska",
        certifications=["MSC"],
    )
    breakdown = ScoreBreakdown(
        biological=15.0, practices=19.5, management=30.0, ecological=16.0
    )
    explanation, score_factors = generate_content(product, breakdown, 80, "A")
    assert isinstance(explanation, str)
    assert len(explanation) > 10
    assert len(score_factors) == 4
    for factor in score_factors:
        assert factor.category
        assert factor.score >= 0
        assert factor.max_score > 0


def test_fallback_mentions_species_name() -> None:
    """Both Gemini and fallback paths mention the species name in the explanation."""
    product = ProductInfo(
        is_seafood=True,
        species="Alaska sockeye salmon",
        wild_or_farmed="wild",
        fishing_method="Purse seine (without FAD)",
        origin_region="Bristol Bay, Alaska",
        certifications=["MSC"],
    )
    breakdown = ScoreBreakdown(
        biological=15.0, practices=19.5, management=30.0, ecological=16.0
    )
    explanation, _ = generate_content(product, breakdown, 80, "A")
    has_specific = any(
        kw in explanation.lower() for kw in ["salmon", "alaska", "msc", "wild"]
    )
    assert has_specific, f"Explanation too generic: {explanation}"


def test_grade_a_has_no_tips() -> None:
    """Grade A products must never have tips (tips are for C/D only)."""
    product = ProductInfo(
        is_seafood=True,
        species="Pacific oyster",
        wild_or_farmed="farmed",
        fishing_method=None,
        origin_region="Pacific Northwest",
        certifications=["ASC"],
    )
    breakdown = ScoreBreakdown(
        biological=17.0, practices=20.0, management=22.0, ecological=22.0
    )
    _, score_factors = generate_content(product, breakdown, 81, "A")
    for factor in score_factors:
        assert factor.tip is None, (
            f"Grade A should have no tips, but got tip in '{factor.category}': {factor.tip}"
        )


def test_grade_d_produces_score_factors() -> None:
    """Grade D products produce 4 score factors (may include tips)."""
    product = ProductInfo(
        is_seafood=True,
        species="bluefin tuna",
        wild_or_farmed="wild",
        fishing_method="Longline (surface)",
        origin_region="Atlantic",
        certifications=[],
    )
    breakdown = ScoreBreakdown(
        biological=9.8, practices=15.0, management=5.0, ecological=10.0
    )
    _, score_factors = generate_content(product, breakdown, 39, "D")
    assert len(score_factors) == 4


def test_template_returns_valid_structure() -> None:
    """generate_template_content returns (str, 4 ScoreFactors) with no API calls."""
    product = ProductInfo(
        is_seafood=True,
        species="Atlantic cod",
        wild_or_farmed="wild",
        fishing_method="Trawl",
        origin_region="North Atlantic",
        certifications=["MSC"],
    )
    breakdown = ScoreBreakdown(
        biological=15.0, practices=18.0, management=25.0, ecological=16.0
    )
    explanation, factors = generate_template_content(product, breakdown, 74, "B")
    assert isinstance(explanation, str)
    assert "cod" in explanation.lower()
    assert "74/100" in explanation
    assert len(factors) == 4
    for f in factors:
        assert f.score >= 0
        assert f.max_score > 0
        assert len(f.explanation) > 5


def test_template_grade_a_has_no_tips() -> None:
    """Template grade A products have no tips."""
    product = ProductInfo(
        is_seafood=True,
        species="sockeye salmon",
        wild_or_farmed="wild",
        fishing_method="Purse seine",
        origin_region="Alaska",
        certifications=["MSC"],
    )
    breakdown = ScoreBreakdown(
        biological=16.0, practices=20.0, management=28.0, ecological=20.0
    )
    _, factors = generate_template_content(product, breakdown, 84, "A")
    for f in factors:
        assert f.tip is None, f"Grade A should have no tips: {f.category}"


def test_template_grade_d_has_tips() -> None:
    """Template grade D products have tips for weak categories."""
    product = ProductInfo(
        is_seafood=True,
        species="bluefin tuna",
        wild_or_farmed="unknown",
        fishing_method=None,
        origin_region=None,
        certifications=[],
    )
    breakdown = ScoreBreakdown(
        biological=5.0, practices=8.0, management=5.0, ecological=8.0
    )
    explanation, factors = generate_template_content(product, breakdown, 26, "D")
    # Should mention unknown fields
    assert "not visible" in explanation.lower() or "unknown" in explanation.lower()
    # At least some factors should have tips
    tips = [f.tip for f in factors if f.tip is not None]
    assert len(tips) > 0


def test_template_mentions_certifications() -> None:
    """Template mentions visible certifications in management factor."""
    product = ProductInfo(
        is_seafood=True,
        species="salmon",
        wild_or_farmed="wild",
        fishing_method=None,
        origin_region=None,
        certifications=["MSC", "ASMI"],
    )
    breakdown = ScoreBreakdown(
        biological=14.0, practices=12.0, management=22.0, ecological=15.0
    )
    _, factors = generate_template_content(product, breakdown, 63, "B")
    mgmt = [f for f in factors if f.category == "Management & Regulation"][0]
    assert "MSC" in mgmt.explanation


@pytest.mark.skipif(
    not _HAS_CREDENTIALS, reason="Requires GOOGLE_CLOUD_PROJECT for Gemini call"
)
def test_explanation_mentions_visible_fields() -> None:
    """Gemini explanation must reference visible species and origin fields."""
    product = ProductInfo(
        is_seafood=True,
        species="Alaska sockeye salmon",
        wild_or_farmed="wild",
        fishing_method="Purse seine (without FAD)",
        origin_region="Bristol Bay, Alaska",
        certifications=["MSC"],
    )
    breakdown = ScoreBreakdown(
        biological=15.0, practices=19.5, management=30.0, ecological=16.0
    )
    explanation, _ = generate_content(product, breakdown, 80, "A")
    assert len(explanation) > 30
    has_specific = any(
        kw in explanation.lower() for kw in ["salmon", "alaska", "msc", "wild"]
    )
    assert has_specific, f"Explanation too generic: {explanation}"


@pytest.mark.skipif(
    not _HAS_CREDENTIALS, reason="Requires GOOGLE_CLOUD_PROJECT for Gemini call"
)
def test_explanation_acknowledges_unknown_method() -> None:
    """Gemini explanation must note unknown/missing fields per honesty rule."""
    product = ProductInfo(
        is_seafood=True,
        species="Atlantic salmon",
        wild_or_farmed="unknown",
        fishing_method=None,
        origin_region=None,
        certifications=[],
    )
    breakdown = ScoreBreakdown(
        biological=8.0, practices=10.0, management=7.0, ecological=14.0
    )
    explanation, _ = generate_content(product, breakdown, 39, "D")
    uncertainty_words = [
        "unknown",
        "not shown",
        "wasn't visible",
        "couldn't",
        "not visible",
        "wasn't shown",
        "default",
        "assumed",
    ]
    has_uncertainty = any(w in explanation.lower() for w in uncertainty_words)
    assert has_uncertainty, f"Explanation should acknowledge unknowns: {explanation}"
