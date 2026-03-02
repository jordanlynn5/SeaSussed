from fastapi import FastAPI, HTTPException

from agents.screen_analyzer import analyze_screenshot
from alternatives import score_alternatives
from explanation import generate_content
from models import (
    AnalyzeRequest,
    ProductInfo,
    ScoreBreakdown,
    ScoreRequest,
    SustainabilityScore,
)
from scoring import compute_score

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
        return _not_seafood_response(product_info)

    return _run_scoring_pipeline(product_info, request.related_products)


@app.post("/score", response_model=SustainabilityScore)
async def score_endpoint(request: ScoreRequest) -> SustainabilityScore:
    """Re-score without vision. Used by 'Not right?' correction flow."""
    return _run_scoring_pipeline(request.product_info, [])


def _run_scoring_pipeline(
    product_info: ProductInfo, related_products: list[str]
) -> SustainabilityScore:
    breakdown, score, grade = compute_score(product_info)
    alternatives, alts_label = score_alternatives(
        related_products, product_info, score, grade
    )
    explanation, score_factors = generate_content(product_info, breakdown, score, grade)
    return SustainabilityScore(
        score=score,
        grade=grade,
        breakdown=breakdown,
        alternatives=alternatives,
        alternatives_label=alts_label,
        explanation=explanation,
        score_factors=score_factors,
        product_info=product_info,
    )


def _not_seafood_response(product_info: ProductInfo) -> SustainabilityScore:
    return SustainabilityScore(
        score=0,
        grade="D",  # unused — UI checks product_info.is_seafood
        breakdown=ScoreBreakdown(biological=0, practices=0, management=0, ecological=0),
        alternatives=[],
        alternatives_label="",
        explanation="",
        score_factors=[],
        product_info=product_info,
    )

