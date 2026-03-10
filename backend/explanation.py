"""Explanation and per-factor educational content generation.

A single Gemini call produces:
  - explanation:   2–3 sentence overall summary (states visible vs unknown)
  - score_factors: per-category WHY + optional tip (C/D grades only)

Gemini honesty rule: never fabricate. The prompt explicitly tells Gemini what
was and was not visible on the page, and anchors factual claims to DB data.
"""

import json
import logging
from typing import Literal

from database import get_gear_score
from gemini_client import get_genai_client, strip_json_fences
from models import ProductInfo, ScoreBreakdown, ScoreFactor

log = logging.getLogger(__name__)


def generate_content(
    product: ProductInfo,
    breakdown: ScoreBreakdown,
    score: int,
    grade: Literal["A", "B", "C", "D"],
) -> tuple[str, list[ScoreFactor]]:
    """Return (explanation, score_factors) via a single Gemini call.

    Falls back to template content if the API call fails or returns unparseable JSON.
    """
    # Build visibility context
    visible: list[str] = []
    unknown: list[str] = []
    if product.species:
        visible.append(f"species: {product.species}")
    else:
        unknown.append("species (unknown)")
    if product.wild_or_farmed != "unknown":
        visible.append(f"wild/farmed: {product.wild_or_farmed}")
    else:
        unknown.append("wild vs farmed (unknown)")
    if product.fishing_method:
        visible.append(f"fishing method: {product.fishing_method}")
    else:
        unknown.append("fishing method (unknown)")
    if product.origin_region:
        visible.append(f"origin: {product.origin_region}")
    else:
        unknown.append("origin (unknown)")
    if product.certifications:
        visible.append(f"certifications seen: {', '.join(product.certifications)}")
    else:
        unknown.append("certifications (none visible)")

    practices_label = (
        "Aquaculture Practices"
        if product.wild_or_farmed == "farmed"
        else "Fishing Practices"
    )

    # Pull gear educational note from DB — static, reliable, never Gemini-generated
    gear_note = ""
    if product.fishing_method:
        gear_data = get_gear_score(product.fishing_method)
        gear_note = str((gear_data or {}).get("educational_note") or "")

    prompt = f"""You are a seafood sustainability educator writing for a consumer shopping app.
Your goal is to help shoppers understand not just their score, but WHY — so they
make more informed choices over time. Be factual, specific, and educational.
Never preachy. Never fabricate information.

PRODUCT INFORMATION:
  Species: {product.species or 'unknown'}
  Wild or farmed: {product.wild_or_farmed}
  Fishing method: {product.fishing_method or 'unknown'}
  Origin: {product.origin_region or 'unknown'}
  Certifications visible: {', '.join(product.certifications) if product.certifications else 'none'}

SCORE:
  Grade: {grade}  ({score}/100)
  Biological & Population:    {breakdown.biological:.1f}/20
  {practices_label}:          {breakdown.practices:.1f}/25
  Management & Regulation:    {breakdown.management:.1f}/30
  Environmental & Ecological: {breakdown.ecological:.1f}/25

WHAT WAS VISIBLE ON PAGE: {', '.join(visible) if visible else 'nothing confirmed'}
WHAT WAS NOT SHOWN (defaults applied): {', '.join(unknown) if unknown else 'all fields visible'}

FISHING METHOD EDUCATION (from database — use this text verbatim
in the Fishing Practices factor if relevant):
{gear_note if gear_note else 'No gear method data available.'}

RULES:
1. Only state facts that come from the product information above. Do NOT invent facts about
   this specific product (e.g. do not claim a stock is overfished unless NOAA data confirms it).
2. If a field was unknown/not shown, say so in the relevant factor explanation.
3. For grade A/B factors: explain what was good and why it matters.
4. For grade C/D factors: explain what the problem is and why it matters.
5. Tips: only include for grade C or D products. One sentence per factor at most.
   Make tips actionable: "Look for the MSC blue fish logo" not "try to find better options."
6. Biological & Ecological explanations may reference species biology known from science
   (e.g. trophic level, maturity age, known population trends) — but label it as
   "scientifically, [species] is known for..." rather than product-specific claims.

Return ONLY valid JSON in this exact structure:
{{
  "summary": "2-3 sentence overall explanation. State grade, key strengths/weaknesses,
              and note any fields not visible on the page.",
  "factors": {{
    "biological": {{
      "explanation": "2-3 sentences: what was found, why this score, why it matters.",
      "tip": "one sentence tip OR null"
    }},
    "practices": {{
      "explanation": "2-3 sentences. If gear is known, use the gear education text above.",
      "tip": "one sentence tip OR null"
    }},
    "management": {{
      "explanation": "2-3 sentences: cert name/absence, NOAA status, why certs matter.",
      "tip": "one sentence tip OR null"
    }},
    "ecological": {{
      "explanation": "2-3 sentences: trophic role, ecosystem impact, species context.",
      "tip": "one sentence tip OR null"
    }}
  }}
}}"""

    try:
        client = get_genai_client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        raw = strip_json_fences(response.text or "")
        data: dict[str, object] = json.loads(raw)

        summary = str(data.get("summary") or "")
        factors_raw = data.get("factors") or {}
        if not isinstance(factors_raw, dict):
            factors_raw = {}
        include_tips = grade in ("C", "D")

        def _factor(key: str, category: str, score_val: float, max_val: int) -> ScoreFactor:
            entry = factors_raw.get(key) or {}
            if not isinstance(entry, dict):
                entry = {}
            tip_val = entry.get("tip") if include_tips else None
            return ScoreFactor(
                category=category,
                score=score_val,
                max_score=max_val,
                explanation=str(entry.get("explanation") or ""),
                tip=str(tip_val) if tip_val else None,
            )

        score_factors = [
            _factor("biological", "Biological & Population", breakdown.biological, 20),
            _factor("practices", practices_label, breakdown.practices, 25),
            _factor("management", "Management & Regulation", breakdown.management, 30),
            _factor("ecological", "Environmental & Ecological", breakdown.ecological, 25),
        ]
        return summary, score_factors

    except Exception as e:
        log.warning("generate_content failed: %s", e)
        return _fallback_summary(product, score, grade), _fallback_factors(
            breakdown, grade, practices_label
        )


def generate_template_content(
    product: ProductInfo,
    breakdown: ScoreBreakdown,
    score: int,
    grade: Literal["A", "B", "C", "D"],
) -> tuple[str, list[ScoreFactor]]:
    """Instant template-based explanation — no API calls.

    Used for the progressive 'scored' phase to give users immediate
    educational content while the Gemini explanation loads.
    """
    species = product.species or "this seafood product"
    practices_label = (
        "Aquaculture Practices"
        if product.wild_or_farmed == "farmed"
        else "Fishing Practices"
    )

    # Summary
    grade_text = {
        "A": "an excellent choice with strong sustainability credentials",
        "B": "a good alternative with some areas for improvement",
        "C": "a product to approach with caution",
        "D": "a product best avoided based on available sustainability data",
    }[grade]

    parts: list[str] = [
        f"{species.capitalize()} scored {score}/100 (grade {grade}), "
        f"making it {grade_text}."
    ]

    unknown: list[str] = []
    if product.wild_or_farmed == "unknown":
        unknown.append("wild vs farmed status")
    if product.fishing_method is None:
        unknown.append("fishing method")
    if product.origin_region is None:
        unknown.append("origin region")
    if not product.certifications:
        unknown.append("certifications")
    if unknown:
        verb = "was" if len(unknown) == 1 else "were"
        parts.append(
            f"{', '.join(unknown).capitalize()} {verb} not visible on the page, "
            "which may affect the score."
        )

    summary = " ".join(parts)

    # Score factors
    include_tips = grade in ("C", "D")

    # Biological
    bio_pct = breakdown.biological / 20
    if bio_pct >= 0.7:
        bio_expl = (
            f"{species.capitalize()} has favorable biological characteristics "
            "for sustainability."
        )
    elif bio_pct >= 0.4:
        bio_expl = f"{species.capitalize()} has moderate biological vulnerability."
    else:
        bio_expl = (
            f"{species.capitalize()} has concerning biological vulnerability, "
            "with characteristics that make population recovery difficult."
        )
    bio_tip = (
        "Look for species with faster growth rates and higher resilience."
        if include_tips and bio_pct < 0.5
        else None
    )

    # Practices
    if product.fishing_method:
        practices_expl = f"Caught using {product.fishing_method}."
    elif product.wild_or_farmed == "farmed":
        if product.certifications and any(
            c.upper() in ("ASC", "BAP") for c in product.certifications
        ):
            practices_expl = (
                "This farmed product has recognized aquaculture certification."
            )
        else:
            practices_expl = (
                "Farmed product without visible aquaculture certification."
            )
    else:
        practices_expl = (
            "No fishing method was visible on the page, "
            "so a default score was applied."
        )
    practices_tip = (
        "Look for products caught with selective gear "
        "like pole-and-line or pot/trap."
        if include_tips and breakdown.practices / 25 < 0.5
        else None
    )

    # Management
    if product.certifications:
        cert_list = ", ".join(product.certifications)
        mgmt_expl = (
            f"Certifications visible: {cert_list}. "
            "Third-party certification indicates independent "
            "sustainability verification."
        )
    else:
        mgmt_expl = (
            "No sustainability certifications were visible on the page, "
            "which limits the management score."
        )
    mgmt_tip = (
        "Look for the MSC blue fish logo (wild-caught) or ASC teal logo "
        "(farmed) for independently verified sustainability."
        if include_tips and not product.certifications
        else None
    )

    # Ecological
    eco_pct = breakdown.ecological / 25
    if eco_pct >= 0.7:
        eco_expl = (
            f"{species.capitalize()} has a relatively low ecological impact "
            "based on its role in the food web."
        )
    elif eco_pct >= 0.4:
        eco_expl = f"{species.capitalize()} has a moderate ecological footprint."
    else:
        eco_expl = (
            f"{species.capitalize()} has a higher ecological impact, "
            "potentially due to its position in the food web."
        )
    eco_tip = (
        "Consider lower-trophic species like sardines, mussels, or oysters "
        "for reduced ecological impact."
        if include_tips and eco_pct < 0.5
        else None
    )

    score_factors = [
        ScoreFactor(
            category="Biological & Population",
            score=breakdown.biological,
            max_score=20,
            explanation=bio_expl,
            tip=bio_tip,
        ),
        ScoreFactor(
            category=practices_label,
            score=breakdown.practices,
            max_score=25,
            explanation=practices_expl,
            tip=practices_tip,
        ),
        ScoreFactor(
            category="Management & Regulation",
            score=breakdown.management,
            max_score=30,
            explanation=mgmt_expl,
            tip=mgmt_tip,
        ),
        ScoreFactor(
            category="Environmental & Ecological",
            score=breakdown.ecological,
            max_score=25,
            explanation=eco_expl,
            tip=eco_tip,
        ),
    ]

    return summary, score_factors


def _fallback_summary(
    product: ProductInfo, score: int, grade: Literal["A", "B", "C", "D"]
) -> str:
    grade_text = {
        "A": "an excellent choice with strong sustainability credentials",
        "B": "a decent choice with some areas for improvement",
        "C": "a product to approach with caution",
        "D": "a product best avoided based on available sustainability data",
    }.get(grade, "a seafood product")
    species = product.species or "this seafood product"
    return (
        f"{species.capitalize()} received a grade {grade} ({score}/100), "
        f"indicating it is {grade_text}. "
        "Detailed explanations are unavailable — please try analyzing again."
    )


def _fallback_factors(
    breakdown: ScoreBreakdown,
    grade: str,
    practices_label: str,
) -> list[ScoreFactor]:
    return [
        ScoreFactor(
            category="Biological & Population",
            score=breakdown.biological,
            max_score=20,
            explanation="Score based on species vulnerability and resilience data.",
            tip=None,
        ),
        ScoreFactor(
            category=practices_label,
            score=breakdown.practices,
            max_score=25,
            explanation="Score based on fishing gear type or aquaculture certifications.",
            tip=None,
        ),
        ScoreFactor(
            category="Management & Regulation",
            score=breakdown.management,
            max_score=30,
            explanation="Score based on visible certifications and fishery management data.",
            tip=None,
        ),
        ScoreFactor(
            category="Environmental & Ecological",
            score=breakdown.ecological,
            max_score=25,
            explanation="Score based on species trophic level and ecosystem role.",
            tip=None,
        ),
    ]
