"""Alternative product scoring.

Primary flow:  DOM-scraped product names → identify species via Gemini → score each.
Fallback flow: seed DB alternatives when no page products are available.
"""

import json
import logging
from typing import Literal

from database import get_seed_alternatives
from gemini_client import get_genai_client, strip_json_fences
from models import Alternative, ProductInfo
from scoring import compute_score

log = logging.getLogger(__name__)


def identify_species_from_names(product_names: list[str]) -> dict[str, str | None]:
    """Map grocery product titles to seafood species names.

    Uses one Gemini call for all names at once.
    Returns {product_title: species_common_name_or_None}.
    """
    if not product_names:
        return {}

    client = get_genai_client()
    names_json = json.dumps(product_names)
    prompt = (
        "You are a seafood species identifier. Given a list of grocery product titles, "
        "identify the seafood species for each item that is a seafood product.\n\n"
        f"Product titles:\n{names_json}\n\n"
        "Return a JSON object mapping each product title to the species common name, "
        "or null if it is not a seafood product.\n"
        "Only return the JSON object, no explanation.\n"
        'Example: {"Wild Alaskan Sockeye Salmon Fillet": "sockeye salmon", "Organic Pasta": null}'
    )

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        raw = strip_json_fences(response.text or "")
        result: dict[str, str | None] = json.loads(raw)
        return result
    except Exception as e:
        log.warning("identify_species_from_names failed: %s", e)
        return {}


def score_alternatives(
    related_products: list[str],
    main_product: ProductInfo,
    main_score: int,
    main_grade: Literal["A", "B", "C", "D"],
) -> tuple[list[Alternative], str]:
    """Score related products and return top alternatives with label.

    Returns (alternatives, label) where label is
    'Similar great choices' or 'Better alternatives'.
    """
    if not related_products:
        return _seed_alternatives(main_product, main_score, main_grade)

    species_map = identify_species_from_names(related_products)

    scored: list[tuple[int, Alternative]] = []
    for product_name, species in species_map.items():
        if species is None:
            continue
        candidate = ProductInfo(
            is_seafood=True,
            species=species,
            wild_or_farmed="unknown",
            fishing_method=None,
            origin_region=None,
            certifications=[],
        )
        _, alt_score, alt_grade = compute_score(candidate)
        scored.append(
            (
                alt_score,
                Alternative(
                    species=species,
                    score=alt_score,
                    grade=alt_grade,
                    reason=product_name,  # actual product title from the site
                    from_page=True,
                ),
            )
        )

    if not scored:
        return _seed_alternatives(main_product, main_score, main_grade)

    scored.sort(key=lambda x: x[0], reverse=True)

    if main_grade == "A":
        top = [alt for _, alt in scored if alt.grade in ("A", "B")][:3]
        label = "Similar great choices"
    else:
        top = [alt for score, alt in scored if score > main_score][:3]
        label = "Better alternatives"

    if not top:
        return _seed_alternatives(main_product, main_score, main_grade)

    return top, label


def _seed_alternatives(
    product: ProductInfo,
    main_score: int,
    main_grade: Literal["A", "B", "C", "D"],
) -> tuple[list[Alternative], str]:
    """Fallback: curated seed DB alternatives, labeled honestly."""
    seeds = get_seed_alternatives(product.species or "")
    alts: list[Alternative] = []
    for s in seeds:
        candidate = ProductInfo(
            is_seafood=True,
            species=s["species"],
            wild_or_farmed="unknown",
            fishing_method=None,
            origin_region=None,
            certifications=[],
        )
        _, alt_score, alt_grade = compute_score(candidate)
        alts.append(
            Alternative(
                species=s["species"],
                score=alt_score,
                grade=alt_grade,
                reason=s["reason"],
                from_page=False,
            )
        )

    label = (
        "Similar great choices"
        if main_grade == "A"
        else "Better alternatives — check if available here"
    )
    return alts[:3], label
