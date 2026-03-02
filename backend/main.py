from fastapi import FastAPI, HTTPException, WebSocket

from agents.screen_analyzer import analyze_screenshot
from models import AnalyzeRequest, ScoreRequest, SustainabilityScore
from pipeline import not_seafood_response, run_scoring_pipeline
from voice_session import VoiceSession

app = FastAPI(title="SeaSussed Backend", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "seasussed-backend", "version": "0.1.0"}


@app.post("/analyze", response_model=SustainabilityScore)
async def analyze(request: AnalyzeRequest) -> SustainabilityScore:
    if not request.screenshot:
        raise HTTPException(status_code=400, detail="screenshot is required")

    product_info = await analyze_screenshot(
        request.screenshot, request.url, request.page_title
    )

    if not product_info.is_seafood:
        return not_seafood_response(product_info)

    return run_scoring_pipeline(product_info, request.related_products)


@app.post("/score", response_model=SustainabilityScore)
async def score_endpoint(request: ScoreRequest) -> SustainabilityScore:
    """Re-score without vision. Used by 'Not right?' correction flow."""
    return run_scoring_pipeline(request.product_info, [])


@app.websocket("/voice")
async def voice_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    session = VoiceSession(websocket)
    await session.run()

