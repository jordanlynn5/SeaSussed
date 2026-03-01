# SeaSussed — Pre-Planning Research

**Date:** 2026-03-01
**Scope:** Grocery site data availability, sustainability databases, Google ADK/Gemini capabilities

---

## Grocery Site Seafood Data Availability

### Key Finding

Mass-market grocery sites (Amazon Fresh, Walmart, Kroger, Instacart) display minimal sustainability data on product pages — at most "wild-caught" + country of origin + occasional MSC badge. Specialty DTC retailers (Vital Choice, Sea to Table, Patagonia Provisions) show gear type, named fisheries, and Seafood Watch ratings — but have tiny market share.

**This validates the UI Navigator approach:** SeaSussed adds the most value precisely where retailers show the least. The agent visually reads whatever IS shown, then supplements with its own database and reasoning.

### Tiered Rankings

**Tier 1 — Most Data (Specialty DTC):**
- **Vital Choice:** scientific names, gear type (gillnet/purse seine/troll), named fishery (Copper River), MSC badge, Seafood Watch rating in text
- **Sea to Table:** fishing method (shallow nets, hook & line), named region (Bristol Bay), Seafood Watch text
- **Patagonia Provisions:** most gear-specific (reef net, set net by name), named locations, B Corp

**Tier 2 — Moderate:**
- **Whole Foods:** MSC badge, "Responsibly Farmed" badge, wild/farmed label — best mass-market option
- **Thrive Market:** passes through brand labeling, varies by product
- **FreshDirect:** MSC/ASC policy-level commitment, inconsistent per-product display

**Tier 3 — Minimal (Mass Market):**
- **Kroger:** "sustainably sourced" label, occasional MSC badge, country of origin
- **Walmart:** MSC badge on some, general "Alaska" origin
- **Amazon Fresh:** "sustainably sourced" marketing term (unverified), general origin
- **Instacart:** pure aggregator — shows whatever the underlying retailer supplies

### Demo Site Selection

Target these three for demo optimization:
1. **Whole Foods** — best mass-market data, MSC badges visible to vision model
2. **Amazon Fresh** — widest reach, demonstrates supplementation of minimal labeling
3. **Instacart** — shows cross-retailer applicability

The agent works universally (visual-first), but these three are optimized for the demo video.

---

## Sustainability Data Sources

### Usable (Free, Open):

**FishBase** (fishbase.ropensci.org)
- Free, no auth, REST API + Parquet files via DuckDB
- Key fields: `vulnerability` (0-100), `resilience` (Very Low/Low/Medium/High), `iucn_code`, `max_age`, `trophic_level`
- 30,000+ species — complete commercial coverage
- Python: use DuckDB/Parquet directly (`pip install duckdb`)

**MSC Fisheries Database** (fisheries.msc.org)
- Free browse + CSV export
- 590+ fisheries, filterable by species/gear/FAO area
- Fields: species, gear type, FAO area, certified (bool), certification status
- Use: pre-download CSV and bake into SQLite

**NOAA FishWatch** (fishwatch.gov/api/species)
- ~100 US commercial species, public JSON (verify endpoint — may have migrated to fisheries.noaa.gov)
- Fields: `Fishing Rate` (overfishing status), `Population`, `Habitat Impacts`, `Bycatch`
- US-centric, public domain

**GBIF / FishBase common names** (api.gbif.org)
- Taxonomy and common name resolution
- Essential for mapping "salmon" → correct species

### Gated (Cannot Use):

**Seafood Watch API** — Requires partner agreement. Cannot obtain in 15 days.
- **Mitigation:** Adopt their methodology (5-factor scoring, Green/Yellow/Red equivalent) and cite their framework in the submission. The scoring categories in this plan are directly derived from Seafood Watch's published methodology.

**Good Fish Guide (MCS)** — No public API or data export. UK-focused.

### Advisory Only:

**Global Fishing Watch** — Free non-commercial. Vessel-level fishing effort data. Not needed for MVP.
**USDA FoodData Central** — Nutritional data only. Not relevant to sustainability score.

---

## Technical Architecture Decisions

### ADK vs GenAI SDK

**Decision: Python ADK v1.17 (GA) + `google-genai` SDK**

- ADK Python is GA and stable at v1.17. Best choice for multi-agent orchestration.
- ADK TypeScript is **unstable** (broken ESM dependency) — skip entirely.
- ADK runs as a backend-only framework; Chrome extension calls Cloud Run via `fetch`.
- Use ADK's `SequentialAgent` to chain ScreenAnalyzerAgent → SustainabilityScorerAgent.
- The `google-genai` SDK is used internally by ADK for model calls — no need to call it separately.

### Model

**Decision: `gemini-2.5-flash` for both agents**

- Best vision + reasoning at fastest speed and lowest cost in the 2.5 family
- 1M token context window — handles 3,000–4,000 tokens per screenshot easily
- `gemini-2.5-pro` considered for sustainability reasoning — skip for hackathon (cost + latency)
- Do NOT use: `gemini-1.5-pro` (deprecated), `gemini-2.0-flash` (superseded)

### Security

**Decision: Proxy backend pattern (no API keys in extension)**
- Extension sends screenshot to Cloud Run backend
- Cloud Run holds `GOOGLE_APPLICATION_CREDENTIALS` / Vertex AI ADC — no user-visible key
- This is required: Chrome extension source is readable by anyone who installs it

### Deployment

**Decision: Cloud Run with `--min-instances 1` for demo**
- Cloud Run free tier: 2M requests/month — sufficient for hackathon
- Python buildpack handles FastAPI + uvicorn without Dockerfile for simple deploys
- `--min-instances 1` during demo prevents cold start (otherwise 2–4s penalty)
- Use **Vertex AI** (not AI Studio) for higher rate limits during live demo

### Backend Language

**Decision: Python 3.13 with `uv`**
- ADK is Python-native — no brainer
- `uv` for dependency management: faster than pip, excellent lockfile support
- FastAPI + uvicorn for the HTTP layer

---

## Scoring Model Design

### Five Categories (Matching User Requirements)

All five from the brief, mapped to available data:

1. **Biological & Population Status** (20 pts)
   - FishBase `vulnerability` (0–100, inverted) → 10 pts
   - FishBase `resilience` (Very Low=0, Low=3, Medium=6, High=10) → 10 pts
   - Bonus: `iucn_code` LC/NT = no penalty, VU/EN/CR = -5/-10/-20

2. **Fishing & Harvesting Practices** (25 pts, wild-caught only)
   - Gear type impact table (hand-coded from literature):
     - Pole & line / hook & line / troll: 25 (max)
     - Purse seine (dolphin-safe): 20
     - Gillnet / longline: 14
     - Trawl (midwater): 10
     - Bottom trawl / dredge: 2
   - Bycatch risk modifier: -5 if High bycatch known for that gear+species combo

3. **Aquaculture & Farming Practices** (25 pts, farmed only)
   - ASC certified: 18
   - BAP 3-4 star: 15
   - BAP 1-2 star: 10
   - No cert but carnivory ratio low (herbivorous/omnivorous): 8
   - No cert, high carnivory (salmon, bluefin): 4

4. **Management & Regulation** (30 pts)
   - MSC certified (from MSC DB): +15
   - NOAA "Not subject to overfishing": +10 (US species)
   - Country management score (proxy table, 0–5 pts):
     - Norway, Iceland, US, Canada, Australia = 5
     - EU, NZ, Japan, Chile = 4
     - Peru, Ecuador, India = 2
     - China, Indonesia, Vietnam = 1

5. **Environmental & Ecological Factors** (25 pts)
   - FishBase `trophic_level`: lower = keystone prey = more sensitive (min(trophic/4.5, 1.0) * 10 pts)
   - Climate vulnerability (IUCN marine + latitude of range): 0–10 pts
   - Ecosystem balance proxy (not overfished + keystone species flag): 0–5 pts

### Grade Scale

- A (80–100): 🟢 Best Choice
- B (60–79): 🟡 Good Alternative
- C (40–59): 🟠 Use Caution
- D (0–39): 🔴 Avoid

### Alternatives Logic

For any B/C/D scored product, suggest 3 alternatives:
- Score > current score + 15 (meaningfully better)
- Nutritionally similar (same flavor profile: mild/rich, texture: flaky/firm, comparable omega-3 tier)
- Commonly available in US grocery stores
- Pre-built `alternatives` table in SQLite mapping species → suggested alternatives

---

## Hackathon Requirements Checklist

| Requirement | Approach |
|---|---|
| Gemini model | `gemini-2.5-flash` via Vertex AI |
| Google GenAI SDK or ADK | Google ADK v1.17 (Python, GA) |
| Google Cloud service | Cloud Run (+ Vertex AI, Artifact Registry) |
| Real-time multimodal | Screenshot → Gemini vision → instant score |
| UI Navigator category | Visual screen reading — no DOM API dependency |
| Handles user interruptions | Extension popup can be dismissed; async backend doesn't block |
| Public repo + spin-up instructions | README with `gcloud run deploy` one-liner |
| Architecture diagram | To be created in Phase 7 |
| Demo video ≤ 4 min | To be recorded in Phase 7 |
| Google Cloud deployment proof | Cloud Run service URL in submission |
| Deadline | March 16, 2026 5:00 PM PDT |
