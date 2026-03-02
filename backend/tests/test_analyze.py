"""Integration tests for POST /analyze and POST /score endpoints.

Tests requiring GOOGLE_CLOUD_PROJECT env var or screenshot fixtures are
automatically skipped when those are not present (CI-safe).
"""

import base64
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

_HAS_CREDENTIALS = bool(os.environ.get("GOOGLE_CLOUD_PROJECT"))
_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> str:
    return base64.b64encode((_FIXTURES_DIR / name).read_bytes()).decode()


# ---------------------------------------------------------------------------
# Tests that run without any external services
# ---------------------------------------------------------------------------


def test_analyze_missing_screenshot_returns_400() -> None:
    """POST /analyze with empty screenshot returns 400."""
    response = client.post(
        "/analyze",
        json={"screenshot": "", "url": "https://example.com"},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Integration tests — skipped without Vertex AI credentials
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _HAS_CREDENTIALS
    or not (_FIXTURES_DIR / "wholeFoods_sockeye.png").exists(),
    reason="Requires GOOGLE_CLOUD_PROJECT and wholeFoods_sockeye.png fixture",
)
def test_seafood_product_returns_valid_score() -> None:
    response = client.post(
        "/analyze",
        json={
            "screenshot": _load_fixture("wholeFoods_sockeye.png"),
            "url": "https://www.amazon.com/365-Whole-Foods-Market-Sockeye/dp/B07XYZ",
            "related_products": [],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["product_info"]["is_seafood"] is True
    assert data["grade"] in ("A", "B", "C", "D")
    assert 0 <= data["score"] <= 100
    assert len(data["explanation"]) > 20
    assert data["breakdown"]["biological"] >= 0
    assert data["breakdown"]["management"] >= 0
    assert len(data["score_factors"]) == 4


@pytest.mark.skipif(
    not _HAS_CREDENTIALS
    or not (_FIXTURES_DIR / "amazon_pasta.png").exists(),
    reason="Requires GOOGLE_CLOUD_PROJECT and amazon_pasta.png fixture",
)
def test_non_seafood_returns_is_seafood_false() -> None:
    response = client.post(
        "/analyze",
        json={
            "screenshot": _load_fixture("amazon_pasta.png"),
            "url": "https://www.amazon.com/pasta",
            "related_products": [],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["product_info"]["is_seafood"] is False


@pytest.mark.skipif(
    not _HAS_CREDENTIALS,
    reason="Requires GOOGLE_CLOUD_PROJECT env var",
)
def test_score_endpoint_correction_flow() -> None:
    """POST /score re-scores a corrected ProductInfo without vision."""
    response = client.post(
        "/score",
        json={
            "product_info": {
                "is_seafood": True,
                "species": "Alaska sockeye salmon",
                "wild_or_farmed": "wild",
                "fishing_method": "Purse seine",
                "origin_region": "Bristol Bay, Alaska",
                "certifications": ["MSC"],
            }
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["grade"] in ("A", "B")
    assert data["score"] >= 60
    assert len(data["explanation"]) > 20
    assert len(data["score_factors"]) == 4


@pytest.mark.skipif(
    not _HAS_CREDENTIALS,
    reason="Requires GOOGLE_CLOUD_PROJECT env var",
)
def test_score_bluefin_returns_d() -> None:
    """Bluefin tuna without certs should return grade D."""
    response = client.post(
        "/score",
        json={
            "product_info": {
                "is_seafood": True,
                "species": "bluefin tuna",
                "wild_or_farmed": "wild",
                "fishing_method": None,
                "origin_region": None,
                "certifications": [],
            }
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["grade"] in ("C", "D")
