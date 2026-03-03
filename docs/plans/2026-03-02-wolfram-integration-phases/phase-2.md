# Phase WA-2: Backend Integration

**Blocked by:** Phase WA-1 (requires `wolfram.py`)

**Goal:** Wire `wolfram.py` into the existing backend — add `HealthInfo` to models, use species fallback in scoring, return health data from both API endpoints.

---

## Files Changed

| File | Change |
|---|---|
| `backend/models.py` | Add `HealthInfo` class; add `health` field to `SustainabilityScore` |
| `backend/scoring.py` | Call `get_species_fallback()` when DB returns None |
| `backend/main.py` | Call `get_health_data()` in pipeline; pass to response |
| `backend/CLAUDE.md` (root) | Document `WOLFRAM_APP_ID` env var |
| `backend/tests/test_scoring.py` | Add fallback scoring test |

---

## Implementation

### `backend/models.py`

Add `HealthInfo` before `SustainabilityScore`, add `health` field:

```python
# Add after ScoreFactor class:

class HealthInfo(BaseModel):
    mercury_ppm: float | None           # average ppm; None if WA only gave tier
    mercury_category: str | None        # "Best Choice" | "Good Choice" | "Lower Choice" | "Avoid"
    health_grade: Literal["A", "B", "C", "D"]
    omega3_mg_per_serving: float | None # mg DHA+EPA per 85g serving; None if not available
    source_note: str                    # "Wolfram Alpha" — shown in UI for transparency


# Modify SustainabilityScore — add one optional field:
class SustainabilityScore(BaseModel):
    score: int
    grade: Literal["A", "B", "C", "D"]
    breakdown: ScoreBreakdown
    alternatives: list[Alternative]
    alternatives_label: str
    explanation: str
    score_factors: list[ScoreFactor]
    product_info: ProductInfo
    health: HealthInfo | None = None    # None = WA had no data; UI hides card
```

---

### `backend/scoring.py`

Add WA species fallback when `get_species()` returns None. The existing scoring math is unchanged — fallback data simply fills the `species_data` dict that the scoring functions already accept.

```python
# Add import at top:
from wolfram import get_species_fallback

# Modify compute_score() — replace:
#   species_data = get_species(product.species or "") if product.species else None
# with:

def compute_score(product: ProductInfo) -> tuple[ScoreBreakdown, int, Literal["A","B","C","D"]]:
    species_data: dict[str, Any] | None = None
    if product.species:
        species_data = get_species(product.species)
        if species_data is None:
            # Not in our DB — try Wolfram Alpha fallback
            species_data = get_species_fallback(product.species)
            # species_data may still be None if WA has no data; scoring handles None fine
    ...rest of function unchanged...
```

The explanation text in `explanation.py` already handles `None` species_data gracefully. When WA provides partial data (e.g. only `iucn_code`), the scoring functions use what's available and default the rest:

```python
# score_biological() already does:
vuln = float(species_data.get("vulnerability") or 50.0)   # safe with partial dict
resilience = resilience_map.get(species_data.get("resilience") or ""), 3.0)
iucn_score = iucn_scores.get(species_data.get("iucn_code") or "LC", 2.0)
```

No changes needed to the scoring functions themselves.

---

### `backend/main.py`

Add `get_health_data` call in `_run_scoring_pipeline()` and include `health` in both responses:

```python
# Add import:
from wolfram import get_health_data

# Modify _run_scoring_pipeline():
def _run_scoring_pipeline(
    product_info: ProductInfo, related_products: list[str]
) -> SustainabilityScore:
    breakdown, score, grade = compute_score(product_info)
    alternatives, alts_label = score_alternatives(related_products, product_info, score, grade)
    explanation, score_factors = generate_content(product_info, breakdown, score, grade)
    health = get_health_data(product_info.species) if product_info.species else None  # NEW
    return SustainabilityScore(
        score=score,
        grade=grade,
        breakdown=breakdown,
        alternatives=alternatives,
        alternatives_label=alts_label,
        explanation=explanation,
        score_factors=score_factors,
        product_info=product_info,
        health=health,  # NEW
    )

# _not_seafood_response() — no change needed (health defaults to None)
```

---

### `CLAUDE.md` (root)

Add `WOLFRAM_APP_ID` to the Local Dev Environment Variables section:

```diff
 export GOOGLE_CLOUD_PROJECT=seasussed-489008
 export GOOGLE_CLOUD_REGION=us-central1
 export GOOGLE_CLOUD_LOCATION=us-central1
 export GOOGLE_GENAI_USE_VERTEXAI=1
+export WOLFRAM_APP_ID=your-app-id-here   # from developer.wolframalpha.com → My Apps
 # Auth: gcloud auth application-default login
```

Also add to Cloud Run deploy command:
```diff
 --set-env-vars GOOGLE_CLOUD_PROJECT=seasussed-489008,GOOGLE_CLOUD_REGION=us-central1
+--set-env-vars WOLFRAM_APP_ID=$$WOLFRAM_APP_ID
```

---

### `backend/tests/test_scoring.py` additions

```python
def test_wolfram_fallback_does_not_crash_scoring() -> None:
    """When species is not in DB and WA returns None, scoring uses neutral defaults."""
    # "zabrafish_unknown_zz" won't be in DB or WA
    product = ProductInfo(
        is_seafood=True,
        species="zabrafish_unknown_zz",
        wild_or_farmed="wild",
        fishing_method=None,
        origin_region=None,
        certifications=[],
    )
    breakdown, score, grade = compute_score(product)
    assert 0 <= score <= 100
    assert grade in ("A", "B", "C", "D")
    # Should return neutral-ish score (biological=10.0 + ecological=12.0 defaults)
    assert breakdown.biological == 10.0
    assert breakdown.ecological == 12.0
```

---

## Success Criteria

### Automated (pytest)
- [ ] `test_wolfram_fallback_does_not_crash_scoring` passes
- [ ] All existing 28 tests still pass (no regressions)
- [ ] `mypy` clean — `HealthInfo` fully typed; `health: HealthInfo | None` field clean
- [ ] `ruff` clean

### Manual
- [ ] `GET /health` still returns `{"status": "ok"}`
- [ ] `POST /analyze` with Whole Foods sockeye screenshot returns `health` field with `health_grade: "A"` and `mercury_category: "Best Choice"`
- [ ] `POST /analyze` with pasta screenshot returns `health: null`
- [ ] `POST /score` with `{"species": "swordfish", ...}` returns `health.health_grade` of `"C"` or `"D"`
- [ ] `POST /score` with `{"species": "zabrafish_unknown_zz"}` returns `health: null` without error

### Pre-commit
- [ ] Full suite: `mypy . && ruff check . && pytest` all green
