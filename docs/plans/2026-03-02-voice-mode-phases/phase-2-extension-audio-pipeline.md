# Phase 2: Extension Audio Pipeline + WebSocket Client

**[batch-eligible with Phase 1]** — touches only extension files; protocol is pre-defined in the parent plan.

Adds browser-side audio capture (microphone → PCM), WebSocket client to backend, screenshot capture bridge to background.js, and audio playback of Gemini's responses. No UI changes — those are Phase 3.

---

## Files Changed

- **NEW** `extension/audio-worklet-processor.js`
- **NEW** `extension/voice-client.js`
- **MODIFY** `extension/background.js`

---

## `extension/audio-worklet-processor.js` (new)

AudioWorklet runs in a dedicated audio rendering thread. Receives Float32 audio frames from the browser's audio pipeline, converts to Int16 PCM (required by Gemini Live API), and posts to the main thread for WebSocket transmission.

```pseudocode
# Must be a standalone file (AudioWorklet cannot import modules)

CLASS PcmProcessor extends AudioWorkletProcessor:
  CONSTRUCTOR:
    super()
    this.bufferSize = 1600      # 100ms @ 16kHz
    this.buffer = new Int16Array(this.bufferSize)
    this.bufferIndex = 0

  METHOD process(inputs, outputs, parameters):
    IF inputs[0] is empty OR inputs[0][0] is empty:
      RETURN true

    channel = inputs[0][0]  # Float32Array, one channel

    FOR EACH float_sample IN channel:
      # Clamp and convert Float32 [-1.0, 1.0] to Int16 [-32768, 32767]
      clamped = Math.max(-1.0, Math.min(1.0, float_sample))
      int16_sample = Math.round(clamped * 32767)
      this.buffer[this.bufferIndex] = int16_sample
      this.bufferIndex++

      IF this.bufferIndex >= this.bufferSize:
        # Post chunk to main thread
        # Transfer the buffer (zero-copy) then reset
        chunk = new Int16Array(this.buffer)
        this.port.postMessage(chunk.buffer, [chunk.buffer])
        this.buffer = new Int16Array(this.bufferSize)
        this.bufferIndex = 0

    RETURN true  # keep processor alive

registerProcessor('pcm-processor', PcmProcessor)
```

---

## `extension/voice-client.js` (new)

Manages the full voice session lifecycle: WebSocket connection, microphone capture, PCM encoding, audio playback, and screenshot bridge. Exports a `VoiceClient` class for use by `sidepanel.js`.

```pseudocode
# extension/voice-client.js

IMPORT BACKEND_URL from config.js

CLASS VoiceClient:
  FIELDS:
    ws: WebSocket | null = null
    audioContext: AudioContext | null = null
    micStream: MediaStream | null = null
    workletNode: AudioWorkletNode | null = null
    nextPlayTime: number = 0
    onStatus: function(state: string) = noop
    onScoreResult: function(score: object) = noop
    onError: function(message: string) = noop

  # ── Public API ──────────────────────────────────────────

  ASYNC METHOD start():
    # 1. Get microphone permission
    this.micStream = await navigator.mediaDevices.getUserMedia({
      audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true }
    })
    # getUserMedia may return a different sample rate depending on hardware.
    # The AudioWorklet always posts 16kHz-equivalent buffers; actual resampling
    # is handled by the browser before the audio reaches the worklet.

    # 2. Create AudioContext (must happen after user gesture — satisfied by button click)
    this.audioContext = new AudioContext({ sampleRate: 16000 })
    this.nextPlayTime = this.audioContext.currentTime

    # 3. Load AudioWorklet
    await this.audioContext.audioWorklet.addModule(
      chrome.runtime.getURL('audio-worklet-processor.js')
    )

    # 4. Open WebSocket to backend
    wsUrl = BACKEND_URL.replace('https://', 'wss://').replace('http://', 'ws://')
    this.ws = new WebSocket(wsUrl + '/voice')
    this.ws.onmessage = (event) => this._handleMessage(JSON.parse(event.data))
    this.ws.onclose = () => this.onStatus('ended')
    this.ws.onerror = (e) => this.onError('Connection error')
    await this._waitForOpen()

    # 5. Wire mic → AudioWorklet → WebSocket
    source = this.audioContext.createMediaStreamSource(this.micStream)
    this.workletNode = new AudioWorkletNode(this.audioContext, 'pcm-processor')
    this.workletNode.port.onmessage = (e) => this._sendAudioChunk(e.data)
    source.connect(this.workletNode)
    # Note: workletNode is NOT connected to audioContext.destination — we don't
    # want mic audio playing back to the user (echo prevention)

  METHOD stop():
    IF this.ws:
      this.ws.send(JSON.stringify({"type": "stop"}))
      this.ws.close()
      this.ws = null
    IF this.workletNode:
      this.workletNode.disconnect()
      this.workletNode = null
    IF this.micStream:
      this.micStream.getTracks().forEach(t => t.stop())
      this.micStream = null
    IF this.audioContext:
      this.audioContext.close()
      this.audioContext = null

  # ── Private Methods ──────────────────────────────────────

  METHOD _sendAudioChunk(arrayBuffer: ArrayBuffer):
    IF NOT this.ws OR this.ws.readyState !== WebSocket.OPEN:
      RETURN
    # Base64-encode the raw PCM bytes
    uint8 = new Uint8Array(arrayBuffer)
    b64 = btoa(String.fromCharCode(...uint8))
    this.ws.send(JSON.stringify({"type": "audio", "data": b64}))

  ASYNC METHOD _handleMessage(msg: object):
    SWITCH msg.type:
      CASE "audio":
        await this._playAudioChunk(msg.data)  # base64 PCM 24kHz 16-bit

      CASE "request_screenshot":
        await this._captureAndSendScreenshot()

      CASE "score_result":
        this.onScoreResult(msg.score)

      CASE "status":
        this.onStatus(msg.state)

      CASE "error":
        this.onError(msg.message)

      CASE "ping":
        PASS  # no-op keepalive

  ASYNC METHOD _playAudioChunk(b64: string):
    IF NOT this.audioContext:
      RETURN

    # Decode base64 → Int16Array (24kHz, 16-bit)
    binary = atob(b64)
    bytes = new Uint8Array(binary.length)
    FOR i FROM 0 TO binary.length - 1:
      bytes[i] = binary.charCodeAt(i)

    int16 = new Int16Array(bytes.buffer)

    # Convert Int16 → Float32
    float32 = new Float32Array(int16.length)
    FOR i FROM 0 TO int16.length - 1:
      float32[i] = int16[i] / 32768.0

    # Create AudioBuffer (24kHz, mono)
    buffer = this.audioContext.createBuffer(1, float32.length, 24000)
    buffer.getChannelData(0).set(float32)

    # Schedule gapless playback
    source = this.audioContext.createBufferSource()
    source.buffer = buffer
    source.connect(this.audioContext.destination)

    startTime = Math.max(this.audioContext.currentTime, this.nextPlayTime)
    source.start(startTime)
    this.nextPlayTime = startTime + buffer.duration

  ASYNC METHOD _captureAndSendScreenshot():
    # Ask background.js to capture the tab (can't do it from side panel directly)
    tabs = await chrome.tabs.query({ active: true, currentWindow: true })
    tab = tabs[0]
    IF NOT tab?.id:
      RETURN

    result = await chrome.runtime.sendMessage({
      type: 'CAPTURE_SCREENSHOT_FOR_VOICE',
      tabId: tab.id,
      url: tab.url,
      pageTitle: tab.title ?? '',
    })

    IF result.error:
      this.ws.send(JSON.stringify({
        "type": "screenshot",
        "data": "",
        "url": tab.url ?? "",
        "page_title": tab.title ?? "",
        "related_products": [],
        "error": result.error
      }))
      RETURN

    this.ws.send(JSON.stringify({
      "type": "screenshot",
      "data": result.screenshot,
      "url": result.url,
      "page_title": result.page_title,
      "related_products": result.related_products,
    }))

  ASYNC METHOD _waitForOpen():
    RETURN new Promise((resolve, reject) =>
      this.ws.onopen = resolve
      this.ws.onerror = reject
      // 5s timeout
      setTimeout(() => reject(new Error('WebSocket open timed out')), 5000)
    )
```

---

## `extension/background.js` (modify)

Add handler for `CAPTURE_SCREENSHOT_FOR_VOICE`. Reuse existing screenshot + DOM scraping logic.

```pseudocode
# ADD to the chrome.runtime.onMessage.addListener handler:

IF msg.type === 'CAPTURE_SCREENSHOT_FOR_VOICE':
  captureScreenshotForVoice(msg.tabId, msg.url, msg.pageTitle)
    .then(sendResponse)
    .catch(err => sendResponse({ error: err.message }))
  RETURN true  # async

DEFINE ASYNC captureScreenshotForVoice(tabId, url, pageTitle):
  # 1. Capture screenshot (reuse existing pattern)
  dataUrl = await captureVisibleTab()
  base64 = dataUrl.split(',')[1]

  # 2. Scrape related products (reuse existing function)
  domData = await chrome.scripting.executeScript({
    target: { tabId: tabId },
    func: scrapeRelatedProducts,
  })
  relatedProducts = domData[0]?.result ?? []

  RETURN {
    screenshot: base64,
    url: url,
    page_title: pageTitle,
    related_products: relatedProducts,
  }

# EXTRACT captureVisibleTab() as a named function if not already:
DEFINE ASYNC captureVisibleTab():
  RETURN new Promise((resolve, reject) =>
    chrome.tabs.captureVisibleTab(null, { format: 'png' }, (result) =>
      IF chrome.runtime.lastError: reject(new Error(chrome.runtime.lastError.message))
      ELSE: resolve(result)
    )
  )

# NOTE: scrapeRelatedProducts() already exists — no changes needed
```

---

## Success Criteria

### Automated
Manual testing only for browser code (no JS test runner in this project).

### Manual
- [ ] Load extension → open DevTools in side panel → no errors on load
- [ ] `new VoiceClient()` in DevTools console → `client.start()` → browser mic permission prompt appears
- [ ] After permission granted: WebSocket connection opens (check Network tab → WS frames)
- [ ] Speaking into mic → audio frames visible in WS frames (base64 JSON messages)
- [ ] Mock `score_result` JSON sent from backend → `onScoreResult` callback fires
- [ ] `client.stop()` → mic track stops, WebSocket closes cleanly
- [ ] `CAPTURE_SCREENSHOT_FOR_VOICE` message from DevTools → returns `{ screenshot, url, related_products }` object
