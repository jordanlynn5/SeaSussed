# Phase 1: GCP Setup & Backend Scaffold [batch-eligible]

**Days:** 1–2 | **Depends on:** nothing | **Blocks:** Phase 4

---

## Steps

### 1. GCP Project Setup

```bash
# Create project and set billing (manual: https://console.cloud.google.com/billing)
gcloud projects create seasussed-hackathon --name="SeaSussed"
gcloud config set project seasussed-hackathon

# Enable required APIs
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com

# Verify Vertex AI access (must have billing enabled)
gcloud ai models list --region=us-central1
```

### 2. Python Project Init

```
backend/
├── main.py
├── agents/
│   ├── __init__.py
│   ├── pipeline.py       # SequentialAgent definition
│   ├── screen_analyzer.py
│   └── sustainability_scorer.py
├── models.py             # Pydantic: ProductInfo, SustainabilityScore, etc.
├── database.py           # SQLite query functions
├── data/                 # seafood.db lives here (gitignored, built by script)
├── scripts/
│   └── build_database.py
├── tests/
│   ├── __init__.py
│   └── test_health.py
├── pyproject.toml
└── Dockerfile
```

```toml
# pyproject.toml
[project]
name = "seasussed-backend"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "google-adk>=1.17",
  "google-genai>=1.0",
  "duckdb>=1.1",
  "pydantic>=2.9",
]

[tool.uv]
dev-dependencies = [
  "pytest>=8",
  "pytest-asyncio>=0.24",
  "httpx>=0.27",   # for TestClient
  "ruff>=0.8",
  "mypy>=1.13",
]
```

### 3. FastAPI App Skeleton

```python
# backend/main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from agents.pipeline import run_pipeline
from models import AnalyzeRequest, SustainabilityScore

app = FastAPI(title="SeaSussed Backend")

@app.get("/health")
async fn health():
  return {"status": "ok", "service": "seasussed-backend", "version": "0.1.0"}

@app.post("/analyze", response_model=SustainabilityScore)
async fn analyze(request: AnalyzeRequest) -> SustainabilityScore:
  if not request.screenshot:
    raise HTTPException(400, "screenshot is required")
  result = await run_pipeline(
    screenshot_b64=request.screenshot,
    page_url=request.url
  )
  return result
```

```python
# backend/models.py
from pydantic import BaseModel
from typing import Literal

class AnalyzeRequest(BaseModel):
  screenshot: str       # base64-encoded PNG
  url: str              # current page URL (for context)
  page_title: str = ""  # optional: page <title> for supplemental text

class ProductInfo(BaseModel):
  is_seafood: bool
  species: str | None
  wild_or_farmed: Literal["wild", "farmed", "unknown"]
  fishing_method: str | None
  origin_region: str | None
  certifications: list[str]

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

class SustainabilityScore(BaseModel):
  score: int
  grade: Literal["A", "B", "C", "D"]
  breakdown: ScoreBreakdown
  alternatives: list[Alternative]
  explanation: str
  product_info: ProductInfo
```

### 4. ADK Agent Pipeline Skeleton

```python
# backend/agents/pipeline.py
from google.adk.agents import SequentialAgent
from agents.screen_analyzer import ScreenAnalyzerAgent
from agents.sustainability_scorer import SustainabilityScorerAgent
from models import SustainabilityScore

pipeline = SequentialAgent(
  name="seasussed_pipeline",
  agents=[ScreenAnalyzerAgent(), SustainabilityScorerAgent()],
)

async fn run_pipeline(screenshot_b64: str, page_url: str) -> SustainabilityScore:
  result = await pipeline.run(
    input={
      "screenshot_b64": screenshot_b64,
      "page_url": page_url,
    }
  )
  return result.output
```

### 5. Dockerfile

```dockerfile
FROM python:3.13-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml .
RUN uv sync --no-dev
COPY . .
# data/seafood.db is baked in at build time
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### 6. Deploy to Cloud Run

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
  --set-env-vars GOOGLE_CLOUD_PROJECT=seasussed-hackathon,GOOGLE_CLOUD_REGION=us-central1
```

### 7. Health Check Test

```python
# backend/tests/test_health.py
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health():
  response = client.get("/health")
  assert response.status_code == 200
  assert response.json()["status"] == "ok"
```

## Verification

Run sequentially (never in parallel):
```bash
cd /Users/jordan/sussed/backend
uv run mypy . 2>&1; uv run ruff check . 2>&1; uv run pytest tests/test_health.py 2>&1
```

Verify Cloud Run:
```bash
SERVICE_URL=$(gcloud run services describe seasussed-backend --region us-central1 --format 'value(status.url)')
curl "$SERVICE_URL/health"
# Expected: {"status":"ok","service":"seasussed-backend","version":"0.1.0"}
```
