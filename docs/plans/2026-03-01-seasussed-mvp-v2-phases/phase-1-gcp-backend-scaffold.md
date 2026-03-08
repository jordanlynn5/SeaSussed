# Phase 1: GCP Setup & Backend Scaffold

**Days:** 1–2 | **Depends on:** nothing | **Blocks:** Phase 4

---

## Deliverable

FastAPI app running locally and deployed to Cloud Run with working `/health`, stubbed `/analyze`, and stubbed `/score` endpoints. All three pass tests.

---

## Steps

### 1. GCP Project Setup

```bash
# Create project and configure billing (manual: https://console.cloud.google.com/billing)
gcloud projects create seasussed-hackathon --name="SeaSussed"
gcloud config set project seasussed-hackathon

# Enable required APIs
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com \
  cloudbuild.googleapis.com

# Create service account for Cloud Run → Vertex AI access
gcloud iam service-accounts create seasussed-sa \
  --display-name="SeaSussed Cloud Run SA"

gcloud projects add-iam-policy-binding seasussed-hackathon \
  --member="serviceAccount:seasussed-sa@seasussed-hackathon.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# Verify Vertex AI access (requires billing)
gcloud ai models list --region=us-central1
```

### 2. Python Project Structure

```
backend/
├── main.py               # FastAPI entry point
├── models.py             # Pydantic: all request/response types
├── database.py           # SQLite query functions
├── scoring.py            # Pure Python sustainability scoring math
├── agents/
│   ├── __init__.py
│   └── screen_analyzer.py  # ADK LlmAgent (vision extraction)
├── data/                 # seafood.db (gitignored, built by script)
├── scripts/
│   └── build_database.py
├── tests/
│   ├── __init__.py
│   └── test_health.py
├── pyproject.toml
└── Dockerfile
```

### 3. pyproject.toml

```toml
[project]
name = "seasussed-backend"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "google-adk>=1.17",
  "google-genai>=1.0",    # for direct Gemini explanation calls
  "duckdb>=1.1",
  "pydantic>=2.9",
]

[tool.uv]
dev-dependencies = [
  "pytest>=8",
  "pytest-asyncio>=0.24",
  "httpx>=0.27",
  "ruff>=0.8",
  "mypy>=1.13",
]

[tool.mypy]
python_version = "3.13"
strict = true
ignore_missing_imports = true

[tool.ruff]
target-version = "py313"
line-length = 100
```

### 4. models.py

```python
# backend/models.py
from pydantic import BaseModel
from typing import Literal

class AnalyzeRequest(BaseModel):
    screenshot: str              # base64-encoded PNG
    url: str                     # current page URL
    page_title: str = ""
    related_products: list[str] = []  # product titles scraped from DOM

class ScoreRequest(BaseModel):
    product_info: "ProductInfo"  # corrected by user; no vision step

class ProductInfo(BaseModel):
    is_seafood: bool
    species: str | None
    wild_or_farmed: Literal["wild", "farmed", "unknown"]
    fishing_method: str | None
    origin_region: str | None
    certifications: list[str]    # ["MSC", "ASC", "BAP", "ASMI", ...]

class ScoreBreakdown(BaseModel):
    biological: float            # 0–20
    practices: float             # 0–25
    management: float            # 0–30
    ecological: float            # 0–25

class Alternative(BaseModel):
    species: str
    score: int
    grade: str
    reason: str
    from_page: bool              # True = scraped from page DOM; False = seed DB

class SustainabilityScore(BaseModel):
    score: int
    grade: Literal["A", "B", "C", "D"]
    breakdown: ScoreBreakdown
    alternatives: list[Alternative]   # 1–3 items
    alternatives_label: str           # "Similar great choices" or "Better alternatives"
    explanation: str                  # 2–3 sentences mentioning visible vs unknown fields
    product_info: ProductInfo
```

### 5. main.py (scaffold with stubs)

```python
# backend/main.py
from fastapi import FastAPI, HTTPException
from models import AnalyzeRequest, ScoreRequest, SustainabilityScore

app = FastAPI(title="SeaSussed Backend", version="0.1.0")

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "seasussed-backend", "version": "0.1.0"}

@app.post("/analyze", response_model=SustainabilityScore)
async def analyze(request: AnalyzeRequest) -> SustainabilityScore:
    # Phase 4 will implement this fully
    raise HTTPException(501, "Not implemented yet")

@app.post("/score", response_model=SustainabilityScore)
async def score(request: ScoreRequest) -> SustainabilityScore:
    # Phase 4 will implement this fully
    raise HTTPException(501, "Not implemented yet")
```

### 6. Dockerfile

```dockerfile
FROM python:3.13-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml .
RUN uv sync --no-dev
COPY . .
# data/seafood.db is baked in at Docker build time (built in Phase 3)
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### 7. Initial Deploy to Cloud Run

```bash
cd /Users/jordan/sussed/backend
gcloud run deploy seasussed-backend \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 5 \
  --port 8080 \
  --service-account seasussed-sa@seasussed-hackathon.iam.gserviceaccount.com \
  --set-env-vars GOOGLE_CLOUD_PROJECT=seasussed-hackathon,GOOGLE_CLOUD_REGION=us-central1
```

### 8. test_health.py

```python
# backend/tests/test_health.py
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "seasussed-backend"

def test_analyze_stub_returns_501():
    """Verify /analyze stub is wired up correctly before Phase 4."""
    response = client.post("/analyze", json={
        "screenshot": "dGVzdA==",  # base64 "test"
        "url": "https://example.com",
    })
    assert response.status_code == 501

def test_score_stub_returns_501():
    """Verify /score stub is wired up correctly before Phase 4."""
    response = client.post("/score", json={
        "product_info": {
            "is_seafood": True,
            "species": "Atlantic salmon",
            "wild_or_farmed": "wild",
            "fishing_method": None,
            "origin_region": None,
            "certifications": [],
        }
    })
    assert response.status_code == 501
```

---

## Automated Success Criteria

```bash
cd /Users/jordan/sussed/backend
uv run mypy . 2>&1; uv run ruff check . 2>&1; uv run pytest tests/test_health.py -v 2>&1
```

All three commands must exit 0.

## Manual Success Criteria

```bash
# Verify Cloud Run deployment
SERVICE_URL=$(gcloud run services describe seasussed-backend \
  --region us-central1 --format 'value(status.url)')
curl "$SERVICE_URL/health"
# Expected: {"status":"ok","service":"seasussed-backend","version":"0.1.0"}
```

- GCP project created and billing enabled
- Vertex AI API enabled (`gcloud ai models list --region=us-central1` returns results)
- Service account created with `roles/aiplatform.user`

---

## ✅ Phase 1 Complete — 2026-03-02

- All automated criteria pass: mypy (10 files), ruff, pytest (3/3)
- Scaffold files created: database.py, scoring.py, agents/screen_analyzer.py, scripts/build_database.py
- Cloud Run deployed (project: seasussed-489008, commit 152191b)
- Minor deviations (non-blocking): pyproject.toml uses [dependency-groups] (PEP 735, functionally identical to [tool.uv]); models.py includes forward-looking ScoreFactor class for Phase 5
