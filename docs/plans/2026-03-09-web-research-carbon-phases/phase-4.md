# Phase 4: Pipeline Integration

**Files modified:** `backend/pipeline.py`, `backend/main.py`, `backend/voice_session.py`
**Depends on:** Phases 1, 2, 3

---

## Goal

Wire health lookup, carbon footprint, and web research into the existing analysis
pipeline. Update the SSE stream to emit new phases. Update voice session tool responses
to include enriched data.

---

## 1. Pipeline Changes (`backend/pipeline.py`)

### `run_scoring_pipeline` — add research + health + carbon

Current flow:
```
compute_score → gather(alternatives, explanation) → SustainabilityScore
```

New flow:
```
research_product (if needed) → compute_score (enriched) →
  gather(alternatives, explanation, carbon) → SustainabilityScore (with health + carbon)
```

```python
# New imports at top
from health import get_health_info
from research import research_product
from wolfram import get_carbon_footprint

async def run_scoring_pipeline(
    product_info: ProductInfo, related_products: list[str]
) -> SustainabilityScore:
    # Step 1: Enrich via web research (only if fields missing)
    enriched = await asyncio.to_thread(research_product, product_info)

    # Step 2: Score with enriched data
    breakdown, score, grade = compute_score(enriched)

    # Step 3: Health lookup (instant, static)
    health = get_health_info(enriched.species)

    # Step 4: Run alternatives + explanation + carbon in parallel
    (alternatives, alts_label), (explanation, score_factors), carbon = (
        await asyncio.gather(
            asyncio.to_thread(
                score_alternatives, related_products, enriched, score, grade
            ),
            asyncio.to_thread(
                generate_content, enriched, breakdown, score, grade
            ),
            asyncio.to_thread(get_carbon_footprint, enriched.species or ""),
        )
    )

    return SustainabilityScore(
        score=score,
        grade=grade,
        breakdown=breakdown,
        alternatives=alternatives,
        alternatives_label=alts_label,
        explanation=explanation,
        score_factors=score_factors,
        product_info=enriched,  # NOTE: enriched, not original
        health=health,
        carbon=carbon,
    )
```

### `analyze_page_progressive` — emit health + carbon phases

```python
async def analyze_page_progressive(
    page_analysis: PageAnalysis, related_products: list[str]
) -> AsyncGenerator[dict[str, Any], None]:
    # ... (no_seafood and product_listing paths unchanged) ...

    # Single product → progressive
    product = seafood_products[0]

    # Phase 0: instant health (static lookup)
    health = get_health_info(product.species)
    if health:
        yield {"phase": "health", "health": health.model_dump()}

    # Phase 1: initial score (before research)
    breakdown, score, grade = compute_score(product)
    yield {
        "phase": "scored",
        "product_info": product.model_dump(),
        "score": score,
        "grade": grade,
        "breakdown": breakdown.model_dump(),
    }

    # Phase 1.5: research + carbon in parallel
    enriched_product, carbon = await asyncio.gather(
        asyncio.to_thread(research_product, product),
        asyncio.to_thread(get_carbon_footprint, product.species or ""),
    )

    if carbon:
        yield {"phase": "carbon", "carbon": carbon.model_dump()}

    # If research found new data, recompute score
    enriched_changed = (enriched_product is not product)
    if enriched_changed:
        breakdown, score, grade = compute_score(enriched_product)
        yield {
            "phase": "enriched",
            "product_info": enriched_product.model_dump(),
            "score": score,
            "grade": grade,
            "breakdown": breakdown.model_dump(),
        }

    # Phase 2: alternatives + explanation (use enriched data)
    final_product = enriched_product if enriched_changed else product
    (alternatives, alts_label), (explanation, score_factors) = await asyncio.gather(
        asyncio.to_thread(
            score_alternatives, related_products, final_product, score, grade
        ),
        asyncio.to_thread(
            generate_content, final_product, breakdown, score, grade
        ),
    )

    full_result = SustainabilityScore(
        score=score,
        grade=grade,
        breakdown=breakdown,
        alternatives=alternatives,
        alternatives_label=alts_label,
        explanation=explanation,
        score_factors=score_factors,
        product_info=final_product,
        health=health,
        carbon=carbon,
    )
    yield {
        "phase": "complete",
        "page_type": "single_product",
        "result": full_result.model_dump(),
    }
```

### `analyze_page` — include health + carbon in non-streaming path

The non-streaming path calls `run_scoring_pipeline` which already includes everything.
No changes needed here — the updated `SustainabilityScore` will include health + carbon.

---

## 2. Main.py Changes

The SSE generator in `analyze_stream` already yields whatever `analyze_page_progressive`
emits, so no changes needed to `main.py` — the new phases flow through automatically.

---

## 3. Voice Session Changes (`backend/voice_session.py`)

### `_handle_analyze_current_product`

The voice tool already calls `run_scoring_pipeline` which now includes research +
health + carbon. Update the tool response dict to include the new data:

```python
async def _handle_analyze_current_product(self) -> dict[str, Any]:
    # ... (existing screenshot capture + analysis) ...

    score_result = await run_scoring_pipeline(
        product_info, msg.get("related_products", [])
    )

    # ... (existing score_result send) ...

    return {
        "score": score_result.score,
        "grade": score_result.grade,
        "species": score_result.product_info.species,          # use enriched
        "wild_or_farmed": score_result.product_info.wild_or_farmed,
        "origin_region": score_result.product_info.origin_region,
        "certifications": score_result.product_info.certifications,
        "fishing_method": score_result.product_info.fishing_method,  # NEW
        "explanation": score_result.explanation,
        "alternatives": [
            {"species": a.species, "score": a.score, "grade": a.grade}
            for a in score_result.alternatives[:2]
        ],
        "not_seafood": not score_result.product_info.is_seafood,
        # New context for Gemini voice to mention:
        "health_advisory": (
            score_result.health.mercury_category if score_result.health else None
        ),
        "carbon_co2": (
            score_result.carbon.co2_kg_per_serving if score_result.carbon else None
        ),
    }
```

### Voice prompt update

Add a short section to `VOICE_SYSTEM_PROMPT`:

```
HEALTH & CARBON CONTEXT:
The tool response may include health_advisory (FDA mercury tier) and carbon_co2
(kg CO₂ per serving). If present, weave them naturally into your response when
relevant — don't list them robotically. Examples:
- "Plus, sardines are a Best Choice for mercury — safe to eat several times a week."
- "One nice thing about this fish — the carbon footprint is really low compared to
  other proteins."
Only mention these if the user seems interested or if the data is noteworthy
(e.g., high mercury = always mention).
```

---

## 4. Update Existing Tests

### `tests/test_pipeline.py`

Patch the new imports so existing tests don't break:

```python
# Add patches for new modules in existing pipeline tests
@patch("pipeline.get_carbon_footprint", return_value=None)
@patch("pipeline.research_product", side_effect=lambda p: p)
@patch("pipeline.get_health_info", return_value=None)
```

### `tests/test_voice.py`

The existing voice tests mock `run_scoring_pipeline` — they should continue to work
since the mock return value shape hasn't changed (health + carbon default to None).

---

## Success Criteria

### Automated
- `uv run mypy .` — no errors
- `uv run ruff check .` — clean
- `uv run pytest` — all existing + new tests pass

### Manual
- Start backend locally, analyze a Wild Planet sardines page:
  - Initial score appears immediately
  - Health card appears instantly
  - Carbon card appears ~1s later
  - Score updates if research found new info (fishing method, certs)
  - Explanation + alternatives appear last
- Voice session: analyze a product, Gemini mentions mercury/health if relevant
