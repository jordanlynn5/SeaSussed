"""Tests for research.py web research enrichment."""
from unittest.mock import MagicMock, patch

from models import ProductInfo
from research import _merge_research, needs_research, research_product

# ── needs_research tests ──

def test_needs_research_all_missing() -> None:
    p = ProductInfo(
        is_seafood=True, species="salmon", wild_or_farmed="wild",
        fishing_method=None, origin_region=None, certifications=[],
    )
    assert needs_research(p) is True


def test_needs_research_all_present() -> None:
    p = ProductInfo(
        is_seafood=True, species="salmon", wild_or_farmed="wild",
        fishing_method="troll", origin_region="Alaska",
        certifications=["MSC"],
    )
    assert needs_research(p) is False


def test_needs_research_one_missing() -> None:
    p = ProductInfo(
        is_seafood=True, species="salmon", wild_or_farmed="wild",
        fishing_method="troll", origin_region="Alaska",
        certifications=[],  # missing
    )
    assert needs_research(p) is True


def test_needs_research_not_seafood() -> None:
    p = ProductInfo(
        is_seafood=False, species=None, wild_or_farmed="unknown",
        fishing_method=None, origin_region=None, certifications=[],
    )
    assert needs_research(p) is False


# ── _merge_research tests ──

def test_merge_fills_gaps() -> None:
    p = ProductInfo(
        is_seafood=True, species="sardines", wild_or_farmed="wild",
        fishing_method=None, origin_region=None, certifications=[],
        product_name="Wild Planet Sardines",
    )
    data = {
        "fishing_method": "purse seine",
        "certifications": ["MSC"],
        "origin_region": "Pacific Ocean",
        "confidence": "high",
    }
    enriched = _merge_research(p, data)
    assert enriched.fishing_method == "purse seine"
    assert enriched.certifications == ["MSC"]
    assert enriched.origin_region == "Pacific Ocean"


def test_merge_does_not_overwrite() -> None:
    p = ProductInfo(
        is_seafood=True, species="salmon", wild_or_farmed="wild",
        fishing_method="troll", origin_region="Alaska",
        certifications=["ASMI"],
    )
    data = {
        "fishing_method": "longline",  # should NOT overwrite
        "certifications": ["MSC"],     # should NOT overwrite
        "origin_region": "Norway",     # should NOT overwrite
    }
    enriched = _merge_research(p, data)
    assert enriched.fishing_method == "troll"
    assert enriched.certifications == ["ASMI"]
    assert enriched.origin_region == "Alaska"


def test_merge_no_data() -> None:
    p = ProductInfo(
        is_seafood=True, species="cod", wild_or_farmed="wild",
        fishing_method=None, origin_region=None, certifications=[],
    )
    data: dict[str, object] = {"fishing_method": None, "certifications": [], "origin_region": None}
    enriched = _merge_research(p, data)
    assert enriched.fishing_method is None  # unchanged


# ── research_product integration test ──

@patch("research.get_genai_client")
def test_research_product_success(mock_client: MagicMock) -> None:
    mock_response = MagicMock()
    mock_response.text = '''{
        "fishing_method": "pole and line",
        "certifications": ["MSC"],
        "origin_region": "Morocco",
        "confidence": "high",
        "source_summary": "Found on Wild Planet website"
    }'''
    mock_client.return_value.models.generate_content.return_value = mock_response

    p = ProductInfo(
        is_seafood=True, species="sardines", wild_or_farmed="wild",
        fishing_method=None, origin_region=None, certifications=[],
        product_name="Wild Planet Sardines",
    )
    enriched = research_product(p)
    assert enriched.fishing_method == "pole and line"
    assert enriched.certifications == ["MSC"]
    assert enriched.origin_region == "Morocco"


@patch("research.get_genai_client")
def test_research_product_api_failure(mock_client: MagicMock) -> None:
    """API failure returns original product unchanged."""
    mock_client.return_value.models.generate_content.side_effect = Exception("API down")

    p = ProductInfo(
        is_seafood=True, species="sardines", wild_or_farmed="wild",
        fishing_method=None, origin_region=None, certifications=[],
    )
    result = research_product(p)
    assert result.fishing_method is None  # unchanged


def test_research_skips_when_not_needed() -> None:
    """No API call when all fields present."""
    p = ProductInfo(
        is_seafood=True, species="salmon", wild_or_farmed="wild",
        fishing_method="troll", origin_region="Alaska",
        certifications=["MSC"],
    )
    # No mock needed — should never call the API
    result = research_product(p)
    assert result is p  # same object, no changes
