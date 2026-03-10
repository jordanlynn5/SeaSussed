"""Tests for wolfram.py food miles queries."""

from unittest.mock import MagicMock, patch

from models import FoodMiles, UserLocation

_USER = UserLocation(
    city="Chicago", region="Illinois", country="United States", lat=41.85, lon=-87.65
)


# ── Test 1: Graceful degradation when no API key ──


def test_no_api_key_returns_none() -> None:
    """get_food_miles returns None when WOLFRAM_APP_ID is unset."""
    from wolfram import get_food_miles

    with patch.dict("os.environ", {}, clear=True):
        assert get_food_miles("Norway", _USER) is None


# ── Test 2: Empty origin returns None ──


def test_empty_origin_returns_none() -> None:
    from wolfram import get_food_miles

    assert get_food_miles("", _USER) is None


# ── Test 3: Successful food miles lookup ──


@patch("wolfram._query_wolfram")
def test_successful_food_miles(mock_wa: MagicMock) -> None:
    """WA returns miles pod → FoodMiles returned."""
    from wolfram import get_food_miles

    mock_wa.return_value = [
        {"title": "Result", "subpods": [{"plaintext": "4213 miles"}]}
    ]

    with patch.dict("os.environ", {"WOLFRAM_APP_ID": "test-key"}):
        result = get_food_miles("Norway", _USER)

    assert result is not None
    assert isinstance(result, FoodMiles)
    assert result.distance_miles == 4213
    assert result.origin == "Norway"
    assert result.destination == "Chicago, Illinois"


# ── Test 4: Km conversion ──


@patch("wolfram._query_wolfram")
def test_wa_km_conversion(mock_wa: MagicMock) -> None:
    """WA returns km → converted to miles."""
    from wolfram import get_food_miles

    mock_wa.return_value = [
        {"title": "Result", "subpods": [{"plaintext": "6780 km"}]}
    ]

    with patch.dict("os.environ", {"WOLFRAM_APP_ID": "test-key"}):
        result = get_food_miles("Norway", _USER)

    assert result is not None
    assert result.distance_miles == int(6780 * 0.621371)


# ── Test 5: WA returns no data ──


@patch("wolfram._query_wolfram")
def test_wa_no_result(mock_wa: MagicMock) -> None:
    from wolfram import get_food_miles

    mock_wa.return_value = []

    with patch.dict("os.environ", {"WOLFRAM_APP_ID": "test-key"}):
        assert get_food_miles("Atlantis", _USER) is None


# ── Test 6: Zero distance returns None ──


@patch("wolfram._query_wolfram")
def test_zero_distance_returns_none(mock_wa: MagicMock) -> None:
    from wolfram import get_food_miles

    mock_wa.return_value = [
        {"title": "Result", "subpods": [{"plaintext": "0 miles"}]}
    ]

    with patch.dict("os.environ", {"WOLFRAM_APP_ID": "test-key"}):
        assert get_food_miles("Chicago", _USER) is None
