"""Tests for model construction and validation."""

from models import (
    AnalyzeRequest,
    AnalyzeResponse,
    PageAnalysis,
    PageProduct,
    ProductInfo,
    ScoreBreakdown,
    SustainabilityScore,
)


def test_analyze_request_new_fields_default_empty() -> None:
    """AnalyzeRequest accepts page_text and product_images with defaults."""
    req = AnalyzeRequest(screenshot="abc", url="https://example.com")
    assert req.page_text == ""
    assert req.product_images == []


def test_analyze_request_with_page_text_and_images() -> None:
    """AnalyzeRequest populates page_text and product_images."""
    req = AnalyzeRequest(
        screenshot="abc",
        url="https://example.com",
        page_text="TITLE: Wild Tuna\nDETAILS: Caught in Pacific Ocean",
        product_images=["base64img1", "base64img2"],
    )
    assert req.page_text.startswith("TITLE:")
    assert len(req.product_images) == 2


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


def test_product_info_price_default_none() -> None:
    """ProductInfo.price defaults to None."""
    pi = ProductInfo(
        is_seafood=True,
        species="cod",
        wild_or_farmed="wild",
        fishing_method=None,
        origin_region=None,
        certifications=[],
    )
    assert pi.price is None


def test_product_info_with_price() -> None:
    """ProductInfo accepts and stores price."""
    pi = ProductInfo(
        is_seafood=True,
        species="sockeye salmon",
        wild_or_farmed="wild",
        fishing_method=None,
        origin_region="Alaska",
        certifications=["MSC"],
        price="$12.99/lb",
    )
    assert pi.price == "$12.99/lb"


def test_page_product_price_default_none() -> None:
    """PageProduct.price defaults to None."""
    pp = PageProduct(
        product_name="Wild Salmon",
        species="salmon",
        wild_or_farmed="wild",
        certifications=[],
        score=75,
        grade="B",
        breakdown=ScoreBreakdown(
            biological=14, practices=18, management=24, ecological=19,
        ),
    )
    assert pp.price is None


def test_page_product_with_price() -> None:
    """PageProduct accepts and stores price."""
    pp = PageProduct(
        product_name="Wild Salmon",
        species="salmon",
        wild_or_farmed="wild",
        certifications=[],
        score=75,
        grade="B",
        breakdown=ScoreBreakdown(
            biological=14, practices=18, management=24, ecological=19,
        ),
        price="$14.99",
    )
    assert pp.price == "$14.99"


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


def test_page_product_url_default_none() -> None:
    """PageProduct.url defaults to None."""
    pp = PageProduct(
        product_name="Wild Salmon",
        species="salmon",
        wild_or_farmed="wild",
        certifications=[],
        score=75,
        grade="B",
        breakdown=ScoreBreakdown(biological=14, practices=18, management=24, ecological=19),
    )
    assert pp.url is None


def test_page_product_with_url() -> None:
    """PageProduct accepts and stores url."""
    pp = PageProduct(
        product_name="Wild Salmon",
        species="salmon",
        wild_or_farmed="wild",
        certifications=[],
        score=75,
        grade="B",
        breakdown=ScoreBreakdown(biological=14, practices=18, management=24, ecological=19),
        url="https://www.amazon.com/dp/B09G543RDP",
    )
    assert pp.url == "https://www.amazon.com/dp/B09G543RDP"


def test_analyze_request_with_related_products_with_urls() -> None:
    """AnalyzeRequest accepts related_products_with_urls."""
    req = AnalyzeRequest(
        screenshot="abc",
        url="https://example.com",
        related_products=["Wild Salmon Fillet", "Atlantic Cod"],
        related_products_with_urls=[
            {"title": "Wild Salmon Fillet 1lb", "url": "https://example.com/product/1"},
            {"title": "Atlantic Cod Fillet", "url": "https://example.com/product/2"},
        ],
    )
    assert len(req.related_products_with_urls) == 2
    assert req.related_products_with_urls[0]["title"] == "Wild Salmon Fillet 1lb"


def test_analyze_request_related_products_with_urls_defaults_empty() -> None:
    """AnalyzeRequest.related_products_with_urls defaults to empty list."""
    req = AnalyzeRequest(screenshot="abc", url="https://example.com")
    assert req.related_products_with_urls == []
