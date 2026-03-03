from fastapi import FastAPI, HTTPException, WebSocket

from agents.screen_analyzer import analyze_screenshot
from models import AnalyzeRequest, AnalyzeResponse, ScoreRequest, SustainabilityScore
from pipeline import analyze_page, run_scoring_pipeline
from voice_session import VoiceSession

app = FastAPI(title="SeaSussed Backend", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "seasussed-backend", "version": "0.1.0"}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    if not request.screenshot:
        raise HTTPException(status_code=400, detail="screenshot is required")

    page_analysis = await analyze_screenshot(
        request.screenshot, request.url, request.page_title
    )
    return await analyze_page(page_analysis, request.related_products)


@app.post("/score", response_model=SustainabilityScore)
async def score_endpoint(request: ScoreRequest) -> SustainabilityScore:
    """Re-score without vision. Used by 'Not right?' correction flow."""
    return await run_scoring_pipeline(request.product_info, [])


@app.websocket("/voice")
async def voice_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    session = VoiceSession(websocket)
    await session.run()
