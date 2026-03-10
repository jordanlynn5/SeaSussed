# Phase 3: Web Research Module [batch-eligible]

**Files created:** `backend/research.py`, `backend/tests/test_research.py`

---

## Goal

When the screen analyzer can't find fishing method, certifications, or origin on the
product page, use a separate Gemini call with `google_search` grounding to research
the brand/product. Returns an enriched `ProductInfo` with gaps filled.

---

## Key Constraint

The Gemini API rejects mixing `google_search` with `function_declarations` in the same
request. This module uses a standalone `generate_content` call with ONLY `google_search`
enabled — completely separate from the screen analyzer or voice session.

---

## 1. Research Module (`backend/research.py`)

```python
"""Web research enrichment via Gemini + Google Search grounding."""

import json
import logging
from typing import Any

from google.genai import types

from gemini_client import get_genai_client, strip_json_fences
from models import ProductInfo

log = logging.getLogger(__name__)


def needs_research(product: ProductInfo) -> bool:
    """Return True if the product is missing key sustainability fields."""
    if not product.is_seafood:
        return False
    missing_method = product.fishing_method is None
    missing_certs = len(product.certifications) == 0
    missing_origin = product.origin_region is None
    return missing_method or missing_certs or missing_origin


def research_product(product: ProductInfo) -> ProductInfo:
    """Research a product via Gemini + Google Search and fill missing fields.

    Returns the original product unchanged if:
    - No fields are missing (needs_research is False)
    - The API call fails
    - No useful information is found

    Only fills fields that were originally None/empty — never overwrites
    existing page-visible data.
    """
    if not needs_research(product):
        return product

    species = product.species or "unknown seafood"
    brand = product.product_name or ""

    # Build a focused search query
    missing_parts = []
    if product.fishing_method is None:
        missing_parts.append("fishing method (gear type)")
    if not product.certifications:
        missing_parts.append("sustainability certifications (MSC, ASC, BAP, etc.)")
    if product.origin_region is None:
        missing_parts.append("origin region / catch location")

    missing_str = ", ".join(missing_parts)

    prompt = f"""Research this seafood product and find the missing sustainability information.

Product: {brand} — {species}
Wild or farmed: {product.wild_or_farmed}
What the product page showed: species={product.species}, method={product.fishing_method}, origin={product.origin_region}, certs={product.certifications}
What is MISSING: {missing_str}

Search for information about this specific brand and product. Look for:
- The brand's website, sustainability page, or sourcing policy
- News articles or certification databases mentioning this brand
- Specific fishing method / gear type used
- MSC, ASC, BAP, or other certification status
- Where the product is sourced from

RULES:
1. Only return information that is specifically about this brand + product.
   Do NOT return generic info about the species.
2. If you can't find specific brand info, return null for that field.
3. For certifications, only include certs you find evidence of (certificate number,
   brand sustainability page mention, certification body database listing).
4. For fishing_method, use specific gear type names: "pole and line", "purse seine",
   "troll", "longline", "midwater trawl", "bottom trawl", "gillnet", "pot/trap", etc.

Return ONLY a JSON object:
{{
  "fishing_method": "<specific gear type>" or null,
  "certifications": ["MSC", ...] or [],
  "origin_region": "<catch/farm location>" or null,
  "confidence": "high" | "medium" | "low",
  "source_summary": "one sentence about where you found this info"
}}"""

    try:
        client = get_genai_client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        raw = strip_json_fences(response.text or "")
        data: dict[str, Any] = json.loads(raw)
        return _merge_research(product, data)
    except Exception as e:
        log.warning("research_product failed for %s: %s", brand or species, e)
        return product


def _merge_research(product: ProductInfo, data: dict[str, Any]) -> ProductInfo:
    """Merge research findings into ProductInfo, only filling gaps."""
    updates: dict[str, Any] = {}

    # Only fill fields that are currently missing
    method = data.get("fishing_method")
    if product.fishing_method is None and method and isinstance(method, str):
        updates["fishing_method"] = method

    certs = data.get("certifications")
    if not product.certifications and isinstance(certs, list) and certs:
        updates["certifications"] = [str(c) for c in certs if c]

    origin = data.get("origin_region")
    if product.origin_region is None and origin and isinstance(origin, str):
        updates["origin_region"] = origin

    if not updates:
        log.info("Research found no new data for %s", product.product_name or product.species)
        return product

    log.info(
        "Research enriched %s: %s (confidence: %s, source: %s)",
        product.product_name or product.species,
        list(updates.keys()),
        data.get("confidence", "unknown"),
        data.get("source_summary", "unknown"),
    )
    return product.model_copy(update=updates)
```

---

## 2. Tests (`backend/tests/test_research.py`)

```python
"""Tests for research.py web research enrichment."""
from unittest.mock import MagicMock, patch

from models import ProductInfo
from research import needs_research, research_product, _merge_research


# ── needs_research tests ──

def test_needs_research_all_missing():
    p = ProductInfo(
        is_seafood=True, species="salmon", wild_or_farmed="wild",
        fishing_method=None, origin_region=None, certifications=[],
    )
    assert needs_research(p) is True


def test_needs_research_all_present():
    p = ProductInfo(
        is_seafood=True, species="salmon", wild_or_farmed="wild",
        fishing_method="troll", origin_region="Alaska",
        certifications=["MSC"],
    )
    assert needs_research(p) is False


def test_needs_research_one_missing():
    p = ProductInfo(
        is_seafood=True, species="salmon", wild_or_farmed="wild",
        fishing_method="troll", origin_region="Alaska",
        certifications=[],  # missing
    )
    assert needs_research(p) is True


def test_needs_research_not_seafood():
    p = ProductInfo(
        is_seafood=False, species=None, wild_or_farmed="unknown",
        fishing_method=None, origin_region=None, certifications=[],
    )
    assert needs_research(p) is False


# ── _merge_research tests ──

def test_merge_fills_gaps():
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


def test_merge_does_not_overwrite():
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


def test_merge_no_data():
    p = ProductInfo(
        is_seafood=True, species="cod", wild_or_farmed="wild",
        fishing_method=None, origin_region=None, certifications=[],
    )
    data = {"fishing_method": None, "certifications": [], "origin_region": None}
    enriched = _merge_research(p, data)
    assert enriched.fishing_method is None  # unchanged


# ── research_product integration test ──

@patch("research.get_genai_client")
def test_research_product_success(mock_client):
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
def test_research_product_api_failure(mock_client):
    """API failure returns original product unchanged."""
    mock_client.return_value.models.generate_content.side_effect = Exception("API down")

    p = ProductInfo(
        is_seafood=True, species="sardines", wild_or_farmed="wild",
        fishing_method=None, origin_region=None, certifications=[],
    )
    result = research_product(p)
    assert result.fishing_method is None  # unchanged


def test_research_skips_when_not_needed():
    """No API call when all fields present."""
    p = ProductInfo(
        is_seafood=True, species="salmon", wild_or_farmed="wild",
        fishing_method="troll", origin_region="Alaska",
        certifications=["MSC"],
    )
    # No mock needed — should never call the API
    result = research_product(p)
    assert result is p  # same object, no changes
```

---

## Success Criteria

### Automated
- `uv run pytest tests/test_research.py` — all pass
- `uv run mypy research.py` — no errors
- `uv run ruff check research.py` — clean

### Manual
- With Vertex AI auth configured, run in Python REPL:
  ```python
  from models import ProductInfo
  from research import research_product
  p = ProductInfo(is_seafood=True, species="sardines", wild_or_farmed="wild",
      fishing_method=None, origin_region=None, certifications=[],
      product_name="Wild Planet Sardines")
  enriched = research_product(p)
  print(enriched.fishing_method, enriched.certifications, enriched.origin_region)
  ```
  Should return enriched data (e.g., "pole and line", ["MSC"], "Morocco").
