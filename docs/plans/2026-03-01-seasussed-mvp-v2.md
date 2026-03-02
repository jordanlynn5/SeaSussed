# SeaSussed MVP v2 — Implementation Plan

**Date:** 2026-03-01
**Supersedes:** `docs/plans/2026-03-01-seasussed-mvp.md`
**Deadline:** 2026-03-16 (15 days)
**Research doc:** `docs/research/2026-03-01-seasussed-research.md`
**Decision log:** This plan incorporates all decisions from the 2026-03-01 architecture interview.

---

## What We're Building

A Chrome extension + Cloud Run Python backend that:
1. Captures a screenshot of any grocery product page when the user clicks Analyze
2. Uses Gemini 2.5 Flash (vision via Google ADK) to identify the seafood species, origin, method, and certification logos
3. Simultaneously scrapes visible related product names from the DOM for alternative scoring
4. Scores the product 0–100 across five sustainability dimensions (pure Python math)
5. Generates a 2–3 sentence explanation via a direct Gemini call (explicitly stating what was/wasn't visible)
6. Displays grade (A–D), breakdown, and real alternatives available on the same site in a Chrome side panel

Category: **UI Navigator** — the agent reads the screen visually, not the DOM. Works on any grocery site.

---

## Architecture

```
[Chrome Extension — Manifest V3]
  background.js      service worker: captureVisibleTab + fetch to backend
  content_script.js  injected into product pages, scrapes related product names from DOM
  sidepanel.html/js  persistent side panel: all UI lives here
                     - Onboarding view (first run, explains screenshot data)
                     - Idle view (Analyze button)
                     - Loading view (spinner)
                     - Result view (grade, breakdown, alternatives, "Not right?")
                     - Correction view (editable fields → re-score)
                     - Non-seafood view (helpful tip + mockup)
                     - Error view (retry prompt)

       │  POST /analyze { screenshot: base64, url: string, related_products: string[] }
       │  POST /score   { product_info: ProductInfo }   ← correction re-score, no vision
       ▼

[Cloud Run — Python FastAPI]
  POST /analyze:
    1. ScreenAnalyzerAgent (google-adk LlmAgent, gemini-2.5-flash, vision)
         reads screenshot → extracts species, origin, method, certifications (all types)
    2. score_product() pure Python scoring
    3. score_alternatives() pure Python, scores each related_product by name
    4. generate_explanation() direct Gemini API call → 2-3 sentence human explanation
         explicitly states what was visible vs. inferred/unknown
    Returns: SustainabilityScore

  POST /score:
    1. score_product() pure Python scoring (uses provided ProductInfo directly)
    2. generate_explanation() direct Gemini API call
    Returns: SustainabilityScore (used by "Not right?" correction flow)

  SQLite (embedded):
    species           (FishBase: vulnerability, resilience, IUCN, stock_exploitation)
    noaa_species      (NOAA FishWatch: US overfishing status)
    fishing_methods   (hand-coded gear impact scores)
    alternatives      (seed data, used only when no DOM alternatives found)
    common_name_aliases

       │  JSON: { score, grade, breakdown, alternatives, explanation, product_info }
       ▼

[Side Panel UI]
  Persistent panel shows grade badge + color, score, breakdown by category,
  explanation (mentioning what Gemini saw), alternatives from the actual site page,
  "Not right?" correction form (all fields editable)
```

---

## Key Decisions vs. v1 Plan

| Topic | v1 Plan | v2 Decision |
|---|---|---|
| Analysis trigger | Auto on product URL patterns | Manual only — Analyze button in side panel |
| UI surface | Page overlay (Shadow DOM) | Chrome side panel (persistent) |
| content_script.js | Renders overlay | DOM scraping only (related product titles) |
| MSC data | MSC CSV → DB lookup | Removed — visual cert detection by Gemini only |
| Cert detection | MSC logo only | All types: MSC, ASC, BAP, GlobalG.A.P., FOS, ASMI |
| Scorer | ADK LlmAgent with tools | Pure Python `scoring.py` |
| ADK usage | SequentialAgent (2 agents) | ADK for ScreenAnalyzerAgent only |
| Explanation | SustainabilityScorerAgent output | Direct Gemini call, explicitly states visible/unknown |
| Re-score endpoint | Not planned | `POST /score` (correction flow, no vision) |
| Alternatives source | Curated species DB | DOM-scraped product names from current site |
| Alternatives for A | "Better Alternatives" | "Similar great choices" reframe |
| Non-seafood | Remove overlay | Helpful tip + mockup in side panel |
| Country score display | In breakdown | Hidden from UI (still used in scoring) |
| Gemini honesty | Not specified | Hard rule: never fabricate; explanation states what was missing |
| Parallel phases | Phases 1+2+3 batch-eligible | Sequential only (one phase at a time) |

---

## Scoring Model (Updated)

Total: 0–100 across four categories.

| Category | Wild-Caught | Farmed | Max | Data Sources |
|---|---|---|---|---|
| Biological & Population | ✓ | ✓ | 20 | FishBase: vulnerability (10), resilience (7), IUCN (3) |
| Fishing / Aquaculture Practices | Wild only | Farmed only | 25 | Gear impact score (wild) or cert + carnivory (farmed) |
| Management & Regulation | ✓ | ✓ | 30 | Visual cert detection (15) + NOAA status (10) + FAO exploitation (5) |
| Environmental & Ecological | ✓ | ✓ | 25 | FishBase trophic (10) + IUCN (10) + resilience bonus (5) |

Grade: **A** (80–100) 🟢 · **B** (60–79) 🟡 · **C** (40–59) 🟠 · **D** (0–39) 🔴

### Management Scoring Detail (30 pts)

```
Visual cert detection (max 15 pts):
  MSC (Marine Stewardship Council)        = 15 pts  [wild]
  ASC (Aquaculture Stewardship Council)   = 15 pts  [farmed]
  BAP (Best Aquaculture Practices)        = 10 pts  [farmed]
  GlobalG.A.P.                            = 8 pts   [farmed]
  Friend of the Sea (FOS)                 = 8 pts   [wild/farmed]
  ASMI (Alaska Seafood Marketing Inst.)   = 7 pts   [wild, Alaska only]
  "Responsibly Farmed" / "Sustainably Sourced" label = 3 pts  [unverified]
  No cert visible                         = 0 pts

NOAA overfishing status (max 10 pts):
  "Not subject to overfishing"            = 10 pts
  Unknown / not a US species              =  4 pts
  "Overfishing occurring"                 =  0 pts

FAO stock exploitation from FishBase (max 5 pts):
  Not overexploited                       =  5 pts
  Fully exploited                         =  2 pts
  Overexploited                           =  0 pts
  Unknown / not in DB                     =  3 pts

Country management: used in explanation text only — not a scored category in the UI.
```

---

## Gemini Honesty Rule

**Hard rule across all Gemini calls:** never fabricate data. Applied in two places:

1. **ScreenAnalyzerAgent system prompt:** "Extract only what is VISUALLY PRESENT on the page. Return null for any field that is not visible or cannot be determined with confidence. Do not infer, assume, or hallucinate."

2. **Explanation generation prompt:** "Your explanation must explicitly state what was and was not visible on the page. Examples: 'The fishing method wasn't shown on this page, so we assumed Unknown.' Do not claim certainty for values Gemini returned as null."

---

## Alternatives Logic

### Primary: DOM Scraping
content_script.js scrapes related product titles from the current page (carousels, "you might also like", related items) and sends them in `related_products: string[]` in the `/analyze` request.

Backend process:
1. For each product name in `related_products`, call `identify_species_from_name()` — a lightweight Gemini prompt that maps grocery product titles to species names (batch prompt, one API call for all)
2. Score each species using pure Python `score_product()`
3. For grade A/B products: return top 3 with label "Similar great choices"
4. For grade C/D products: return top 3 **better** than the current product's score

### Fallback: Seed Data
If `related_products` is empty or none score better, fall back to the curated `alternatives` table in SQLite (species-level suggestions with `reason` text). Label them: "Common alternatives — check if available on this site."

### Category Page Escalation
If user dismisses the primary alternatives panel: show prompt "Want more options? Navigate to the seafood section and click Analyze again." The side panel remains open and re-analyzes the category page automatically when the user arrives there.

---

## Phase Summary

| Phase | Name | Status |
|---|---|---|
| 1 | GCP Setup & Backend Scaffold | ✅ complete |
| 2 | Chrome Extension Scaffold | ✅ complete |
| 3 | Sustainability Database | pending |
| 4 | Gemini Agent Pipeline | pending |
| 5 | Extension UI Integration | pending |
| 6 | Testing & Optimization | pending |
| 7 | Deployment & Submission | pending |

**All phases are sequential.** No parallel execution.

Phase dependencies:
- 4 blocked by 1 (backend) and 3 (database)
- 5 blocked by 2 (extension) and 4 (API contract)
- 6 blocked by 5
- 7 blocked by 6

---

## Data Model Reference

```python
# backend/models.py

class AnalyzeRequest(BaseModel):
    screenshot: str           # base64-encoded PNG
    url: str                  # current page URL
    page_title: str = ""      # optional: <title> tag text
    related_products: list[str] = []  # product titles from DOM scraping

class ScoreRequest(BaseModel):
    product_info: ProductInfo  # corrected by user; no vision step

class ProductInfo(BaseModel):
    is_seafood: bool
    species: str | None
    wild_or_farmed: Literal["wild", "farmed", "unknown"]
    fishing_method: str | None
    origin_region: str | None
    certifications: list[str]  # e.g. ["MSC", "ASC", "ASMI"]

class ScoreBreakdown(BaseModel):
    biological: float     # 0–20
    practices: float      # 0–25
    management: float     # 0–30
    ecological: float     # 0–25

class Alternative(BaseModel):
    species: str
    score: int
    grade: str
    reason: str
    from_page: bool       # True if scraped from page DOM; False if from seed DB

class SustainabilityScore(BaseModel):
    score: int
    grade: Literal["A", "B", "C", "D"]
    breakdown: ScoreBreakdown
    alternatives: list[Alternative]   # 1–3 items
    alternatives_label: str           # "Similar great choices" (A) or "Better alternatives" (B/C/D)
    explanation: str                  # 2–3 sentences, states what was visible
    product_info: ProductInfo         # what was extracted from screenshot
```

---

## API Contract

```
GET  /health
     → {"status": "ok", "service": "seasussed-backend", "version": "0.1.0"}

POST /analyze
     Request:  AnalyzeRequest
     Response: SustainabilityScore
     Notes: full pipeline — vision + scoring + explanation + alternatives
            returns is_seafood=false in product_info if not a seafood page

POST /score
     Request:  ScoreRequest
     Response: SustainabilityScore
     Notes: no vision step; used by "Not right?" correction flow
            generates fresh explanation from corrected ProductInfo
```

---

## Extension Structure

```
extension/
├── manifest.json         # MV3, sidePanel permission, no default_popup
├── config.js             # BACKEND_URL constant
├── background.js         # service worker: screenshot + API calls + DOM injection
├── content_script.js     # injected into pages: scrapes related product titles
├── sidepanel.html        # persistent side panel (all UI views)
├── sidepanel.js          # side panel controller
└── icons/
    ├── icon16.png
    ├── icon48.png
    └── icon128.png
```

---

## Key Risks & Mitigations (Updated)

| Risk | Likelihood | Mitigation |
|---|---|---|
| Grocery sites have no related product carousels | Medium | Fallback to seed alternatives DB with honest label |
| content_script DOM scraping blocked by site CSP | Low | Use innerText/textContent only — not DOM manipulation; reading is safe |
| Gemini misidentifies species | Medium | "Not right?" correction flow always available; extraction visible in result |
| Side panel not supported (Chrome < 114) | Low | Chrome 114 is June 2023; show graceful error for unsupported versions |
| Gemini response > 5s | Low | gemini-2.5-flash is fast; 8s frontend timeout with retry prompt |
| Cloud Run cold start during demo | High | --min-instances 1 during demo recording |
| Rate limits | Low | Vertex AI with billing enabled; manual-only trigger limits call volume |
| Product page uses SPA routing | Low | content_script sends DOM data at time of Analyze click, not page load |
