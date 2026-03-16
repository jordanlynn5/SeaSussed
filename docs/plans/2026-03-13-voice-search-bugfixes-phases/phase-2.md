# Phase 2: Fix _find_product_url with Species-Gated Matching

## Goal
Ensure product names are matched to the correct scraped URLs by prioritizing species-specific words over generic grocery terms.

## Files
- `backend/voice_session.py` — rewrite `_find_product_url()`, update call site to pass species
- `backend/tests/test_voice.py` — add unit tests for URL matching

## Changes

### voice_session.py — _find_product_url (lines 24-45)

Rewrite with new signature and three-tier matching:

```pseudo
def _find_product_url(
    product_name: str,
    links: list[dict[str, str]],
    species: str | None = None,
) -> str | None:
    """Match a product name to a scraped URL.

    Three-tier matching:
    1. Bidirectional substring — either name contains the other
    2. Species-gated fuzzy — require species word match, then count remaining
    3. Fallback fuzzy — original word-overlap but with generic word exclusion
    """
    if not product_name or not links:
        return None

    name_lower = product_name.lower()

    # Tier 1: Bidirectional exact substring
    for link in links:
        link_name = link.get("name", "").lower()
        if not link_name:
            continue
        if name_lower in link_name or link_name in name_lower:
            return link.get("url")

    # Generic grocery words to exclude from fuzzy scoring
    GENERIC = {"amazon", "grocery", "fresh", "brand", "oz",
               "fillets", "fillet", "skinless", "boneless", "portions",
               "portion", "previously", "packaging", "vary", "may",
               "frozen", "caught", "wild", "farmed", "product",
               "organic", "natural", "premium", "select", "choice"}

    # Extract species words for gating
    species_words = set()
    if species:
        species_words = {w.lower() for w in species.split() if len(w) >= 3} - GENERIC

    # Significant words from product name, excluding generic
    all_words = [w for w in name_lower.split() if len(w) >= 3]
    meaningful_words = [w for w in all_words if w not in GENERIC]

    best_url: str | None = None
    best_score: float = 0.0

    for link in links:
        link_lower = link.get("name", "").lower()
        if not link_lower:
            continue

        # Tier 2: If we have species words, require at least one match
        if species_words:
            has_species = any(sw in link_lower for sw in species_words)
            if not has_species:
                continue  # Skip links that don't match the species

        # Count meaningful word matches
        matched = sum(1 for w in meaningful_words if w in link_lower)
        if not meaningful_words:
            continue
        score = matched / len(meaningful_words)

        if score > best_score:
            best_score = score
            best_url = link.get("url")

    if best_url and best_score >= 0.3:
        return best_url

    # Tier 3: Fallback without species gate (if species gate was too strict)
    if species_words:
        best_url = None
        best_score = 0.0
        for link in links:
            link_lower = link.get("name", "").lower()
            matched = sum(1 for w in meaningful_words if w in link_lower)
            if not meaningful_words:
                continue
            score = matched / len(meaningful_words)
            if score > best_score:
                best_score = score
                best_url = link.get("url")
        if best_url and best_score >= 0.3:
            return best_url

    return None
```

### voice_session.py — call site in _handle_search_store (line ~826)

Pass species to the function:

```pseudo
- url = _find_product_url(name, product_links)
+ url = _find_product_url(name, product_links, species=p.species)
```

### test_voice.py — new tests

```pseudo
MOCK_LINKS = [
    {"name": "Amazon Grocery, Wild Caught Pacific Cod, Boneless Skinless Fillets, 16 oz", "url": "https://example.com/cod"},
    {"name": "Amazon Grocery, Skinless Tilapia Fillets, 12 Oz", "url": "https://example.com/tilapia"},
    {"name": "MOWI Atlantic Salmon 12oz, 2 Portions", "url": "https://example.com/salmon"},
]

test_find_product_url_exact_substring:
    - product_name = "Amazon Grocery, Wild Caught Pacific Cod, Boneless Skinless Fillets, 16 oz"
    - Assert returns cod URL (bidirectional substring match)

test_find_product_url_species_gated:
    - product_name = "Amazon Grocery, Wild Caught Pacific Cod, Boneless Skinless Fillets, 16 oz (Previously Amazon Fresh, Packaging May Vary)"
    - species = "Pacific Cod"
    - Assert returns cod URL, NOT tilapia URL

test_find_product_url_no_match:
    - product_name = "Totally Different Product"
    - Assert returns None

test_find_product_url_salmon_not_cod:
    - product_name = "MOWI Atlantic Salmon 12oz"
    - species = "Atlantic Salmon"
    - Assert returns salmon URL, not cod or tilapia
```

## Success Criteria
- **Automated:** All new `_find_product_url` tests pass
- **Automated:** `uv run mypy .` and `uv run ruff check .` pass
- **Manual:** Search for "cod" in voice session → Gemini navigates to a cod product, not tilapia
