# Phase Pre: Extract `pipeline.py`

**Prerequisite for Phases 1 and 2.**
Extracts `_run_scoring_pipeline` from `main.py` into a new `pipeline.py` module so both `main.py` and `voice_session.py` can import it without circular imports. Zero logic changes — pure structural refactor.

---

## Files Changed

- **NEW** `backend/pipeline.py`
- **MODIFY** `backend/main.py`

---

## `backend/pipeline.py` (new)

```pseudocode
# backend/pipeline.py

imports:
  from alternatives import score_alternatives
  from explanation import generate_content
  from models import ProductInfo, SustainabilityScore, ScoreBreakdown
  from scoring import compute_score

DEFINE run_scoring_pipeline(product_info: ProductInfo, related_products: list[str]) -> SustainabilityScore:
  breakdown, score, grade = compute_score(product_info)
  alternatives, alts_label = score_alternatives(related_products, product_info, score, grade)
  explanation, score_factors = generate_content(product_info, breakdown, score, grade)
  RETURN SustainabilityScore(
    score=score,
    grade=grade,
    breakdown=breakdown,
    alternatives=alternatives,
    alternatives_label=alts_label,
    explanation=explanation,
    score_factors=score_factors,
    product_info=product_info,
  )

DEFINE not_seafood_response(product_info: ProductInfo) -> SustainabilityScore:
  RETURN SustainabilityScore(
    score=0,
    grade="D",
    breakdown=ScoreBreakdown(biological=0, practices=0, management=0, ecological=0),
    alternatives=[],
    alternatives_label="",
    explanation="",
    score_factors=[],
    product_info=product_info,
  )
```

---

## `backend/main.py` (modify)

```pseudocode
# REMOVE these functions (move to pipeline.py):
#   _run_scoring_pipeline()
#   _not_seafood_response()

# ADD import:
from pipeline import run_scoring_pipeline, not_seafood_response

# UPDATE /analyze endpoint:
# BEFORE: return _not_seafood_response(product_info)
# AFTER:  return not_seafood_response(product_info)

# BEFORE: return _run_scoring_pipeline(product_info, request.related_products)
# AFTER:  return run_scoring_pipeline(product_info, request.related_products)

# UPDATE /score endpoint:
# BEFORE: return _run_scoring_pipeline(request.product_info, [])
# AFTER:  return run_scoring_pipeline(request.product_info, [])
```

---

## Success Criteria

### Automated
- [x] All existing tests pass without modification after this refactor
- [x] `uv run mypy .` passes
- [x] `uv run ruff check .` passes

### Manual
- [ ] None — this is a pure refactor
