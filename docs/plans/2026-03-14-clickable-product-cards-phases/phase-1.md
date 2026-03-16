# Phase 1: Backend — Model + Pipeline [batch-eligible with Phase 2]

## Files Changed
- `backend/models.py`
- `backend/pipeline.py`
- `backend/tests/test_models.py`
- `backend/tests/test_pipeline.py`

---

## Step 1 — Write failing tests first (TDD)

### `backend/tests/test_models.py` — add at end of file

```python
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
```

### `backend/tests/test_pipeline.py` — add one test

```python
@pytest.mark.asyncio
async def test_listing_url_passed_to_page_product() -> None:
    """URL from related_products_with_urls is matched to PageProduct.url."""
    products = [
        _make_product("Atlantic cod", name="Fresh Atlantic Cod Fillet"),
        _make_product("sockeye salmon", name="Wild Sockeye Salmon"),
    ]
    pa = PageAnalysis(page_type="product_listing", products=products)
    url_map = [
        {"title": "Fresh Atlantic Cod Fillet 1 lb", "url": "https://example.com/cod"},
        {"title": "Wild Sockeye Salmon Fillet", "url": "https://example.com/salmon"},
    ]
    result = await analyze_page(pa, [], related_products_with_urls=url_map)

    assert result.page_type == "product_listing"
    urls = {p.product_name: p.url for p in result.products}
    # At least one should have matched (token overlap)
    assert any(v is not None for v in urls.values())
```

---

## Step 2 — Implement `models.py`

### `PageProduct` — add `url` field

```python
class PageProduct(BaseModel):
    product_name: str
    species: str | None
    wild_or_farmed: Literal["wild", "farmed", "unknown"]
    certifications: list[str]
    score: int
    grade: Literal["A", "B", "C", "D"]
    breakdown: ScoreBreakdown
    price: str | None = None
    url: str | None = None        # ← NEW
```

### `AnalyzeRequest` — add `related_products_with_urls` field

```python
class AnalyzeRequest(BaseModel):
    screenshot: str
    url: str
    page_title: str = ""
    related_products: list[str] = []
    page_text: str = ""
    product_images: list[str] = []
    related_products_with_urls: list[dict[str, str]] = []   # ← NEW
```

---

## Step 3 — Implement `pipeline.py`

### Add URL matching helper (module-level private function)

```python
_STOPWORDS = {"the", "a", "an", "of", "and", "or", "in", "at", "to", "with", "for", "lb", "oz"}

def _match_url(product_name: str, url_entries: list[dict[str, str]]) -> str | None:
    """Return the best-matching URL for product_name from url_entries.

    url_entries: list of {"title": str, "url": str}
    Returns None if no confident match found.
    """
    if not product_name or not url_entries:
        return None
    name_lower = product_name.strip().lower()

    for entry in url_entries:
        title_lower = entry.get("title", "").strip().lower()
        url = entry.get("url", "")
        if not title_lower or not url:
            continue
        # Tier 1: exact match
        if name_lower == title_lower:
            return url
        # Tier 2: substring containment
        if name_lower in title_lower or title_lower in name_lower:
            return url

    # Tier 3: token overlap ≥ 2 significant tokens
    name_tokens = {t for t in name_lower.split() if t not in _STOPWORDS and len(t) > 2}
    best_url: str | None = None
    best_overlap = 1  # require at least 2 (i.e., > 1)
    for entry in url_entries:
        title_tokens = {
            t for t in entry.get("title", "").lower().split()
            if t not in _STOPWORDS and len(t) > 2
        }
        overlap = len(name_tokens & title_tokens)
        if overlap > best_overlap:
            best_overlap = overlap
            best_url = entry.get("url") or None
    return best_url
```

### Update `analyze_page` signature and both `PageProduct` construction sites

**Function signature change:**
```python
async def analyze_page(
    page_analysis: PageAnalysis,
    related_products: list[str],
    client_ip: str = "",
    related_products_with_urls: list[dict[str, str]] | None = None,  # ← NEW
) -> AnalyzeResponse:
```

**Both PageProduct construction blocks** (lines ~131 and ~190) get URL lookup added:

```python
# In the loop:
url = _match_url(
    product.product_name or product.species or "",
    related_products_with_urls or [],
)
PageProduct(
    product_name=product.product_name or product.species or "Seafood product",
    species=product.species,
    wild_or_farmed=product.wild_or_farmed,
    certifications=product.certifications,
    score=total,
    grade=grade,
    breakdown=breakdown,
    price=product.price,
    url=url,        # ← NEW
)
```

Same pattern applies to `analyze_page_progressive` for the product_listing branch.

### Update `main.py` — pass the new field

In both `/analyze` and `/analyze/stream`:

```python
# /analyze endpoint
return await analyze_page(
    page_analysis,
    body.related_products,
    client_ip=ip,
    related_products_with_urls=body.related_products_with_urls,   # ← NEW
)

# /analyze/stream endpoint (inside generate())
async for event in analyze_page_progressive(
    page_analysis,
    body.related_products,
    client_ip=ip,
    related_products_with_urls=body.related_products_with_urls,   # ← NEW
):
```

`analyze_page_progressive` needs the same signature change as `analyze_page`.

---

## Step 4 — Verify

```bash
cd /Users/jordan/sussed/backend && uv run mypy . 2>&1; uv run ruff check . 2>&1; uv run pytest 2>&1
```

All tests green, mypy clean, ruff clean.
