"""Pure Python sustainability scoring math.

Four categories, 0–100 total:
  Biological & Population   0–20
  Fishing / Aquaculture     0–25
  Management & Regulation   0–30
  Environmental & Ecological 0–25

Grade: A (80–100) · B (60–79) · C (40–59) · D (0–39)
"""

from typing import Any, Literal

from database import get_gear_score, get_noaa_status, get_species
from models import ProductInfo, ScoreBreakdown

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Certification impact on Management score (max 15 pts there)
CERT_SCORES: dict[str, int] = {
    "MSC": 15,
    "MARINE STEWARDSHIP COUNCIL": 15,
    "ASC": 15,
    "AQUACULTURE STEWARDSHIP COUNCIL": 15,
    "BAP": 10,
    "BEST AQUACULTURE PRACTICES": 10,
    "GLOBALG.A.P.": 8,
    "GLOBAL GAP": 8,
    "FRIEND OF THE SEA": 8,
    "FOS": 8,
    "ASMI": 7,
    "ALASKA SEAFOOD": 7,
    "SEAFOOD WATCH": 6,
    "RESPONSIBLY FARMED": 3,
    "SUSTAINABLY SOURCED": 3,
}

# Species commonly farmed — used when wild_or_farmed is "unknown"
_MOSTLY_FARMED: frozenset[str] = frozenset(
    {
        "atlantic salmon",
        "tilapia",
        "catfish",
        "rainbow trout",
        "pangasius",
        "basa",
        "whiteleg shrimp",
    }
)

# Country management quality — used in explanation text only (not scored)
COUNTRY_MANAGEMENT_NOTES: dict[str, str] = {
    "norway": "strong fisheries management",
    "iceland": "strong fisheries management",
    "united states": "NOAA-regulated, strong management",
    "alaska": "NOAA-regulated, strong management",
    "canada": "DFO-regulated management",
    "australia": "strong fisheries management",
    "new zealand": "strong fisheries management",
    "china": "limited independent verification of fishing practices",
    "indonesia": "limited independent verification of fishing practices",
    "vietnam": "limited independent verification of fishing practices",
    "thailand": "limited independent verification of fishing practices",
    "india": "limited independent verification of fishing practices",
    "bangladesh": "limited independent verification of fishing practices",
}


# ---------------------------------------------------------------------------
# Per-category scoring functions
# ---------------------------------------------------------------------------


def score_biological(species_data: dict[str, Any] | None) -> float:
    """Max 20 pts: vulnerability (10) + resilience (7) + IUCN (3)."""
    if species_data is None:
        return 10.0  # neutral default for unknown species

    vuln = float(species_data.get("vulnerability") or 50.0)
    vuln_score = (100.0 - vuln) / 100.0 * 10.0

    resilience_map: dict[str, float] = {
        "Very Low": 0.0,
        "Low": 2.0,
        "Medium": 5.0,
        "High": 7.0,
    }
    resilience_score = resilience_map.get(
        str(species_data.get("resilience") or ""), 3.0
    )

    iucn_scores: dict[str, float] = {
        "LC": 3.0,
        "NT": 2.0,
        "VU": 1.0,
        "EN": 0.5,
        "CR": 0.0,
        "DD": 1.5,
    }
    iucn_score = iucn_scores.get(str(species_data.get("iucn_code") or "LC"), 2.0)

    return min(20.0, vuln_score + resilience_score + iucn_score)


def score_wild_practices(gear_data: dict[str, Any] | None) -> float:
    """Max 25 pts: gear impact score scaled to 0–25."""
    if gear_data is None:
        return 10.0  # penalty for unknown gear — reflects real uncertainty
    return float(gear_data["impact_score"]) / 100.0 * 25.0


def _best_cert_score(
    certifications: list[str], base: float = 0.0, cap: float = 100.0
) -> float:
    """Return the highest matching cert score, bounded by base and cap."""
    cert_upper = [c.upper() for c in certifications]
    best = base
    for cert in cert_upper:
        for key, pts in CERT_SCORES.items():
            if key in cert or cert in key:
                best = max(best, float(pts))
                break
    return min(cap, best)


def score_aquaculture(
    certifications: list[str], species_data: dict[str, Any] | None
) -> float:
    """Max 25 pts: certifications (max 20) + carnivory bonus (max 5)."""
    cert_score = _best_cert_score(certifications, base=5.0, cap=20.0)

    carnivory = float((species_data or {}).get("carnivory_ratio") or 0.5)
    carnivory_bonus = (1.0 - carnivory) * 5.0  # 0–5 pts (lower carnivory = better)

    return min(25.0, cert_score + carnivory_bonus)


def score_management(
    certifications: list[str],
    noaa_data: dict[str, Any] | None,
    species_data: dict[str, Any] | None,
) -> float:
    """Max 30 pts: visual cert (15) + NOAA status (10) + FAO exploitation (5)."""
    cert_score = _best_cert_score(certifications, base=0.0, cap=15.0)

    # NOAA overfishing status
    noaa_score = 4.0  # default for non-US or unknown species
    if noaa_data:
        rate = str(noaa_data.get("fishing_rate") or "").lower()
        if "not subject" in rate or "not overfishing" in rate:
            noaa_score = 10.0
        elif "overfishing" in rate:
            noaa_score = 0.0

    # FAO stock exploitation from FishBase
    exploitation = str((species_data or {}).get("stock_exploitation") or "")
    exploitation_score_map: dict[str, float] = {
        "not overexploited": 5.0,
        "fully exploited": 2.0,
        "overexploited": 0.0,
    }
    exploitation_score = exploitation_score_map.get(exploitation.lower(), 3.0)

    return min(30.0, cert_score + noaa_score + exploitation_score)


def score_ecological(species_data: dict[str, Any] | None) -> float:
    """Max 25 pts: trophic level (10) + IUCN conservation (10) + resilience bonus (5)."""
    if species_data is None:
        return 12.0  # neutral

    trophic = float(species_data.get("trophic_level") or 3.0)
    if trophic <= 2.5:
        trophic_score = 10.0  # filter feeders, herbivores
    elif trophic <= 3.5:
        trophic_score = 7.0  # small pelagics
    else:
        trophic_score = 4.0  # large predators

    iucn_map: dict[str, float] = {
        "LC": 10.0,
        "NT": 7.0,
        "VU": 4.0,
        "EN": 2.0,
        "CR": 0.0,
        "DD": 5.0,
    }
    iucn_score = iucn_map.get(str(species_data.get("iucn_code") or "LC"), 5.0)

    resilience_bonus = (
        2.0 if species_data.get("resilience") in ("High", "Medium") else 1.0
    )

    return min(25.0, trophic_score + iucn_score + resilience_bonus)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def compute_score(
    product: ProductInfo,
) -> tuple[ScoreBreakdown, int, Literal["A", "B", "C", "D"]]:
    """Return (breakdown, total_score, grade) for a ProductInfo."""
    species_data = get_species(product.species or "") if product.species else None
    noaa_data = get_noaa_status(product.species or "") if product.species else None

    biological = score_biological(species_data)
    ecological = score_ecological(species_data)
    management = score_management(product.certifications, noaa_data, species_data)

    # Determine effective wild/farmed for practices scoring
    effective = product.wild_or_farmed
    if effective == "unknown" and product.species:
        if product.species.lower() in _MOSTLY_FARMED:
            effective = "farmed"

    if effective == "farmed":
        practices = score_aquaculture(product.certifications, species_data)
    else:
        gear_data = get_gear_score(product.fishing_method or "Unknown")
        practices = score_wild_practices(gear_data)

    breakdown = ScoreBreakdown(
        biological=biological,
        practices=practices,
        management=management,
        ecological=ecological,
    )
    total = int(biological + practices + management + ecological)
    grade: Literal["A", "B", "C", "D"] = (
        "A" if total >= 80 else "B" if total >= 60 else "C" if total >= 40 else "D"
    )
    return breakdown, total, grade
