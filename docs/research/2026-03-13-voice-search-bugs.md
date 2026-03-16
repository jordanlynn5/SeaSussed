# Voice Search Bugs — Research Document

**Date:** 2026-03-13
**Scope:** Three bugs observed in voice session search/navigate flow

---

## Bug 1: Gemini Calls search_store and navigate_to_product Multiple Times

### Observed Behavior
From logs on 2026-03-13:
- `search_store({'query': 'cod'})` called at log line 415, then again at line 470 — two identical searches in the same session.
- `navigate_to_product(...)` called at log line 527, then again at line 529 with the same URL (only `qid` timestamp differs).

### Code Path
The tool call handling is in `_relay_from_gemini()` at `voice_session.py:556-668`. The flow is:

1. `session.receive()` yields a `response` with `response.tool_call` (`voice_session.py:556-546`)
2. Each `function_call` in `response.tool_call.function_calls` is dispatched sequentially (`voice_session.py:584-614`)
3. Tool responses are sent back to Gemini via `session.send_tool_response()` (`voice_session.py:617`)
4. The outer `while True` loop at `voice_session.py:545` continues receiving, so Gemini can issue another tool call in the next turn

### Why It Happens
There is no deduplication or cooldown mechanism. After Gemini receives the `search_store` tool response (which includes a summary telling it to "IMMEDIATELY call navigate_to_product"), Gemini may:
- Call `search_store` again instead of `navigate_to_product` (as observed — two consecutive `search_store({'query': 'cod'})` calls)
- Call `navigate_to_product` and then immediately call it again in a subsequent turn with the same URL

The native audio model's behavior is non-deterministic. There is no server-side guard preventing the same tool from being called twice with identical arguments in rapid succession.

### Relevant State
- `self.search_event` (`voice_session.py:337`) is an `asyncio.Event` — it gets `.clear()`ed at the start of each `_handle_search_store()` call (`voice_session.py:769`), but there's no lock or flag preventing a second call while the first is still in progress or just completed.
- `self._awaiting_search_result` (`voice_session.py:344`) is set to `True` after search but is only read by `_format_context_update()` — not used to gate tool calls.

---

## Bug 2: _find_product_url Matches Wrong URLs to Product Names

### Observed Behavior
A cod product name was matched to a Tilapia URL. Gemini navigated to `B08LZV91ZM` ("Fresh Brand Skinless Responsibly Previously") which resolved to a Tilapia product page, not the cod product it intended.

### Code Path
`_find_product_url()` at `voice_session.py:24-45`:

```python
def _find_product_url(product_name: str, links: list[dict[str, str]]) -> str | None:
    name_lower = product_name.lower()
    # Try exact substring match first
    for link in links:
        if name_lower in link.get("name", "").lower():
            return link.get("url")
    # Try matching significant words (3+ chars)
    words = [w for w in name_lower.split() if len(w) >= 3]
    best_url = None
    best_count = 0
    for link in links:
        link_lower = link.get("name", "").lower()
        count = sum(1 for w in words if w in link_lower)
        if count > best_count:
            best_count = count
            best_url = link.get("url")
    return best_url if best_count >= 2 else None
```

### Why It Happens

**Phase 1 — Exact substring match (line 32-34):**
The product name extracted by Gemini vision (e.g., `"Amazon Grocery, Wild Caught Pacific Cod, Boneless Skinless Fillets, 16 oz (Previously Amazon Fresh, Packaging May Vary)"`) is checked as a substring within each scraped link's `name` field. If the scraped link names are short (e.g., card `innerText` truncated to first line at `background.js:417`: `p.text.split('\n')[0].trim()`), this substring check will fail because the long product name won't be found inside the short link name.

**Phase 2 — Word overlap (lines 36-45):**
Falls through to fuzzy word matching. The product name `"Amazon Grocery, Wild Caught Pacific Cod, Boneless Skinless Fillets, 16 oz (Previously Amazon Fresh, Packaging May Vary)"` splits into significant words: `["amazon", "grocery", "wild", "caught", "pacific", "cod", "boneless", "skinless", "fillets", "previously", "amazon", "fresh", "packaging", "may", "vary"]`.

A Tilapia link named `"Amazon Grocery, Skinless Tilapia Fillets, 12 Oz"` would match on words: `"amazon"`, `"grocery"`, `"skinless"`, `"fillets"` — **4 matches**, easily clearing the `>= 2` threshold. If the actual cod link's scraped name has fewer matching words (e.g., if it was truncated or differently formatted), the Tilapia link could score higher.

The function tracks only `best_count` (highest word overlap) without considering **species-specific words** or **word proportion**. Generic words like "amazon", "grocery", "skinless", "fillets" dominate the match score, drowning out the species-distinguishing word "cod" vs "tilapia".

### Scraped Link Name Format
At `background.js:344-349`, Amazon search result cards are scraped using `data-component-type="s-search-result"`. The card's `innerText` includes the full card text (title + rating + price + delivery info). At `background.js:417`, only the first line is kept as the link name: `p.text.split('\n')[0].trim()`. This first line is typically the product title, but may be truncated or may include "Sponsored" prefixes.

At `background.js:404`, fallback links use `a.innerText.trim()` which may be much shorter.

---

## Bug 3: Double Navigate Triggers Duplicate POST /analyze/stream

### Observed Behavior
From logs: two `POST /analyze/stream HTTP/1.1 200 OK` at lines 531 and 539, both analyzing the same Tilapia product. Two full analysis pipelines ran in parallel (both producing identical Gemini vision responses at lines 548-563 and 569-584).

### Code Path

**Server side — `_handle_navigate_to_product()`** at `voice_session.py:910-924`:
```python
async def _handle_navigate_to_product(self, url: str) -> dict[str, Any]:
    if not url:
        return {"error": "No URL provided"}
    log.info("Navigating user to: %s", url)
    await self.ws.send_json({"type": "navigate", "url": url})
    return {"success": True, "url": url, "instruction": "..."}
```
This sends `{"type": "navigate", "url": ...}` to the client WebSocket. There is no guard against sending two navigate messages.

**Client side — `_navigateToUrl()`** at `voice-client.js:288-310`:
```javascript
async _navigateToUrl(url) {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    const tab = tabs[0];
    await chrome.tabs.update(tab.id, { url });
    // ... sets up onUpdated listener ...
    // When tab loads: calls triggerAnalyze()
}
```
Each call to `_navigateToUrl()` independently:
1. Updates the tab URL
2. Sets up a new `onUpdated` listener
3. When tab completes loading, calls `triggerAnalyze()`

If called twice, two listeners are registered. The second `chrome.tabs.update()` may be a no-op (same URL) or cause a re-navigation. Both listeners will fire on tab load complete, each calling `triggerAnalyze()`.

**`triggerAnalyze()`** at `sidepanel.js:227` performs a full analysis cycle: captures page data, calls `POST /analyze/stream`, renders results. Two concurrent calls mean two captures and two backend requests.

### Why It Happens
Bug 1 (double tool calls) directly causes Bug 3. When Gemini calls `navigate_to_product` twice, the backend sends two `navigate` WebSocket messages, the client processes both, and two `triggerAnalyze()` calls fire.

---

## Data Flow Summary

```
User speaks → Gemini Live → tool_call: search_store
  → backend _handle_search_store()
    → sends {"type": "search_store"} to client WS
    → client background.js opens search tab, scrapes DOM
    → client sends {"type": "search_results", page_text, product_links} back
    → backend calls analyze_screenshot() on page_text (no images)
    → backend scores each seafood product with compute_score()
    → backend matches product names to scraped URLs via _find_product_url()
    → returns scored list + summary to Gemini as tool response

Gemini Live → tool_call: navigate_to_product(url)
  → backend sends {"type": "navigate", url} to client WS
  → client voice-client.js _navigateToUrl() updates tab
  → tab loads → triggerAnalyze() called
  → POST /analyze/stream fires
  → results stream back, context_update sent to Gemini via WS
```

---

## Key File References

| File | Lines | Purpose |
|---|---|---|
| `backend/voice_session.py` | 24-45 | `_find_product_url()` — name-to-URL matching |
| `backend/voice_session.py` | 545-668 | `_relay_from_gemini()` — receives Gemini tool calls, no dedup |
| `backend/voice_session.py` | 766-908 | `_handle_search_store()` — search + score + summary |
| `backend/voice_session.py` | 910-924 | `_handle_navigate_to_product()` — no guard against duplicates |
| `extension/voice-client.js` | 288-310 | `_navigateToUrl()` — no guard against duplicate navigations |
| `extension/voice-client.js` | 297-309 | `onUpdated` listener — each call registers a new one |
| `extension/sidepanel.js` | 227-266 | `triggerAnalyze()` — full analysis cycle, called by navigate |
| `extension/background.js` | 330-418 | Search DOM scraping — product card text + link extraction |
| `extension/background.js` | 417 | Link name = first line of card text: `p.text.split('\n')[0].trim()` |
