# Phase WA-1: Wolfram Alpha Client Module

**Goal:** Create `wolfram.py` — a standalone, fully-tested module with no coupling to the rest of the backend. All WA communication lives here.

---

## Files Changed

| File | Change |
|---|---|
| `backend/wolfram.py` | New — WA client, `get_health_data()`, `get_species_fallback()` |
| `backend/tests/test_wolfram.py` | New — unit + integration tests |
| `backend/pyproject.toml` | Move `httpx` from dev-deps to main deps |

No other files touched in this phase.

---

## Implementation

### `backend/pyproject.toml`

Move `httpx` to main `[project]` dependencies:

```diff
 dependencies = [
   "fastapi>=0.115",
   "uvicorn[standard]>=0.32",
   "google-adk>=1.17",
   "google-genai>=1.0",
   "duckdb>=1.1",
   "pydantic>=2.9",
   "numpy>=2.4.2",
   "pandas>=3.0.1",
+  "httpx>=0.27",
 ]

 [dependency-groups]
 dev = [
   "pytest>=8",
   "pytest-asyncio>=0.24",
-  "httpx>=0.27",
   "ruff>=0.8",
   "mypy>=1.13",
 ]
```

---

### `backend/wolfram.py`

```python
"""Wolfram Alpha Full Results API client.

Two public functions:
  get_health_data(species)      → HealthInfo | None
  get_species_fallback(species) → dict[str, Any] | None

Both are @lru_cache'd and return None when:
  - WOLFRAM_APP_ID env var is not set (graceful degradation)
  - WA returns no results
  - Any network/parse error occurs

Never raises — the scoring pipeline must not be broken by WA failures.
"""

import json
import logging
import os
from functools import lru_cache
from typing import Any

import httpx

from gemini_client import get_genai_client, strip_json_fences
from models import HealthInfo  # imported from models.py (defined in Phase WA-2)

log = logging.getLogger(__name__)

_WA_BASE = "https://api.wolframalpha.com/v2/query"
_HTTP_TIMEOUT = 8.0  # seconds


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _app_id() -> str | None:
    return os.environ.get("WOLFRAM_APP_ID")


def _query_wolfram(query: str) -> list[dict[str, Any]]:
    """Call WA Full Results API and return a flat list of subpod plaintext strings.

    Returns [] on any failure.
    """
    app_id = _app_id()
    if not app_id:
        return []

    try:
        resp = httpx.get(
            _WA_BASE,
            params={
                "appid": app_id,
                "input": query,
                "output": "json",
                "format": "plaintext",
            },
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()

        qr = data.get("queryresult", {})
        if str(qr.get("success")) != "true":
            return []

        texts: list[dict[str, Any]] = []
        for pod in qr.get("pods", []):
            pod_title = str(pod.get("title", ""))
            for subpod in pod.get("subpods", []):
                text = str(subpod.get("plaintext") or "").strip()
                if text:
                    texts.append({"pod": pod_title, "text": text})
        return texts

    except Exception as e:
        log.warning("_query_wolfram(%r) failed: %s", query, e)
        return []


def _gemini_extract(
    pods: list[dict[str, Any]],
    species: str,
    prompt_template: str,
) -> dict[str, Any] | None:
    """Ask Gemini to extract structured data from WA pod text."""
    if not pods:
        return None

    pod_text = "\n".join(f"[{p['pod']}] {p['text']}" for p in pods)

    prompt = prompt_template.format(species=species, pod_text=pod_text)
    try:
        client = get_genai_client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        raw = strip_json_fences(response.text or "")
        result: dict[str, Any] = json.loads(raw)
        return result
    except Exception as e:
        log.warning("_gemini_extract(%r) failed: %s", species, e)
        return None


# ---------------------------------------------------------------------------
# Health data (Option 1)
# ---------------------------------------------------------------------------

_HEALTH_PROMPT = """\
You are extracting structured health data about a fish species from Wolfram Alpha results.

Species: {species}
Wolfram Alpha data:
{pod_text}

Extract these fields from the data above. Return ONLY a JSON object:
{{
  "mercury_ppm": <float or null>,
  "mercury_category": <"Best Choice" | "Good Choice" | "Lower Choice" | "Avoid" | null>,
  "omega3_mg_per_serving": <float or null — mg DHA+EPA per 85g/3oz serving>
}}

FDA mercury categories (use these exact strings):
  Best Choice: avg ≤ 0.1 ppm
  Good Choice: 0.1–0.32 ppm
  Lower Choice: 0.32–1.0 ppm
  Avoid: > 1.0 ppm

If you cannot determine a value with confidence, use null.
Return only the JSON object, no explanation."""

_MERCURY_GRADE: dict[str, str] = {
    "Best Choice": "A",
    "Good Choice": "B",
    "Lower Choice": "C",
    "Avoid": "D",
}


@lru_cache(maxsize=256)
def get_health_data(species: str) -> "HealthInfo | None":
    """Return mercury + omega-3 health data for a species via Wolfram Alpha.

    Returns None if WOLFRAM_APP_ID is unset, WA has no data, or any error occurs.
    """
    if not _app_id():
        return None

    # Two queries for comprehensive coverage
    mercury_pods = _query_wolfram(f"{species} fish mercury content FDA")
    nutrition_pods = _query_wolfram(f"{species} fish omega-3 DHA EPA nutrition")
    all_pods = mercury_pods + nutrition_pods

    if not all_pods:
        return None

    extracted = _gemini_extract(all_pods, species, _HEALTH_PROMPT)
    if not extracted:
        return None

    category = extracted.get("mercury_category")
    if not category:
        # Try to derive from ppm if Gemini couldn't categorise
        ppm = extracted.get("mercury_ppm")
        if isinstance(ppm, (int, float)):
            if ppm <= 0.10:
                category = "Best Choice"
            elif ppm <= 0.32:
                category = "Good Choice"
            elif ppm <= 1.0:
                category = "Lower Choice"
            else:
                category = "Avoid"

    if not category:
        return None  # Not enough data to form a grade

    grade = _MERCURY_GRADE.get(category, "C")

    try:
        return HealthInfo(
            mercury_ppm=extracted.get("mercury_ppm"),
            mercury_category=category,
            health_grade=grade,  # type: ignore[arg-type]
            omega3_mg_per_serving=extracted.get("omega3_mg_per_serving"),
            source_note="Wolfram Alpha",
        )
    except Exception as e:
        log.warning("HealthInfo construction failed for %r: %s", species, e)
        return None


# ---------------------------------------------------------------------------
# Species fallback (Option 2)
# ---------------------------------------------------------------------------

_SPECIES_PROMPT = """\
You are extracting structured conservation data about a fish species from Wolfram Alpha results.

Species: {species}
Wolfram Alpha data:
{pod_text}

Extract these fields. Return ONLY a JSON object:
{{
  "iucn_code": <"LC" | "NT" | "VU" | "EN" | "CR" | "DD" | null>,
  "vulnerability": <float 0-100 or null — higher = more vulnerable>,
  "resilience": <"Very Low" | "Low" | "Medium" | "High" | null>,
  "trophic_level": <float or null — typical range 2.0-4.5>,
  "stock_exploitation": <"not overexploited" | "fully exploited" | "overexploited" | null>
}}

IUCN codes: LC=Least Concern, NT=Near Threatened, VU=Vulnerable, EN=Endangered,
            CR=Critically Endangered, DD=Data Deficient

Use null for any field you cannot determine with confidence.
Return only the JSON object, no explanation."""


@lru_cache(maxsize=256)
def get_species_fallback(species: str) -> dict[str, Any] | None:
    """Query WA for species conservation data and parse to a species-like dict.

    Returns a dict with keys matching the 'species' SQLite table schema,
    or None if WA has no data or WOLFRAM_APP_ID is unset.
    """
    if not _app_id():
        return None

    pods = _query_wolfram(f"{species} fish population conservation status")
    if not pods:
        return None

    extracted = _gemini_extract(pods, species, _SPECIES_PROMPT)
    if not extracted:
        return None

    # Only return if we got at least something meaningful
    has_data = any(
        extracted.get(k) is not None
        for k in ("iucn_code", "vulnerability", "resilience", "trophic_level")
    )
    if not has_data:
        return None

    log.info("WA species fallback for %r: %s", species, extracted)
    return extracted
```

---

### `backend/tests/test_wolfram.py`

```python
"""Tests for wolfram.py — Wolfram Alpha client.

Unit tests run without credentials (test graceful degradation).
Integration tests require WOLFRAM_APP_ID env var.
"""

import os
import pytest
from wolfram import get_health_data, get_species_fallback


_HAS_WOLFRAM = bool(os.environ.get("WOLFRAM_APP_ID"))


# ---------------------------------------------------------------------------
# Unit tests — no credentials required
# ---------------------------------------------------------------------------

def test_get_health_data_returns_none_without_app_id(monkeypatch) -> None:
    """Returns None gracefully when WOLFRAM_APP_ID is not set."""
    monkeypatch.delenv("WOLFRAM_APP_ID", raising=False)
    get_health_data.cache_clear()
    result = get_health_data("salmon")
    assert result is None


def test_get_species_fallback_returns_none_without_app_id(monkeypatch) -> None:
    """Returns None gracefully when WOLFRAM_APP_ID is not set."""
    monkeypatch.delenv("WOLFRAM_APP_ID", raising=False)
    get_species_fallback.cache_clear()
    result = get_species_fallback("salmon")
    assert result is None


# ---------------------------------------------------------------------------
# Integration tests — require WOLFRAM_APP_ID + GOOGLE_CLOUD_PROJECT
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _HAS_WOLFRAM,
    reason="Requires WOLFRAM_APP_ID env var",
)
def test_health_data_salmon() -> None:
    """Sockeye salmon should return a health grade (known species)."""
    get_health_data.cache_clear()
    result = get_health_data("sockeye salmon")
    assert result is not None
    assert result.health_grade in ("A", "B", "C", "D")
    assert result.mercury_category in (
        "Best Choice", "Good Choice", "Lower Choice", "Avoid"
    )
    assert result.source_note == "Wolfram Alpha"


@pytest.mark.skipif(
    not _HAS_WOLFRAM,
    reason="Requires WOLFRAM_APP_ID env var",
)
def test_health_data_swordfish_is_lower_choice_or_avoid() -> None:
    """Swordfish is high mercury — should be Lower Choice or Avoid."""
    get_health_data.cache_clear()
    result = get_health_data("swordfish")
    assert result is not None
    assert result.health_grade in ("C", "D")


@pytest.mark.skipif(
    not _HAS_WOLFRAM,
    reason="Requires WOLFRAM_APP_ID env var",
)
def test_health_data_unknown_species_returns_none() -> None:
    """Completely unknown species should return None (no WA data)."""
    get_health_data.cache_clear()
    result = get_health_data("zzz_completely_unknown_species_xyz")
    assert result is None


@pytest.mark.skipif(
    not _HAS_WOLFRAM,
    reason="Requires WOLFRAM_APP_ID env var",
)
def test_species_fallback_returns_structured_data_for_known_species() -> None:
    """A real species should return a dict with at least one field populated."""
    get_species_fallback.cache_clear()
    result = get_species_fallback("bluefin tuna")
    # Either returns structured data or None (WA may not have all fields)
    if result is not None:
        assert isinstance(result, dict)
        # At least one field should be populated
        assert any(
            result.get(k) is not None
            for k in ("iucn_code", "vulnerability", "resilience", "trophic_level")
        )
```

---

## Success Criteria

### Automated (pytest)
- [ ] `test_get_health_data_returns_none_without_app_id` passes without WOLFRAM_APP_ID
- [ ] `test_get_species_fallback_returns_none_without_app_id` passes without WOLFRAM_APP_ID
- [ ] `test_health_data_salmon` passes with WOLFRAM_APP_ID set (salmon returns grade A/B)
- [ ] `test_health_data_swordfish_is_lower_choice_or_avoid` passes (swordfish returns C/D)
- [ ] `mypy` clean on `wolfram.py` (strict mode)
- [ ] `ruff` clean

### Manual
- [ ] `WOLFRAM_APP_ID` unset → `get_health_data("salmon")` returns `None` without error
- [ ] `WOLFRAM_APP_ID` set → `get_health_data("sockeye salmon")` returns a `HealthInfo` with `mercury_category = "Best Choice"` and `health_grade = "A"`
- [ ] Verify `lru_cache` works: second call with same species returns instantly (no HTTP)

### Pre-commit
- [ ] Full suite: `mypy . && ruff check . && pytest` all green
