import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from alternatives import score_alternatives
from explanation import generate_content
from health import get_health_info
from models import (
    AnalyzeResponse,
    PageAnalysis,
    PageProduct,
    ProductInfo,
    ScoreBreakdown,
    SustainabilityScore,
)
from research import research_product
from scoring import compute_score
from wolfram import get_carbon_footprint


async def run_scoring_pipeline(
    product_info: ProductInfo, related_products: list[str]
) -> SustainabilityScore:
    # Step 1: Enrich via web research (only if fields missing)
    enriched = await asyncio.to_thread(research_product, product_info)

    # Step 2: Score with enriched data
    breakdown, score, grade = compute_score(enriched)

    # Step 3: Health lookup (instant, static)
    health = get_health_info(enriched.species)

    # Step 4: Run alternatives + explanation + carbon in parallel
    (alternatives, alts_label), (explanation, score_factors), carbon = (
        await asyncio.gather(
            asyncio.to_thread(
                score_alternatives, related_products, enriched, score, grade
            ),
            asyncio.to_thread(
                generate_content, enriched, breakdown, score, grade
            ),
            asyncio.to_thread(get_carbon_footprint, enriched.species or ""),
        )
    )

    return SustainabilityScore(
        score=score,
        grade=grade,
        breakdown=breakdown,
        alternatives=alternatives,
        alternatives_label=alts_label,
        explanation=explanation,
        score_factors=score_factors,
        product_info=enriched,
        health=health,
        carbon=carbon,
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


async def analyze_page_progressive(
    page_analysis: PageAnalysis, related_products: list[str]
) -> AsyncGenerator[dict[str, Any], None]:
    """Yield progressive SSE events as dicts.

    Phase 1 ('scored'):  product_info + score + grade + breakdown (instant after vision).
    Phase 2 ('complete'): full result with alternatives + explanation.
    For product_listing or no_seafood, a single 'complete' event is emitted.
    """
    seafood_products = [p for p in page_analysis.products if p.is_seafood]

    # No seafood → single complete event
    if page_analysis.page_type == "no_seafood" or not seafood_products:
        placeholder = ProductInfo(
            is_seafood=False,
            species=None,
            wild_or_farmed="unknown",
            fishing_method=None,
            origin_region=None,
            certifications=[],
        )
        yield {
            "phase": "complete",
            "page_type": "no_seafood",
            "result": not_seafood_response(placeholder).model_dump(),
        }
        return

    # Product listing → batch score, single complete event
    if len(seafood_products) > 1 and page_analysis.page_type != "single_product":
        page_products: list[dict[str, Any]] = []
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
                ).model_dump()
            )
        page_products.sort(key=lambda p: p["score"], reverse=True)
        yield {"phase": "complete", "page_type": "product_listing", "products": page_products}
        return

    # Single product → progressive: score first, then enrichment
    product = seafood_products[0]

    # Phase 0: instant health (static lookup)
    health = get_health_info(product.species)
    if health:
        yield {"phase": "health", "health": health.model_dump()}

    # Phase 1: initial score (before research)
    breakdown, score, grade = compute_score(product)
    yield {
        "phase": "scored",
        "product_info": product.model_dump(),
        "score": score,
        "grade": grade,
        "breakdown": breakdown.model_dump(),
    }

    # Phase 1.5: research + carbon in parallel
    enriched_product, carbon = await asyncio.gather(
        asyncio.to_thread(research_product, product),
        asyncio.to_thread(get_carbon_footprint, product.species or ""),
    )

    if carbon:
        yield {"phase": "carbon", "carbon": carbon.model_dump()}

    # If research found new data, recompute score
    enriched_changed = enriched_product is not product
    if enriched_changed:
        breakdown, score, grade = compute_score(enriched_product)
        yield {
            "phase": "enriched",
            "product_info": enriched_product.model_dump(),
            "score": score,
            "grade": grade,
            "breakdown": breakdown.model_dump(),
        }

    # Phase 2: alternatives + explanation (use enriched data)
    final_product = enriched_product if enriched_changed else product
    (alternatives, alts_label), (explanation, score_factors) = await asyncio.gather(
        asyncio.to_thread(
            score_alternatives, related_products, final_product, score, grade
        ),
        asyncio.to_thread(
            generate_content, final_product, breakdown, score, grade
        ),
    )

    full_result = SustainabilityScore(
        score=score,
        grade=grade,
        breakdown=breakdown,
        alternatives=alternatives,
        alternatives_label=alts_label,
        explanation=explanation,
        score_factors=score_factors,
        product_info=final_product,
        health=health,
        carbon=carbon,
    )
    yield {
        "phase": "complete",
        "page_type": "single_product",
        "result": full_result.model_dump(),
    }
