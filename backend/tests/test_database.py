"""Tests for database.py query functions.

Written before implementation (TDD). Requires data/seafood.db to be built first
via: uv run python -m scripts.build_database
"""

from database import get_gear_score, get_noaa_status, get_seed_alternatives, get_species


def test_salmon_lookup() -> None:
    result = get_species("Atlantic salmon")
    assert result is not None
    assert result["vulnerability"] is not None
    assert result["resilience"] in ("Very Low", "Low", "Medium", "High")


def test_species_has_exploitation_field() -> None:
    """stock_exploitation field exists (may be None for some species)."""
    result = get_species("Atlantic salmon")
    assert result is not None
    assert "stock_exploitation" in result


def test_pollock_noaa() -> None:
    result = get_noaa_status("Alaska pollock")
    assert result is not None
    rate = (result["fishing_rate"] or "").lower()
    assert "not" in rate or rate == "unknown"


def test_gear_bottom_trawl() -> None:
    result = get_gear_score("Bottom trawl")
    assert result is not None
    assert result["impact_score"] <= 10


def test_gear_pole_line() -> None:
    result = get_gear_score("Pole and line")
    assert result is not None
    assert result["impact_score"] >= 90


def test_seed_alternatives() -> None:
    alts = get_seed_alternatives("Bluefin tuna")
    assert len(alts) >= 1


def test_common_name_alias() -> None:
    """'sockeye salmon' and 'Atlantic salmon' should both resolve."""
    for name in ("sockeye salmon", "Atlantic salmon", "Atlantic mackerel"):
        result = get_species(name)
        assert result is not None, f"Species not found: {name}"
