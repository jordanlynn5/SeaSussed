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
    this.onStatus = () => {};
    this.onScoreResult = () => {};
    this.onError = () => {};
  }

  // ── Public API ──────────────────────────────────────────

  async start() {
    // 1. Get microphone permission
    this.micStream = await navigator.mediaDevices.getUserMedia({
      audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true },
    });

    // 2. Create AudioContext (must happen after user gesture — satisfied by button click)
    this.audioContext = new AudioContext({ sampleRate: 16000 });
    this.nextPlayTime = this.audioContext.currentTime;

    // 3. Load AudioWorklet
    await this.audioContext.audioWorklet.addModule(
      chrome.runtime.getURL('audio-worklet-processor.js')
    );

    // 4. Open WebSocket to backend
    const wsUrl = BACKEND_URL
      .replace('https://', 'wss://')
      .replace('http://', 'ws://');
    this.ws = new WebSocket(wsUrl + '/voice');
    this.ws.onmessage = (event) => this._handleMessage(JSON.parse(event.data));
    this.ws.onclose = () => this.onStatus('ended');
    this.ws.onerror = () => this.onError('Connection error');
    await this._waitForOpen();

    // 5. Wire mic → AudioWorklet → WebSocket
    const source = this.audioContext.createMediaStreamSource(this.micStream);
    this.workletNode = new AudioWorkletNode(this.audioContext, 'pcm-processor');
    this.workletNode.port.onmessage = (e) => this._sendAudioChunk(e.data);
    source.connect(this.workletNode);
    // workletNode is NOT connected to destination — prevents mic echo
  }

  stop() {
    if (this.ws) {
      this.ws.send(JSON.stringify({ type: 'stop' }));
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
    const b64 = btoa(String.fromCharCode(...uint8));
    this.ws.send(JSON.stringify({ type: 'audio', data: b64 }));
  }

  async _handleMessage(msg) {
    switch (msg.type) {
      case 'audio':
        await this._playAudioChunk(msg.data);
        break;
      case 'request_screenshot':
        await this._captureAndSendScreenshot();
        break;
      case 'score_result':
        this.onScoreResult(msg.score);
        break;
      case 'status':
        this.onStatus(msg.state);
        break;
      case 'error':
        this.onError(msg.message);
        break;
      case 'ping':
        break; // no-op keepalive
    }
  }

  async _playAudioChunk(b64) {
    if (!this.audioContext) {
      return;
    }

    // Decode base64 → bytes
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }

    // Interpret as Int16 (24kHz, 16-bit PCM) → Float32
    const int16 = new Int16Array(bytes.buffer);
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

  _waitForOpen() {
    return new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = reject;
      setTimeout(() => reject(new Error('WebSocket open timed out')), 5000);
    });
  }
}
