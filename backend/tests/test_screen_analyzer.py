"""Tests for _parse_page_analysis in screen_analyzer."""

import json
from typing import Any

from agents.screen_analyzer import _parse_page_analysis
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


def test_parse_invalid_json_fallback() -> None:
    """Malformed JSON falls back to no_seafood with empty products."""
    result = _parse_page_analysis("this is not json at all")
    assert result.page_type == "no_seafood"
    assert result.products == []


def test_parse_empty_string_fallback() -> None:
    """Empty string falls back to no_seafood."""
    result = _parse_page_analysis("")
    assert result.page_type == "no_seafood"
    assert result.products == []


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
