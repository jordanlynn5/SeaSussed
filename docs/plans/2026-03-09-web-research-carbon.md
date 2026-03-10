# Web Research + Carbon Footprint + Mercury/Health Plan

**Date:** 2026-03-09
**Feature:** Enrich scoring with web research, add carbon footprint (Wolfram), add mercury/health card
**Phase files:** `docs/plans/2026-03-09-web-research-carbon-phases/`

---

## What We're Building

Three features that work together to fill the analysis timeline with useful information
while improving scoring accuracy:

### 1. Web Research Enrichment (Gemini + Google Search grounding)

When the screen analyzer can't find fishing method, certifications, or origin on the
product page, a separate Gemini call with `google_search` grounding researches the
brand/product online. Example: "Wild Planet sardines" page doesn't mention fishing
method, but web research finds they use pole & line fishing and are MSC certified.

**Trigger:** Only when `fishing_method`, `certifications`, or `origin_region` are missing
after screen analysis. Skip entirely if all three are present.

**Trust level:** Web research findings are treated identically to page-visible data for
scoring purposes.

### 2. Carbon Footprint (Wolfram Alpha)

A small info card showing estimated CO₂ per serving, with comparison to beef. Runs in
parallel with research — fills the loading gap with useful content.

**API:** Wolfram Alpha Full Results API (`WOLFRAM_APP_ID` env var, already available).
Graceful degradation: card hidden if env var unset or WA returns no data.

### 3. Mercury / Health Advisory (static lookup)

Instant display — zero API calls. Uses FDA-published mercury levels for common seafood
species. Shows mercury tier (Best Choice / Good Choice / etc.) and omega-3 info.

**Data source:** FDA/EPA mercury advisory table (hardcoded dict, ~40 species).

---

## Progressive Timeline (User Experience)

```
t=0.0s  Screen analyzer returns ProductInfo
        ├─ Compute initial score → emit SSE "scored" phase
        └─ Show mercury/health card (static, instant)

t=0.5s  Carbon footprint returns (Wolfram) → emit SSE "carbon" phase
        └─ Show carbon card

t=2-4s  Web research completes (if needed) → recompute score
        Alternatives + explanation generated
        → emit SSE "complete" phase with enriched data
        └─ Score card updates, explanation + alternatives appear
```

For the `/analyze` (non-streaming) endpoint, all steps run and the final enriched
result is returned. For voice, the enrichment happens during tool execution (transparent).

---

## Architecture

```
                    ┌─ mercury_lookup(species)     → instant, static
Screen Analyzer ──┤
  (ProductInfo)    ├─ wolfram_carbon(species)      → ~0.5s, Wolfram API
                    │
                    ├─ research_product(ProductInfo) → ~2-3s, Gemini + google_search
                    │    └─ returns EnrichedProductInfo (fills gaps only)
                    │
                    └─ compute_score(enriched)       → instant, pure Python
                         ├─ alternatives (Gemini)
                         └─ explanation (Gemini)
```

**Key constraint:** Gemini API rejects mixing `google_search` with `function_declarations`
in the same request. The research step uses a SEPARATE `generate_content` call with only
`google_search` enabled — not part of the screen analyzer or voice Live session.

---

## New Files

| File | Purpose |
|---|---|
| `backend/research.py` | Web research via Gemini + google_search grounding |
| `backend/wolfram.py` | Wolfram Alpha carbon footprint queries |
| `backend/health.py` | Static mercury/omega-3 lookup (FDA data) |
| `backend/tests/test_research.py` | Tests for research module |
| `backend/tests/test_wolfram.py` | Tests for Wolfram module |
| `backend/tests/test_health.py` | Tests for health lookup |

## Modified Files

| File | Changes |
|---|---|
| `backend/models.py` | Add `CarbonFootprint`, `HealthInfo` models; add fields to `SustainabilityScore` |
| `backend/pipeline.py` | Insert research + carbon + health steps; update progressive generator |
| `backend/main.py` | Emit `carbon` and `health` SSE phases |
| `backend/voice_session.py` | Include health + carbon in tool response context |
| `extension/sidepanel.html` | Carbon card + health card HTML containers |
| `extension/sidepanel.js` | Render carbon + health cards; handle new SSE phases; update on enriched score |

---

## Data Models

```python
# models.py additions

class CarbonFootprint(BaseModel):
    co2_kg_per_serving: float         # kg CO₂e per ~113g serving
    comparison_text: str              # "vs 6.6 kg for beef"
    source: str = "Wolfram Alpha"

class HealthInfo(BaseModel):
    mercury_category: str             # "Best Choice" | "Good Choice" | "Choices to Avoid"
    mercury_ppm: float | None         # average ppm (None if only tier known)
    omega3_note: str                  # "Rich in omega-3s" | "Moderate omega-3s" | ""
    serving_advice: str               # "FDA: 2-3 servings/week" etc.
    health_grade: Literal["A","B","C","D"]

# SustainabilityScore additions
class SustainabilityScore(BaseModel):
    ...existing fields...
    carbon: CarbonFootprint | None = None
    health: HealthInfo | None = None
```

---

## API Contract Changes

### SSE stream (`POST /analyze/stream`)

New phases inserted between `scored` and `complete`:

```
data: {"phase": "scored", "product_info": {...}, "score": 72, ...}

data: {"phase": "health", "health": {"mercury_category": "Best Choice", ...}}

data: {"phase": "carbon", "carbon": {"co2_kg_per_serving": 1.8, ...}}

data: {"phase": "complete", "result": {...enriched score with health + carbon...}}
```

### Non-streaming endpoints

`POST /analyze` and `POST /score` responses gain two optional fields:
```json
{
  "score": 87,
  ...existing...,
  "carbon": { "co2_kg_per_serving": 1.8, "comparison_text": "vs 6.6 kg for beef", "source": "Wolfram Alpha" },
  "health": { "mercury_category": "Best Choice", "mercury_ppm": 0.022, "omega3_note": "Rich in omega-3s", "serving_advice": "FDA recommends 2-3 servings/week", "health_grade": "A" }
}
```

Both are `null` when data is unavailable. Backward compatible.

---

## Environment Variables

```bash
export WOLFRAM_APP_ID=...   # Wolfram Alpha App ID (do NOT commit to git)
```

If `WOLFRAM_APP_ID` is unset: carbon card hidden, no errors. Full graceful degradation.

Cloud Run deploy command gains: `WOLFRAM_APP_ID` in `--set-env-vars`.

---

## Phase Summary

| Phase | Name | Files Created/Modified | Batch |
|---|---|---|---|
| 1 | Health lookup module | `health.py`, `tests/test_health.py`, `models.py` | ✅ complete |
| 2 | Wolfram carbon module | `wolfram.py`, `tests/test_wolfram.py`, `models.py` | ✅ complete |
| 3 | Web research module | `research.py`, `tests/test_research.py` | ✅ complete |
| 4 | Pipeline integration | `pipeline.py`, `main.py`, `voice_session.py`, `scoring.py` | ✅ complete |
| 5 | Extension UI | `sidepanel.html`, `sidepanel.js` | ✅ complete |

Phases 1, 2, and 3 are independent — no shared file modifications (models.py additions
are non-overlapping fields). They can run in parallel via `/batch`.

Phase 4 depends on all three completing. Phase 5 depends on Phase 4's API contract.

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Gemini google_search can't mix with function_declarations | Separate `generate_content` call, not part of screen analyzer or Live session |
| Wolfram has no data for obscure species | Return None → carbon card hidden |
| Web research returns incorrect brand info | Gemini prompt instructs: only return info specifically about the brand + product queried |
| Added latency (2-4s for research) | Health card instant, carbon ~0.5s — user always has content to view |
| Wolfram API rate limit (2000/month free) | `@lru_cache` on queries; common species cached in-process |
| Research enriches score after initial display | UI smoothly updates score card when enriched data arrives |
