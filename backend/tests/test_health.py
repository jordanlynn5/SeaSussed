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


def test_analyze_missing_screenshot_returns_400() -> None:
    """POST /analyze with empty screenshot returns 400."""
    response = client.post(
        "/analyze",
        json={
            "screenshot": "",
            "url": "https://example.com",
        },
    )
    assert response.status_code == 400
