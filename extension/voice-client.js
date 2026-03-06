// extension/voice-client.js
// Manages the full voice session lifecycle: WebSocket connection, microphone
// capture, PCM encoding, audio playback, and screenshot bridge.
// Requires: BACKEND_URL global (from config.js, loaded before this script).

/* global BACKEND_URL */

class VoiceClient {
  constructor() {
    this.ws = null;
    this.audioContext = null;
    this.micStream = null;
    this.workletNode = null;
    this.nextPlayTime = 0;
    this._receivedFirstAudio = false;
    this.onStatus = () => {};
    this.onScoreResult = () => {};
    this.onError = () => {};
    this.onAudioActivity = () => {}; // fires each time a mic chunk is sent
  }

  // ── Public API ──────────────────────────────────────────

  async start(preAcquiredStream = null) {
    // 1. Get microphone (use pre-acquired stream if provided to avoid re-requesting permission)
    console.log('[SeaSussed] VoiceClient.start() — acquiring mic…');
    this.micStream = preAcquiredStream ?? await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true },
    });
    console.log('[SeaSussed] Mic acquired, tracks:', this.micStream.getTracks().map(t => t.readyState));

    // 2. Create AudioContext for playback (24kHz to match Gemini output)
    this.audioContext = new AudioContext({ sampleRate: 24000 });
    if (this.audioContext.state === 'suspended') {
      console.log('[SeaSussed] AudioContext suspended, resuming…');
      await this.audioContext.resume();
    }
    console.log('[SeaSussed] AudioContext state:', this.audioContext.state, 'sampleRate:', this.audioContext.sampleRate);
    this.nextPlayTime = this.audioContext.currentTime;

    // 3. Separate AudioContext for mic capture at 16kHz
    this._micContext = new AudioContext({ sampleRate: 16000 });
    if (this._micContext.state === 'suspended') {
      await this._micContext.resume();
    }

    // 4. Load AudioWorklet on the mic context
    await this._micContext.audioWorklet.addModule(
      chrome.runtime.getURL('audio-worklet-processor.js')
    );
    console.log('[SeaSussed] AudioWorklet loaded');

    // 5. Open WebSocket to backend
    const wsUrl = BACKEND_URL
      .replace('https://', 'wss://')
      .replace('http://', 'ws://');
    console.log('[SeaSussed] Opening WebSocket to', wsUrl + '/voice');
    this.ws = new WebSocket(wsUrl + '/voice');
    await this._waitForOpen();
    console.log('[SeaSussed] WebSocket connected');

    // 6. Set up message and lifecycle handlers (AFTER _waitForOpen so they aren't overwritten)
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
    this.ws.onclose = (event) => {
      console.warn('[SeaSussed] WebSocket closed — code:', event.code, 'reason:', event.reason || '(none)');
      this.onStatus('ended');
    };
    this.ws.onerror = (event) => {
      console.error('[SeaSussed] WebSocket error:', event);
      this.onError('Connection error');
    };

    // 7. Wire mic → AudioWorklet → WebSocket
    const source = this._micContext.createMediaStreamSource(this.micStream);
    this.workletNode = new AudioWorkletNode(this._micContext, 'pcm-processor');
    this.workletNode.port.onmessage = (e) => this._sendAudioChunk(e.data);
    source.connect(this.workletNode);
    // workletNode is NOT connected to destination — prevents mic echo
    console.log('[SeaSussed] Mic wired to worklet, audio flowing');
  }

  sendResultContext(ctx) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify({ type: 'result_context', ...ctx }));
  }

  stop() {
    if (this.ws) {
      if (this.ws.readyState === WebSocket.OPEN) {
        try { this.ws.send(JSON.stringify({ type: 'stop' })); } catch (_) {}
      }
      this.ws.close();
      this.ws = null;
    }
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

  // ── Private Methods ──────────────────────────────────────

  _sendAudioChunk(arrayBuffer) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return;
    }
    const uint8 = new Uint8Array(arrayBuffer);
    // Build base64 in chunks to avoid stack overflow with spread operator
    let binary = '';
    for (let i = 0; i < uint8.length; i++) {
      binary += String.fromCharCode(uint8[i]);
    }
    const b64 = btoa(binary);
    this.ws.send(JSON.stringify({ type: 'audio', data: b64 }));
    this.onAudioActivity();
  }

  async _handleMessage(msg) {
    switch (msg.type) {
      case 'audio':
        if (!this._receivedFirstAudio) {
          this._receivedFirstAudio = true;
          console.log('[SeaSussed] First audio chunk from server');
          this.onStatus('speaking');
        }
        this._playAudioChunk(msg.data);
        break;
      case 'request_screenshot':
        await this._captureAndSendScreenshot();
        break;
      case 'search_store':
        await this._searchStoreAndSend(msg.query);
        break;
      case 'score_result':
        this.onScoreResult(msg.score);
        break;
      case 'status':
        console.log('[SeaSussed] Status from server:', msg.state);
        if (msg.state === 'listening') this._receivedFirstAudio = false;
        if (msg.state !== 'connecting') this.onStatus(msg.state);
        break;
      case 'error':
        console.error('[SeaSussed] Error from server:', msg.message);
        this.onError(msg.message);
        break;
      case 'ping':
        break; // no-op keepalive
    }
  }

  _playAudioChunk(b64) {
    if (!this.audioContext || this.audioContext.state === 'closed') {
      return;
    }

    try {
      // Decode base64 -> bytes
      const binary = atob(b64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
      }

      // Ensure even byte length for Int16 conversion
      const usableLength = bytes.length & ~1;
      if (usableLength === 0) return;

      // Interpret as Int16 (24kHz, 16-bit PCM) -> Float32
      const int16 = new Int16Array(bytes.buffer, 0, usableLength / 2);
      const float32 = new Float32Array(int16.length);
      for (let i = 0; i < int16.length; i++) {
        float32[i] = int16[i] / 32768.0;
      }

      // Create AudioBuffer (24kHz, mono) and schedule gapless playback
      const buffer = this.audioContext.createBuffer(1, float32.length, 24000);
      buffer.getChannelData(0).set(float32);

      const source = this.audioContext.createBufferSource();
      source.buffer = buffer;
      source.connect(this.audioContext.destination);

      const startTime = Math.max(this.audioContext.currentTime, this.nextPlayTime);
      source.start(startTime);
      this.nextPlayTime = startTime + buffer.duration;
    } catch (err) {
      console.warn('[SeaSussed] Audio playback error (non-fatal):', err.message);
    }
  }

  async _captureAndSendScreenshot() {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    const tab = tabs[0];
    if (!tab?.id) {
      return;
    }

    const result = await chrome.runtime.sendMessage({
      type: 'CAPTURE_SCREENSHOT_FOR_VOICE',
      tabId: tab.id,
      url: tab.url,
      pageTitle: tab.title ?? '',
    });

    if (result.error) {
      this.ws.send(JSON.stringify({
        type: 'screenshot',
        data: '',
        url: tab.url ?? '',
        page_title: tab.title ?? '',
        related_products: [],
        error: result.error,
      }));
      return;
    }

    this.ws.send(JSON.stringify({
      type: 'screenshot',
      data: result.screenshot,
      url: result.url,
      page_title: result.page_title,
      related_products: result.related_products,
    }));
  }

  async _searchStoreAndSend(query) {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    const tab = tabs[0];
    if (!tab?.id) return;

    const result = await chrome.runtime.sendMessage({
      type: 'SEARCH_STORE_FOR_VOICE',
      tabId: tab.id,
      url: tab.url,
      query,
    });

    if (result.error) {
      this.ws.send(JSON.stringify({
        type: 'search_results',
        data: '',
        url: '',
        page_title: '',
        error: result.error,
      }));
      return;
    }

    this.ws.send(JSON.stringify({
      type: 'search_results',
      data: result.screenshot,
      url: result.url,
      page_title: result.page_title,
      page_text: result.page_text || '',
    }));
  }

  _waitForOpen() {
    return new Promise((resolve, reject) => {
      const cleanup = () => {
        clearTimeout(timer);
      };
      const timer = setTimeout(() => {
        cleanup();
        reject(new Error('WebSocket open timed out'));
      }, 5000);
      this.ws.onopen = () => {
        cleanup();
        resolve();
      };
      this.ws.onerror = (event) => {
        cleanup();
        reject(new Error('WebSocket connection failed'));
      };
      this.ws.onclose = (event) => {
        cleanup();
        reject(new Error(`WebSocket closed during connect: code=${event.code}`));
      };
    });
  }
}
