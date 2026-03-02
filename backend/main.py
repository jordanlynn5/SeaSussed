from fastapi import FastAPI, HTTPException

from models import AnalyzeRequest, ScoreRequest, SustainabilityScore

app = FastAPI(title="SeaSussed Backend", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "seasussed-backend", "version": "0.1.0"}


@app.post("/analyze", response_model=SustainabilityScore)
async def analyze(request: AnalyzeRequest) -> SustainabilityScore:
    # Phase 4 will implement this fully
    raise HTTPException(status_code=501, detail="Not implemented yet")


@app.post("/score", response_model=SustainabilityScore)
async def score(request: ScoreRequest) -> SustainabilityScore:
    # Phase 4 will implement this fully
    raise HTTPException(status_code=501, detail="Not implemented yet")
