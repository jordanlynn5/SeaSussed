# Phase 1: Backend Live API Session + `/voice` Endpoint

**[batch-eligible with Phase 2]** — touches only backend files; protocol is pre-defined in the parent plan.

Adds a `WebSocket /voice` FastAPI endpoint backed by `VoiceSession`, which manages a Gemini Live API session, proxies audio bidirectionally, and handles the `analyze_current_product` tool call using the existing scoring pipeline.

---

## Files Changed

- **NEW** `backend/voice_session.py`
- **NEW** `backend/tests/test_voice.py`
- **MODIFY** `backend/main.py`

---

## TDD Order

Write `test_voice.py` first. Tests must fail before implementation. Then implement `voice_session.py` and the endpoint.

---

## `backend/tests/test_voice.py` (write first)

```pseudocode
# Imports: TestClient from fastapi.testclient, app from main, unittest.mock

FIXTURE mock_gemini_live_session:
  # AsyncMock that simulates client.aio.live.connect() context manager
  # session.send_realtime_input() → no-op
  # session.receive() → yields one audio response chunk then stops
  # session.send_tool_response() → no-op

TEST test_voice_websocket_connects_and_stops(mock_gemini_live_session):
  with TestClient(app).websocket_connect("/voice") as ws:
    ws.send_json({"type": "stop"})
    # Connection should close cleanly — no exception

TEST test_voice_analyze_tool_call(mock_gemini_live_session):
  # Configure mock session.receive() to yield a tool_call for analyze_current_product
  # Mock analyze_screenshot() → returns ProductInfo(is_seafood=True, species="Atlantic cod", ...)
  # Mock run_scoring_pipeline() → returns SustainabilityScore(score=72, grade="B", ...)

  with TestClient(app).websocket_connect("/voice") as ws:
    # Backend will send request_screenshot; respond with mock screenshot data
    msg = ws.receive_json()
    ASSERT msg["type"] == "request_screenshot"

    ws.send_json({
      "type": "screenshot",
      "data": MOCK_BASE64_PNG,
      "url": "https://example.com",
      "page_title": "Atlantic Cod",
      "related_products": ["Pacific Salmon", "Alaskan Halibut"]
    })

    # Backend should send score_result
    result_msg = ws.receive_json()
    ASSERT result_msg["type"] == "score_result"
    ASSERT result_msg["score"]["grade"] == "B"
    ASSERT result_msg["score"]["score"] == 72

TEST test_voice_screenshot_timeout(mock_gemini_live_session):
  # Configure mock session.receive() to yield a tool_call but browser never responds
  # Expect VoiceSession to handle TimeoutError gracefully (no crash)
  # Expect "error" message sent to client

TEST test_voice_session_cleanup_on_disconnect:
  # Client disconnects mid-stream
  # Expect no unhandled exceptions, no resource leak (tasks cancelled cleanly)
```

---

## `backend/voice_session.py` (new)

```pseudocode
# backend/voice_session.py

imports:
  asyncio, base64, json, logging
  from fastapi import WebSocket, WebSocketDisconnect
  from google import genai
  from google.genai import types
  from google.genai.live import AsyncSession  # type annotation
  from agents.screen_analyzer import analyze_screenshot
  from gemini_client import get_genai_client
  from models import SustainabilityScore
  from pipeline import run_scoring_pipeline

CONSTANTS:
  LIVE_MODEL = "gemini-live-2.5-flash-native-audio"
  SCREENSHOT_TIMEOUT_S = 8.0
  KEEPALIVE_INTERVAL_S = 30.0

  ANALYZE_CURRENT_PRODUCT_TOOL = {
    "name": "analyze_current_product",
    "description": "Capture and analyze the seafood product currently visible on the user's screen. Call this when the user mentions or asks about a specific seafood product. Returns a sustainability score with grade, explanation, and alternatives.",
    "parameters": {"type": "object", "properties": {}, "required": []}
  }

  VOICE_SYSTEM_PROMPT = """
  You are SeaSussed, an expert marine biologist and sustainable seafood shopping companion...
  [full system prompt as defined in parent plan]
  """

  LIVE_CONFIG = LiveConnectConfig(
    response_modalities=["AUDIO"],
    system_instruction=VOICE_SYSTEM_PROMPT,
    tools=[{"function_declarations": [ANALYZE_CURRENT_PRODUCT_TOOL]}],
    output_audio_transcription={},
  )


CLASS VoiceSession:
  FIELD ws: WebSocket
  FIELD screenshot_event: asyncio.Event
  FIELD screenshot_data: dict | None = None

  CONSTRUCTOR(ws: WebSocket):
    self.ws = ws
    self.screenshot_event = asyncio.Event()
    self.screenshot_data = None

  ASYNC METHOD run() -> None:
    client = get_genai_client()
    TRY:
      async with client.aio.live.connect(model=LIVE_MODEL, config=LIVE_CONFIG) as session:
        await self.ws.send_json({"type": "status", "state": "listening"})
        await asyncio.gather(
          self._relay_audio_to_gemini(session),
          self._relay_from_gemini(session),
          self._keepalive(),
        )
    EXCEPT WebSocketDisconnect:
      log.info("Client disconnected")
    EXCEPT Exception as e:
      log.error("VoiceSession error: %s", e)
      TRY:
        await self.ws.send_json({"type": "error", "message": str(e)})
      EXCEPT: pass

  ASYNC METHOD _relay_audio_to_gemini(session: AsyncSession) -> None:
    LOOP:
      TRY:
        msg = await self.ws.receive_json()
      EXCEPT WebSocketDisconnect:
        BREAK

      IF msg["type"] == "audio":
        pcm_bytes = base64.b64decode(msg["data"])
        await session.send_realtime_input(
          audio=types.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000")
        )
      ELIF msg["type"] == "screenshot":
        self.screenshot_data = msg
        self.screenshot_event.set()
      ELIF msg["type"] == "stop":
        BREAK

  ASYNC METHOD _relay_from_gemini(session: AsyncSession) -> None:
    async for response in session.receive():
      IF response.data:  # audio bytes from Gemini
        audio_b64 = base64.b64encode(response.data).decode()
        await self.ws.send_json({"type": "audio", "data": audio_b64})

      IF response.tool_call:
        await self.ws.send_json({"type": "status", "state": "thinking"})
        tool_responses = []
        for fc in response.tool_call.function_calls:
          IF fc.name == "analyze_current_product":
            result = await self._handle_analyze_current_product()
            tool_responses.append(
              types.FunctionResponse(id=fc.id, name=fc.name, response=result)
            )
        IF tool_responses:
          await session.send_tool_response(function_responses=tool_responses)
          await self.ws.send_json({"type": "status", "state": "speaking"})

      # When Gemini starts/stops outputting: update status
      IF response.server_content and response.server_content.interrupted:
        await self.ws.send_json({"type": "status", "state": "listening"})

  ASYNC METHOD _handle_analyze_current_product() -> dict:
    # Reset event and data
    self.screenshot_event.clear()
    self.screenshot_data = None

    # Ask browser to capture screenshot
    await self.ws.send_json({"type": "request_screenshot"})

    # Wait for response
    TRY:
      await asyncio.wait_for(self.screenshot_event.wait(), timeout=SCREENSHOT_TIMEOUT_S)
    EXCEPT asyncio.TimeoutError:
      log.warning("Screenshot capture timed out")
      RETURN {"error": "Screenshot capture timed out", "not_seafood": True}

    msg = self.screenshot_data
    IF msg IS None:
      RETURN {"error": "No screenshot received", "not_seafood": True}

    # Run existing scoring pipeline
    product_info = await analyze_screenshot(
      msg["data"], msg.get("url", ""), msg.get("page_title", "")
    )
    score_result = run_scoring_pipeline(product_info, msg.get("related_products", []))

    # Send full score card to browser for UI update
    await self.ws.send_json({
      "type": "score_result",
      "score": score_result.model_dump()
    })

    # Return compact summary for Gemini to speak about
    RETURN {
      "score": score_result.score,
      "grade": score_result.grade,
      "species": product_info.species,
      "wild_or_farmed": product_info.wild_or_farmed,
      "origin_region": product_info.origin_region,
      "certifications": product_info.certifications,
      "explanation": score_result.explanation,
      "alternatives": [
        {"species": a.species, "score": a.score, "grade": a.grade}
        for a in score_result.alternatives[:2]  # top 2 for brevity
      ],
      "not_seafood": not product_info.is_seafood,
    }

  ASYNC METHOD _keepalive() -> None:
    # Send periodic pings to prevent Cloud Run timeout (default 3600s, but be safe)
    LOOP:
      await asyncio.sleep(KEEPALIVE_INTERVAL_S)
      TRY:
        await self.ws.send_json({"type": "ping"})
      EXCEPT:
        BREAK
```

---

## `backend/main.py` (modify — add endpoint)

```pseudocode
# ADD import:
from fastapi import WebSocket
from voice_session import VoiceSession

# ADD after existing routes:
@app.websocket("/voice")
async def voice_endpoint(websocket: WebSocket) -> None:
  await websocket.accept()
  session = VoiceSession(websocket)
  await session.run()
```

---

## `backend/pyproject.toml` (no changes needed)

`google-genai>=1.0` already installed — Live API is part of this SDK.
`fastapi` already has built-in WebSocket support via Starlette.

---

## Success Criteria

### Automated
- [x] `test_voice_websocket_connects_and_stops` passes
- [x] `test_voice_analyze_tool_call` passes: score_result sent, correct grade
- [x] `test_voice_screenshot_timeout` passes: error message sent, no crash
- [x] `test_voice_session_cleanup_on_disconnect` passes: no exception propagated
- [x] All existing tests still pass
- [x] `uv run mypy .` passes
- [x] `uv run ruff check .` passes

### Manual
- [ ] `curl -i --no-buffer -H "Connection: Upgrade" -H "Upgrade: websocket" http://localhost:8000/voice` → 101 Switching Protocols
- [ ] (with valid Vertex AI credentials) WebSocket client connects, sends `{"type": "stop"}`, connection closes cleanly
