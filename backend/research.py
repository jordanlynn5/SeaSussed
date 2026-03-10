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
What the product page showed:
  species={product.species}, method={product.fishing_method}
  origin={product.origin_region}, certs={product.certifications}
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
