# WebSocket Reconnect & Close Code Propagation

**Created:** 2026-03-16
**Status:** Draft
**Branch:** `dev`

## Problem

Voice session WebSocket connections drop with codes 1005/1006 due to:
- Gemini Live session timeout (~15 min hard limit)
- Cloud Run container recycling
- Network issues

Currently there is **no distinction** between user-clicking-End and abnormal drops — both converge to `onStatus('ended')`. There is no reconnection logic.

## Goals

1. **Close code propagation** — backend sends semantic close codes so the client knows WHY
2. **Client auto-reconnect** — silent reconnect for abnormal drops (1005/1006), max 3 retries
3. **Expired session UI** — "Session expired" with Reconnect button for Gemini timeout
4. **Cloud Run timeout** — extend to 15 min to match Gemini Live session limit

## Close Code Contract

| Code | Meaning | Client Behavior |
|------|---------|-----------------|
| 1000 | User clicked End / clean close | No reconnect, hide voice bar |
| 4000 | Gemini Live session expired/died | Show "Session expired" + Reconnect button |
| 4001 | Backend error (non-Gemini) | Show "Connection lost" + Reconnect button |
| 1005 | No close frame (network drop) | Auto-reconnect silently (max 3 retries) |
| 1006 | Abnormal closure (connection lost) | Auto-reconnect silently (max 3 retries) |

## Reconnect Behavior

**Auto-reconnect (1005/1006):**
- Keep mic stream + AudioWorklet + AudioContexts alive (don't call `stop()`)
- Show "Reconnecting..." in voice bar
- Exponential backoff: 1s, 2s, 4s
- Max 3 attempts; if all fail → show "Connection lost" + Reconnect button
- On success: resend `result_context`, resume listening

**Expired/error (4000/4001):**
- Clean up all audio resources
- Show message + Reconnect button
- Reconnect button starts a completely fresh session via `connectVoice(lastData)`

**User-initiated End:**
- `_userInitiatedClose` flag set in `stop()` before closing WebSocket
- `onclose` checks flag first — if true, always `onStatus('ended')`, no reconnect

## Phase Summary

| Phase | Description | Files | Batch |
|-------|-------------|-------|-------|
| 1 | Backend close code propagation | voice_session.py, main.py, test_voice.py | [batch-eligible] |
| 2 | Client reconnect logic + UI | voice-client.js, sidepanel.js | [batch-eligible] |
| 3 | Cloud Run timeout | deploy.yml, CLAUDE.md | [batch-eligible] |

All three phases modify independent file sets with no overlap.
Close codes are defined as constants in both backend and client, so no build-time dependency.

## Risks

- **Gemini session expiry signal is indirect** — we detect it via empty `session.receive()` iterator or exception, not a dedicated API signal. May need tuning.
- **Mic stream can die during reconnect** — browser may revoke mic permission if side panel loses focus. Added a guard check.
- **Backoff timing** — 3 retries at 1s/2s/4s means ~7s max reconnect window. If backend is down longer, user must manually reconnect.

## Phase Files

- [Phase 1: Backend Close Codes](2026-03-16-websocket-reconnect-phases/phase-1.md)
- [Phase 2: Client Reconnect + UI](2026-03-16-websocket-reconnect-phases/phase-2.md)
- [Phase 3: Cloud Run Timeout](2026-03-16-websocket-reconnect-phases/phase-3.md)
