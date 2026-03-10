"""Wolfram Alpha food miles (distance) queries."""

import logging
import os
import re
from typing import Any

import httpx

from models import FoodMiles, UserLocation

log = logging.getLogger(__name__)

_WOLFRAM_URL = "https://api.wolframalpha.com/v2/query"
_TIMEOUT = 5.0  # seconds

_MILES_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*miles", re.IGNORECASE)
_KM_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*(?:km|kilometers|kilometres)", re.IGNORECASE)


def get_food_miles(origin_region: str, user_location: UserLocation) -> FoodMiles | None:
    """Query Wolfram Alpha for distance between origin and user location.

    Returns None if WOLFRAM_APP_ID is unset, origin is empty, or WA has no data.
    """
    app_id = os.environ.get("WOLFRAM_APP_ID")
    if not app_id or not origin_region:
        return None

    destination = f"{user_location.city}, {user_location.country}"
    query = f"distance from {origin_region} to {destination}"

    try:
        pods = _query_wolfram(query, app_id)
        if not pods:
            return None

        miles = _parse_distance(pods)
        if miles is None or miles <= 0:
            return None

        return FoodMiles(
            distance_miles=miles,
            origin=origin_region,
            destination=f"{user_location.city}, {user_location.region}",
        )
    except Exception as e:
        log.warning("get_food_miles(%s) failed: %s", origin_region, e)
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


def _parse_distance(pods: list[dict[str, Any]]) -> int | None:
    """Extract distance in miles from Wolfram Alpha pods.

    Looks for "Result" pod first, then any pod with miles/km.
    """
    # Collect all pod text, prioritising "Result" pod
    result_texts: list[str] = []
    other_texts: list[str] = []
    for pod in pods:
        for subpod in pod.get("subpods", []):
            txt = subpod.get("plaintext", "")
            if txt:
                if pod.get("title", "").lower() == "result":
                    result_texts.append(txt)
                else:
                    other_texts.append(txt)

    # Search Result pod first, then others
    for txt in result_texts + other_texts:
        m = _MILES_RE.search(txt)
        if m:
            return int(float(m.group(1).replace(",", "")))
        m = _KM_RE.search(txt)
        if m:
            km = float(m.group(1).replace(",", ""))
            return int(km * 0.621371)

    return None
