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

SeaSussed installs as a Chrome extension. When you browse seafood products on any grocery website, it:

1. Captures a screenshot of the product page
2. Sends it to a Gemini multimodal agent that visually reads the species, origin, and fishing method
3. Scores the product across five sustainability dimensions (0–100)
4. Shows you the grade (A–D) with a breakdown and 3 better alternatives

It works on any site — Amazon Fresh, Whole Foods, Instacart, Walmart, specialty retailers — without relying on structured data from the retailer.

## Quickstart

### Backend (Cloud Run)

```bash
cd backend
uv sync
uv run python -m scripts.build_database   # one-time: builds seafood.db
uv run uvicorn main:app --reload          # local dev at http://localhost:8000
```

### Chrome Extension

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked** → select the `extension/` directory
4. Set `BACKEND_URL` in `extension/config.js` to your Cloud Run URL

### Deploy to Google Cloud

```bash
gcloud projects create seasussed-hackathon --name="SeaSussed"
gcloud config set project seasussed-hackathon
gcloud run deploy seasussed-backend \
  --source backend/ \
  --region us-central1 \
  --allow-unauthenticated \
  --min-instances 1
```

## Architecture

See `docs/plans/2026-03-01-seasussed-mvp.md` for the full implementation plan and architecture diagram.

## Sustainability Scoring

Five categories, total 0–100:

| Category | Points |
|---|---|
| Biological & Population Status | 20 |
| Fishing / Aquaculture Practices | 25 |
| Management & Regulation | 30 |
| Environmental & Ecological | 25 |

**A (80–100):** Best Choice 🟢 · **B (60–79):** Good Alternative 🟡 · **C (40–59):** Use Caution 🟠 · **D (0–39):** Avoid 🔴

## Data Sources

- **FishBase** — species biology (vulnerability, resilience, IUCN status)
- **MSC Fisheries Database** — wild-capture certification status
- **NOAA FishWatch** — US species overfishing status
- **Gemini 2.5 Flash** — visual product recognition + reasoning for gaps

Built for the [Gemini Live Agent Challenge](https://geminiliveagentchallenge.devpost.com/) · UI Navigator category
