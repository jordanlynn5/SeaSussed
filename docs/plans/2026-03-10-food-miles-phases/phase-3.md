# Phase 3: Pipeline + API Integration

**Status:** pending
**Depends on:** Phase 1 + Phase 2

---

## Goal

Wire food miles into the scoring pipeline, pass user IP from request handlers, emit the `food_miles` SSE phase, and update voice session context.

---

## Modified Files

### `backend/pipeline.py`

**Import changes:**
```python
# Remove:
from wolfram import get_carbon_footprint

# Add:
from geolocation import get_user_location
from wolfram import get_food_miles
from models import UserLocation
```

**`run_scoring_pipeline` signature change:**
```python
async def run_scoring_pipeline(
    product_info: ProductInfo,
    related_products: list[str],
    client_ip: str = "",          # NEW — for geolocation
) -> SustainabilityScore:
```

**Inside `run_scoring_pipeline`:**
```python
# Step 4: parallel — replace carbon with food_miles
user_location = get_user_location(client_ip)  # cached, ~50ms first call

(alternatives, alts_label), (explanation, score_factors), food_miles = (
    await asyncio.gather(
        asyncio.to_thread(score_alternatives, ...),
        asyncio.to_thread(generate_content, ...),
        asyncio.to_thread(
            get_food_miles,
            enriched.origin_region or "",
            user_location,
        ) if user_location else asyncio.coroutine(lambda: None)(),
    )
)

# In SustainabilityScore construction:
#   carbon=carbon  →  food_miles=food_miles
```

**`analyze_page_progressive` signature change:**
```python
async def analyze_page_progressive(
    page_analysis: PageAnalysis,
    related_products: list[str],
    client_ip: str = "",          # NEW
) -> AsyncGenerator[dict[str, Any], None]:
```

**Inside `analyze_page_progressive`:**
```python
# Phase 1.5: replace carbon with food_miles
user_location = get_user_location(client_ip)
food_miles_result = None
if user_location:
    enriched_product, food_miles_result = await asyncio.gather(
        asyncio.to_thread(research_product, product),
        asyncio.to_thread(get_food_miles, product.origin_region or "", user_location),
    )
else:
    enriched_product = await asyncio.to_thread(research_product, product)

if food_miles_result:
    yield {"phase": "food_miles", "food_miles": food_miles_result.model_dump()}

# In final SustainabilityScore construction:
#   carbon=carbon  →  food_miles=food_miles_result
```

### `backend/main.py`

**Helper to extract client IP:**
```python
def _get_client_ip(request: Request) -> str:
    """Extract client IP, checking X-Forwarded-For for Cloud Run."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""
```

**`analyze` endpoint:**
```python
@app.post("/analyze")
async def analyze(request: Request, body: AnalyzeRequest) -> AnalyzeResponse:
    ...
    ip = _get_client_ip(request)
    _check_rate_limit(ip)
    ...
    return await analyze_page(page_analysis, body.related_products, client_ip=ip)
```

Note: `analyze_page` also needs the `client_ip` parameter threaded through to `run_scoring_pipeline`.

**`analyze_stream` endpoint:**
```python
@app.post("/analyze/stream")
async def analyze_stream(request: Request, body: AnalyzeRequest) -> StreamingResponse:
    ...
    ip = _get_client_ip(request)
    _check_rate_limit(ip)
    ...
    async for event in analyze_page_progressive(page_analysis, body.related_products, client_ip=ip):
        yield f"data: {json.dumps(event)}\n\n"
```

**`score_endpoint`:**
```python
@app.post("/score")
async def score_endpoint(request: Request, body: ScoreRequest) -> SustainabilityScore:
    ip = _get_client_ip(request)
    return await run_scoring_pipeline(body.product_info, [], client_ip=ip)
```

### `backend/voice_session.py`

**Voice system prompt update:**

Replace the HEALTH & CARBON CONTEXT section:
```
HEALTH & FOOD MILES CONTEXT:
The tool response may include health_advisory (FDA mercury tier) and food_miles
(distance in miles from origin to the user's location). If present, weave them
naturally:
- "Plus, sardines are a Best Choice for mercury — safe to eat several times a week."
- "Interesting — this salmon traveled about 4,200 miles from Norway to get to you."
Only mention food_miles if the distance is notable (over 1000 miles) or the user
seems interested in where their food comes from.
```

**Tool response context update (in `_handle_analyze_current_product`):**
```python
# Replace:
"carbon_co2": (score_result.carbon.co2_kg_per_serving if score_result.carbon else None),

# With:
"food_miles": (score_result.food_miles.distance_miles if score_result.food_miles else None),
"food_origin": (score_result.food_miles.origin if score_result.food_miles else None),
```

**Note:** Voice session's `_handle_analyze_current_product` calls `run_scoring_pipeline`, which needs the client IP. The voice WebSocket doesn't have a `Request` object, but we can extract the IP from the WebSocket's client attribute: `self.ws.client.host` (or check headers). Pass through the IP at VoiceSession init time.

---

## Success Criteria

### Automated
- `uv run pytest` — full suite passes (all existing tests + new ones)
- `uv run mypy .` — no errors
- `uv run ruff check .` — clean

### Manual
- Start local backend, POST to `/analyze/stream` — see `food_miles` SSE event (if origin detected and not on localhost)
- Verify `carbon` phase no longer emitted
