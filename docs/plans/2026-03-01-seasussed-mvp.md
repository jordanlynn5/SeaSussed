# SeaSussed MVP — Implementation Plan

**Date:** 2026-03-01
**Deadline:** 2026-03-16 (15 days)
**Research doc:** `docs/research/2026-03-01-seasussed-research.md`

---

## What We're Building

A Chrome extension + Cloud Run Python backend that:
1. Captures a screenshot of any grocery product page
2. Uses Gemini 2.5 Flash (vision) to identify the seafood species, origin, and fishing method
3. Scores the product 0–100 across five sustainability dimensions
4. Displays a grade (A–D) with breakdown and 3 better alternatives

Category: **UI Navigator** — the agent reads the screen visually, not the DOM. Works on any grocery site.

---

## Architecture

```
[Chrome Extension — Manifest V3]
  content_script.js    injects overlay into product pages
  background.js        service worker: captureVisibleTab + fetch to backend
  popup.html/js        extension status + settings

        │  POST /analyze { screenshot: base64, url: string }
        ▼

[Cloud Run — Python FastAPI + ADK]
  SequentialAgent:
    1. ScreenAnalyzerAgent  (gemini-2.5-flash, vision)
         reads screenshot → extracts species, origin, method, certifications
    2. SustainabilityScorerAgent (gemini-2.5-flash + DB tools)
         scores species → returns breakdown + 3 alternatives

  SQLite (embedded):
    species table     (FishBase: vulnerability, resilience, IUCN)
    msc_fisheries     (MSC CSV: certified wild-capture fisheries)
    noaa_species      (NOAA FishWatch: US overfishing status)
    fishing_methods   (hand-coded gear impact scores)
    alternatives      (curated species → better-alternatives mapping)

        │  JSON: { score, grade, breakdown, alternatives, explanation }
        ▼

[Extension UI — content script overlay]
  Score badge (grade letter + color) on product image
  Expanded panel: factor breakdown + alternatives + explanation
```

---

## Scoring Model

| Category | Wild | Farmed | Primary Data |
|---|---|---|---|
| 1. Biological & Population | 20 pts | 20 pts | FishBase vulnerability + resilience |
| 2. Fishing Practices | 25 pts | — | Gear type table |
| 3. Aquaculture Practices | — | 25 pts | ASC/BAP cert + species carnivory |
| 4. Management & Regulation | 30 pts | 30 pts | MSC cert + NOAA status + country |
| 5. Environmental & Ecological | 25 pts | 25 pts | FishBase trophic + IUCN + climate |

Grade: **A** (80–100) 🟢 · **B** (60–79) 🟡 · **C** (40–59) 🟠 · **D** (0–39) 🔴

---

## Phase Summary

| Phase | Name | Days | Depends On | Batch? |
|---|---|---|---|---|
| 1 | GCP Setup & Backend Scaffold | 1–2 | — | ✅ with 2, 3 |
| 2 | Chrome Extension Scaffold | 1–2 | — | ✅ with 1, 3 |
| 3 | Sustainability Database | 2–3 | — | ✅ with 1, 2 |
| 4 | Gemini Agent Pipeline | 3–6 | 1, 3 | — |
| 5 | Extension UI Integration | 5–8 | 2, 4 | — |
| 6 | Testing & Optimization | 8–10 | 5 | — |
| 7 | Deployment & Submission | 10–14 | 6 | — |

**Phases 1, 2, and 3 are `[batch-eligible]`** — no file overlap, no dependencies between them.

---

## Phase 1: GCP Setup & Backend Scaffold [batch-eligible]

**Target:** Days 1–2
**Phase file:** `docs/plans/2026-03-01-seasussed-mvp-phases/phase-1-gcp-backend-scaffold.md`

**Deliverable:** FastAPI app running on Cloud Run with a working `/health` endpoint.

### Automated Success Criteria
- `gcloud run services list` shows `seasussed-backend` in `us-central1`
- `curl https://<service-url>/health` returns `{"status": "ok"}`
- `uv run pytest tests/test_health.py` passes

### Manual Success Criteria
- GCP project created and billing enabled
- Vertex AI API enabled and `gemini-2.5-flash` accessible via test call

---

## Phase 2: Chrome Extension Scaffold [batch-eligible]

**Target:** Days 1–2
**Phase file:** `docs/plans/2026-03-01-seasussed-mvp-phases/phase-2-extension-scaffold.md`

**Deliverable:** Extension loads in Chrome, captures a screenshot, and logs the base64 to console.

### Automated Success Criteria
- `manifest.json` passes Chrome extension validation (no errors in `chrome://extensions`)

### Manual Success Criteria
- Extension loads unpacked without errors
- Click "Analyze" in popup → background.js captures screenshot → base64 logged to console
- Content script injected into a test product page URL

---

## Phase 3: Sustainability Database [batch-eligible]

**Target:** Days 2–3
**Phase file:** `docs/plans/2026-03-01-seasussed-mvp-phases/phase-3-sustainability-database.md`

**Deliverable:** `backend/data/seafood.db` SQLite database queryable by common name, with 500+ species records.

### Automated Success Criteria
- `uv run python -m scripts.build_database` exits 0
- `uv run pytest tests/test_database.py` passes:
  - query `atlantic salmon` → returns `vulnerability`, `resilience`, `iucn_code`
  - query `bluefin tuna` → returns MSC-not-certified result
  - query `alaskan pollock` → returns NOAA "not overfished" status
  - gear lookup `bottom trawl` → `impact_score` ≤ 10

---

## Phase 4: Gemini Agent Pipeline

**Target:** Days 3–6
**Phase file:** `docs/plans/2026-03-01-seasussed-mvp-phases/phase-4-gemini-agent-pipeline.md`
**Blocked by:** Phase 1 (backend scaffold), Phase 3 (database)

**Deliverable:** `POST /analyze` endpoint returns a structured `SustainabilityScore` JSON from a real screenshot in under 5 seconds.

### Automated Success Criteria
- `uv run pytest tests/test_analyze.py` passes:
  - POST with whole_foods_salmon.png fixture → grade is A or B, score > 60
  - POST with walmart_tilapia.png fixture → responds without error, grade A–D
  - POST with non-seafood page fixture → `{"is_seafood": false}`
- Response time p50 < 3s (measured in test)

---

## Phase 5: Extension UI Integration

**Target:** Days 5–8
**Phase file:** `docs/plans/2026-03-01-seasussed-mvp-phases/phase-5-extension-ui.md`
**Blocked by:** Phase 2 (extension scaffold), Phase 4 (API contract defined)

**Deliverable:** Score badge and expanded panel appear on seafood product pages on Whole Foods and Amazon Fresh.

### Manual Success Criteria
- Load Whole Foods salmon page → badge appears within 4 seconds
- Badge shows correct grade letter and color
- Click badge → panel expands with: score, 3-row factor breakdown, 3 alternatives
- Click badge again → panel collapses
- Load a non-seafood page → no badge appears
- Loading state spinner visible during analysis

---

## Phase 6: Testing & Optimization

**Target:** Days 8–10
**Phase file:** `docs/plans/2026-03-01-seasussed-mvp-phases/phase-6-testing-optimization.md`
**Blocked by:** Phase 5

**Deliverable:** 10 test cases pass, response time < 3s p90, works on 3+ grocery sites.

### Automated Success Criteria
- `uv run pytest tests/` all pass (includes 10 species test cases)
- Response time benchmark: `uv run python scripts/benchmark.py` shows p90 < 3000ms

### Manual Success Criteria
- Works on: Whole Foods, Amazon Fresh, Instacart (3 sites verified)
- Grade A/B for: Alaska sockeye, Atlantic mackerel, US farmed oysters
- Grade C/D for: bluefin tuna, shark, imported shrimp (no cert)
- Error state shown (not crash) for unknown species
- Extension survives page navigation without memory leak

---

## Phase 7: Deployment & Submission

**Target:** Days 10–14 (submit by March 15 for buffer)
**Phase file:** `docs/plans/2026-03-01-seasussed-mvp-phases/phase-7-deployment-submission.md`
**Blocked by:** Phase 6

**Deliverable:** Submitted Devpost entry with all required artifacts.

### Automated Success Criteria
- `curl https://<prod-url>/health` → 200 from production Cloud Run
- GitHub repo is public and `README.md` spin-up instructions work end-to-end

### Manual Success Criteria
- Architecture diagram complete (PNG in `docs/`)
- Demo video ≤ 4 minutes recorded and uploaded
- Devpost form submitted with: video, repo URL, Cloud Run proof, description, architecture diagram
- All 4 judging dimensions covered in description: Innovation (40%), Technical (30%), Demo (30%)

---

## Data Model Reference

```python
# Pydantic models — shared between agents and API

class ProductInfo(BaseModel):
    is_seafood: bool
    species: str | None          # common name, e.g. "Atlantic salmon"
    wild_or_farmed: Literal["wild", "farmed", "unknown"]
    fishing_method: str | None   # e.g. "Bottom trawl", "Pole & line"
    origin_region: str | None    # e.g. "Norway", "Alaska, US"
    certifications: list[str]    # ["MSC", "ASC", "BAP"]

class ScoreBreakdown(BaseModel):
    biological: float            # 0–20
    practices: float             # 0–25
    management: float            # 0–30
    ecological: float            # 0–25

class Alternative(BaseModel):
    species: str
    score: int
    grade: str
    reason: str                  # "Similar mild white fish, pole & line caught"

class SustainabilityScore(BaseModel):
    score: int                   # 0–100
    grade: Literal["A", "B", "C", "D"]
    breakdown: ScoreBreakdown
    alternatives: list[Alternative]  # exactly 3
    explanation: str             # 2–3 sentence human-readable explanation
    product_info: ProductInfo    # what was extracted from the screenshot
```

---

## Key Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Gemini misidentifies species from screenshot | Medium | Fall back to page title/URL text extraction in content_script.js as supplement |
| NOAA FishWatch API endpoint broken (migrated) | Medium | Bake NOAA data into SQLite at build time (one-time fetch during database build) |
| Cloud Run cold start during demo | High | `--min-instances 1` keeps container warm |
| Gemini response > 5s for complex species | Low | Set `timeout=8s` in frontend; show spinner; `gemini-2.5-flash` is fast |
| Content Security Policy blocks overlay injection | Medium | Use shadow DOM for overlay to avoid CSS conflicts |
| Rate limits during demo | Low | Use Vertex AI (not AI Studio) — higher quotas with billing enabled |
