"""Static certification definitions for the educational layer.

All content here is factual constant text — never Gemini-generated.
Used by the Phase 5 side panel to render expandable cert education cards.
"""

CERT_DEFINITIONS: dict[str, dict[str, str]] = {
    "MSC": {
        "full_name": "Marine Stewardship Council",
        "color_hint": "blue fish logo",
        "explanation": (
            "The MSC blue fish logo means this fishery has been independently audited "
            "against rigorous science-based standards. To earn MSC certification, a fishery "
            "must demonstrate: (1) fish stocks are healthy and not overfished, "
            "(2) fishing operations minimize environmental impact and bycatch, and "
            "(3) effective management systems are in place. Annual surveillance audits "
            "maintain the certification."
        ),
    },
    "ASC": {
        "full_name": "Aquaculture Stewardship Council",
        "color_hint": "teal logo",
        "explanation": (
            "The ASC teal logo certifies that farmed seafood was raised responsibly. "
            "ASC-certified farms must meet standards covering: feed sourcing and efficiency, "
            "disease and chemical use, water quality, impacts on surrounding ecosystems, "
            "worker welfare, and traceability. Considered the gold standard for "
            "farmed seafood certification."
        ),
    },
    "BAP": {
        "full_name": "Best Aquaculture Practices",
        "color_hint": "star logo",
        "explanation": (
            "BAP (Best Aquaculture Practices) is a certification for farmed seafood covering "
            "four areas: hatcheries, farms, processing, and feed mills. The number of stars "
            "indicates how many components in the supply chain are certified. More stars "
            "indicate greater supply chain traceability and sustainability verification."
        ),
    },
    "GLOBALG.A.P.": {
        "full_name": "GlobalG.A.P.",
        "color_hint": "green logo",
        "explanation": (
            "GlobalG.A.P. (Good Agricultural Practices) certifies farms against standards "
            "covering food safety, environmental sustainability, and worker welfare. "
            "In seafood, it's primarily used for farmed fish and shellfish. "
            "Respected internationally but less seafood-specific than ASC."
        ),
    },
    "FRIEND OF THE SEA": {
        "full_name": "Friend of the Sea",
        "color_hint": "blue wave logo",
        "explanation": (
            "Friend of the Sea certifies both wild-caught and farmed seafood products "
            "against sustainability criteria including stock status, bycatch reduction, "
            "and no impact on endangered species or seabed. Widely recognized internationally."
        ),
    },
    "FOS": {
        "full_name": "Friend of the Sea",
        "color_hint": "blue wave logo",
        "explanation": (
            "Friend of the Sea (FOS) certifies both wild-caught and farmed seafood "
            "against sustainability criteria including stock status, bycatch reduction, "
            "and no impact on endangered species or seabed."
        ),
    },
    "ASMI": {
        "full_name": "Alaska Seafood Marketing Institute",
        "color_hint": "Alaska Seafood logo",
        "explanation": (
            "The Alaska Seafood logo indicates seafood from Alaska — one of the world's "
            "best-managed fisheries regions. All Alaska commercial fisheries are governed "
            "by the Magnuson-Stevens Act with science-based catch limits and independent "
            "stock assessments. Alaska pollock and sockeye salmon fisheries are among the "
            "largest MSC-certified fisheries on Earth."
        ),
    },
    "SUSTAINABLY SOURCED": {
        "full_name": "Sustainably Sourced (retailer claim)",
        "color_hint": "text label",
        "explanation": (
            "'Sustainably sourced' is an unverified marketing claim — it is not backed "
            "by an independent third-party audit. Unlike MSC or ASC, there is no standard "
            "defining what 'sustainably sourced' means. When you see this label without "
            "an MSC, ASC, or BAP logo, treat it with caution and look for more specific "
            "information about where and how the fish was caught."
        ),
    },
    "RESPONSIBLY FARMED": {
        "full_name": "Responsibly Farmed (retailer claim)",
        "color_hint": "text label",
        "explanation": (
            "'Responsibly Farmed' is a retailer-defined standard, not an independent "
            "third-party certification. Whole Foods Market's Responsibly Farmed program "
            "does have documented requirements, but it is audited by the retailer itself "
            "rather than an independent body. A step above no label, but not equivalent "
            "to ASC or BAP certification."
        ),
    },
    "SEAFOOD WATCH": {
        "full_name": "Monterey Bay Aquarium Seafood Watch",
        "color_hint": "green/yellow/red card",
        "explanation": (
            "Seafood Watch is a science-based consumer guide from the Monterey Bay Aquarium "
            "that rates seafood as Best Choice, Good Alternative, or Avoid. It is not a "
            "certification (no logo on packaging) but a widely respected rating system "
            "used by restaurants and retailers. The methodology closely mirrors the "
            "factors SeaSussed uses to calculate this score."
        ),
    },
}


def get_cert_definition(cert_name: str) -> dict[str, str] | None:
    """Look up a cert definition by name (case-insensitive partial match)."""
    cert_upper = cert_name.upper()
    for key, definition in CERT_DEFINITIONS.items():
        if key in cert_upper or cert_upper in key:
            return definition
    return None
