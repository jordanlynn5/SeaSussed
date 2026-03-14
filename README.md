# SeaSussed — Sustainable Seafood at the Point of Purchase

[![Python](https://img.shields.io/badge/Python-3.13-blue.svg)]()
[![Gemini](https://img.shields.io/badge/Gemini-2.5%20Flash-green.svg)]()
[![Google ADK](https://img.shields.io/badge/Google%20ADK-1.17-orange.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Chapa Badge](https://chapa.thecreativetoken.com/u/jordanlynn5/badge.svg)](https://chapa.thecreativetoken.com/u/jordanlynn5)

A Chrome extension powered by Gemini 2.5 Flash that gives you an instant sustainability score for any seafood product — right while you're shopping online.

---

## How It Works

SeaSussed lives in your Chrome side panel. Browse any grocery website, click **Analyze**, and in seconds you get:

1. **A sustainability score (0–100)** based on species biology, fishing practices, management, and ecological impact
2. **An animated score card** that builds up tag by tag, bar by bar — revealing the final grade only after everything is ready
3. **Plain-language explanations** for each scoring category with actionable tips
4. **Health advisory** — mercury levels and omega-3 content for the species
5. **Food miles** — how far the product traveled to reach you, with carbon context
6. **Better alternatives** from the same store, automatically scored and ranked
7. **Certification education** — tap any cert badge (MSC, ASC, BAP, etc.) to learn what it actually means

### Voice Mode

Tap the microphone for a live conversation with your sustainability expert:

- Explains *why* your product scored the way it did — fishery management, environmental impact, what the certifications mean
- Searches the store for better alternatives and **automatically navigates** to higher-scoring products
- **Analyzes the new page instantly** when it opens — no extra step
- Answers questions about seafood sustainability, fishing practices, and ocean ecology

### Works Everywhere

Amazon Fresh, Whole Foods, Instacart, Walmart, specialty seafood retailers — SeaSussed reads screenshots and page text, so it works on any site without needing retailer integrations.

---

## Try It

### Install the Extension

1. Clone this repo
2. Open `chrome://extensions` in Chrome
3. Enable **Developer mode** (top right)
4. Click **Load unpacked** and select the `extension/` directory
5. Click the SeaSussed icon in your toolbar to open the side panel
6. Navigate to any seafood product page and click **Analyze This Page**

The extension connects to our hosted Cloud Run backend — no local setup needed.

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
        │     └── Auto-analyzes new page on navigation
        └── navigate_to_product — opens a product page in user's browser

Cloud Run (FastAPI)
  ├── POST /analyze/stream (SSE)
  │     Phase 1 (instant): Gemini vision (multi-image + DOM text)
  │       → species, origin, method, certifications → score + breakdown
  │     Phase 1.5: Health advisory (mercury, omega-3) + food miles
  │     Phase 1.7: Web research enrichment (fills gaps vision missed)
  │     Phase 2 (~2-3s): alternatives + explanation → complete result
  │
  ├── POST /score — re-scores corrected product info (no vision step)
  │
  └── WS /voice
        VoiceSession ←→ Gemini Live (gemini-live-2.5-flash-native-audio)
          Mic → 16kHz PCM → Gemini → 24kHz PCM → Speaker
          Tools: screenshot capture, store search + scoring, page navigation
```

### Technology

- **Backend:** Python 3.13, FastAPI, Google ADK v1.17, Gemini 2.5 Flash (Vertex AI)
- **Extension:** Chrome Manifest V3, Vanilla JS
- **Data:** SQLite (FishBase + NOAA FishWatch), Wolfram Alpha (food miles), ip-api.com (geolocation)
- **Infrastructure:** Google Cloud Run (us-central1), Artifact Registry, Vertex AI

### Google Cloud Services

| Service | How It's Used |
|---|---|
| **Vertex AI** | Gemini 2.5 Flash for screenshot analysis (vision), sustainability scoring, and generating plain-language explanations |
| **Vertex AI — Gemini Live API** | Real-time voice conversations via `gemini-live-2.5-flash-native-audio` for hands-free sustainability guidance |
| **Google ADK** | Agent Development Kit (v1.17) orchestrates the screen analyzer agent with tool-use and structured output |
| **Cloud Run** | Hosts the FastAPI backend — handles all Gemini calls, scoring, and voice WebSocket sessions |
| **Artifact Registry** | Stores Docker images built from source during Cloud Run deployments |
| **Cloud Build** | Builds container images from `backend/Dockerfile` as part of `gcloud run deploy --source` |
| **Cloud Logging** | Backend request tracing, agent debugging, and error monitoring in production |

---

## Sustainability Scoring

Four categories, total 0–100:

| Category | Points |
|---|---|
| Biological & Population Status | 20 |
| Fishing / Aquaculture Practices | 25 |
| Management & Regulation | 30 |
| Environmental & Ecological | 25 |

**A (80-100):** Best Choice | **B (60-79):** Good Alternative | **C (40-59):** Use Caution | **D (0-39):** Avoid

---

## Development

<details>
<summary>Local backend setup</summary>

```bash
# Prerequisites: Python 3.13, uv, gcloud CLI, Vertex AI enabled

gcloud auth application-default login

export GOOGLE_CLOUD_PROJECT=seasussed-489008
export GOOGLE_CLOUD_REGION=us-central1
export GOOGLE_CLOUD_LOCATION=us-central1
export GOOGLE_GENAI_USE_VERTEXAI=1
export WOLFRAM_APP_ID=your-wolfram-app-id  # optional: food miles

cd backend
uv sync
uv run python -m scripts.build_database   # one-time: builds data/seafood.db
uv run uvicorn main:app --reload           # http://localhost:8000
```

Set `BACKEND_URL` in `extension/config.js` to `http://localhost:8000` for local dev.

</details>

<details>
<summary>Running tests</summary>

```bash
cd backend
uv run pytest                        # all tests
uv run mypy .                        # type check
uv run ruff check .                  # lint

# Run all three (same as pre-commit hook):
uv run mypy . 2>&1; uv run ruff check . 2>&1; uv run pytest 2>&1
```

</details>

<details>
<summary>Deploy to Cloud Run</summary>

```bash
gcloud run deploy seasussed-backend \
  --source backend/ \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --min-instances 1 \
  --set-env-vars GOOGLE_CLOUD_PROJECT=seasussed-489008,GOOGLE_CLOUD_REGION=us-central1,GOOGLE_CLOUD_LOCATION=us-central1,GOOGLE_GENAI_USE_VERTEXAI=1,WOLFRAM_APP_ID=$WOLFRAM_APP_ID
```

</details>

---

Built for the [Gemini Live Agent Challenge](https://geminiliveagentchallenge.devpost.com/) · UI Navigator category
