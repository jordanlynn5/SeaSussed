from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "seasussed-backend"
    assert data["version"] == "0.1.0"


def test_analyze_stub_returns_501() -> None:
    """Verify /analyze stub is wired up correctly before Phase 4."""
    response = client.post(
        "/analyze",
        json={
            "screenshot": "dGVzdA==",  # base64 "test"
            "url": "https://example.com",
        },
    )
    assert response.status_code == 501


def test_score_stub_returns_501() -> None:
    """Verify /score stub is wired up correctly before Phase 4."""
    response = client.post(
        "/score",
        json={
            "product_info": {
                "is_seafood": True,
                "species": "Atlantic salmon",
                "wild_or_farmed": "wild",
                "fishing_method": None,
                "origin_region": None,
                "certifications": [],
            }
        },
    )
    assert response.status_code == 501
