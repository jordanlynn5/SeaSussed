# Phase 7: Deployment & Submission

**Days:** 10–14 (target submit by March 15 for buffer) | **Depends on:** Phase 6

---

## Steps

### 1. Production Cloud Run Deployment

```bash
# Set project
gcloud config set project seasussed-hackathon

# Bake seafood.db into container (do NOT gitignore it for the Docker build)
# Temporarily copy for build:
cp /Users/jordan/sussed/backend/data/seafood.db /Users/jordan/sussed/backend/data/seafood.db.bak

# Deploy with production settings
gcloud run deploy seasussed-backend \
  --source /Users/jordan/sussed/backend \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --min-instances 1 \
  --max-instances 10 \
  --port 8080 \
  --service-account seasussed-sa@seasussed-hackathon.iam.gserviceaccount.com \
  --set-env-vars GOOGLE_CLOUD_PROJECT=seasussed-hackathon,GOOGLE_CLOUD_REGION=us-central1

# Get the URL
SERVICE_URL=$(gcloud run services describe seasussed-backend \
  --region us-central1 --format 'value(status.url)')
echo "Service URL: $SERVICE_URL"

# Update extension config
# Edit extension/config.js: BACKEND_URL = "$SERVICE_URL"
```

### 2. Service Account Setup (Vertex AI access)

```bash
# Create service account for Cloud Run
gcloud iam service-accounts create seasussed-sa \
  --display-name="SeaSussed Cloud Run SA"

# Grant Vertex AI access
gcloud projects add-iam-policy-binding seasussed-hackathon \
  --member="serviceAccount:seasussed-sa@seasussed-hackathon.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# Cloud Run uses this SA automatically when deployed with --service-account
```

### 3. Production Smoke Test

```bash
SERVICE_URL=$(gcloud run services describe seasussed-backend \
  --region us-central1 --format 'value(status.url)')

# Health check
curl "$SERVICE_URL/health"
# Expected: {"status":"ok","service":"seasussed-backend","version":"0.1.0"}

# Screenshot test
python3 - << 'EOF'
import base64, json, urllib.request
from pathlib import Path

screenshot = base64.b64encode(
  Path("backend/tests/fixtures/whole_foods_salmon.png").read_bytes()
).decode()

payload = json.dumps({
  "screenshot": screenshot,
  "url": "https://www.wholefoodsmarket.com/product/salmon"
}).encode()

req = urllib.request.Request(
  f"{SERVICE_URL}/analyze",
  data=payload,
  headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req) as resp:
  data = json.loads(resp.read())
  print(f"Grade: {data['grade']} ({data['score']}/100)")
  print(f"Species: {data['product_info']['species']}")
  print(f"Explanation: {data['explanation'][:100]}...")
EOF
```

### 4. GitHub Repository Setup

```bash
# Initialize git (if not already)
cd /Users/jordan/sussed
git init
git add .
git commit -m "feat: initial SeaSussed MVP implementation"

# Create public GitHub repo
gh repo create seasussed \
  --public \
  --description "Real-time seafood sustainability scores in your browser — Gemini Live Agent Challenge" \
  --homepage "https://geminiliveagentchallenge.devpost.com"

git remote add origin https://github.com/jordan294/seasussed.git
git push -u origin main
```

### 5. Architecture Diagram

Create `docs/architecture-diagram.png` showing:

```
┌─────────────────────────────────────────────────────────────────┐
│                    BROWSER (Chrome Extension)                    │
│                                                                  │
│  ┌──────────────────┐    ┌───────────────────────────────────┐  │
│  │   Grocery Site   │    │     SeaSussed Extension (MV3)     │  │
│  │  (Any website)   │    │                                   │  │
│  │                  │    │  content_script.js                │  │
│  │  Product page    │───▶│  ├─ Renders overlay (Shadow DOM)  │  │
│  │  (screenshot)    │    │  │  └─ Grade badge + panel        │  │
│  │                  │    │  │                                │  │
│  └──────────────────┘    │  background.js (service worker)  │  │
│                          │  └─ captureVisibleTab()           │  │
│                          │  └─ POST /analyze → Cloud Run     │  │
│                          └────────────────┬──────────────────┘  │
└───────────────────────────────────────────┼─────────────────────┘
                                            │ HTTPS POST
                                            │ { screenshot: base64, url }
                                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                  GOOGLE CLOUD PLATFORM                          │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              Cloud Run: seasussed-backend                │   │
│  │                                                          │   │
│  │  FastAPI /analyze                                        │   │
│  │        │                                                 │   │
│  │        ▼                                                 │   │
│  │  Google ADK SequentialAgent                              │   │
│  │        │                                                 │   │
│  │        ├─▶ ScreenAnalyzerAgent                          │   │
│  │        │     model: gemini-2.5-flash (vision)           │   │
│  │        │     → extracts: species, method, origin, certs │   │
│  │        │                                                 │   │
│  │        └─▶ SustainabilityScorerAgent                    │   │
│  │              model: gemini-2.5-flash                     │   │
│  │              tools: query_species_db                     │   │
│  │                     query_msc_db                         │   │
│  │                     query_noaa_db                        │   │
│  │                     find_alternatives                    │   │
│  │              → returns: score (0-100), grade, breakdown  │   │
│  │                                                          │   │
│  │  SQLite (embedded):                                      │   │
│  │  ├─ species (FishBase: vulnerability, resilience, IUCN)  │   │
│  │  ├─ msc_fisheries (590+ MSC-certified fisheries)         │   │
│  │  ├─ noaa_species (~100 US species status)               │   │
│  │  ├─ fishing_methods (gear impact scores)                 │   │
│  │  └─ alternatives (curated better-choice mappings)        │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           │                                      │
│                           ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │            Vertex AI — gemini-2.5-flash                  │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

Tool: Use [draw.io](https://draw.io) or [Excalidraw](https://excalidraw.com) to recreate this as a polished PNG.

### 6. Demo Video Script (4 minutes max)

**Structure:**

| Time | Section | Content |
|---|---|---|
| 0:00–0:30 | Problem | "Every day millions of people buy fish with no idea if it's sustainable. Labels like 'sustainably sourced' are unverified marketing." |
| 0:30–1:00 | Solution | "SeaSussed is a Chrome extension that gives you an instant sustainability score for any seafood, on any grocery site." |
| 1:00–2:00 | Demo 1 | Whole Foods salmon: show extension analyzing page, badge appearing, expand panel, show breakdown and alternatives |
| 2:00–2:45 | Demo 2 | Amazon Fresh (low-rated product): show D grade appearing, explain why, show alternatives |
| 2:45–3:15 | Architecture | Brief architecture overview (screen share of diagram), mention Gemini 2.5 Flash + ADK + Cloud Run |
| 3:15–3:45 | Real-time | Demonstrate auto-analysis on navigation (SPA page change) |
| 3:45–4:00 | Closing | "SeaSussed — suss out your seafood before you buy." |

**Recording tips:**
- Use OBS or Loom for screen recording
- Record in 1080p
- Slow mouse movements on product page so extension analysis is visible
- Keep Cloud Run `--min-instances 1` during recording

### 7. README Spin-Up Instructions (Final)

Verify the README includes working commands for each component:

```bash
# Test complete spin-up from scratch
git clone https://github.com/jordan294/seasussed.git
cd seasussed/backend
uv sync
# (Download MSC CSV from fisheries.msc.org → Export → save as backend/data/msc_fisheries.csv)
uv run python -m scripts.build_database
uv run uvicorn main:app --reload
# In another terminal: verify health
curl http://localhost:8000/health
# Load extension/ in Chrome
```

### 8. Devpost Submission Checklist

**Before submitting:**
- [ ] GitHub repo is public
- [ ] README has complete spin-up instructions
- [ ] Cloud Run URL is live (`curl <url>/health` returns 200)
- [ ] Architecture diagram is a PNG in the repo and/or uploaded to Devpost
- [ ] Demo video is ≤ 4 minutes
- [ ] Demo video shows real-time multimodal features (screenshot → score)
- [ ] Demo video uploaded to YouTube (unlisted is fine) or directly to Devpost

**Devpost form fields:**
- **Project name:** SeaSussed
- **Tagline:** Real-time seafood sustainability scores, on any grocery site
- **Description:** Cover all 4 judging dimensions:
  - *Innovation (40%):* Universal visual analysis — works on any grocery site without DOM access; supplements the least-informative retailers the most
  - *Technical (30%):* Google ADK SequentialAgent, Gemini 2.5 Flash multimodal, Cloud Run, Vertex AI, SQLite sustainability database from FishBase + MSC + NOAA
  - *Demo (30%):* Clear demonstration of real-time analysis, score breakdown, alternatives
- **Video:** Link
- **Code repo:** https://github.com/jordan294/seasussed
- **Google Cloud proof:** Cloud Run service URL or screen recording of deployed service

**Category:** UI Navigator
**Required tech:** ✅ Gemini model · ✅ Google ADK · ✅ Google Cloud (Cloud Run + Vertex AI)

Submit by: **March 15, 2026** (one day before deadline for buffer)

## Verification

```bash
# Final pre-submission checks
SERVICE_URL=$(gcloud run services describe seasussed-backend \
  --region us-central1 --format 'value(status.url)')

curl "$SERVICE_URL/health"
# Expected 200 ✅

gh repo view jordan294/seasussed --json visibility --jq '.visibility'
# Expected: "PUBLIC" ✅
```
