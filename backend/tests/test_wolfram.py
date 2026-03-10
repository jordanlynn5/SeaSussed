"""Tests for wolfram.py carbon footprint queries."""
from unittest.mock import MagicMock, patch

from models import CarbonFootprint

# ── Test 1: Graceful degradation when no API key ──

def test_no_api_key_returns_none() -> None:
    """get_carbon_footprint returns None when WOLFRAM_APP_ID is unset."""
    from wolfram import get_carbon_footprint
    get_carbon_footprint.cache_clear()
    with patch.dict("os.environ", {}, clear=True):
        assert get_carbon_footprint("salmon") is None


# ── Test 2: None species ──

def test_none_species() -> None:
    from wolfram import get_carbon_footprint
    get_carbon_footprint.cache_clear()
    assert get_carbon_footprint("") is None


# ── Test 3: Successful parse ──

@patch("wolfram._query_wolfram")
@patch("wolfram.get_genai_client")
def test_successful_carbon_lookup(mock_client: MagicMock, mock_wa: MagicMock) -> None:
    """Full flow: WA returns pods -> Gemini parses -> CarbonFootprint returned."""
    from wolfram import get_carbon_footprint
    get_carbon_footprint.cache_clear()

    mock_wa.return_value = [
        {"title": "Result", "subpods": [{"plaintext": "salmon: 3.2 kg CO2e per kg"}]}
    ]
    # Gemini returns parsed JSON
    mock_response = MagicMock()
    mock_response.text = '{"co2_kg_per_serving": 0.36}'
    mock_client.return_value.models.generate_content.return_value = mock_response

    with patch.dict("os.environ", {"WOLFRAM_APP_ID": "test-key"}):
        result = get_carbon_footprint("salmon")

    assert result is not None
    assert isinstance(result, CarbonFootprint)
    assert result.co2_kg_per_serving == 0.36
    assert "beef" in result.comparison_text.lower()


# ── Test 4: WA returns no data ──

@patch("wolfram._query_wolfram")
def test_wa_no_data(mock_wa: MagicMock) -> None:
    from wolfram import get_carbon_footprint
    get_carbon_footprint.cache_clear()

    mock_wa.return_value = []
    with patch.dict("os.environ", {"WOLFRAM_APP_ID": "test-key"}):
        assert get_carbon_footprint("unknown deep sea fish") is None


# ── Test 5: Gemini parse failure ──

@patch("wolfram._query_wolfram")
@patch("wolfram.get_genai_client")
def test_gemini_parse_failure(mock_client: MagicMock, mock_wa: MagicMock) -> None:
    from wolfram import get_carbon_footprint
    get_carbon_footprint.cache_clear()

    mock_wa.return_value = [
        {"title": "Result", "subpods": [{"plaintext": "some text"}]}
    ]
    mock_response = MagicMock()
    mock_response.text = '{"co2_kg_per_serving": null}'
    mock_client.return_value.models.generate_content.return_value = mock_response

    with patch.dict("os.environ", {"WOLFRAM_APP_ID": "test-key"}):
        assert get_carbon_footprint("salmon") is None
