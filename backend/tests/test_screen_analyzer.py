"""Tests for _parse_page_analysis in screen_analyzer."""

import json
from typing import Any

import pytest

from agents.screen_analyzer import _parse_page_analysis, _sanitize_price
from models import PageAnalysis


def test_parse_single_product() -> None:
    """Valid single-product JSON parses to PageAnalysis."""
    raw = json.dumps({
        "page_type": "single_product",
        "products": [
            {
                "is_seafood": True,
                "species": "Atlantic cod",
                "wild_or_farmed": "wild",
                "fishing_method": "Trawl",
                "origin_region": "North Atlantic",
                "certifications": ["MSC"],
                "product_name": "Fresh Atlantic Cod Fillet",
            }
        ],
    })
    result = _parse_page_analysis(raw)
    assert isinstance(result, PageAnalysis)
    assert result.page_type == "single_product"
    assert len(result.products) == 1
    assert result.products[0].species == "Atlantic cod"
    assert result.products[0].product_name == "Fresh Atlantic Cod Fillet"


def test_parse_product_with_price() -> None:
    """Product with price field parses correctly."""
    raw = json.dumps({
        "page_type": "single_product",
        "products": [
            {
                "is_seafood": True,
                "species": "sockeye salmon",
                "wild_or_farmed": "wild",
                "fishing_method": None,
                "origin_region": "Alaska",
                "certifications": ["MSC"],
                "product_name": "Wild Sockeye Salmon",
                "price": "$14.99/lb",
            }
        ],
    })
    result = _parse_page_analysis(raw)
    assert result.products[0].price == "$14.99/lb"


def test_parse_product_without_price_defaults_none() -> None:
    """Product without price field defaults to None."""
    raw = json.dumps({
        "page_type": "single_product",
        "products": [
            {
                "is_seafood": True,
                "species": "cod",
                "wild_or_farmed": "wild",
                "fishing_method": None,
                "origin_region": None,
                "certifications": [],
            }
        ],
    })
    result = _parse_page_analysis(raw)
    assert result.products[0].price is None


def test_parse_multi_product() -> None:
    """Valid multi-product JSON parses with correct count."""
    products: list[dict[str, Any]] = [
        {
            "is_seafood": True,
            "species": f"species_{i}",
            "wild_or_farmed": "wild",
            "fishing_method": None,
            "origin_region": None,
            "certifications": [],
            "product_name": f"Product {i}",
        }
        for i in range(4)
    ]
    raw = json.dumps({"page_type": "product_listing", "products": products})
    result = _parse_page_analysis(raw)
    assert result.page_type == "product_listing"
    assert len(result.products) == 4


def test_parse_no_seafood() -> None:
    """no_seafood JSON parses with empty products."""
    raw = json.dumps({"page_type": "no_seafood", "products": []})
    result = _parse_page_analysis(raw)
    assert result.page_type == "no_seafood"
    assert result.products == []


def test_parse_invalid_json_raises() -> None:
    """Malformed JSON raises ValueError instead of silently returning no_seafood."""
    with pytest.raises(ValueError, match="invalid JSON"):
        _parse_page_analysis("this is not json at all")


def test_parse_empty_string_raises() -> None:
    """Empty string raises ValueError."""
    with pytest.raises(ValueError, match="invalid JSON"):
        _parse_page_analysis("")


def test_parse_truncates_to_10_products() -> None:
    """More than 10 products get truncated to 10."""
    products: list[dict[str, Any]] = [
        {
            "is_seafood": True,
            "species": f"species_{i}",
            "wild_or_farmed": "wild",
            "fishing_method": None,
            "origin_region": None,
            "certifications": [],
            "product_name": f"Product {i}",
        }
        for i in range(15)
    ]
    raw = json.dumps({"page_type": "product_listing", "products": products})
    result = _parse_page_analysis(raw)
    assert len(result.products) == 10


def test_parse_with_json_fences() -> None:
    """JSON wrapped in markdown code fences still parses."""
    inner = json.dumps({
        "page_type": "single_product",
        "products": [
            {
                "is_seafood": True,
                "species": "salmon",
                "wild_or_farmed": "wild",
                "fishing_method": None,
                "origin_region": None,
                "certifications": [],
            }
        ],
    })
    raw = f"```json\n{inner}\n```"
    result = _parse_page_analysis(raw)
    assert result.page_type == "single_product"
    assert len(result.products) == 1


# ── Price sanitizer ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("$899",   "$8.99"),
    ("$1099",  "$10.99"),
    ("$1149",  "$11.49"),
    ("$2399",  "$23.99"),
    ("$.899",  "$8.99"),
    ("$.1099", "$10.99"),
    ("$8.99",  "$8.99"),   # already correct — unchanged
    ("$10",    "$10"),     # 2-digit whole number — unchanged
    ("$14.99/lb", "$14.99/lb"),  # already correct with suffix
    (None,     None),
])
def test_sanitize_price(raw: str | None, expected: str | None) -> None:
    assert _sanitize_price(raw) == expected


def test_parse_page_analysis_fixes_price() -> None:
    """_parse_page_analysis corrects dropped decimals in price fields."""
    raw = json.dumps({
        "page_type": "product_listing",
        "products": [
            {
                "is_seafood": True,
                "species": "Atlantic salmon",
                "wild_or_farmed": "farmed",
                "fishing_method": None,
                "origin_region": None,
                "certifications": ["BAP"],
                "product_name": "MOWI Atlantic Salmon 12oz",
                "price": "$899",
            },
        ],
    })
    result = _parse_page_analysis(raw)
    assert result.products[0].price == "$8.99"
