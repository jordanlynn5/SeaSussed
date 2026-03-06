import logging
from collections import defaultdict
from time import time

from fastapi import FastAPI, HTTPException, Request, WebSocket

from agents.screen_analyzer import analyze_screenshot
from models import AnalyzeRequest, AnalyzeResponse, ScoreRequest, SustainabilityScore
from pipeline import analyze_page, run_scoring_pipeline
from voice_session import VoiceSession

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s: %(message)s")

app = FastAPI(title="SeaSussed Backend", version="0.1.0")

_request_times: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 10
_RATE_WINDOW = 60.0


def _check_rate_limit(ip: str) -> None:
    now = time()
    _request_times[ip] = [t for t in _request_times[ip] if now - t < _RATE_WINDOW]
    if len(_request_times[ip]) >= _RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please wait before analyzing again.",
        )
    _request_times[ip].append(now)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "seasussed-backend", "version": "0.1.0"}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: Request, body: AnalyzeRequest) -> AnalyzeResponse:
    if not body.screenshot:
        raise HTTPException(status_code=400, detail="screenshot is required")
    ip = request.client.host if request.client else "unknown"
    _check_rate_limit(ip)

    page_analysis = await analyze_screenshot(
        body.screenshot, body.url, body.page_title
    )
    return await analyze_page(page_analysis, body.related_products)


@app.post("/score", response_model=SustainabilityScore)
async def score_endpoint(request: ScoreRequest) -> SustainabilityScore:
    """Re-score without vision. Used by 'Not right?' correction flow."""
    return await run_scoring_pipeline(request.product_info, [])


@app.websocket("/voice")
async def voice_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    session = VoiceSession(websocket)
    try:
        await session.run()
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
