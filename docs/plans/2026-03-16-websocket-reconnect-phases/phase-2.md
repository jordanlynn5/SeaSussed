# Phase 2: Client Reconnect Logic + UI

**Files:** `extension/voice-client.js`, `extension/sidepanel.js`
**Batch:** [batch-eligible] — no file overlap with phases 1 or 3

## Overview

Add smart reconnection to the voice client based on close codes from Phase 1. Auto-reconnect silently for network drops (1005/1006). Show "Session expired" with Reconnect button for Gemini timeout (4000). Never reconnect when user clicks End.

## Design: Audio Preservation During Reconnect

Key insight: on abnormal drops, only the WebSocket dies. The mic stream, AudioWorklet, and AudioContexts are still alive. `_sendAudioChunk` already guards on `ws.readyState !== WebSocket.OPEN` (line 142), so audio chunks are silently dropped while disconnected. Once a new WebSocket opens, audio flows again automatically.

For expired/error sessions (4000/4001), we DO clean up audio and require a full fresh session.

## Changes to `voice-client.js`

### 1. New instance variables (constructor, after line 22)

```javascript
this._userInitiatedClose = false;
this._reconnectAttempts = 0;
this._maxReconnectAttempts = 3;
this._lastResultContext = null;   // stored for resend on reconnect
this._sessionEndCode = null;      // set by session_end message before close
this._sessionEndReason = null;
```

### 2. Store result_context for reconnect (`sendResultContext`, line 94-97)

```javascript
sendResultContext(ctx) {
    this._lastResultContext = ctx;  // ← NEW: store for reconnect
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify({ type: 'result_context', ...ctx }));
}
```

### 3. Handle `session_end` message (`_handleMessage`, add new case before `ping`)

```javascript
case 'session_end':
    console.warn('[SeaSussed] Session end:', msg.code, msg.reason);
    this._sessionEndCode = msg.code;
    this._sessionEndReason = msg.reason;
    break;
```

### 4. Set flag in `stop()` (line 104, at top of method)

```javascript
stop() {
    this._userInitiatedClose = true;  // ← NEW: prevent reconnect
    // ... rest of existing stop() unchanged ...
}
```

### 5. Replace `onclose` handler (lines 76-79)

```javascript
// BEFORE:
this.ws.onclose = (event) => {
    console.warn('[SeaSussed] WebSocket closed — code:', event.code, 'reason:', event.reason || '(none)');
    this.onStatus('ended');
};

// AFTER:
this.ws.onclose = (event) => {
    const code = this._sessionEndCode || event.code;
    console.warn('[SeaSussed] WebSocket closed — code:', code,
        'frame:', event.code, 'reason:', this._sessionEndReason || event.reason || '(none)');
    this._sessionEndCode = null;
    this._sessionEndReason = null;

    // User clicked End — never reconnect
    if (this._userInitiatedClose) {
        this.onStatus('ended');
        return;
    }

    // Gemini session expired — show expired UI, clean up audio
    if (code === 4000) {
        this._cleanupAudio();
        this.onStatus('expired');
        return;
    }

    // Server error — show error UI, clean up audio
    if (code === 4001) {
        this._cleanupAudio();
        this.onStatus('disconnected');
        return;
    }

    // Abnormal close (network drop) — auto-reconnect
    if (code === 1005 || code === 1006) {
        if (this._reconnectAttempts < this._maxReconnectAttempts) {
            this.onStatus('reconnecting');
            this._reconnect().catch(() => {
                this._cleanupAudio();
                this.onStatus('disconnected');
            });
            return;
        }
        // Max retries exceeded
        this._cleanupAudio();
        this.onStatus('disconnected');
        return;
    }

    // Any other code (1000 from server, etc.) — clean end
    this.onStatus('ended');
};
```

### 6. Change `onerror` handler (lines 80-83)

Currently `onerror` calls `this.onError()` which triggers `stopVoiceBar()` in sidepanel.js — this kills the voice client before `onclose` can run reconnect logic. Fix: let `onclose` handle everything.

```javascript
// BEFORE:
this.ws.onerror = (event) => {
    console.error('[SeaSussed] WebSocket error:', event);
    this.onError('Connection error');
};

// AFTER:
this.ws.onerror = (event) => {
    console.error('[SeaSussed] WebSocket error:', event);
    // Don't call onError — onclose fires next and handles reconnect logic.
    // onError is reserved for server-sent error messages (type: "error").
};
```

### 7. New `_reconnect()` method

```javascript
async _reconnect() {
    this._reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, this._reconnectAttempts - 1), 4000);
    console.log(`[SeaSussed] Reconnect attempt ${this._reconnectAttempts}/${this._maxReconnectAttempts} in ${delay}ms`);
    await new Promise(r => setTimeout(r, delay));

    // Guard: mic stream may have died
    if (!this.micStream || this.micStream.getTracks().every(t => t.readyState === 'ended')) {
        throw new Error('Mic stream ended during reconnect');
    }

    // Create new WebSocket
    const wsUrl = BACKEND_URL.replace('https://', 'wss://').replace('http://', 'ws://');
    this.ws = new WebSocket(wsUrl + '/voice');
    await this._waitForOpen();

    // Set up handlers (same as in start(), lines 66-83 equivalent)
    this.ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            this._handleMessage(msg).catch(err => {
                console.error('[SeaSussed] Error in _handleMessage:', err);
            });
        } catch (parseErr) {
            console.error('[SeaSussed] Failed to parse WS message:', parseErr);
        }
    };
    this.ws.onclose = /* same reconnect-aware handler as step 5 */;
    this.ws.onerror = /* same log-only handler as step 6 */;

    // Reset playback timing
    this.nextPlayTime = this.audioContext.currentTime;
    this._receivedFirstAudio = false;

    // Resend context so Gemini knows what product we're looking at
    if (this._lastResultContext) {
        this.sendResultContext(this._lastResultContext);
    }

    this._reconnectAttempts = 0;  // reset on success
    console.log('[SeaSussed] Reconnected successfully');
}
```

**Implementation note:** To avoid duplicating the `onclose`/`onerror` handler code, extract them into named methods (`_setupWsHandlers()`) called from both `start()` and `_reconnect()`.

### 8. New `_cleanupAudio()` method

Extracts audio cleanup from `stop()` so it can be called without closing the WebSocket:

```javascript
_cleanupAudio() {
    if (this.workletNode) {
        this.workletNode.disconnect();
        this.workletNode = null;
    }
    if (this.micStream) {
        this.micStream.getTracks().forEach(t => t.stop());
        this.micStream = null;
    }
    if (this._micContext) {
        this._micContext.close();
        this._micContext = null;
    }
    if (this.audioContext) {
        this.audioContext.close();
        this.audioContext = null;
    }
}
```

Then refactor `stop()` to use it:

```javascript
stop() {
    this._userInitiatedClose = true;
    // ... navigate cleanup (lines 105-113) ...
    if (this.ws) {
        if (this.ws.readyState === WebSocket.OPEN) {
            try { this.ws.send(JSON.stringify({ type: 'stop' })); } catch (_) {}
        }
        this.ws.close();
        this.ws = null;
    }
    this._cleanupAudio();
}
```

## Changes to `sidepanel.js`

### 9. Store last voice data for Reconnect button (`connectVoice`, line 150)

```javascript
let _lastVoiceData = null;  // ← NEW: top-level variable near line 57

async function connectVoice(data, preStream = null) {
    _lastVoiceData = data;  // ← NEW: store for reconnect
    // ... rest unchanged ...
}
```

### 10. New voice bar states (`updateVoiceBar`, line 120)

```javascript
function updateVoiceBar(state) {
    const dot = document.getElementById('voice-bar-indicator');
    const status = document.getElementById('voice-bar-status');
    if (!dot || !status) return;

    // ← NEW: Reconnect button states
    if (state === 'expired' || state === 'disconnected') {
        dot.className = 'vbar-dot';  // neutral (no animation)
        const msg = state === 'expired' ? 'Session expired' : 'Connection lost';
        status.innerHTML = `${msg} &mdash; <button id="voice-reconnect-btn" class="vbar-reconnect">Reconnect</button>`;
        document.getElementById('voice-reconnect-btn')?.addEventListener('click', () => {
            stopVoiceBar();
            if (_lastVoiceData) connectVoice(_lastVoiceData);
        });
        return;
    }

    const thinkingStates = ['thinking', 'searching', 'analyzing', 'navigating'];
    const dotClass = state === 'speaking' ? ' speaking'
        : thinkingStates.includes(state) ? ' thinking'
        : state === 'reconnecting' ? ' thinking'  // ← NEW: pulse dot during reconnect
        : '';
    dot.className = 'vbar-dot' + dotClass;

    const labels = {
        listening: 'Listening\u2026',
        thinking: 'Thinking\u2026',
        searching: 'Searching the store\u2026',
        analyzing: 'Analyzing product\u2026',
        navigating: 'Opening product page\u2026',
        speaking: 'Speaking\u2026',
        reconnecting: 'Reconnecting\u2026',  // ← NEW
    };
    if (labels[state]) status.textContent = labels[state];

    if (state === 'searching' || state === 'analyzing') playNotificationTone();
    // ← CHANGED: 'reconnecting' does NOT trigger stopVoiceBar
    if (state === 'ended' || state === 'error') stopVoiceBar();
}
```

### 11. Prevent `onError` from killing reconnect (`connectVoice`, line 162)

Currently: `voiceClient.onError = () => stopVoiceBar();`

This is still correct for server-sent error messages (type: "error"). Since we removed the `onError` call from `ws.onerror` (step 6), this handler only fires for explicit server errors, not connection drops. No change needed.

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| User clicks End while reconnecting | `stop()` sets `_userInitiatedClose=true`, closes new WS if open, cleans up audio. `_reconnect()`'s `_waitForOpen` fails, catch fires, but `onclose` sees flag → `onStatus('ended')` |
| Mic stream dies during reconnect | `_reconnect()` guard throws → catch in onclose → `_cleanupAudio()` + `onStatus('disconnected')` |
| Backend completely down | Auto-reconnect fails 3 times → "Connection lost" + Reconnect button |
| Reconnect succeeds but drops again | `_reconnectAttempts` was reset to 0 on success, so gets 3 fresh retries |
| Tab closes during voice | Extension unloads, everything cleaned up by browser. No reconnect. |

## Success Criteria

### Automated
- No JS lint errors (manual `eslint` check if available)

### Manual
1. Start voice → kill backend process → voice bar shows "Reconnecting..." → restart backend → auto-reconnects, resumes listening
2. Start voice → kill backend, keep it down → 3 retries → "Connection lost" + Reconnect button
3. Start voice → click End → voice bar hides immediately, no reconnect attempt
4. Start voice → wait for Gemini expiry (~15 min) → "Session expired" + Reconnect button → click → fresh session starts
5. Start voice → click Reconnect after "Connection lost" → new session starts with correct product context
6. Start voice → disconnect network briefly → "Reconnecting..." → reconnect on network restore → audio resumes
