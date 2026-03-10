"""Tests for geolocation.py IP lookup."""

from unittest.mock import MagicMock, patch

from models import UserLocation

# ── Test 1: Private IP returns None ──


def test_private_ip_returns_none() -> None:
    from geolocation import get_user_location

    get_user_location.cache_clear()
    assert get_user_location("127.0.0.1") is None
    assert get_user_location("10.0.0.1") is None
    assert get_user_location("192.168.1.1") is None


# ── Test 2: Empty IP returns None ──


def test_empty_ip_returns_none() -> None:
    from geolocation import get_user_location

    get_user_location.cache_clear()
    assert get_user_location("") is None


# ── Test 3: Successful geolocation ──


@patch("geolocation.httpx.Client")
def test_successful_geolocation(mock_client_cls: MagicMock) -> None:
    from geolocation import get_user_location

    get_user_location.cache_clear()

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "city": "Chicago",
        "regionName": "Illinois",
        "country": "United States",
        "lat": 41.85,
        "lon": -87.65,
    }
    mock_response.raise_for_status = MagicMock()
    mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
    mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_response
    mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

    result = get_user_location("8.8.8.8")

    assert result is not None
    assert isinstance(result, UserLocation)
    assert result.city == "Chicago"
    assert result.region == "Illinois"
    assert result.country == "United States"
    assert result.lat == 41.85
    assert result.lon == -87.65


# ── Test 4: API failure returns None ──


@patch("geolocation.httpx.Client")
def test_api_failure_returns_none(mock_client_cls: MagicMock) -> None:
    from geolocation import get_user_location

    get_user_location.cache_clear()

    mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
    mock_client_cls.return_value.__enter__.return_value.get.side_effect = Exception(
        "Connection error"
    )
    mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

    assert get_user_location("8.8.8.8") is None


# ── Test 5: Missing city returns None ──


@patch("geolocation.httpx.Client")
def test_missing_city_returns_none(mock_client_cls: MagicMock) -> None:
    from geolocation import get_user_location

    get_user_location.cache_clear()

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "city": "",
        "regionName": "Illinois",
        "country": "United States",
        "lat": 41.85,
        "lon": -87.65,
    }
    mock_response.raise_for_status = MagicMock()
    mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
    mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_response
    mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

    assert get_user_location("8.8.8.8") is None
