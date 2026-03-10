# Phase 2: Wolfram Alpha Carbon Footprint Module [batch-eligible]

**Files created:** `backend/wolfram.py`, `backend/tests/test_wolfram.py`
**Files modified:** `backend/models.py`

---

## Goal

Query Wolfram Alpha for carbon footprint data per seafood species. Returns CO₂ per
serving with beef comparison. Graceful degradation when API key unset or no data.

---

## 1. Model (`backend/models.py`)

Add `CarbonFootprint` class:

```python
class CarbonFootprint(BaseModel):
    co2_kg_per_serving: float         # kg CO₂e per ~113g (4oz) serving
    comparison_text: str              # "Beef produces ~6.6 kg CO₂ per serving"
    source: str = "Wolfram Alpha"
```

Add to `SustainabilityScore`:
```python
carbon: CarbonFootprint | None = None
```

---

## 2. Wolfram Module (`backend/wolfram.py`)

```python
"""Wolfram Alpha carbon footprint queries."""

import json
import logging
import os
from functools import lru_cache

import httpx

from gemini_client import get_genai_client, strip_json_fences
from models import CarbonFootprint

log = logging.getLogger(__name__)

_WOLFRAM_URL = "https://api.wolframalpha.com/v2/query"
_TIMEOUT = 5.0  # seconds
_BEEF_CO2_PER_SERVING = 6.6  # kg CO₂e per 113g serving (reference point)


@lru_cache(maxsize=256)
def get_carbon_footprint(species: str) -> CarbonFootprint | None:
    """Query Wolfram Alpha for CO₂ footprint of a seafood species.

    Returns None if WOLFRAM_APP_ID is unset, WA has no data, or any error occurs.
    """
    app_id = os.environ.get("WOLFRAM_APP_ID")
    if not app_id or not species:
        return None

    try:
        pods = _query_wolfram(
            f"carbon footprint of {species} fish per kilogram",
            app_id,
        )
        if not pods:
            return None
        return _parse_carbon(pods, species)
    except Exception as e:
        log.warning("get_carbon_footprint(%s) failed: %s", species, e)
        return None


def _query_wolfram(query: str, app_id: str) -> list[dict]:
    """Send query to WA Full Results API, return list of pod dicts."""
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.get(
            _WOLFRAM_URL,
            params={
                "input": query,
                "appid": app_id,
                "output": "json",
                "format": "plaintext",
            },
        )
        resp.raise_for_status()
    data = resp.json()
    qr = data.get("queryresult", {})
    if not qr.get("success"):
        return []
    return qr.get("pods", [])


def _parse_carbon(pods: list[dict], species: str) -> CarbonFootprint | None:
    """Extract CO₂ kg per serving from WA pod text using Gemini."""
    # Collect all pod plaintext
    all_text = []
    for pod in pods:
        for subpod in pod.get("subpods", []):
            txt = subpod.get("plaintext", "")
            if txt:
                all_text.append(f"[{pod.get('title', '')}] {txt}")

    if not all_text:
        return None

    pod_text = "\n".join(all_text)
    prompt = f"""Extract the carbon footprint (CO₂ equivalent) for {species} from this
Wolfram Alpha data. Convert to kg CO₂e per 113g (4oz) serving.

Data:
{pod_text}

Return ONLY a JSON object:
{{"co2_kg_per_serving": <float or null>}}

If the data doesn't contain carbon/CO₂/greenhouse gas information, return null.
Return ONLY the JSON, no explanation."""

    try:
        client = get_genai_client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        raw = strip_json_fences(response.text or "")
        result = json.loads(raw)
        co2 = result.get("co2_kg_per_serving")
        if co2 is None or not isinstance(co2, (int, float)):
            return None
        co2_float = float(co2)
        if co2_float <= 0:
            return None
        return CarbonFootprint(
            co2_kg_per_serving=round(co2_float, 2),
            comparison_text=f"Beef produces ~{_BEEF_CO2_PER_SERVING} kg CO₂ per serving",
        )
    except Exception as e:
        log.warning("_parse_carbon failed for %s: %s", species, e)
        return None
```

---

## 3. Tests (`backend/tests/test_wolfram.py`)

```python
"""Tests for wolfram.py carbon footprint queries."""
from unittest.mock import MagicMock, patch

from models import CarbonFootprint


# ── Test 1: Graceful degradation when no API key ──

def test_no_api_key_returns_none():
    """get_carbon_footprint returns None when WOLFRAM_APP_ID is unset."""
    from wolfram import get_carbon_footprint
    get_carbon_footprint.cache_clear()
    with patch.dict("os.environ", {}, clear=True):
        assert get_carbon_footprint("salmon") is None


# ── Test 2: None species ──

def test_none_species():
    from wolfram import get_carbon_footprint
    get_carbon_footprint.cache_clear()
    assert get_carbon_footprint("") is None


# ── Test 3: Successful parse ──

@patch("wolfram._query_wolfram")
@patch("wolfram.get_genai_client")
def test_successful_carbon_lookup(mock_client, mock_wa):
    """Full flow: WA returns pods → Gemini parses → CarbonFootprint returned."""
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
def test_wa_no_data(mock_wa):
    from wolfram import get_carbon_footprint
    get_carbon_footprint.cache_clear()

    mock_wa.return_value = []
    with patch.dict("os.environ", {"WOLFRAM_APP_ID": "test-key"}):
        assert get_carbon_footprint("unknown deep sea fish") is None


# ── Test 5: Gemini parse failure ──

@patch("wolfram._query_wolfram")
@patch("wolfram.get_genai_client")
def test_gemini_parse_failure(mock_client, mock_wa):
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
```

---

## Dependencies

`httpx` is already in dev dependencies. Verify it's also in main dependencies:
```bash
# Check pyproject.toml — if httpx is only in dev, add to main deps:
uv add httpx
```

---

## Success Criteria

### Automated
- `uv run pytest tests/test_wolfram.py` — all pass
- `uv run mypy wolfram.py` — no errors
- `uv run ruff check wolfram.py` — clean

### Manual
- With `WOLFRAM_APP_ID` set, run in Python REPL:
  `from wolfram import get_carbon_footprint; print(get_carbon_footprint("salmon"))`
  Should return a `CarbonFootprint` object (or None if WA has no data for that query).
