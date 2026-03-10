# Phase 2: Wolfram Food Miles Module

**Status:** pending
**Batch-eligible:** yes (no file overlap with Phase 1)

---

## Goal

Replace `get_carbon_footprint` and `_parse_carbon` in `wolfram.py` with `get_food_miles` and `_parse_distance`. Remove the Gemini parsing step entirely — distance results are simple enough for regex extraction.

---

## Modified Files

### `backend/wolfram.py`

**Remove:**
- `get_carbon_footprint(species)` function
- `_parse_carbon(pods, species)` function
- `from gemini_client import get_genai_client, strip_json_fences` import
- `from models import CarbonFootprint` import
- `_BEEF_CO2_PER_SERVING` constant

**Keep:**
- `_query_wolfram(query, app_id)` — unchanged, reused for distance queries
- `_WOLFRAM_URL`, `_TIMEOUT` constants

**Add:**

```python
from models import FoodMiles, UserLocation

@lru_cache(maxsize=256)
def get_food_miles(origin_region: str, user_location: UserLocation) -> FoodMiles | None:
    """Query Wolfram Alpha for distance between origin and user location.

    Returns None if WOLFRAM_APP_ID is unset, origin is empty, or WA has no data.
    """
    app_id = os.environ.get("WOLFRAM_APP_ID")
    if not app_id or not origin_region:
        return None

    destination = f"{user_location.city}, {user_location.country}"
    query = f"distance from {origin_region} to {destination}"

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

def _parse_distance(pods: list[dict]) -> int | None:
    """Extract distance in miles from Wolfram Alpha pods.

    Looks for "Result" pod first, then any pod with miles/km.
    Uses regex: r"([\d,]+)\s*miles" or converts from km.
    """
    # 1. Check "Result" pod for "NNNN miles"
    # 2. Fallback: check all pods for miles pattern
    # 3. Fallback: check for km pattern, convert to miles
    # Return int(miles) or None
```

**Cache note:** `UserLocation` is a Pydantic model — needs to be hashable for `@lru_cache`. Make it frozen (`model_config = ConfigDict(frozen=True)`) in models.py, or cache on `(origin_region, city, country)` tuple instead.

### `backend/models.py`

**Remove:**
- `CarbonFootprint` class

**Add:**
```python
class FoodMiles(BaseModel):
    distance_miles: int      # e.g., 4213
    origin: str              # e.g., "Norway"
    destination: str         # e.g., "Chicago, IL"
    source: str = "Wolfram Alpha"
```

**Modify `SustainabilityScore`:**
```python
class SustainabilityScore(BaseModel):
    ...
    health: HealthInfo | None = None
    food_miles: FoodMiles | None = None   # was: carbon: CarbonFootprint | None = None
```

### `backend/tests/test_wolfram.py`

**Rewrite all tests** for the new `get_food_miles` function:

1. `test_no_api_key_returns_none` — env var unset → None
2. `test_empty_origin_returns_none` — empty origin string → None
3. `test_successful_food_miles` — mock WA returning "4213 miles" → FoodMiles(distance_miles=4213, ...)
4. `test_wa_km_conversion` — mock WA returning "6780 km" → FoodMiles(distance_miles=4213, ...)
5. `test_wa_no_result` — mock WA returning empty pods → None
6. `test_zero_distance_returns_none` — mock WA returning "0 miles" → None

**No Gemini mocking needed** — the new function doesn't use Gemini.

---

## Success Criteria

### Automated
- `uv run pytest tests/test_wolfram.py` — all 6 tests pass
- `uv run mypy wolfram.py models.py` — no errors
- `uv run ruff check wolfram.py models.py` — clean

### Manual
- None (integration happens in Phase 3)
