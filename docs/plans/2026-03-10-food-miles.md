# Food Miles — Replace Carbon Footprint with Distance Traveled

**Date:** 2026-03-10
**Feature:** Replace non-working Wolfram carbon footprint card with a "Food Miles" card showing how far the seafood traveled to reach the user
**Phase files:** `docs/plans/2026-03-10-food-miles-phases/`

---

## What We're Building

The Wolfram carbon footprint card (`get_carbon_footprint`) doesn't return useful results — Wolfram Alpha's computational engine lacks structured CO₂ data for seafood species. We're replacing it with a **Food Miles** card that shows how far the seafood traveled from its origin to the user.

**Why this works with Wolfram:** Distance queries like `"distance from Oslo Norway to Chicago IL"` are Wolfram Alpha's bread and butter — they return reliable, structured results every time.

### User Experience

```
🌊 Food Miles
~4,200 miles from Norway → Chicago, IL
Source: Wolfram Alpha
```

### Data Flow

1. **User location:** IP geolocation via `ip-api.com` (free, no API key, ~50ms, returns city + country)
2. **Origin location:** `origin_region` from Gemini's screen analysis (e.g., "Alaska, USA", "Norway", "Gulf of Mexico")
3. **Distance:** Wolfram Alpha query: `"distance from {origin} to {user_city}, {user_country}"`
4. **No Gemini parsing needed:** Wolfram distance results are simple — extract directly from the "Result" pod plaintext (e.g., "4213 miles")

---

## Architecture

```
                     ┌─ get_user_location(ip)     → ~50ms, ip-api.com
Screen Analyzer ──┤
  (ProductInfo)    ├─ get_food_miles(origin, user_location)  → ~0.5s, Wolfram API
                     │    └─ No Gemini parsing — regex extract from WA "Result" pod
                     │
                     ├─ research_product(...)       → existing (unchanged)
                     └─ compute_score(...)          → existing (unchanged)
```

**Key simplification vs. carbon:** No Gemini call needed to parse Wolfram output. Distance queries return clean plaintext like `"4213 miles (geodesic distance)"` — a simple regex extracts the number.

---

## Graceful Degradation

The card is hidden (not an error) when any of these occur:
- `WOLFRAM_APP_ID` env var is unset
- `origin_region` is `None` or empty (Gemini couldn't determine origin)
- IP geolocation fails or returns no city
- Wolfram returns no distance data
- Origin and user are in the same city (distance ≈ 0 — not useful)

---

## Data Models

### Replace `CarbonFootprint` with `FoodMiles`

```python
# models.py — replace CarbonFootprint

class FoodMiles(BaseModel):
    distance_miles: int            # e.g., 4213
    origin: str                    # e.g., "Norway"
    destination: str               # e.g., "Chicago, IL"
    source: str = "Wolfram Alpha"
```

### `SustainabilityScore` field change

```python
class SustainabilityScore(BaseModel):
    ...existing fields...
    health: HealthInfo | None = None
    food_miles: FoodMiles | None = None    # was: carbon: CarbonFootprint | None = None
```

### `UserLocation` (internal, not exposed in API)

```python
class UserLocation(BaseModel):
    city: str          # "Chicago"
    region: str        # "Illinois"
    country: str       # "United States"
    lat: float
    lon: float
```

---

## API Contract Changes

### SSE stream (`POST /analyze/stream`)

The `carbon` phase is renamed to `food_miles`:

```
data: {"phase": "health", "health": {...}}
data: {"phase": "scored", ...}
data: {"phase": "food_miles", "food_miles": {"distance_miles": 4213, "origin": "Norway", "destination": "Chicago, IL", "source": "Wolfram Alpha"}}
data: {"phase": "complete", "result": {...}}
```

### Non-streaming endpoints

`POST /analyze` and `POST /score` responses: `carbon` field replaced by `food_miles`.

Backward compatible — `carbon` was already optional (`None` when unavailable).

---

## IP Geolocation

**Service:** `ip-api.com` (free tier: 45 requests/minute from a single IP, no key required)

```
GET http://ip-api.com/json/{ip}?fields=city,regionName,country,lat,lon
```

**Response:**
```json
{"city": "Chicago", "regionName": "Illinois", "country": "United States", "lat": 41.85, "lon": -87.65}
```

**Caching:** `@lru_cache(maxsize=256)` on IP → location. Most extension users have a single IP per session, so this effectively means one geolocation call per user session.

**Cloud Run note:** `request.client.host` gives the client IP. On Cloud Run behind a load balancer, we may need `X-Forwarded-For` header instead. We'll check both.

---

## Wolfram Distance Query

**Query format:** `"distance from {origin_region} to {city}, {country}"`

**Example:** `"distance from Norway to Chicago, United States"`

**Response parsing:** The "Result" pod contains text like:
```
4213 miles
```
or
```
4213 miles (geodesic distance)
```

**Extraction:** Simple regex `r"([\d,]+)\s*miles"` — no Gemini needed.

**Fallback:** If the Result pod says "km" instead of "miles", convert: `int(km * 0.621371)`.

---

## Files Changed

### New Files

| File | Purpose |
|---|---|
| `backend/geolocation.py` | IP → city/country via ip-api.com + caching |
| `backend/tests/test_geolocation.py` | Tests for geolocation module |

### Modified Files

| File | Changes |
|---|---|
| `backend/wolfram.py` | Replace `get_carbon_footprint` + `_parse_carbon` with `get_food_miles` + `_parse_distance`. Remove Gemini parsing. Keep `_query_wolfram` as-is. |
| `backend/models.py` | Replace `CarbonFootprint` with `FoodMiles`. Add `UserLocation`. Update `SustainabilityScore`. |
| `backend/pipeline.py` | Replace carbon calls with food_miles calls. Pass user IP through. |
| `backend/main.py` | Pass `request.client.host` (or `X-Forwarded-For`) to pipeline. Emit `food_miles` SSE phase. |
| `backend/voice_session.py` | Replace `carbon_co2` with `food_miles` in tool response context. Update voice prompt. |
| `backend/tests/test_wolfram.py` | Rewrite tests for `get_food_miles` instead of `get_carbon_footprint`. |
| `extension/sidepanel.html` | Rename carbon card → food miles card. Update icon + title. |
| `extension/sidepanel.js` | Replace `renderCarbonCard` with `renderFoodMilesCard`. Handle `food_miles` SSE phase. |

---

## Phase Summary

| Phase | Name | Files | Batch | Status |
|---|---|---|---|---|
| 1 | Geolocation module | `geolocation.py`, `tests/test_geolocation.py` | [batch-eligible] | ✅ complete |
| 2 | Wolfram food miles | `wolfram.py`, `tests/test_wolfram.py`, `models.py` | [batch-eligible] | ✅ complete |
| 3 | Pipeline + API integration | `pipeline.py`, `main.py`, `voice_session.py` | — | ✅ complete |
| 4 | Extension UI | `sidepanel.html`, `sidepanel.js` | — | ✅ complete |

Phases 1 and 2 are independent — no shared file modifications (models.py changes in Phase 2 don't overlap with Phase 1's new file). They can run in parallel via `/batch`.

Phase 3 depends on both Phase 1 and 2. Phase 4 depends on Phase 3's SSE contract.

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| `origin_region` too vague (e.g., "Pacific Ocean") | Wolfram handles geographic region names well; worst case returns None → card hidden |
| IP geolocation blocked/rate-limited | `@lru_cache` + graceful degradation (card hidden) |
| Cloud Run returns load balancer IP, not client IP | Check `X-Forwarded-For` header first, fall back to `request.client.host` |
| ip-api.com free tier: 45 req/min | Cache per IP; Cloud Run instance serves many users but each user's IP is cached after first call |
| Wolfram distance query fails for unusual origins | Graceful None return → card hidden |
| Same-region origin (e.g., user in Alaska, fish from Alaska) | Show short distance — still interesting ("only ~200 miles!") unless distance ≈ 0 |
