"""Wolfram Alpha carbon footprint queries."""

import json
import logging
import os
from functools import lru_cache
from typing import Any

import httpx

from gemini_client import get_genai_client, strip_json_fences
from models import CarbonFootprint

log = logging.getLogger(__name__)

_WOLFRAM_URL = "https://api.wolframalpha.com/v2/query"
_TIMEOUT = 5.0  # seconds
_BEEF_CO2_PER_SERVING = 6.6  # kg CO₂e per 113g serving (reference point)


@lru_cache(maxsize=256)
def get_carbon_footprint(species: str) -> CarbonFootprint | None:
    """Query Wolfram Alpha for CO2 footprint of a seafood species.

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


def _query_wolfram(query: str, app_id: str) -> list[dict[str, Any]]:
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
    pods: list[dict[str, Any]] = qr.get("pods", [])
    return pods


def _parse_carbon(pods: list[dict[str, Any]], species: str) -> CarbonFootprint | None:
    """Extract CO2 kg per serving from WA pod text using Gemini."""
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
    prompt = f"""Extract the carbon footprint (CO2 equivalent) for {species} from this
Wolfram Alpha data. Convert to kg CO2e per 113g (4oz) serving.

Data:
{pod_text}

Return ONLY a JSON object:
{{"co2_kg_per_serving": <float or null>}}

If the data doesn't contain carbon/CO2/greenhouse gas information, return null.
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
            comparison_text=f"Beef produces ~{_BEEF_CO2_PER_SERVING} kg CO2 per serving",
        )
    except Exception as e:
        log.warning("_parse_carbon failed for %s: %s", species, e)
        return None
