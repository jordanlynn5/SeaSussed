# Phase 7: Deployment & Submission

**Days:** 14–15 | **Depends on:** Phase 6 | **Blocks:** nothing

**Target submit by: March 15, 2026** (one day buffer before the March 16 deadline)

---

## Deliverable

Submitted Devpost entry with all required artifacts: public GitHub repo, live Cloud Run service, architecture diagram, and demo video ≤ 4 minutes.

---

## Step 1: Production Cloud Run Deployment

Before deploying: `seafood.db` must be built (Phase 3) and present at `backend/data/seafood.db`.
The Dockerfile copies it into the image — it is **not** gitignored for Docker builds.

```bash
gcloud config set project seasussed-hackathon

# Build and deploy
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

# Get the service URL
SERVICE_URL=$(gcloud run services describe seasussed-backend \
  --region us-central1 --format 'value(status.url)')
echo "Service URL: $SERVICE_URL"
```

Note: `--min-instances 1` is critical — keeps the container warm during the demo recording. Switch to `--min-instances 0` after the submission to avoid ongoing costs.

---

## Step 2: Update Extension Config

```javascript
// extension/config.js — update BACKEND_URL to production
const BACKEND_URL = "https://seasussed-backend-<hash>-uc.a.run.app";
```

---

## Step 3: Production Smoke Test

```bash
SERVICE_URL=$(gcloud run services describe seasussed-backend \
  --region us-central1 --format 'value(status.url)')

# Health check
curl "$SERVICE_URL/health"
# Expected: {"status":"ok","service":"seasussed-backend","version":"0.1.0"}

# Full analyze test with a fixture
python3 - << 'EOF'
import base64, json, urllib.request, os
from pathlib import Path

SERVICE_URL = os.environ.get("SERVICE_URL", "")  # set this first
screenshot = base64.b64encode(
  Path("backend/tests/fixtures/whole_foods_sockeye.png").read_bytes()
).decode()

payload = json.dumps({
  "screenshot": screenshot,
  "url": "https://www.wholefoodsmarket.com/product/sockeye-salmon",
  "related_products": [],
}).encode()

req = urllib.request.Request(
  f"{SERVICE_URL}/analyze",
  data=payload,
  headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=15) as resp:
  data = json.loads(resp.read())
  print(f"Grade: {data['grade']} ({data['score']}/100)")
  print(f"Species: {data['product_info']['species']}")
  print(f"Explanation: {data['explanation'][:100]}...")
  print("PASS" if data['grade'] in ('A', 'B') else f"UNEXPECTED GRADE: {data['grade']}")
EOF
```

---

## Step 4: GitHub Repository

```bash
cd /Users/jordan/sussed
git init
git add .
git commit -m "feat: initial SeaSussed MVP implementation"

gh repo create seasussed \
  --public \
  --description "Real-time seafood sustainability scores in your browser — Gemini Live Agent Challenge" \
  --homepage "https://geminiliveagentchallenge.devpost.com"

git remote add origin https://github.com/jordan294/seasussed.git
git push -u origin main
```

Verify README spin-up instructions work end-to-end:
```bash
git clone https://github.com/jordan294/seasussed.git
cd seasussed/backend
uv sync
uv run python -m scripts.build_database
uv run uvicorn main:app --reload
# In another terminal:
curl http://localhost:8000/health
# Load extension/ in Chrome, set BACKEND_URL in config.js to http://localhost:8000
```

---

## Step 5: Architecture Diagram

Create `docs/architecture-diagram.png`.

Content (recreate in Excalidraw or draw.io):

```
┌─────────────────────────────────────────────────────────┐
│               CHROME BROWSER                            │
│                                                         │
│  ┌─────────────────┐   ┌──────────────────────────────┐ │
│  │  Grocery Site   │   │  SeaSussed Extension (MV3)   │ │
│  │  (Any website)  │   │                              │ │
│  │                 │   │  background.js               │ │
│  │  Product page ──┼──▶│  ├─ captureVisibleTab()      │ │
│  │  with seafood   │   │  ├─ DOM scrape product titles │ │
│  └─────────────────┘   │  └─ POST /analyze            │ │
│                         │                              │ │
│                         │  sidepanel.js / html         │ │
│                         │  ├─ Grade badge (A–D)        │ │
│                         │  ├─ Score breakdown          │ │
│                         │  ├─ Explanation              │ │
│                         │  ├─ Alternatives (from page) │ │
│                         │  └─ "Not right?" correction  │ │
│                         └──────────────┬───────────────┘ │
└──────────────────────────────────────  ┼  ───────────────┘
                                         │ HTTPS POST
                                         │ { screenshot, related_products }
                                         ▼
┌─────────────────────────────────────────────────────────┐
│               GOOGLE CLOUD (us-central1)                │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │            Cloud Run: seasussed-backend           │  │
│  │                                                   │  │
│  │  POST /analyze                                    │  │
│  │    ① ScreenAnalyzerAgent (Google ADK)             │  │
│  │       gemini-2.5-flash (vision)                   │  │
│  │       → species, origin, method, certifications  │  │
│  │    ② score_product() — pure Python math          │  │
│  │    ③ score_alternatives() — DOM titles + Python  │  │
│  │    ④ generate_explanation() — Gemini API call    │  │
│  │         states what was/wasn't visible           │  │
│  │                                                   │  │
│  │  POST /score (correction flow, no vision)         │  │
│  │                                                   │  │
│  │  SQLite (embedded in container):                  │  │
│  │  ├─ species    (FishBase: 30k+ species)           │  │
│  │  ├─ noaa       (~100 US species status)           │  │
│  │  ├─ methods    (18 gear types, impact scores)     │  │
│  │  └─ alts       (seed fallback alternatives)       │  │
│  └───────────────────────────────────────────────────┘  │
│                        │                                │
│                        ▼                                │
│  ┌───────────────────────────────────────────────────┐  │
│  │        Vertex AI — gemini-2.5-flash               │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

Tool: Use [Excalidraw](https://excalidraw.com) — export as PNG at 2x resolution.
Save to: `docs/architecture-diagram.png`

---

## Step 6: Demo Video Script (≤ 4 minutes)

**Demo site:** Whole Foods Market (wholefoodsmarket.com)
**Recording tool:** OBS or Loom at 1080p

| Time | Section | Content |
|---|---|---|
| 0:00–0:25 | Problem | "Every day millions of people buy fish with no idea if it's sustainable. Labels like 'sustainably sourced' are marketing, not measurement." |
| 0:25–0:55 | Solution | "SeaSussed is a Chrome extension that gives you an instant science-based sustainability score for any seafood, on any grocery website, using Gemini to visually read the page." |
| 0:55–2:00 | Demo: A grade | Whole Foods wild Alaska sockeye salmon page. Click toolbar icon → side panel opens. Click Analyze. Score appears (grade A). Show grade badge, extracted data tags, explanation text, score breakdown. |
| 2:00–2:45 | Demo: D grade | Whole Foods product with lower score. Grade D appears. Show explanation (mentions what Gemini saw). Click "Not right?" — show correction form. |
| 2:45–3:15 | Correction demo | Change a field in the correction form (e.g., change species). Click Recalculate. Score updates instantly — no page refresh. |
| 3:15–3:40 | Architecture | Brief screen share of the architecture diagram. "Gemini 2.5 Flash reads the screenshot. Google ADK orchestrates the pipeline. Everything runs on Cloud Run." |
| 3:40–4:00 | Closing | "SeaSussed works on any grocery site — no DOM access needed. Just Gemini, ADK, and a sustainability database built from FishBase, NOAA, and open data. Suss out your seafood." |

Recording tips:
- Keep `--min-instances 1` active during recording (no cold starts)
- Slow mouse movements on the Analyze button for emphasis
- Record in a private/incognito window to avoid personal data in recording
- The side panel stays open while you navigate — show this naturally

---

## Step 7: Devpost Submission

**Before submitting:**
- [ ] GitHub repo is public
- [ ] README has working spin-up instructions (tested from scratch)
- [ ] `curl <service-url>/health` returns 200 from production Cloud Run
- [ ] Architecture diagram PNG is in `docs/`
- [ ] Demo video is ≤ 4 minutes and uploaded to YouTube (unlisted) or Devpost directly
- [ ] Extension config.js points to production Cloud Run URL in the final commit

**Devpost form fields:**

| Field | Value |
|---|---|
| Project name | SeaSussed |
| Tagline | Real-time seafood sustainability scores on any grocery site |
| Category | UI Navigator |
| Required tech | ✅ Gemini model · ✅ Google ADK · ✅ Google Cloud (Cloud Run + Vertex AI) |
| Code repo | https://github.com/jordan294/seasussed |
| Cloud proof | Cloud Run service URL: `$SERVICE_URL/health` → 200 |

**Description — cover all 4 judging dimensions:**

- **Innovation (40%):** SeaSussed works on any grocery website without relying on structured data or retailer cooperation. Gemini 2.5 Flash visually reads the product page — just like a human would — to identify the species, origin, certifications, and fishing method. The system is honest: it explicitly tells you what it could and couldn't see.

- **Technical (30%):** Google ADK SequentialAgent powers the vision extraction step (ScreenAnalyzerAgent). Scoring is deterministic Python math over a SQLite database built from FishBase (30k+ species), NOAA FishWatch, and hand-coded gear impact tables. Alternatives are scored from products actually visible on the retailer's page — real choices, not abstract suggestions.

- **Demo (30%):** Whole Foods demo shows: grade A for wild Alaska sockeye, grade D for an unsustainable choice, correction flow, and alternatives from the page. The side panel stays open while browsing — score at a glance, always available.

---

## Automated Success Criteria

```bash
# Final pre-submission verification
SERVICE_URL=$(gcloud run services describe seasussed-backend \
  --region us-central1 --format 'value(status.url)')

curl -s "$SERVICE_URL/health" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['status']=='ok', d"
echo "Health check: PASS"

gh repo view jordan294/seasussed --json visibility --jq '.visibility'
# Expected: "PUBLIC"
```

## Manual Success Criteria

- [ ] Cold start test: scale Cloud Run to 0, wait 2 min, then call `/health` → responds within 10s
- [ ] Production analyze call with sockeye fixture → grade A or B
- [ ] README: a new developer can spin up locally following only the README instructions
- [ ] Demo video uploaded and shareable link working
- [ ] Devpost form submitted with all required fields filled
