import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any

from alternatives import score_alternatives
from explanation import generate_content, generate_listing_summary, generate_template_content
from geolocation import get_user_location
from health import get_health_info
from models import (
    AnalyzeResponse,
    FoodMiles,
    PageAnalysis,
    PageProduct,
    ProductInfo,
    ScoreBreakdown,
    SustainabilityScore,
)
from research import research_product
from scoring import compute_score
from wolfram import get_food_miles

_STOPWORDS = {"the", "a", "an", "of", "and", "or", "in", "at", "to", "with", "for", "lb", "oz"}


def _match_url(product_name: str, url_entries: list[dict[str, str]]) -> str | None:
    """Return the best-matching URL for product_name from url_entries.

    Three-tier match: exact → substring containment → token overlap ≥ 2.
    Returns None if no confident match found.
    """
    if not product_name or not url_entries:
        return None
    name_lower = product_name.strip().lower()
    for entry in url_entries:
        title_lower = entry.get("title", "").strip().lower()
        url = entry.get("url", "")
        if not title_lower or not url:
            continue
        if name_lower == title_lower:
            return url
        if name_lower in title_lower or title_lower in name_lower:
            return url
    name_tokens = {t for t in name_lower.split() if t not in _STOPWORDS and len(t) > 2}
    best_url: str | None = None
    best_overlap = 1
    for entry in url_entries:
        title_tokens = {
            t for t in entry.get("title", "").lower().split()
            if t not in _STOPWORDS and len(t) > 2
        }
        overlap = len(name_tokens & title_tokens)
        if overlap > best_overlap:
            best_overlap = overlap
            best_url = entry.get("url") or None
    return best_url


async def run_scoring_pipeline(
    product_info: ProductInfo,
    related_products: list[str],
    client_ip: str = "",
) -> SustainabilityScore:
    # Step 1: Enrich via web research + food miles in parallel
    user_location = get_user_location(client_ip)
    origin = product_info.origin_region or ""

    async def _food_miles_early() -> FoodMiles | None:
        if user_location and origin:
            return await asyncio.to_thread(
                get_food_miles, origin, user_location
            )
        return None

    enriched, food_miles = await asyncio.gather(
        asyncio.to_thread(research_product, product_info),
        _food_miles_early(),
    )

    # Step 2: Score with enriched data
    breakdown, score, grade = compute_score(enriched)

    # Step 3: Health lookup (instant, static)
    health = get_health_info(enriched.species)

    # If research found origin we didn't have, get food miles now
    enriched_origin = enriched.origin_region or ""
    if user_location and enriched_origin and not food_miles:
        food_miles = await asyncio.to_thread(
            get_food_miles, enriched_origin, user_location
        )

    # Step 4: Run alternatives + explanation in parallel
    (alternatives, alts_label), (explanation, score_factors) = (
        await asyncio.gather(
            asyncio.to_thread(
                score_alternatives, related_products, enriched, score, grade
            ),
            asyncio.to_thread(
                generate_content, enriched, breakdown, score, grade
            ),
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
        food_miles=food_miles,
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
    page_analysis: PageAnalysis,
    related_products: list[str],
    client_ip: str = "",
    related_products_with_urls: list[dict[str, str]] | None = None,
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
        result = await run_scoring_pipeline(product, related_products, client_ip=client_ip)
        return AnalyzeResponse(page_type="single_product", result=result)

    # Multiple seafood products → batch score + comparative summary
    url_entries = related_products_with_urls or []
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
                price=product.price,
                url=_match_url(product.product_name or product.species or "", url_entries),
            )
        )

    # Sort by score descending
    page_products.sort(key=lambda p: p.score, reverse=True)

    # Gemini comparative summary
    summary = await asyncio.to_thread(generate_listing_summary, page_products)

    return AnalyzeResponse(
        page_type="product_listing", products=page_products, summary=summary,
    )


async def analyze_page_progressive(
    page_analysis: PageAnalysis,
    related_products: list[str],
    client_ip: str = "",
    related_products_with_urls: list[dict[str, str]] | None = None,
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

    # Product listing → batch score + comparative summary, single complete event
    if len(seafood_products) > 1 and page_analysis.page_type != "single_product":
        url_entries_prog = related_products_with_urls or []
        scored_products: list[PageProduct] = []
        for product in seafood_products:
            breakdown, total, grade = compute_score(product)
            scored_products.append(
                PageProduct(
                    product_name=product.product_name or product.species or "Seafood product",
                    species=product.species,
                    wild_or_farmed=product.wild_or_farmed,
                    certifications=product.certifications,
                    score=total,
                    grade=grade,
                    breakdown=breakdown,
                    price=product.price,
                    url=_match_url(
                        product.product_name or product.species or "", url_entries_prog
                    ),
                )
            )
        scored_products.sort(key=lambda p: p.score, reverse=True)
        summary = await asyncio.to_thread(generate_listing_summary, scored_products)
        yield {
            "phase": "complete",
            "page_type": "product_listing",
            "products": [p.model_dump() for p in scored_products],
            "summary": summary,
        }
        return

    # Single product → progressive: score first, then enrichment
    product = seafood_products[0]
    log = logging.getLogger(__name__)

    # Phase 0: instant health (static lookup)
    health = get_health_info(product.species)
    if health:
        yield {"phase": "health", "health": health.model_dump()}

    # Phase 1: initial score + template explanation (instant, no API calls)
    breakdown, score, grade = compute_score(product)
    template_explanation, template_factors = generate_template_content(
        product, breakdown, score, grade
    )
    yield {
        "phase": "scored",
        "product_info": product.model_dump(),
        "score": score,
        "grade": grade,
        "breakdown": breakdown.model_dump(),
        "explanation": template_explanation,
        "score_factors": [f.model_dump() for f in template_factors],
    }

    # Phase 1.5: food miles + research in parallel
    # Fire food miles immediately with original origin (don't wait for research)
    user_location = get_user_location(client_ip)
    origin = product.origin_region or ""
    log.info(
        "Food miles: client_ip=%s user_location=%s origin=%s",
        client_ip, user_location, origin,
    )

    async def _food_miles_if_possible() -> FoodMiles | None:
        if user_location and origin:
            return await asyncio.to_thread(get_food_miles, origin, user_location)
        return None

    food_miles_result, enriched_product = await asyncio.gather(
        _food_miles_if_possible(),
        asyncio.to_thread(research_product, product),
    )

    if food_miles_result:
        yield {"phase": "food_miles", "food_miles": food_miles_result.model_dump()}

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
        # If research found origin we didn't have, get food miles now
        enriched_origin = enriched_product.origin_region or ""
        if user_location and enriched_origin and not food_miles_result:
            food_miles_result = await asyncio.to_thread(
                get_food_miles, enriched_origin, user_location
            )
            log.info("Food miles (post-research): %s", food_miles_result)
            if food_miles_result:
                yield {
                    "phase": "food_miles",
                    "food_miles": food_miles_result.model_dump(),
                }

    log.info("Food miles result: %s", food_miles_result)

    # Phase 2: alternatives + Gemini explanation (use enriched data)
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
        food_miles=food_miles_result,
    )
    yield {
        "phase": "complete",
        "page_type": "single_product",
        "result": full_result.model_dump(),
    }
