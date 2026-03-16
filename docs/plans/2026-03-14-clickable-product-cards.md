# Plan: Clickable Product Cards on Listing Page

**Date:** 2026-03-14
**Branch:** dev
**Phases:** [phase-1](2026-03-14-clickable-product-cards-phases/phase-1.md) · [phase-2](2026-03-14-clickable-product-cards-phases/phase-2.md) · [phase-3](2026-03-14-clickable-product-cards-phases/phase-3.md)

---

## Goal

When SeaSussed analyzes a product listing page, each scored product card in the side panel should be clickable — clicking navigates the current browser tab to that product's URL.

---

## Current State

- `scrapeRelatedProducts()` in `background.js` returns `[title_string, ...]` — no URLs.
- `AnalyzeRequest.related_products: list[str]` carries only titles to the backend.
- `PageProduct` (the model for listing items) has no `url` field.
- `renderProductList()` in `sidepanel.js` renders card headers with expand/collapse only — no navigation.

---

## Design

### URL Matching Strategy (pipeline.py)

Gemini vision extracts `product_name` (e.g. `"Wild Alaska Sockeye Salmon"`). The DOM scraper extracts verbatim titles (e.g. `"Wild Caught Sockeye Salmon Fillets 1 lb"`). Exact match will often miss. We use a three-tier lookup:

1. Exact match (case-insensitive)
2. Substring containment (either string contains the other)
3. Token overlap ≥ 2 significant tokens (skip stopwords)

Returns `None` if no match reaches threshold — `PageProduct.url` stays `None`.

### Backward Compatibility

- `related_products: list[str]` on `AnalyzeRequest` is unchanged — alternatives scoring and Gemini analysis still use it.
- `related_products_with_urls: list[dict[str, str]] = []` is a new optional field on `AnalyzeRequest`. Pydantic v2 ignores extra fields by default, so Phase 2 (extension) can be deployed independently of Phase 1 (backend) without errors.

### Click Behavior (sidepanel.js)

The product name element becomes a clickable link. Clicking it navigates the active tab to the product URL via `chrome.tabs.update`. The expand/collapse chevron behavior is preserved on the rest of the header. If `product.url` is null (matching failed), the name renders as plain text — no click handler.

---

## Phase Structure

| Phase | Scope | Files | Batch-eligible |
|---|---|---|---|
| 1 | Backend: model + pipeline | `models.py`, `pipeline.py`, `test_models.py`, `test_pipeline.py` | ✅ with Phase 2 |
| 2 | Extension: scraper + passthrough | `background.js`, `sidepanel.js` (fetch body only) | ✅ with Phase 1 |
| 3 | Extension: UI click | `sidepanel.js` (renderProductList) | ❌ depends on Phase 1 |

Phases 1 and 2 are **[batch-eligible]** — disjoint files, no sequential output dependency (extension sends new field; backend silently accepts it once Phase 1 is done).

Phase 3 depends on Phase 1 completing so `product.url` exists in the response.

---

## Success Criteria

### Automated
- `test_page_product_url_default_none` passes (Phase 1)
- `test_page_product_with_url` passes (Phase 1)
- `test_analyze_request_with_related_products_with_urls` passes (Phase 1)
- `test_listing_passes_url_to_page_product` passes (Phase 1)
- Full suite: `mypy . && ruff check . && pytest` green (Phase 1)

### Manual
- On a product listing page (e.g. Amazon Fresh seafood search), each scored card shows the product name as a clickable element (cursor changes)
- Clicking a product name navigates the current tab to that product's URL
- Expand/collapse chevron still works independently
- Cards without a matched URL render with plain (non-clickable) names
- No console errors when `product.url` is null
