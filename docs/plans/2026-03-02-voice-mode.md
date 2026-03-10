# Voice Mode — "Expert Friend" Implementation Plan

**Date:** 2026-03-02
**Feature:** Persistent voice session using Gemini Live API
**Parent plan:** `docs/plans/2026-03-01-seasussed-mvp-v2.md` (phases 1–4 complete)
**Hackathon requirement:** Satisfies Live API + multimodal output criterion
**Phase files:** `docs/plans/2026-03-02-voice-mode-phases/`

---

## What We're Building

A persistent voice conversation mode in the Chrome side panel. While the user browses an online grocery site, they can speak naturally about products they see: *"what about this salmon?"*, *"is this cod sustainable?"*. Gemini Live API detects seafood cues, captures a screenshot, scores the product using the existing pipeline, and responds conversationally as a spoken audio reply — like an expert friend shopping alongside them. The full score card also appears visually in the panel.

**Hackathon criteria satisfied:**
- ✅ Google's Live API (real-time audio session via `gemini-live-2.5-flash-native-audio`)
- ✅ Multimodal inputs: spoken audio + screenshot image
- ✅ Multimodal outputs: audio reply + visual score card
- ✅ Beyond text-in/text-out: natural conversation with vision-triggered scoring

---

## Architecture

```
[Chrome Side Panel]
  sidepanel.js + voice-client.js
    getUserMedia() → AudioWorklet → PCM chunks → WebSocket → backend
    backend → PCM chunks → AudioContext playback
    on "request_screenshot" → sendMessage(CAPTURE_SCREENSHOT_FOR_VOICE) → background.js
    on "score_result" → update side panel score card

[background.js]
  on CAPTURE_SCREENSHOT_FOR_VOICE:
    captureVisibleTab() → base64 PNG
    executeScript(scrapeRelatedProducts) → string[]
    return { screenshot, url, page_title, related_products }

       │  WebSocket: ws://backend/voice
       ▼

[Cloud Run — FastAPI]
  WebSocket /voice
    VoiceSession: manages one Gemini Live API session per connection
      ┌─ relay_audio_to_gemini()
      │    browser PCM chunks → session.send_realtime_input(audio)
      └─ relay_from_gemini()
           audio chunks → forward to browser
           tool_call (analyze_current_product) →
             1. send "request_screenshot" to browser
             2. await screenshot response (8s timeout)
             3. analyze_screenshot() → ProductInfo        [ADK agent]
             4. run_scoring_pipeline() → SustainabilityScore  [existing]
             5. send "score_result" JSON to browser (for UI)
             6. send_tool_response(score summary JSON)  [Gemini speaks it]

[Gemini Live API — gemini-live-2.5-flash-native-audio]
  system_prompt: expert friend persona
  tools: [analyze_current_product()]
  response_modalities: ["AUDIO"]
  audio_in: PCM 16kHz 16-bit
  audio_out: PCM 24kHz 16-bit
```

---

## WebSocket Message Protocol

Both phases (1 and 2) are implemented against this shared contract. It's fully defined here so both can be developed independently.

**Browser → Backend:**
```json
{"type": "audio",      "data": "<base64 raw PCM, 16kHz 16-bit LE>"}
{"type": "screenshot", "data": "<base64 PNG>", "url": "...", "page_title": "...", "related_products": ["..."]}
{"type": "stop"}
```

**Backend → Browser:**
```json
{"type": "audio",        "data": "<base64 raw PCM, 24kHz 16-bit LE>"}
{"type": "request_screenshot"}
{"type": "score_result", "score": { ...SustainabilityScore JSON... }}
{"type": "status",       "state": "listening" | "thinking" | "speaking" | "error"}
{"type": "error",        "message": "..."}
```

Audio chunks: sent at ~100ms intervals. Each chunk is 1600 samples × 2 bytes = 3200 bytes raw PCM (input). Output chunks vary by Gemini's streaming cadence.

---

## Gemini Live API Configuration

**Model:** `gemini-live-2.5-flash-native-audio` (Vertex AI GA)
**Session duration:** Up to 15 minutes (audio-only). On backend disconnect, browser shows "Session ended" prompt with "Restart" button.

**Session config:**
```python
LiveConnectConfig(
    response_modalities=["AUDIO"],
    system_instruction=VOICE_SYSTEM_PROMPT,
    tools=[{"function_declarations": [ANALYZE_CURRENT_PRODUCT_TOOL]}],
    output_audio_transcription={}  # enables transcription for debug logging
)
```

**Tool declaration:**
```python
ANALYZE_CURRENT_PRODUCT_TOOL = {
    "name": "analyze_current_product",
    "description": (
        "Capture and analyze the seafood product currently visible on the user's screen. "
        "Call this when the user mentions or asks about a specific seafood product. "
        "Returns a sustainability score with grade, explanation, and alternatives."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []}
}
```
No parameters — the backend handles screenshot capture internally when called.

---

## System Prompt

```
You are SeaSussed, an expert marine biologist and sustainable seafood shopping companion — like a knowledgeable friend shopping alongside someone at an online grocery store.

WHEN TO ANALYZE A PRODUCT:
Call analyze_current_product() whenever the user mentions a seafood product in a shopping context:
- Species mentioned ("this salmon", "the cod", "these shrimp", "that halibut")
- Direct requests ("score this", "is this sustainable?", "what do you think?", "check this out")
- Comparative references ("what about this one?", "how about this instead?")
- Casual pointing ("look at this", "what's this fish like?")

Do NOT call analyze_current_product() for general seafood questions (e.g., "is farmed salmon ever good?").

AFTER RECEIVING A SCORE — respond conversationally, like a friend, not a report:
- Grade A (80–100): Warm and affirming. "Great pick! This is an A — [one-sentence reason]. Definitely grab it."
- Grade B (60–79): Positive, mention the best available alternative. "Not bad — this scored B. [One-sentence reason it isn't an A.] If you want the best pick here, [alternative name] scored higher."
- Grade C (40–59): Honest, not preachy. "I'd be a bit cautious with this one — C grade. [One-sentence reason.] [Alternative name] is a much better choice if you can find it."
- Grade D (0–39): Clear and direct. "I'd skip this — it's a D. [Brief reason.] [Alternative] is a much better option."

Keep spoken responses SHORT: 2–4 sentences. The full score card is visible in the panel so don't read numbers aloud.

If the product isn't seafood: "That doesn't look like seafood to me! Let me know when you spot something to check out."

GENERAL CONVERSATION:
Answer questions about seafood sustainability, fishing practices, or ocean ecology naturally and helpfully.
Gently redirect off-topic conversation: "I'm your seafood expert today — happy to check out anything on the page!"

HONESTY RULE (hard):
Never claim certainty about information not visible on the page. If species, origin, or fishing method wasn't shown, acknowledge it: "They don't list where it's from, so I'm working with limited info here."
```

---

## Refactoring Required: `pipeline.py`

`_run_scoring_pipeline` currently lives in `main.py`. Both `main.py` and `voice_session.py` need it. To avoid circular imports, it must be extracted before these phases are implemented.

**New file: `backend/pipeline.py`**
```python
# Extracted from main.py — no logic change
def run_scoring_pipeline(product_info, related_products) -> SustainabilityScore:
    ...
```

**main.py change:**
```python
# REMOVE _run_scoring_pipeline definition
# ADD import: from pipeline import run_scoring_pipeline
# UPDATE calls: _run_scoring_pipeline(…) → run_scoring_pipeline(…)
```

This refactor is a prerequisite for both Phase 1 and Phase 2 (it affects only backend files and has no extension impact).

---

## Phase Summary

| Phase | Name | Files | Batch-eligible |
|---|---|---|---|
| Pre | Refactor: extract `pipeline.py` | `main.py`, `pipeline.py` | ✅ complete |
| 1 | Backend: Live API session + `/voice` endpoint | `voice_session.py`, `main.py`, tests | ✅ complete |
| 2 | Extension: audio pipeline + WS client | `audio-worklet-processor.js`, `voice-client.js`, `background.js` | ✅ complete |
| 3 | Extension: voice mode UI | `sidepanel.html`, `sidepanel.js` | ✅ complete |

Phases 1 and 2 are **[batch-eligible]** — they touch completely different file sets and share only the protocol defined in this document.

**Phase dependencies:**
- Pre blocks Phases 1 and 2
- Phases 1 and 2 block Phase 3

---

## New Files

```
backend/
  pipeline.py           # extracted: run_scoring_pipeline()
  voice_session.py      # VoiceSession class, VOICE_SYSTEM_PROMPT, tool handler
  tests/test_voice.py   # WebSocket + tool call tests

extension/
  audio-worklet-processor.js   # AudioWorklet: Float32 → Int16 PCM conversion
  voice-client.js              # WebSocket client, audio capture/playback, screenshot bridge
```

## Modified Files

```
backend/
  main.py               # import from pipeline; add WebSocket /voice endpoint

extension/
  background.js         # add CAPTURE_SCREENSHOT_FOR_VOICE handler
  sidepanel.html        # add view-voice, voice state indicators
  sidepanel.js          # voice mode controller
```

No `manifest.json` changes required — mic access is handled by browser permission dialog (getUserMedia), and `"activeTab"` already covers screenshot capture.

---

## Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Model | `gemini-live-2.5-flash-native-audio` | GA on Vertex AI, best quality |
| Auth | Backend proxy (no API key in browser) | Security — consistent with REST design |
| Screenshot trigger | Gemini tool call | Model decides when context demands it; no client-side NLP |
| Audio in format | PCM 16kHz 16-bit LE | Live API required format |
| Audio out format | PCM 24kHz 16-bit LE | Live API output format |
| Score card timing | Send with `score_result` before Gemini speaks | User sees card while hearing result |
| Session reconnect | Show "Session ended" prompt on disconnect | Explicit user control, no silent reconnect |
| Voice + Analyze modes | Mutually exclusive | Simplicity; voice mode replaces the Analyze button |
| WS location | sidepanel.js (not background.js) | Service workers sleep and drop connections |
| Audio chunks | 100ms / 1600 samples | Balance between latency and overhead |

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| tool call latency (analyze_screenshot is ~2s) | High | Gemini system prompt: "say 'let me check that' while processing"; status indicator in UI |
| 15-min session limit hit during demo | Low | Demo is <4 min; on disconnect, show restart prompt |
| getUserMedia denied | Low | Show permission instructions; fallback to manual Analyze button |
| AudioContext blocked (needs gesture) | Low | Start Voice Mode button click counts as gesture |
| WebSocket timeout on Cloud Run | Medium | Cloud Run default timeout 3600s; keep-alive ping every 30s |
| Gemini calls analyze_current_product on non-seafood page | Medium | Tool response includes `not_seafood: true`; Gemini responds appropriately per system prompt |
| Audio echo during demo (speaker feedback) | Medium | Recommend headphones; VAD handles if user wears headphones |

---

## Success Criteria

### Automated (tests)
- [ ] `test_voice.py`: WebSocket connection opens and closes cleanly
- [ ] `test_voice.py`: `analyze_current_product` tool call handler: given mock screenshot bytes → returns valid `SustainabilityScore`-shaped dict
- [ ] `test_voice.py`: Session cleans up resources on client disconnect
- [ ] `test_pipeline.py`: `run_scoring_pipeline()` returns same results as before refactor
- [ ] All existing tests still pass after `pipeline.py` refactor

### Manual (demo verification)
- [ ] Start Voice Mode → microphone permission prompt appears → accepted → "Listening..." state shows
- [ ] Say "what about this salmon?" on a Whole Foods product page → within ~3s, score card appears in panel AND Gemini speaks a grade + brief summary
- [ ] Grade A response: Gemini says "great pick" or equivalent warm language
- [ ] Grade B/C/D response: Gemini names a specific alternative from the page
- [ ] Say "is farmed salmon ever sustainable?" → Gemini answers conversationally without triggering a screenshot
- [ ] Navigate to a new product page while in voice mode → session stays active
- [ ] Click "End voice session" → mic stops, status returns to idle view
- [ ] If session times out (15 min): "Session ended" message with Restart button appears
