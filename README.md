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

1. Captures a screenshot of the product page
2. Sends it to a Gemini multimodal agent that visually reads the species, origin, and fishing method
3. Scores the product across four sustainability dimensions (0–100)
4. Shows you the grade (A–D) with a breakdown and 3 better alternatives
5. Lets you correct any misread fields and re-score without a new screenshot

It also supports **voice mode** — talk to a live Gemini session that sees your screen and answers sustainability questions in real time.

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

For local dev, `extension/config.js` already points to `http://localhost:8000`. Update it to your Cloud Run URL for production.

### 4. Deploy to Google Cloud

```bash
gcloud run deploy seasussed-backend \
  --source backend/ \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --min-instances 1 \
  --set-env-vars GOOGLE_CLOUD_PROJECT=seasussed-489008,GOOGLE_CLOUD_REGION=us-central1
```

---

## Architecture

```
Chrome Extension (side panel)
  ├── Analyze button → captures screenshot → POST /analyze
  ├── "Not right?" correction → POST /score (no screenshot)
  └── Voice button → WebSocket /voice ←→ Gemini Live API

Cloud Run (FastAPI)
  ├── POST /analyze
  │     ScreenAnalyzerAgent (Gemini vision)
  │       → species, origin, method, certifications
  │     scoring.py (pure Python)
  │       → 0–100 score, grade, breakdown, alternatives
  │     explanation.py (Gemini)
  │       → 2–3 sentence plain-English summary
  │
  ├── POST /score
  │     Re-scores corrected product info (no vision step)
  │
  └── WS /voice
        VoiceSession ←→ Gemini Live API (bidirectional audio)
          Microphone → 16kHz PCM → Gemini
          Gemini → 24kHz PCM → Speaker
          Gemini requests screenshot on demand → /analyze pipeline
```

### Data Sources

- **FishBase** — species biology (vulnerability, resilience, IUCN status)
- **NOAA FishWatch** — US species overfishing status
- **Gemini 2.5 Flash** — visual product recognition + reasoning for data gaps

---

## Sustainability Scoring

Four categories, total 0–100:

| Category | Points |
|---|---|
| Biological & Population Status | 20 |
| Fishing / Aquaculture Practices | 25 |
| Management & Regulation | 30 |
| Environmental & Ecological | 25 |

**A (80–100):** Best Choice 🟢 · **B (60–79):** Good Alternative 🟡 · **C (40–59):** Use Caution 🟠 · **D (0–39):** Avoid 🔴

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/analyze` | Screenshot → sustainability score |
| `POST` | `/score` | Re-score corrected product info |
| `WS` | `/voice` | Gemini Live voice session |

---

## Running Tests

```bash
cd backend
uv run pytest                        # all tests
uv run mypy .                        # type check
uv run ruff check .                  # lint
```

---

Built for the [Gemini Live Agent Challenge](https://geminiliveagentchallenge.devpost.com/) · UI Navigator category
