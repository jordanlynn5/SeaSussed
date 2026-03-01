# Phase 6: Testing & Optimization

**Days:** 12–13 | **Depends on:** Phase 5 | **Blocks:** Phase 7

---

## Deliverable

All automated tests pass. Response time p90 < 3s. Manual checklist verified on Whole Foods. Extension survives page navigation cleanly.

---

## Scoring Unit Tests (no fixtures needed)

These test the pure Python scoring logic directly — no Gemini calls, no DB required beyond a built database.

```python
# backend/tests/test_scoring.py
import pytest
from scoring import compute_score, score_biological, score_management, score_ecological
from models import ProductInfo

TEST_CASES = [
  # (description, ProductInfo kwargs, expected_min_grade, expected_max_grade)
  (
    "Alaska sockeye salmon — MSC, purse seine, Bristol Bay",
    dict(is_seafood=True, species="sockeye salmon", wild_or_farmed="wild",
         fishing_method="Purse seine (without FAD)", origin_region="Bristol Bay, Alaska",
         certifications=["MSC"]),
    "A", "A",
  ),
  (
    "US farmed oysters — ASC certified",
    dict(is_seafood=True, species="Pacific oyster", wild_or_farmed="farmed",
         fishing_method=None, origin_region="Pacific Northwest",
         certifications=["ASC"]),
    "A", "A",
  ),
  (
    "Atlantic mackerel — purse seine, no cert",
    dict(is_seafood=True, species="Atlantic mackerel", wild_or_farmed="wild",
         fishing_method="Purse seine", origin_region="North Atlantic",
         certifications=[]),
    "A", "B",
  ),
  (
    "Alaskan pollock — midwater trawl, MSC",
    dict(is_seafood=True, species="Alaska pollock", wild_or_farmed="wild",
         fishing_method="Midwater trawl", origin_region="Bering Sea",
         certifications=["MSC"]),
    "B", "B",
  ),
  (
    "Atlantic cod — bottom trawl, no cert",
    dict(is_seafood=True, species="Atlantic cod", wild_or_farmed="wild",
         fishing_method="Bottom trawl", origin_region="Norway",
         certifications=[]),
    "C", "C",
  ),
  (
    "Farmed Atlantic salmon — no cert, Norway",
    dict(is_seafood=True, species="Atlantic salmon", wild_or_farmed="farmed",
         fishing_method=None, origin_region="Norway",
         certifications=[]),
    "C", "C",
  ),
  (
    "Imported shrimp — unknown gear, Thailand, no cert",
    dict(is_seafood=True, species="whiteleg shrimp", wild_or_farmed="farmed",
         fishing_method=None, origin_region="Thailand",
         certifications=[]),
    "C", "D",
  ),
  (
    "Bluefin tuna — longline, Atlantic, no cert",
    dict(is_seafood=True, species="bluefin tuna", wild_or_farmed="wild",
         fishing_method="Longline (surface)", origin_region="Atlantic",
         certifications=[]),
    "D", "D",
  ),
  (
    "Orange roughy — bottom trawl",
    dict(is_seafood=True, species="orange roughy", wild_or_farmed="wild",
         fishing_method="Bottom trawl", origin_region="New Zealand",
         certifications=[]),
    "D", "D",
  ),
]

GRADE_ORDER = ["A", "B", "C", "D"]

@pytest.mark.parametrize("description,kwargs,min_grade,max_grade", TEST_CASES)
def test_species_grade(description, kwargs, min_grade, max_grade):
    product = ProductInfo(**kwargs)
    breakdown, total, grade = compute_score(product)
    min_idx = GRADE_ORDER.index(min_grade)
    max_idx = GRADE_ORDER.index(max_grade)
    actual_idx = GRADE_ORDER.index(grade)
    assert min_idx <= actual_idx <= max_idx, (
        f"{description}: expected {min_grade}–{max_grade}, got {grade} ({total})\n"
        f"  biological={breakdown.biological:.1f}, practices={breakdown.practices:.1f}, "
        f"  management={breakdown.management:.1f}, ecological={breakdown.ecological:.1f}"
    )

def test_msci_cert_gives_max_management_pts():
    """MSC certification should give full 15 pts in management."""
    from scoring import score_management
    pts = score_management(["MSC"], noaa_data=None, species_data=None)
    assert pts >= 15.0 + 3.0  # cert (15) + exploitation unknown default (3) = 18 minimum

def test_unknown_species_gives_neutral_score():
    """Unknown species should return a neutral non-zero score, not crash."""
    product = ProductInfo(
        is_seafood=True, species="xenophish 9000", wild_or_farmed="unknown",
        fishing_method=None, origin_region=None, certifications=[])
    breakdown, total, grade = compute_score(product)
    assert 20 <= total <= 60, f"Neutral default should be C range, got {grade} ({total})"

def test_farmed_oyster_uses_aquaculture_scorer():
    """Farmed oyster (low carnivory) should get aquaculture scoring bonus."""
    product = ProductInfo(
        is_seafood=True, species="Pacific oyster", wild_or_farmed="farmed",
        fishing_method=None, origin_region=None, certifications=[])
    breakdown, _, _ = compute_score(product)
    # Oysters are filter feeders — carnivory_ratio should be low → practices bonus
    assert breakdown.practices >= 7.0  # at least the base + carnivory bonus
```

---

## Explanation Quality Tests

```python
# backend/tests/test_explanation.py
from explanation import generate_explanation
from models import ProductInfo, ScoreBreakdown

def test_explanation_mentions_visible_fields():
    """Explanation must reference species and visible origin."""
    product = ProductInfo(
        is_seafood=True, species="Alaska sockeye salmon", wild_or_farmed="wild",
        fishing_method="Purse seine", origin_region="Bristol Bay, Alaska",
        certifications=["MSC"])
    breakdown = ScoreBreakdown(biological=16.0, practices=19.5, management=27.0, ecological=21.0)
    text = generate_explanation(product, breakdown, 84, "A")
    assert len(text) > 30
    # Must mention species or origin — not generic text
    has_specific = any(kw in text.lower() for kw in ["salmon", "alaska", "msc", "wild"])
    assert has_specific, f"Explanation too generic: {text}"

def test_explanation_acknowledges_unknown_method():
    """When fishing method is null, explanation should note it."""
    product = ProductInfo(
        is_seafood=True, species="Atlantic salmon", wild_or_farmed="unknown",
        fishing_method=None, origin_region=None, certifications=[])
    breakdown = ScoreBreakdown(biological=8.0, practices=10.0, management=7.0, ecological=14.0)
    text = generate_explanation(product, breakdown, 39, "D")
    # Should mention something was unknown or not shown
    uncertainty_words = ["unknown", "not shown", "wasn't visible", "couldn't", "not visible",
                         "wasn't shown", "default", "assumed"]
    has_uncertainty = any(w in text.lower() for w in uncertainty_words)
    assert has_uncertainty, f"Explanation should acknowledge unknowns: {text}"
```

---

## Response Time Benchmark

```python
# backend/scripts/benchmark.py
"""Run response time benchmark against local or Cloud Run backend."""
import time, statistics, base64, sys, json, urllib.request
from pathlib import Path

BACKEND_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
FIXTURE = Path(__file__).parent.parent / "tests/fixtures/whole_foods_sockeye.png"

screenshot_b64 = base64.b64encode(FIXTURE.read_bytes()).decode()
payload = json.dumps({
  "screenshot": screenshot_b64,
  "url": "https://www.wholefoodsmarket.com/product/sockeye-salmon",
  "related_products": [],
}).encode()

N = 5
times = []
print(f"Benchmarking {BACKEND_URL} with {N} requests...")
for i in range(N):
  start = time.time()
  req = urllib.request.Request(
    f"{BACKEND_URL}/analyze",
    data=payload,
    headers={"Content-Type": "application/json"},
  )
  urllib.request.urlopen(req)
  elapsed = (time.time() - start) * 1000
  times.append(elapsed)
  print(f"  [{i+1}/{N}] {elapsed:.0f}ms")

print(f"\np50: {statistics.median(times):.0f}ms")
print(f"p90: {sorted(times)[int(N * 0.9)]:.0f}ms")
print(f"max: {max(times):.0f}ms")
print("PASS" if sorted(times)[int(N * 0.9)] < 3000 else "FAIL — p90 exceeds 3000ms")
```

---

## Edge Cases to Verify

### Unknown Species (DB miss)
- `get_species("xenophish 9000")` returns `None`
- All scoring functions handle `None` gracefully with neutral defaults
- Explanation states "limited information was available for this species"

### Wild/Farmed Unknown Resolution
- Atlantic salmon with `wild_or_farmed = "unknown"` → scoring defaults to farmed
- This is the MOSTLY_FARMED heuristic in `compute_score()`

### Cert Detection: Partial String Matches
- "Marine Stewardship Council" in certifications list → must map to 15 pts cert score
- "Responsibly Farmed by Whole Foods" → matches "Responsibly Farmed" → 3 pts
- Verify `CERT_SCORES` matching logic in `scoring.py` covers these

### Empty Related Products
- If `related_products = []`, alternatives fall back to seed DB
- Seed DB alternatives show "(check if available on this site)" note

### DOM Scraping Returns Non-Seafood Only
- All 15 scraped product names are non-seafood (e.g. chicken, vegetables)
- `identify_species_from_names()` returns all `null` values
- Falls back to seed alternatives

### Side Panel Persistence
- User opens panel, analyzes page, navigates to another page within same site
- Panel retains the previous result (correct behavior — result is still visible)
- User can click "Analyze Again" to re-run on the new page

---

## Manual Test Checklist (Whole Foods Only)

- [ ] Wild Alaskan sockeye salmon product page → grade A, score ≥ 75
- [ ] Farmed Atlantic salmon product page → grade B or C
- [ ] A non-seafood product page (e.g. Whole Foods butter) → non-seafood view
- [ ] Page with MSC badge visible → "MSC" appears in extraction tags
- [ ] Click "Not right?", change species to "bluefin tuna" → grade drops to D
- [ ] Cancel correction → previous result restored
- [ ] Related products scraped from carousel on Whole Foods seafood section page → alternatives show real product names (from_page: true)
- [ ] Disconnect from network during analysis → error view appears with retry button
- [ ] Retry after reconnecting → analysis succeeds
- [ ] Extension persists across page navigations (side panel stays open)

---

## Automated Success Criteria

```bash
cd /Users/jordan/sussed/backend
uv run mypy . 2>&1; uv run ruff check . 2>&1; uv run pytest tests/ -v 2>&1

# Benchmark (requires local server running)
uv run uvicorn main:app --port 8000 &
uv run python -m scripts.benchmark http://localhost:8000
# Expected: p90 < 3000ms
```
