# SeaSussed — Sustainable Seafood at the Point of Purchase

[![CI](https://github.com/jordan294/seasussed/actions/workflows/ci.yml/badge.svg)](https://github.com/jordan294/seasussed/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.13-blue.svg)]()
[![Gemini](https://img.shields.io/badge/Gemini-2.5%20Flash-green.svg)]()
[![Google ADK](https://img.shields.io/badge/Google%20ADK-1.17-orange.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A Chrome extension that uses Gemini 2.5 Flash to analyze any grocery website and give you an instant sustainability score for seafood — right at the point of purchase.

![Chapa Badge](https://chapa.thecreativetoken.com/u/jordanlynn5/badge.svg)

---

## What It Does

SeaSussed installs as a Chrome side panel extension. When you browse seafood products on any grocery website, it:

1. Captures a screenshot, product gallery images, and page text from the product page
2. Sends everything to a Gemini multimodal agent that reads the species, origin, fishing method, and certifications — including back-of-package labels
3. Scores the product across four sustainability dimensions (0–100) with progressive streaming results
4. Shows you the grade (A-D) with an animated build sequence — score and grade are revealed only after all results are in
5. Displays expandable score factors with educational explanations, health advisories, and food miles estimates
6. Suggests alternatives from the same store, scored and ranked
7. Lets you correct any misread fields and re-score without a new screenshot

**Voice mode** takes it further — a live Gemini audio session that:
- Greets you with a detailed, educational explanation of your score (not just reading the card)
- Explains *why* a product scores the way it does — fishery management, environmental impact, certification meaning
- Searches the store for better alternatives and auto-navigates to higher-scoring products
- Automatically analyzes the new page when it opens — no extra step needed
- Announces its intent before every tool call so you're never left in silence
- Answers any sustainability or ocean ecology questions

It works on any site — Amazon Fresh, Whole Foods, Instacart, Walmart, specialty retailers — without relying on structured data from the retailer.

---

## Quickstart

### 1. Prerequisites

- Python 3.13
- [uv](https://docs.astral.sh/uv/) (`pip install uv`)
- [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) (`gcloud`)
- A Google Cloud project with Vertex AI enabled

### 2. Backend (local dev)

```bash
# Authenticate with Google Cloud
gcloud auth application-default login

# Set environment variables (add to ~/.zshrc to persist)
export GOOGLE_CLOUD_PROJECT=seasussed-489008
export GOOGLE_CLOUD_REGION=us-central1
export GOOGLE_CLOUD_LOCATION=us-central1
export GOOGLE_GENAI_USE_VERTEXAI=1
export WOLFRAM_APP_ID=your-wolfram-app-id  # optional: enables food miles via Wolfram Alpha

# Install dependencies and build the database
cd backend
uv sync
uv run python -m scripts.build_database   # one-time: builds data/seafood.db

# Start the server
uv run uvicorn main:app --reload          # http://localhost:8000
```

Verify it's running: open `http://localhost:8000/health` in your browser.

### 3. Chrome Extension

1. Open `chrome://extensions`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked** → select the `extension/` directory
4. Click the SeaSussed icon in your toolbar to open the side panel

For local dev, set `BACKEND_URL` in `extension/config.js` to `http://localhost:8000`. Update it to your Cloud Run URL for production.

### 4. Deploy to Google Cloud

```bash
gcloud run deploy seasussed-backend \
  --source backend/ \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --min-instances 1 \
  --set-env-vars GOOGLE_CLOUD_PROJECT=seasussed-489008,GOOGLE_CLOUD_REGION=us-central1,GOOGLE_CLOUD_LOCATION=us-central1,GOOGLE_GENAI_USE_VERTEXAI=1,WOLFRAM_APP_ID=$WOLFRAM_APP_ID
```

---

## Architecture

```
Chrome Extension (side panel)
  ├── Analyze → screenshot + gallery images + DOM text → POST /analyze/stream (SSE)
  │     └── Progressive phases: analyzing → scored → health → food_miles → enriched → complete
  ├── "Not right?" correction → POST /score (no screenshot)
  └── Voice → WebSocket /voice ←→ Gemini Live API
        ├── analyze_current_product — captures & scores current page
        ├── search_store — DOM-scrapes store search results, scores & auto-navigates
        │     └── Auto-analyzes new page on navigation (no user prompt needed)
        └── navigate_to_product — opens a product page in user's browser

Cloud Run (FastAPI)
  ├── POST /analyze/stream (SSE)
  │     Phase 1 (instant): Gemini vision (multi-image + DOM text)
  │       → species, origin, method, certifications → score + breakdown
  │     Phase 1.5: Health advisory (mercury, omega-3) + food miles (Wolfram Alpha)
  │     Phase 1.7: Web research enrichment (fills gaps Gemini vision missed)
  │     Phase 2 (~2-3s): alternatives + explanation → complete result
  │     Score + grade revealed only after Phase 2 completes
  │
  ├── POST /analyze — single-response version (backward compat)
  │
  ├── POST /score — re-scores corrected product info (no vision step)
  │
  └── WS /voice
        VoiceSession ←→ Gemini Live (gemini-live-2.5-flash-native-audio)
          Mic → 16kHz PCM → Gemini → 24kHz PCM → Speaker
          Tools: screenshot capture, store search + scoring, page navigation
```

### Data Sources

- **FishBase** — species biology (vulnerability, resilience, IUCN status, trophic level)
- **NOAA FishWatch** — US species overfishing status
- **Wolfram Alpha** — carbon footprint and food miles estimation
- **Gemini 2.5 Flash** — visual product recognition, web research for data gaps, natural language explanations
- **ip-api.com** — user geolocation for food miles calculation

---

## Sustainability Scoring

Four categories, total 0–100:

| Category | Points |
|---|---|
| Biological & Population Status | 20 |
| Fishing / Aquaculture Practices | 25 |
| Management & Regulation | 30 |
| Environmental & Ecological | 25 |

**A (80-100):** Best Choice 🟢 · **B (60-79):** Good Alternative 🟡 · **C (40-59):** Use Caution 🟠 · **D (0-39):** Avoid 🔴

### Score Card Features

- **Animated build sequence** — tags, explanation, and breakdown bars animate in progressively; score and grade are revealed last, only after all data is ready
- **Expandable score factors** — each category has a plain-language explanation and actionable tip
- **Health advisory** — mercury level and omega-3 content for the species
- **Food miles** — estimated distance from origin to your location, with carbon context
- **Certification explainers** — tap any cert badge for a detailed explanation of what it means
- **"Not right?" correction** — edit any field and re-score instantly

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/analyze/stream` | Multi-image analysis → SSE progressive results |
| `POST` | `/analyze` | Multi-image analysis → single JSON response |
| `POST` | `/score` | Re-score corrected product info (no vision) |
| `WS` | `/voice` | Gemini Live voice session with tool calling |

---

## Running Tests

```bash
cd backend
uv run pytest                        # all tests
uv run mypy .                        # type check
uv run ruff check .                  # lint

# Run all three sequentially (same as pre-commit hook):
uv run mypy . 2>&1; uv run ruff check . 2>&1; uv run pytest 2>&1
```

---

Built for the [Gemini Live Agent Challenge](https://geminiliveagentchallenge.devpost.com/) · UI Navigator category
