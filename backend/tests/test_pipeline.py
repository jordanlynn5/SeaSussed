"""Tests for analyze_page routing and batch scoring."""

from unittest.mock import AsyncMock, patch

import pytest

from models import (
    Alternative,
    PageAnalysis,
    ProductInfo,
    ScoreBreakdown,
    ScoreFactor,
    SustainabilityScore,
)
from pipeline import analyze_page, analyze_page_progressive

_MOCK_SCORE = SustainabilityScore(
    score=72,
    grade="B",
    breakdown=ScoreBreakdown(biological=15, practices=18, management=22, ecological=17),
    alternatives=[
        Alternative(
            species="Pacific Salmon", score=85, grade="A",
            reason="Well-managed wild fishery", from_page=False,
        ),
    ],
    alternatives_label="Better alternatives",
    explanation="Atlantic cod from the North Atlantic scores a B.",
    score_factors=[
        ScoreFactor(
            category="biological", score=15, max_score=20,
            explanation="Moderate vulnerability", tip=None,
        ),
    ],
    product_info=ProductInfo(
        is_seafood=True, species="Atlantic cod", wild_or_farmed="wild",
        fishing_method="Trawl", origin_region="North Atlantic",
        certifications=["MSC"],
    ),
)


def _make_product(
    species: str, is_seafood: bool = True, name: str | None = None,
) -> ProductInfo:
    return ProductInfo(
        is_seafood=is_seafood,
        species=species if is_seafood else None,
        wild_or_farmed="wild",
        fishing_method=None,
        origin_region=None,
        certifications=[],
        product_name=name or species,
    )


@pytest.mark.asyncio
async def test_no_seafood_returns_no_seafood_page_type() -> None:
    pa = PageAnalysis(page_type="no_seafood", products=[])
    result = await analyze_page(pa, [])
    assert result.page_type == "no_seafood"
    assert result.result is not None
    assert result.result.score == 0
    assert result.products == []


@pytest.mark.asyncio
async def test_empty_products_returns_no_seafood() -> None:
    pa = PageAnalysis(page_type="single_product", products=[])
    result = await analyze_page(pa, [])
    assert result.page_type == "no_seafood"
    assert result.result is not None
    assert result.result.score == 0


@pytest.mark.asyncio
@patch("pipeline.run_scoring_pipeline", new_callable=AsyncMock, return_value=_MOCK_SCORE)
async def test_single_product_delegates_to_scoring_pipeline(
    mock_pipeline: AsyncMock,
) -> None:
    product = _make_product("Atlantic cod")
    pa = PageAnalysis(page_type="single_product", products=[product])
    result = await analyze_page(pa, ["Pacific Salmon"])

    assert result.page_type == "single_product"
    assert result.result is not None
    assert result.result.score == 72
    assert result.products == []
    mock_pipeline.assert_awaited_once()


@pytest.mark.asyncio
async def test_product_listing_returns_sorted_page_products() -> None:
    """3 seafood products → PageProduct list sorted by score desc."""
    products = [
        _make_product("tilapia", name="Tilapia Fillet"),
        _make_product("sockeye salmon", name="Wild Sockeye Salmon"),
        _make_product("Atlantic cod", name="Fresh Cod"),
    ]
    pa = PageAnalysis(page_type="product_listing", products=products)
    result = await analyze_page(pa, [])

    assert result.page_type == "product_listing"
    assert result.result is None
    assert len(result.products) >= 2
    # Sorted by score descending
    scores = [p.score for p in result.products]
    assert scores == sorted(scores, reverse=True)
    # Each PageProduct has required fields
    for pp in result.products:
        assert pp.product_name
        assert pp.grade in ("A", "B", "C", "D")
        assert 0 <= pp.score <= 100
        assert pp.breakdown.biological >= 0


@pytest.mark.asyncio
@patch("pipeline.run_scoring_pipeline", new_callable=AsyncMock, return_value=_MOCK_SCORE)
async def test_listing_with_one_seafood_falls_through_to_single(
    mock_pipeline: AsyncMock,
) -> None:
    """product_listing with only 1 seafood product → single_product flow."""
    products = [
        _make_product("Atlantic cod", name="Fresh Cod"),
        _make_product("chicken", is_seafood=False, name="Chicken Breast"),
    ]
    pa = PageAnalysis(page_type="product_listing", products=products)
    result = await analyze_page(pa, [])

    assert result.page_type == "single_product"
    assert result.result is not None
    mock_pipeline.assert_awaited_once()


@pytest.mark.asyncio
async def test_listing_filters_non_seafood() -> None:
    """product_listing filters out is_seafood=False items."""
    products = [
        _make_product("salmon", name="Wild Salmon"),
        _make_product("chicken", is_seafood=False, name="Chicken"),
        _make_product("cod", name="Cod Fillet"),
        _make_product("pasta", is_seafood=False, name="Spaghetti"),
    ]
    pa = PageAnalysis(page_type="product_listing", products=products)
    result = await analyze_page(pa, [])

    assert result.page_type == "product_listing"
    # Only 2 seafood products should remain
    assert len(result.products) == 2
    names = [p.product_name for p in result.products]
    assert "Chicken" not in names
    assert "Spaghetti" not in names


# ── Progressive pipeline tests ──


@pytest.mark.asyncio
async def test_progressive_no_seafood_yields_single_complete() -> None:
    """no_seafood emits a single 'complete' event."""
    pa = PageAnalysis(page_type="no_seafood", products=[])
    events = [e async for e in analyze_page_progressive(pa, [])]
    assert len(events) == 1
    assert events[0]["phase"] == "complete"
    assert events[0]["page_type"] == "no_seafood"


@pytest.mark.asyncio
async def test_progressive_listing_yields_single_complete() -> None:
    """product_listing emits a single 'complete' event with products."""
    products = [
        _make_product("salmon", name="Wild Salmon"),
        _make_product("cod", name="Cod Fillet"),
    ]
    pa = PageAnalysis(page_type="product_listing", products=products)
    events = [e async for e in analyze_page_progressive(pa, [])]
    assert len(events) == 1
    assert events[0]["phase"] == "complete"
    assert events[0]["page_type"] == "product_listing"
    assert len(events[0]["products"]) == 2


@pytest.mark.asyncio
@patch("pipeline.get_carbon_footprint", return_value=None)
@patch("pipeline.research_product", side_effect=lambda p: p)
@patch("pipeline.get_health_info", return_value=None)
@patch("pipeline.generate_content", return_value=("Good choice.", []))
@patch("pipeline.score_alternatives", return_value=([], "Better alternatives"))
async def test_progressive_single_product_yields_scored_then_complete(
    _mock_alts: AsyncMock, _mock_explain: AsyncMock,
    _mock_health: AsyncMock, _mock_research: AsyncMock,
    _mock_carbon: AsyncMock,
) -> None:
    """Single product emits 'scored' then 'complete'."""
    product = _make_product("Atlantic cod", name="Fresh Cod")
    pa = PageAnalysis(page_type="single_product", products=[product])
    events = [e async for e in analyze_page_progressive(pa, [])]

    assert len(events) == 2
    # Phase 1: scored
    assert events[0]["phase"] == "scored"
    assert events[0]["product_info"]["species"] == "Atlantic cod"
    assert "score" in events[0]
    assert "grade" in events[0]
    assert "breakdown" in events[0]
    # Phase 2: complete
    assert events[1]["phase"] == "complete"
    assert events[1]["page_type"] == "single_product"
    assert "result" in events[1]
    assert events[1]["result"]["score"] == events[0]["score"]
