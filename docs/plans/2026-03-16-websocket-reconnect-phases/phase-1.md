# Phase 1: Backend Close Code Propagation

**Files:** `backend/voice_session.py`, `backend/main.py`, `backend/tests/test_voice.py`
**Batch:** [batch-eligible] — no file overlap with phases 2 or 3

## Overview

Add semantic WebSocket close codes so the client can distinguish user-initiated close, Gemini session expiry, and backend errors. Send a `session_end` JSON message before the close frame (more reliable than close frame reason strings).

## Changes

### 1. Close code constants (`voice_session.py`, after line 530)

```python
# WebSocket close codes (4000-4999 = application-defined, RFC 6455)
WS_CLOSE_NORMAL = 1000
WS_CLOSE_GEMINI_EXPIRED = 4000
WS_CLOSE_SERVER_ERROR = 4001
```

### 2. VoiceSession state tracking (`voice_session.py`, `__init__` after line 553)

```python
self._close_code: int = WS_CLOSE_NORMAL
self._close_reason: str = ""
```

Add a read-only property so `main.py` can access it:

```python
@property
def close_code(self) -> int:
    return self._close_code
```

### 3. Detect Gemini session expiry (`voice_session.py`, `_relay_from_gemini`)

The `session.receive()` async iterator is turn-scoped. If the Gemini session expires, it either:
- Returns an empty iterator (async for yields nothing)
- Raises an exception

**Change the `while True` loop (line 762):**

```python
# BEFORE (line 762-763):
while True:
    async for response in session.receive():

# AFTER:
while True:
    turn_had_response = False
    async for response in session.receive():
        turn_had_response = True
        # ... all existing response handling unchanged ...

    if not turn_had_response:
        log.info("Gemini session ended (empty receive)")
        self._close_code = WS_CLOSE_GEMINI_EXPIRED
        self._close_reason = "Gemini session expired"
        break
```

**Change the exception handler (lines 936-941):**

```python
# BEFORE:
except Exception as e:
    log.error("Gemini receive error: %s", e, exc_info=True)
    try:
        await self.ws.send_json({"type": "error", "message": str(e)})
    except Exception:
        pass

# AFTER:
except Exception as e:
    log.error("Gemini receive error: %s", e, exc_info=True)
    self._close_code = WS_CLOSE_GEMINI_EXPIRED
    self._close_reason = f"Gemini error: {e}"
    try:
        await self.ws.send_json({"type": "error", "message": str(e)})
    except Exception:
        pass
```

### 4. Set close code on user stop (`voice_session.py`, `_relay_audio_to_gemini`)

Lines 752-754 — no change needed. `_close_code` defaults to `WS_CLOSE_NORMAL` (1000), which is correct for user-initiated stop.

### 5. Send `session_end` message before close (`voice_session.py`, `run()`)

After the inner try/finally (task cleanup), still inside the `async with` block, send a `session_end` message for non-normal closes:

```python
# After line 596 (task gather), before exiting async with:
if self._close_code != WS_CLOSE_NORMAL:
    try:
        await self.ws.send_json({
            "type": "session_end",
            "code": self._close_code,
            "reason": self._close_reason,
        })
    except Exception:
        pass  # Client may already be gone
```

### 6. Set close code on connection-level errors (`voice_session.py`, `run()`)

```python
# BEFORE (lines 599-604):
except Exception as e:
    log.error("VoiceSession error: %s", e, exc_info=True)
    try:
        await self.ws.send_json({"type": "error", "message": str(e)})
    except Exception:
        pass

# AFTER:
except Exception as e:
    log.error("VoiceSession error: %s", e, exc_info=True)
    self._close_code = WS_CLOSE_SERVER_ERROR
    self._close_reason = str(e)
    try:
        await self.ws.send_json({
            "type": "session_end",
            "code": self._close_code,
            "reason": self._close_reason,
        })
    except Exception:
        pass
```

### 7. Pass close code to WebSocket.close() (`main.py`, lines 141-145)

```python
# BEFORE:
finally:
    try:
        await websocket.close()
    except Exception:
        pass

# AFTER:
finally:
    try:
        await websocket.close(code=session.close_code)
    except Exception:
        pass
```

## Tests (`test_voice.py`)

### New test: close code on user stop

```python
async def test_voice_close_code_on_user_stop():
    """When client sends 'stop', WebSocket closes with code 1000."""
    async with AsyncClient(...) as client:
        async with client.websocket_connect("/voice") as ws:
            msg = await ws.receive_json()
            assert msg["type"] == "status"
            await ws.send_json({"type": "stop"})
            # Server should close with 1000
            close = await ws.receive()
            assert close["code"] == 1000
```

### New test: session_end message on Gemini error

```python
async def test_voice_session_end_on_gemini_error():
    """When Gemini session dies, client receives session_end before close."""
    # Mock Gemini session.receive() to raise RuntimeError
    # Verify client receives: {"type": "session_end", "code": 4000, "reason": "..."}
    # Then WebSocket closes with code 4000
```

### New test: session_end on empty Gemini turn

```python
async def test_voice_session_end_on_gemini_expiry():
    """When Gemini session.receive() yields nothing, detect as expiry."""
    # Mock session.receive() to return empty async iterator
    # Verify session_end message with code 4000
```

## Success Criteria

### Automated
- `mypy .` passes with new type annotations
- `ruff check .` passes
- All existing tests still pass
- New close code tests pass
- `WS_CLOSE_NORMAL`, `WS_CLOSE_GEMINI_EXPIRED`, `WS_CLOSE_SERVER_ERROR` constants exported

### Manual
- Start voice session → click End → backend logs "Client requested stop", close code 1000
- Start voice session → wait ~15 min for Gemini expiry → client receives `session_end` with code 4000
