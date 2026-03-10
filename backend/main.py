import json
import logging
import os
from collections import defaultdict
from collections.abc import AsyncGenerator
from time import time

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agents.screen_analyzer import analyze_screenshot
from models import AnalyzeRequest, AnalyzeResponse, ScoreRequest, SustainabilityScore
from pipeline import analyze_page, analyze_page_progressive, run_scoring_pipeline
from voice_session import VoiceSession

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s: %(message)s")

app = FastAPI(title="SeaSussed Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_request_times: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 10
_RATE_WINDOW = 60.0


def _get_client_ip(request: Request) -> str:
    """Extract client IP, checking X-Forwarded-For for Cloud Run.

    Set DEV_CLIENT_IP env var to override for local testing (private IPs
    can't be geolocated).
    """
    dev_ip = os.environ.get("DEV_CLIENT_IP")
    if dev_ip:
        return dev_ip
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


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
    ip = _get_client_ip(request)
    _check_rate_limit(ip)

    page_analysis = await analyze_screenshot(
        body.screenshot,
        body.url,
        body.page_title,
        page_text=body.page_text,
        product_images=body.product_images,
    )
    return await analyze_page(page_analysis, body.related_products, client_ip=ip)


@app.post("/analyze/stream")
async def analyze_stream(request: Request, body: AnalyzeRequest) -> StreamingResponse:
    """SSE endpoint for progressive analysis results.

    Streams events:
      phase=analyzing  — connection established, Gemini vision running
      phase=scored     — product_info + score + breakdown (single product only)
      phase=complete   — full result with alternatives + explanation
    """
    if not body.screenshot:
        raise HTTPException(status_code=400, detail="screenshot is required")
    ip = _get_client_ip(request)
    _check_rate_limit(ip)

    async def generate() -> AsyncGenerator[str, None]:
        # Emit immediately so the client knows the connection is live
        yield f"data: {json.dumps({'phase': 'analyzing'})}\n\n"

        page_analysis = await analyze_screenshot(
            body.screenshot,
            body.url,
            body.page_title,
            page_text=body.page_text,
            product_images=body.product_images,
        )

        async for event in analyze_page_progressive(
            page_analysis, body.related_products, client_ip=ip
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/score", response_model=SustainabilityScore)
async def score_endpoint(request: Request, body: ScoreRequest) -> SustainabilityScore:
    """Re-score without vision. Used by 'Not right?' correction flow."""
    ip = _get_client_ip(request)
    return await run_scoring_pipeline(body.product_info, [], client_ip=ip)


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
