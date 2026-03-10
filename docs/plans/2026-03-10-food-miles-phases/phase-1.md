# Phase 1: Geolocation Module

**Status:** pending
**Batch-eligible:** yes (no file overlap with Phase 2)

---

## Goal

Create `backend/geolocation.py` — a cached IP-to-location lookup using ip-api.com. Returns city + country for use in Wolfram distance queries.

---

## New Files

### `backend/geolocation.py`

```python
"""IP geolocation via ip-api.com (free, no API key)."""

_IP_API_URL = "http://ip-api.com/json/{ip}"
_TIMEOUT = 3.0
_FIELDS = "city,regionName,country,lat,lon"

class UserLocation:  # Pydantic model, defined in models.py
    city: str
    region: str
    country: str
    lat: float
    lon: float

@lru_cache(maxsize=256)
def get_user_location(ip: str) -> UserLocation | None:
    """Geolocate an IP address. Returns None on failure."""
    # Skip private/local IPs (127.x, 10.x, 192.168.x, etc.)
    if _is_private_ip(ip):
        return None

    # GET http://ip-api.com/json/{ip}?fields=city,regionName,country,lat,lon
    # Parse response → UserLocation
    # Return None if city is empty or request fails

def _is_private_ip(ip: str) -> bool:
    """Return True for loopback, private, or link-local IPs."""
    # Use ipaddress.ip_address(ip).is_private
```

### `backend/tests/test_geolocation.py`

Tests (all mock httpx, no real API calls):

1. `test_private_ip_returns_none` — `get_user_location("127.0.0.1")` → None
2. `test_empty_ip_returns_none` — `get_user_location("")` → None
3. `test_successful_geolocation` — mock ip-api.com response → UserLocation with correct fields
4. `test_api_failure_returns_none` — mock 500 response → None
5. `test_missing_city_returns_none` — mock response with empty city → None

---

## Models Addition

In `models.py`, add:

```python
class UserLocation(BaseModel):
    city: str
    region: str
    country: str
    lat: float
    lon: float
```

**Note:** This model is only used internally (not exposed in API responses).

---

## Success Criteria

### Automated
- `uv run pytest tests/test_geolocation.py` — all 5 tests pass
- `uv run mypy geolocation.py` — no errors
- `uv run ruff check geolocation.py` — clean

### Manual
- None (no UI changes in this phase)
