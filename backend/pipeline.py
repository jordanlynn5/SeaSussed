import asyncio

from alternatives import score_alternatives
from explanation import generate_content
from models import (
    AnalyzeResponse,
    PageAnalysis,
    PageProduct,
    ProductInfo,
    ScoreBreakdown,
    SustainabilityScore,
)
from scoring import compute_score


async def run_scoring_pipeline(
    product_info: ProductInfo, related_products: list[str]
) -> SustainabilityScore:
    breakdown, score, grade = compute_score(product_info)
    # Run the two Gemini calls concurrently — they are fully independent.
    (alternatives, alts_label), (explanation, score_factors) = await asyncio.gather(
        asyncio.to_thread(score_alternatives, related_products, product_info, score, grade),
        asyncio.to_thread(generate_content, product_info, breakdown, score, grade),
    )
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


def not_seafood_response(product_info: ProductInfo) -> SustainabilityScore:
    return SustainabilityScore(
        score=0,
        grade="D",
        breakdown=ScoreBreakdown(biological=0, practices=0, management=0, ecological=0),
        alternatives=[],
        alternatives_label="",
        explanation="",
        score_factors=[],
        product_info=product_info,
    )


async def analyze_page(
    page_analysis: PageAnalysis, related_products: list[str]
) -> AnalyzeResponse:
    """Route a PageAnalysis to the correct scoring path and return AnalyzeResponse."""
    # No seafood or empty products → no_seafood response
    seafood_products = [p for p in page_analysis.products if p.is_seafood]

    if page_analysis.page_type == "no_seafood" or not seafood_products:
        placeholder = ProductInfo(
            is_seafood=False,
            species=None,
            wild_or_farmed="unknown",
            fishing_method=None,
            origin_region=None,
            certifications=[],
        )
        return AnalyzeResponse(
            page_type="no_seafood",
            result=not_seafood_response(placeholder),
        )

    # Single seafood product (or listing with only 1) → full scoring pipeline
    if len(seafood_products) == 1 or page_analysis.page_type == "single_product":
        product = seafood_products[0]
        result = await run_scoring_pipeline(product, related_products)
        return AnalyzeResponse(page_type="single_product", result=result)

    # Multiple seafood products → batch score with pure Python (no Gemini calls)
    page_products: list[PageProduct] = []
    for product in seafood_products:
        breakdown, total, grade = compute_score(product)
        page_products.append(
            PageProduct(
                product_name=product.product_name or product.species or "Seafood product",
                species=product.species,
                wild_or_farmed=product.wild_or_farmed,
                certifications=product.certifications,
                score=total,
                grade=grade,
                breakdown=breakdown,
            )
        )

    # Sort by score descending
    page_products.sort(key=lambda p: p.score, reverse=True)

    return AnalyzeResponse(page_type="product_listing", products=page_products)
