# Phase 6: Testing & Optimization

**Days:** 8–10 | **Depends on:** Phase 5 | **Blocks:** Phase 7

---

## 10 Species Test Cases

These 10 cases cover the full grade range and both wild/farmed scenarios.
Add screenshots to `backend/tests/fixtures/` and parameterize in `test_analyze.py`.

| # | Species | Method | Origin | Expected Grade | Rationale |
|---|---|---|---|---|---|
| 1 | Alaska sockeye salmon | Purse seine | Bristol Bay, AK | A | MSC-cert, not overfished, high resilience |
| 2 | Atlantic mackerel | Purse seine | North Atlantic | A | Highly abundant, fast-reproducing, good management |
| 3 | US farmed oysters | Aquaculture | Pacific NW | A | Filter feeder, ASC-eligible, improves water quality |
| 4 | Pacific albacore tuna | Pole and line | North Pacific | A | Pole & line, not overfished, well-managed |
| 5 | Alaskan pollock | Midwater trawl | Bering Sea | B | MSC-certified, but midwater trawl is B-tier |
| 6 | Atlantic cod | Bottom trawl | Norway | C | Recovering stocks, bottom trawl penalty |
| 7 | Atlantic salmon | Aquaculture | Norway (no cert shown) | C | No cert visible, high carnivory, escapes risk |
| 8 | Imported shrimp | Unknown | India/Thailand | D | High bycatch region, minimal management, unknown gear |
| 9 | Bluefin tuna | Longline | Atlantic | D | Critically depleted, high vulnerability, longline bycatch |
| 10 | Orange roughy | Bottom trawl | New Zealand | D | 100+ year lifespan, extreme vulnerability |

```python
# backend/tests/test_species_cases.py
import pytest
from scoring import compute_total_score, breakdown_to_grade
from models import ProductInfo

TEST_CASES = [
  # (description, ProductInfo kwargs, min_grade, max_grade)
  (
    "Alaska sockeye salmon - MSC purse seine",
    dict(is_seafood=True, species="sockeye salmon", wild_or_farmed="wild",
         fishing_method="Purse seine", origin_region="Alaska", certifications=["MSC"]),
    "A", "A"
  ),
  (
    "Atlantic mackerel - purse seine",
    dict(is_seafood=True, species="Atlantic mackerel", wild_or_farmed="wild",
         fishing_method="Purse seine", origin_region="North Atlantic", certifications=[]),
    "A", "B"
  ),
  (
    "US farmed oysters",
    dict(is_seafood=True, species="Pacific oyster", wild_or_farmed="farmed",
         fishing_method=None, origin_region="Pacific Northwest", certifications=["ASC"]),
    "A", "A"
  ),
  (
    "Imported shrimp no cert",
    dict(is_seafood=True, species="whiteleg shrimp", wild_or_farmed="farmed",
         fishing_method=None, origin_region="Thailand", certifications=[]),
    "C", "D"
  ),
  (
    "Bluefin tuna longline",
    dict(is_seafood=True, species="bluefin tuna", wild_or_farmed="wild",
         fishing_method="Longline", origin_region="Atlantic", certifications=[]),
    "D", "D"
  ),
  (
    "Orange roughy bottom trawl",
    dict(is_seafood=True, species="orange roughy", wild_or_farmed="wild",
         fishing_method="Bottom trawl", origin_region="New Zealand", certifications=[]),
    "D", "D"
  ),
]

GRADE_ORDER = ["A", "B", "C", "D"]

@pytest.mark.parametrize("description,kwargs,min_grade,max_grade", TEST_CASES)
def test_species_scoring(description, kwargs, min_grade, max_grade):
  product = ProductInfo(**kwargs)
  breakdown = compute_total_score(product)
  total, grade = breakdown_to_grade(breakdown)

  min_idx = GRADE_ORDER.index(min_grade)
  max_idx = GRADE_ORDER.index(max_grade)
  actual_idx = GRADE_ORDER.index(grade)

  assert min_idx <= actual_idx <= max_idx, (
    f"{description}: expected {min_grade}–{max_grade}, got {grade} (score={total})\n"
    f"breakdown={breakdown}"
  )
```

## Response Time Benchmark

```python
# backend/scripts/benchmark.py
"""Run benchmark against local or remote backend."""
import time, statistics, base64, sys
from pathlib import Path
import urllib.request, json

BACKEND_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
FIXTURE = Path(__file__).parent.parent / "tests/fixtures/whole_foods_salmon.png"

screenshot_b64 = base64.b64encode(FIXTURE.read_bytes()).decode()
payload = json.dumps({
  "screenshot": screenshot_b64,
  "url": "https://www.wholefoodsmarket.com/product/salmon"
}).encode()

N = 5
times = []
for i in range(N):
  start = time.time()
  req = urllib.request.Request(
    f"{BACKEND_URL}/analyze",
    data=payload,
    headers={"Content-Type": "application/json"},
  )
  urllib.request.urlopen(req)
  times.append((time.time() - start) * 1000)

print(f"n={N} requests to {BACKEND_URL}")
print(f"  p50: {statistics.median(times):.0f}ms")
print(f"  p90: {sorted(times)[int(N * 0.9)]:.0f}ms")
print(f"  max: {max(times):.0f}ms")
```

## Caching Strategy

Add a simple in-memory LRU cache for repeated species lookups to cut latency:

```python
# backend/database.py — add caching
from functools import lru_cache

@lru_cache(maxsize=512)
fn get_species_cached(common_name: str) -> tuple | None:
  """Cached version — SQLite reads are already fast but this helps for repeated species."""
  result = get_species(common_name)
  if result is None:
    return None
  # Return tuple (hashable) for lru_cache compatibility
  return tuple(sorted(result.items()))

# In scoring.py, use get_species_cached and convert back to dict
```

## Edge Cases to Verify

### Unknown Species
- Gemini returns a species name not in the database → `get_species()` returns None
- Scoring functions handle `None` gracefully with neutral defaults (verified in Phase 4)
- Explanation should note "limited data available for this species"

### Farmed vs Wild Ambiguity
- "Atlantic salmon" with no wild/farmed label shown → `wild_or_farmed = "unknown"`
- System defaults to farmed scoring (Atlantic salmon is almost always farmed at grocery stores)
- Add a heuristic in `run_pipeline()`:
  ```python
  if product.wild_or_farmed == "unknown":
    MOSTLY_FARMED = {"atlantic salmon", "tilapia", "catfish", "rainbow trout",
                     "pangasius", "basa"}
    if (product.species or "").lower() in MOSTLY_FARMED:
      product = product.model_copy(update={"wild_or_farmed": "farmed"})
  ```

### SPA Navigation
- Tested in Phase 5 MutationObserver. Re-verify overlay doesn't appear twice.

### Content Security Policy (CSP) Conflicts
- If `shadow.innerHTML` is blocked by site CSP, fall back to `document.createElement` approach
- Test on Amazon (strict CSP site): if inline styles blocked, use a style element

## Manual Test Checklist

- [ ] Whole Foods salmon product page: badge appears, grade A or B
- [ ] Amazon Fresh tilapia page: badge appears, grade C or lower
- [ ] Instacart shrimp page: badge appears
- [ ] Amazon Fresh pasta page (non-seafood): no badge
- [ ] Navigate Whole Foods SPA: seafood → non-seafood → old badge gone, no new badge
- [ ] Navigate Whole Foods SPA: non-seafood → seafood → badge appears
- [ ] Popup "Analyze" button works on any page
- [ ] Panel expand/collapse works
- [ ] × close button works
- [ ] Error state (disconnect backend): error panel shows, no crash

## Verification

```bash
cd /Users/jordan/sussed/backend
uv run mypy . 2>&1; uv run ruff check . 2>&1; uv run pytest tests/ -v 2>&1

# Response time benchmark (against local server):
uv run uvicorn main:app &
uv run python -m scripts.benchmark http://localhost:8000
```
