# Phase 1: Server-Side Tool Call Deduplication

## Goal
Prevent Gemini from executing the same tool call twice in rapid succession.

## Files
- `backend/voice_session.py` — add cooldown tracking to `VoiceSession.__init__` and guard logic to `_relay_from_gemini`
- `backend/tests/test_voice.py` — add test for duplicate tool call suppression

## Changes

### voice_session.py — VoiceSession.__init__ (line ~332)

Add cooldown state:

```pseudo
+ import time  (top of file)

  self._last_search_query: str = ""
  self._last_search_time: float = 0.0
  self._last_navigate_url: str = ""
  self._last_navigate_time: float = 0.0
+ TOOL_COOLDOWN_S = 30.0  (module-level constant)
```

### voice_session.py — _relay_from_gemini tool dispatch (line ~584)

Wrap each tool handler with cooldown check:

```pseudo
# Before calling _handle_search_store:
if fc.name == "search_store":
    query = (fc.args or {}).get("query", "")
    now = time.monotonic()
    if (query == self._last_search_query
            and now - self._last_search_time < TOOL_COOLDOWN_S):
        log.warning("Suppressed duplicate search_store('%s')", query)
        result = {"query": query, "products": [], "summary": "Search already performed — use the results above."}
    else:
        self._last_search_query = query
        self._last_search_time = now
        result = await self._handle_search_store(query)

# Before calling _handle_navigate_to_product:
elif fc.name == "navigate_to_product":
    url = (fc.args or {}).get("url", "")
    now = time.monotonic()
    if (url == self._last_navigate_url
            and now - self._last_navigate_time < TOOL_COOLDOWN_S):
        log.warning("Suppressed duplicate navigate_to_product")
        result = {"success": True, "url": url, "instruction": "Already navigating to this page."}
    else:
        self._last_navigate_url = url
        self._last_navigate_time = now
        result = await self._handle_navigate_to_product(url)
```

### test_voice.py — new test

```pseudo
test_voice_duplicate_search_suppressed:
    - Create MockSession with TWO search_store tool call responses (same query)
    - Connect, receive statuses
    - Send search_results for first call
    - Verify only ONE search_store message was sent to client (second was suppressed)
    - Verify send_tool_response was called twice (both get responses back to Gemini)
```

## Success Criteria
- **Automated:** `uv run pytest tests/test_voice.py` passes including new dedup test
- **Automated:** `uv run mypy .` and `uv run ruff check .` pass
- **Manual:** Start voice session, ask Gemini to search — logs show at most one `search_store` and one `navigate_to_product` per request
