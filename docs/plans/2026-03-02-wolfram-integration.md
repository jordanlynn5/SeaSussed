# Wolfram Alpha Integration Plan

**Date:** 2026-03-02
**Feature:** Health Score (Option 1) + Species DB Fallback (Option 2)
**Subscription:** Wolfram One (Full Results API, App ID required)
**Phase files:** `docs/plans/2026-03-02-wolfram-integration-phases/`

---

## What We're Building

### Option 1 — Health Score

A second score card alongside the sustainability score, powered by Wolfram Alpha mercury and omega-3 data:

- **Mercury advisory**: FDA category (Best Choice / Good Choice / Lower Choice / Avoid)
- **Omega-3 content**: DHA + EPA mg per serving
- **Health grade**: A–D derived from FDA mercury tier
- Displayed as a compact card in the side panel, visible only when WA returns data
- Hidden for obscure species with no WA data (clean UI, no empty states)

### Option 2 — Species DB Fallback

When a species is not found in our FishBase/NOAA SQLite database:

1. Query Wolfram Alpha for conservation/population status text
2. Pass the WA text to Gemini to extract structured fields:
   `iucn_code`, `vulnerability`, `resilience`, `trophic_level`, `stock_exploitation`
3. These fields plug directly into the existing `score_biological()` and `score_ecological()` functions — same math, richer data
4. The explanation text also notes "Data sourced from Wolfram Alpha (not in our primary database)"

**Impact:** Species currently returning neutral defaults (biological=10.0, ecological=12.0) get real scores. Meaningful for less common species that appear on grocery sites.

---

## Architecture

```
wolfram.py (new)
  get_health_data(species)     → HealthInfo | None
  get_species_fallback(species) → dict[str, Any] | None
  _query_wolfram(query)         → list[WAPod]  (shared WA client)
  _parse_with_gemini(pods, schema, species) → dict  (shared Gemini parser)

Both functions:
  - @lru_cache(maxsize=256) — in-memory per process
  - Skip WA call if WOLFRAM_APP_ID not set (graceful degradation)
  - Return None on any WA error (never crash the scoring pipeline)

scoring.py (modified)
  compute_score():
    species_data = get_species(species)
    if species_data is None:
        species_data = get_species_fallback(species)  ← WA fallback

main.py (modified)
  _run_scoring_pipeline():
    health = get_health_data(product_info.species)  ← new
    return SustainabilityScore(..., health=health)

models.py (modified)
  + class HealthInfo
  + SustainabilityScore.health: HealthInfo | None

extension/sidepanel.html/.js (modified)
  + health card section (rendered only when result.health is not null)
```

---

## Health Score Methodology

### Mercury Advisory (FDA/EPA tiers)

| Tier | Mercury (avg ppm) | Health Grade | Examples |
|---|---|---|---|
| Best Choice | ≤ 0.10 | A 🟢 | Salmon, sardines, shrimp, tilapia |
| Good Choice | 0.10–0.32 | B 🟡 | Canned tuna, cod, lobster |
| Lower Choice | 0.32–1.0 | C 🟠 | Grouper, bluefish, mahi-mahi |
| Avoid | > 1.0 | D 🔴 | Shark, swordfish, king mackerel |

### Wolfram Alpha Queries

**Health data** — two queries per species (both cached):
```
Query 1: "{species} fish mercury content FDA"
  → Parse pod text for ppm value or FDA category string

Query 2: "{species} fish omega-3 DHA EPA per serving"
  → Parse pod text for mg DHA+EPA per 85g serving
```

**Species fallback** — one query per unknown species:
```
Query: "{species} fish conservation status population"
  → Extract full pod text
  → Gemini maps to: iucn_code, vulnerability (0-100), resilience, trophic_level, stock_exploitation
```

### WA Response Parsing Strategy

1. Fetch JSON from `https://api.wolframalpha.com/v2/query?input=...&appid=...&output=json&format=plaintext`
2. Check `queryresult.success == "true"` — return None if false
3. Iterate pods, collect `plaintext` from all subpods
4. Pass concatenated pod text to Gemini with a structured extraction prompt
5. Return parsed dict / None on failure

Using Gemini to parse (not regex) handles the variability in how WA phrases results across species — no brittle string matching.

---

## Data Model

```python
# models.py additions

class HealthInfo(BaseModel):
    mercury_ppm: float | None           # average ppm (may be None if only tier known)
    mercury_category: str | None        # "Best Choice" | "Good Choice" | "Lower Choice" | "Avoid"
    health_grade: Literal["A","B","C","D"]
    omega3_mg_per_serving: float | None # mg DHA+EPA per 85g serving (may be None)
    source_note: str                    # "Wolfram Alpha" — shown in UI for transparency

# SustainabilityScore addition
class SustainabilityScore(BaseModel):
    ...existing fields...
    health: HealthInfo | None = None    # None = WA had no data; UI hides card
```

---

## API Contract Change

`POST /analyze` and `POST /score` responses gain one optional field:

```json
{
  "score": 87,
  "grade": "A",
  ...existing fields...,
  "health": {
    "mercury_ppm": 0.048,
    "mercury_category": "Best Choice",
    "health_grade": "A",
    "omega3_mg_per_serving": 892,
    "source_note": "Wolfram Alpha"
  }
}
```

`health` is `null` when WA returns no data. This is backward-compatible with Phase 5 UI if it's already in progress — the UI simply checks `if (result.health)` before rendering the card.

---

## Environment Variables

```bash
export WOLFRAM_APP_ID=your-app-id-here   # from developer.wolframalpha.com → My Apps
```

If `WOLFRAM_APP_ID` is unset:
- `get_health_data()` returns `None` (health card hidden)
- `get_species_fallback()` returns `None` (scoring uses neutral defaults as before)
- No errors raised — full graceful degradation

Add to: `CLAUDE.md`, Cloud Run deploy command (`--set-env-vars`)

---

## Phase Summary

| Phase | Name | Files | Batch-eligible |
|---|---|---|---|
| WA-1 | Wolfram client module | `wolfram.py`, `tests/test_wolfram.py`, `pyproject.toml` | No |
| WA-2 | Backend integration | `models.py`, `scoring.py`, `main.py`, `CLAUDE.md` | No (blocked by WA-1) |
| WA-3 | Extension UI health card | `sidepanel.html`, `sidepanel.js` | No (blocked by WA-2 contract) |

All phases sequential. WA-1 must complete before WA-2 (imports wolfram.py). WA-3 can begin once WA-2's API contract is finalized (the `health` field shape).

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| WA has no data for the queried species | Return None → graceful degradation (health card hidden, scoring uses defaults) |
| WA mercury data is imprecise / wrong tier | Label clearly as "Source: Wolfram Alpha" — not authoritative medical advice |
| Gemini mis-parses WA pod text | Fallback to None if JSON parse fails; full try/except around all WA+Gemini calls |
| Added latency (WA + Gemini calls) | `lru_cache` on both functions — common species cached after first request |
| Wolfram One API quota | 2 queries per new species (health) + 1 for fallback; cache prevents repeat calls; 2000/month is sufficient for hackathon |
| `httpx` not in main deps | Move from dev-deps to main deps in pyproject.toml (Phase WA-1) |
