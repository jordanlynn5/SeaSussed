from alternatives import score_alternatives
from explanation import generate_content
from models import ProductInfo, ScoreBreakdown, SustainabilityScore
from scoring import compute_score


def run_scoring_pipeline(
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
