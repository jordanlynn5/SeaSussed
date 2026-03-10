# Phase 1: Health Lookup Module [batch-eligible]

**Files created:** `backend/health.py`, `backend/tests/test_health.py`
**Files modified:** `backend/models.py`

---

## Goal

Static mercury/omega-3 lookup by species name. Zero API calls, instant results.
Based on FDA/EPA mercury advisory data.

---

## 1. Model (`backend/models.py`)

Add `HealthInfo` class:

```python
class HealthInfo(BaseModel):
    mercury_category: str             # "Best Choice" | "Good Choice" | "Choices to Avoid"
    mercury_ppm: float | None         # avg ppm, None if tier-only
    omega3_note: str                  # "Rich in omega-3s" | "Moderate omega-3s" | ""
    serving_advice: str               # "FDA recommends 2-3 servings/week"
    health_grade: Literal["A","B","C","D"]
```

Add to `SustainabilityScore`:
```python
health: HealthInfo | None = None
```

---

## 2. Health Module (`backend/health.py`)

```python
"""Static mercury + omega-3 lookup from FDA/EPA data."""

# FDA mercury tiers mapped to species common names (lowercase).
# Source: https://www.fda.gov/food/consumers/advice-about-eating-fish
#
# "Best Choices" (≤0.15 ppm):  salmon, sardines, tilapia, shrimp, pollock,
#   catfish, cod, crab, crawfish, anchovies, herring, squid, trout, etc.
# "Good Choices" (0.15-0.46 ppm): tuna (albacore/white), halibut, snapper,
#   grouper, mahi-mahi, monkfish, etc.
# "Choices to Avoid" (>0.46 ppm): shark, swordfish, king mackerel,
#   tilefish (Gulf), bigeye tuna, marlin, orange roughy

MERCURY_DATA: dict[str, dict] = {
    # key = lowercase species keyword
    # value = { ppm, category, omega3 }
    #   omega3: "high" | "moderate" | "low"
    "salmon":       {"ppm": 0.022, "category": "Best Choice",      "omega3": "high"},
    "sockeye salmon": {"ppm": 0.022, "category": "Best Choice",    "omega3": "high"},
    "atlantic salmon": {"ppm": 0.022, "category": "Best Choice",   "omega3": "high"},
    "pink salmon":  {"ppm": 0.016, "category": "Best Choice",      "omega3": "high"},
    "king salmon":  {"ppm": 0.030, "category": "Best Choice",      "omega3": "high"},
    "chinook salmon": {"ppm": 0.030, "category": "Best Choice",    "omega3": "high"},
    "coho salmon":  {"ppm": 0.024, "category": "Best Choice",      "omega3": "high"},
    "chum salmon":  {"ppm": 0.024, "category": "Best Choice",      "omega3": "moderate"},
    "sardine":      {"ppm": 0.013, "category": "Best Choice",      "omega3": "high"},
    "sardines":     {"ppm": 0.013, "category": "Best Choice",      "omega3": "high"},
    "anchovy":      {"ppm": 0.016, "category": "Best Choice",      "omega3": "high"},
    "anchovies":    {"ppm": 0.016, "category": "Best Choice",      "omega3": "high"},
    "herring":      {"ppm": 0.078, "category": "Best Choice",      "omega3": "high"},
    "mackerel":     {"ppm": 0.050, "category": "Best Choice",      "omega3": "high"},
    "atlantic mackerel": {"ppm": 0.050, "category": "Best Choice",  "omega3": "high"},
    "king mackerel": {"ppm": 0.730, "category": "Choices to Avoid", "omega3": "high"},
    "tilapia":      {"ppm": 0.013, "category": "Best Choice",      "omega3": "low"},
    "shrimp":       {"ppm": 0.009, "category": "Best Choice",      "omega3": "low"},
    "pollock":      {"ppm": 0.031, "category": "Best Choice",      "omega3": "moderate"},
    "alaska pollock": {"ppm": 0.031, "category": "Best Choice",    "omega3": "moderate"},
    "cod":          {"ppm": 0.111, "category": "Best Choice",      "omega3": "moderate"},
    "atlantic cod": {"ppm": 0.111, "category": "Best Choice",      "omega3": "moderate"},
    "pacific cod":  {"ppm": 0.111, "category": "Best Choice",      "omega3": "moderate"},
    "catfish":      {"ppm": 0.024, "category": "Best Choice",      "omega3": "low"},
    "crab":         {"ppm": 0.065, "category": "Best Choice",      "omega3": "moderate"},
    "crawfish":     {"ppm": 0.033, "category": "Best Choice",      "omega3": "low"},
    "squid":        {"ppm": 0.024, "category": "Best Choice",      "omega3": "moderate"},
    "calamari":     {"ppm": 0.024, "category": "Best Choice",      "omega3": "moderate"},
    "trout":        {"ppm": 0.071, "category": "Best Choice",      "omega3": "high"},
    "rainbow trout": {"ppm": 0.071, "category": "Best Choice",     "omega3": "high"},
    "clam":         {"ppm": 0.009, "category": "Best Choice",      "omega3": "moderate"},
    "clams":        {"ppm": 0.009, "category": "Best Choice",      "omega3": "moderate"},
    "oyster":       {"ppm": 0.012, "category": "Best Choice",      "omega3": "high"},
    "oysters":      {"ppm": 0.012, "category": "Best Choice",      "omega3": "high"},
    "mussel":       {"ppm": 0.009, "category": "Best Choice",      "omega3": "moderate"},
    "mussels":      {"ppm": 0.009, "category": "Best Choice",      "omega3": "moderate"},
    "scallop":      {"ppm": 0.003, "category": "Best Choice",      "omega3": "moderate"},
    "scallops":     {"ppm": 0.003, "category": "Best Choice",      "omega3": "moderate"},
    "lobster":      {"ppm": 0.107, "category": "Good Choice",      "omega3": "moderate"},
    "tuna":         {"ppm": 0.144, "category": "Good Choice",      "omega3": "high"},
    "skipjack tuna": {"ppm": 0.144, "category": "Best Choice",     "omega3": "high"},
    "albacore tuna": {"ppm": 0.350, "category": "Good Choice",     "omega3": "high"},
    "yellowfin tuna": {"ppm": 0.354, "category": "Good Choice",    "omega3": "high"},
    "ahi tuna":     {"ppm": 0.354, "category": "Good Choice",      "omega3": "high"},
    "bigeye tuna":  {"ppm": 0.689, "category": "Choices to Avoid", "omega3": "high"},
    "bluefin tuna": {"ppm": 0.689, "category": "Choices to Avoid", "omega3": "high"},
    "halibut":      {"ppm": 0.241, "category": "Good Choice",      "omega3": "moderate"},
    "pacific halibut": {"ppm": 0.241, "category": "Good Choice",   "omega3": "moderate"},
    "snapper":      {"ppm": 0.166, "category": "Good Choice",      "omega3": "moderate"},
    "red snapper":  {"ppm": 0.166, "category": "Good Choice",      "omega3": "moderate"},
    "grouper":      {"ppm": 0.448, "category": "Good Choice",      "omega3": "moderate"},
    "mahi-mahi":    {"ppm": 0.178, "category": "Good Choice",      "omega3": "moderate"},
    "mahi mahi":    {"ppm": 0.178, "category": "Good Choice",      "omega3": "moderate"},
    "monkfish":     {"ppm": 0.181, "category": "Good Choice",      "omega3": "low"},
    "sea bass":     {"ppm": 0.152, "category": "Good Choice",      "omega3": "moderate"},
    "chilean sea bass": {"ppm": 0.354, "category": "Good Choice",  "omega3": "high"},
    "swordfish":    {"ppm": 0.995, "category": "Choices to Avoid", "omega3": "high"},
    "shark":        {"ppm": 0.979, "category": "Choices to Avoid", "omega3": "moderate"},
    "tilefish":     {"ppm": 1.450, "category": "Choices to Avoid", "omega3": "moderate"},
    "marlin":       {"ppm": 0.485, "category": "Choices to Avoid", "omega3": "moderate"},
    "orange roughy": {"ppm": 0.571, "category": "Choices to Avoid","omega3": "low"},
    "pangasius":    {"ppm": 0.015, "category": "Best Choice",      "omega3": "low"},
    "basa":         {"ppm": 0.015, "category": "Best Choice",      "omega3": "low"},
    "swai":         {"ppm": 0.015, "category": "Best Choice",      "omega3": "low"},
    "haddock":      {"ppm": 0.055, "category": "Best Choice",      "omega3": "moderate"},
    "sole":         {"ppm": 0.035, "category": "Best Choice",      "omega3": "low"},
    "flounder":     {"ppm": 0.056, "category": "Best Choice",      "omega3": "low"},
    "perch":        {"ppm": 0.034, "category": "Best Choice",      "omega3": "low"},
    "whiting":      {"ppm": 0.051, "category": "Best Choice",      "omega3": "moderate"},
    "branzino":     {"ppm": 0.152, "category": "Good Choice",      "omega3": "moderate"},
}

_CATEGORY_GRADE: dict[str, str] = {
    "Best Choice": "A",
    "Good Choice": "B",
    "Choices to Avoid": "D",
}

_OMEGA3_NOTE: dict[str, str] = {
    "high": "Rich in omega-3 fatty acids",
    "moderate": "Moderate omega-3 content",
    "low": "Low omega-3 content",
}

_SERVING_ADVICE: dict[str, str] = {
    "Best Choice": "FDA recommends 2-3 servings/week",
    "Good Choice": "FDA recommends 1 serving/week",
    "Choices to Avoid": "FDA advises avoiding this fish",
}


def get_health_info(species: str | None) -> HealthInfo | None:
    """Lookup mercury + omega-3 data for a species. Returns None if unknown."""
    if not species:
        return None
    key = species.lower().strip()
    # Try exact match first, then try matching each word combination
    data = MERCURY_DATA.get(key)
    if data is None:
        # Try progressively shorter substrings from the end
        # "wild alaska sockeye salmon" → "sockeye salmon" → "salmon"
        words = key.split()
        for i in range(1, len(words)):
            sub = " ".join(words[i:])
            data = MERCURY_DATA.get(sub)
            if data:
                break
    if data is None:
        return None
    category = data["category"]
    return HealthInfo(
        mercury_category=category,
        mercury_ppm=data.get("ppm"),
        omega3_note=_OMEGA3_NOTE.get(data.get("omega3", ""), ""),
        serving_advice=_SERVING_ADVICE.get(category, ""),
        health_grade=_CATEGORY_GRADE.get(category, "B"),
    )
```

---

## 3. Tests (`backend/tests/test_health.py`)

```python
"""Tests for health.py mercury/omega-3 lookup."""
from health import get_health_info

def test_known_species_salmon():
    h = get_health_info("sockeye salmon")
    assert h is not None
    assert h.mercury_category == "Best Choice"
    assert h.health_grade == "A"
    assert "omega-3" in h.omega3_note.lower()

def test_known_species_swordfish():
    h = get_health_info("swordfish")
    assert h is not None
    assert h.mercury_category == "Choices to Avoid"
    assert h.health_grade == "D"

def test_partial_match():
    """'wild alaska sockeye salmon' should match 'sockeye salmon'."""
    h = get_health_info("wild Alaska sockeye salmon")
    assert h is not None
    assert h.mercury_category == "Best Choice"

def test_unknown_species():
    assert get_health_info("unicorn fish from mars") is None

def test_none_species():
    assert get_health_info(None) is None

def test_case_insensitive():
    h = get_health_info("ATLANTIC COD")
    assert h is not None
    assert h.mercury_category == "Best Choice"

def test_serving_advice_present():
    h = get_health_info("shrimp")
    assert h is not None
    assert "FDA" in h.serving_advice

def test_good_choice_grade():
    h = get_health_info("halibut")
    assert h is not None
    assert h.health_grade == "B"
```

---

## Success Criteria

### Automated
- `uv run pytest tests/test_health.py` — all pass
- `uv run mypy health.py` — no errors
- `uv run ruff check health.py` — clean

### Manual
- None required for this phase (no UI yet)
