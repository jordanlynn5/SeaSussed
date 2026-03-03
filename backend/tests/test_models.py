"""Tests for model construction and validation."""

from models import (
    AnalyzeResponse,
    PageAnalysis,
    PageProduct,
    ProductInfo,
    ScoreBreakdown,
    SustainabilityScore,
)


def test_product_info_without_product_name() -> None:
    """ProductInfo construction without product_name still works (backward compat)."""
    pi = ProductInfo(
        is_seafood=True,
        species="Atlantic salmon",
        wild_or_farmed="farmed",
        fishing_method=None,
        origin_region="Norway",
        certifications=["ASC"],
    )
    assert pi.product_name is None
    assert pi.species == "Atlantic salmon"


def test_product_info_with_product_name() -> None:
    """ProductInfo with product_name populates correctly."""
    pi = ProductInfo(
        is_seafood=True,
        species="sockeye salmon",
        wild_or_farmed="wild",
        fishing_method="Purse seine",
        origin_region="Alaska",
        certifications=["MSC"],
        product_name="365 Wild Caught Sockeye Salmon Fillet",
    )
    assert pi.product_name == "365 Wild Caught Sockeye Salmon Fillet"
    assert pi.species == "sockeye salmon"


def test_page_analysis_single_product() -> None:
    pi = ProductInfo(
        is_seafood=True,
        species="cod",
        wild_or_farmed="wild",
        fishing_method=None,
        origin_region=None,
        certifications=[],
    )
    pa = PageAnalysis(page_type="single_product", products=[pi])
    assert pa.page_type == "single_product"
    assert len(pa.products) == 1


def test_page_analysis_product_listing() -> None:
    products = [
        ProductInfo(
            is_seafood=True,
            species=f"species_{i}",
            wild_or_farmed="wild",
            fishing_method=None,
            origin_region=None,
            certifications=[],
        )
        for i in range(3)
    ]
    pa = PageAnalysis(page_type="product_listing", products=products)
    assert pa.page_type == "product_listing"
    assert len(pa.products) == 3


def test_page_analysis_no_seafood() -> None:
    pa = PageAnalysis(page_type="no_seafood", products=[])
    assert pa.page_type == "no_seafood"
    assert pa.products == []


def test_page_product_holds_score_summary() -> None:
    pp = PageProduct(
        product_name="Wild Salmon Fillet",
        species="sockeye salmon",
        wild_or_farmed="wild",
        certifications=["MSC"],
        score=82,
        grade="A",
        breakdown=ScoreBreakdown(
            biological=16, practices=20, management=26, ecological=20
        ),
    )
    assert pp.score == 82
    assert pp.grade == "A"
    assert pp.breakdown.biological == 16


def test_analyze_response_single_product() -> None:
    """AnalyzeResponse wraps single-product result."""
    score = SustainabilityScore(
        score=75,
        grade="B",
        breakdown=ScoreBreakdown(
            biological=14, practices=18, management=24, ecological=19
        ),
        alternatives=[],
        alternatives_label="",
        explanation="Good choice.",
        score_factors=[],
        product_info=ProductInfo(
            is_seafood=True,
            species="cod",
            wild_or_farmed="wild",
            fishing_method=None,
            origin_region=None,
            certifications=[],
        ),
    )
    resp = AnalyzeResponse(page_type="single_product", result=score)
    assert resp.page_type == "single_product"
    assert resp.result is not None
    assert resp.result.score == 75
    assert resp.products == []


def test_analyze_response_multi_product() -> None:
    """AnalyzeResponse wraps multi-product list."""
    products = [
        PageProduct(
            product_name=f"Product {i}",
            species=f"species_{i}",
            wild_or_farmed="wild",
            certifications=[],
            score=80 - i * 10,
            grade="A" if i == 0 else "B",
            breakdown=ScoreBreakdown(
                biological=15, practices=18, management=25, ecological=22
            ),
        )
        for i in range(3)
    ]
    resp = AnalyzeResponse(page_type="product_listing", products=products)
    assert resp.page_type == "product_listing"
    assert resp.result is None
    assert len(resp.products) == 3
