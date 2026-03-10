from fastapi.testclient import TestClient

from health import get_health_info
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


# --- Health lookup module tests ---


def test_known_species_salmon() -> None:
    h = get_health_info("sockeye salmon")
    assert h is not None
    assert h.mercury_category == "Best Choice"
    assert h.health_grade == "A"
    assert "omega-3" in h.omega3_note.lower()


def test_known_species_swordfish() -> None:
    h = get_health_info("swordfish")
    assert h is not None
    assert h.mercury_category == "Choices to Avoid"
    assert h.health_grade == "D"


def test_partial_match() -> None:
    """'wild alaska sockeye salmon' should match 'sockeye salmon'."""
    h = get_health_info("wild Alaska sockeye salmon")
    assert h is not None
    assert h.mercury_category == "Best Choice"


def test_unknown_species() -> None:
    assert get_health_info("unicorn fish from mars") is None


def test_none_species() -> None:
    assert get_health_info(None) is None


def test_case_insensitive() -> None:
    h = get_health_info("ATLANTIC COD")
    assert h is not None
    assert h.mercury_category == "Best Choice"


def test_serving_advice_present() -> None:
    h = get_health_info("shrimp")
    assert h is not None
    assert "FDA" in h.serving_advice


def test_good_choice_grade() -> None:
    h = get_health_info("halibut")
    assert h is not None
    assert h.health_grade == "B"
