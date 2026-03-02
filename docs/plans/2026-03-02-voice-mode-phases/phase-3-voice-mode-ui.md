# Phase 3: Voice Mode UI

**Depends on Phases 1 and 2.** Adds the voice mode view to the side panel and wires up `VoiceClient` to the UI. The user experience: a mic button starts the voice session; a pulsing indicator shows listening/speaking states; the score card appears as each product is analyzed; an "End session" button stops everything.

---

## Files Changed

- **MODIFY** `extension/sidepanel.html` — add voice mode view + styles
- **MODIFY** `extension/sidepanel.js` — voice mode controller

---

## `extension/sidepanel.html` (modify)

### New view: `view-voice`

```pseudocode
# ADD to <head> <style>:

/* ── Voice Mode ── */
.voice-mode { padding: 16px; display: flex; flex-direction: column; gap: 12px; }

/* Mic indicator — pulsing rings */
.voice-indicator {
  width: 64px; height: 64px; border-radius: 50%;
  background: #1a73e8; margin: 0 auto;
  position: relative; display: flex; align-items: center; justify-content: center;
}
.voice-indicator::before, .voice-indicator::after {
  content: ''; position: absolute;
  border-radius: 50%; border: 2px solid #1a73e8;
  animation: pulse 1.5s ease-out infinite;
}
.voice-indicator::before { width: 80px; height: 80px; }
.voice-indicator::after  { width: 96px; height: 96px; animation-delay: 0.3s; }
@keyframes pulse {
  0%   { transform: scale(1); opacity: 0.7; }
  100% { transform: scale(1.2); opacity: 0; }
}
.voice-indicator.speaking { background: #34a853; }
.voice-indicator.speaking::before,
.voice-indicator.speaking::after { border-color: #34a853; }
.voice-indicator.thinking { background: #fbbc04; animation: none; }

/* Status label */
.voice-status { text-align: center; font-size: 13px; color: #6b7280; }

/* Voice result card — compact version of the full score */
.voice-result-card {
  background: white; border-radius: 10px;
  border: 1px solid #e5e7eb; padding: 12px;
}
.voice-result-card .grade-badge {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 20px; font-weight: 700;
}
.voice-result-card .grade-A { color: #166534; }
.voice-result-card .grade-B { color: #854d0e; }
.voice-result-card .grade-C { color: #92400e; }
.voice-result-card .grade-D { color: #991b1b; }
.voice-result-card .species-name { font-size: 13px; color: #374151; margin-top: 4px; }
.voice-result-card .score-bar-wrap { margin-top: 8px; }
.voice-result-card .score-bar {
  height: 6px; border-radius: 3px; background: #e5e7eb;
}
.voice-result-card .score-bar-fill { height: 100%; border-radius: 3px; }
.voice-result-card .alt-chip {
  display: inline-block; font-size: 11px; padding: 2px 8px;
  border-radius: 12px; background: #eff6ff; color: #1d4ed8;
  margin-top: 6px; margin-right: 4px;
}

/* Stop button */
.btn-stop {
  width: 100%; padding: 10px; background: transparent;
  border: 1px solid #d1d5db; border-radius: 8px;
  color: #6b7280; font-size: 13px; cursor: pointer;
}
.btn-stop:hover { background: #f9fafb; }
```

### New `view-voice` div

```pseudocode
# ADD before the closing </body> tag (after existing views):

<div class="view voice-mode" id="view-voice">

  <!-- Mic indicator -->
  <div class="voice-indicator" id="voice-indicator">
    🎤
  </div>
  <div class="voice-status" id="voice-status">Connecting...</div>

  <!-- Score card (hidden until first result) -->
  <div class="voice-result-card" id="voice-result-card" style="display:none">
    <div class="grade-badge" id="vc-grade-badge">—</div>
    <div class="species-name" id="vc-species">—</div>
    <div class="score-bar-wrap">
      <div class="score-bar">
        <div class="score-bar-fill" id="vc-score-fill" style="width:0%"></div>
      </div>
    </div>
    <div id="vc-alternatives"></div>
  </div>

  <!-- Stop button -->
  <button class="btn-stop" id="stop-voice-btn">End voice session</button>

</div>

# ADD "Start Voice Mode" button in the existing idle view:
# Find: <button class="btn-primary" id="analyze-btn">Analyze This Page</button>
# ADD AFTER:
<button class="btn-secondary" id="start-voice-btn"
  style="width:100%; padding:10px; margin-top:8px; background:transparent;
         border:1px solid #1a73e8; border-radius:8px; color:#1a73e8;
         font-size:14px; font-weight:500; cursor:pointer;">
  🎤 Start Voice Mode
</button>

# ADD script tag before </body>:
<script src="voice-client.js"></script>
```

---

## `extension/sidepanel.js` (modify)

```pseudocode
# ADD at top:
let voiceClient = null  # VoiceClient instance, null when not in voice mode

# ── Grade helpers ──
GRADE_EMOJI = { "A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴" }
GRADE_LABEL  = { "A": "Best Choice", "B": "Good Alternative", "C": "Use Caution", "D": "Avoid" }
SCORE_FILL_COLOR = { "A": "#16a34a", "B": "#ca8a04", "C": "#ea580c", "D": "#dc2626" }

# ── Voice mode: start ──

document.getElementById('start-voice-btn')?.addEventListener('click', async () => {
  IF voiceClient IS NOT null: RETURN  # already running

  voiceClient = new VoiceClient()
  voiceClient.onStatus = (state) => updateVoiceStatus(state)
  voiceClient.onScoreResult = (score) => renderVoiceScore(score)
  voiceClient.onError = (msg) => {
    showVoiceStatus('error', 'Connection failed — ' + msg)
    stopVoiceMode()
  }

  showView('view-voice')
  updateVoiceStatus('connecting')

  TRY:
    await voiceClient.start()
    updateVoiceStatus('listening')
  CATCH (err):
    # Mic permission denied or WebSocket failed
    showVoiceError(err.message)
    stopVoiceMode()
    showView('view-idle')
})

# ── Voice mode: stop ──

document.getElementById('stop-voice-btn')?.addEventListener('click', () => {
  stopVoiceMode()
  showView('view-idle')
})

DEFINE stopVoiceMode():
  IF voiceClient:
    voiceClient.stop()
    voiceClient = null
  resetVoiceView()

# ── Status display ──

DEFINE updateVoiceStatus(state: string):
  indicator = document.getElementById('voice-indicator')
  statusEl  = document.getElementById('voice-status')

  SWITCH state:
    CASE 'connecting':
      indicator.className = 'voice-indicator'
      statusEl.textContent = 'Connecting...'
    CASE 'listening':
      indicator.className = 'voice-indicator'
      statusEl.textContent = 'Listening — tell me about anything on the page'
    CASE 'thinking':
      indicator.className = 'voice-indicator thinking'
      statusEl.textContent = 'Checking that product...'
    CASE 'speaking':
      indicator.className = 'voice-indicator speaking'
      statusEl.textContent = 'SeaSussed is speaking...'
    CASE 'ended':
      statusEl.textContent = 'Session ended'
      showSessionEndedPrompt()
    CASE 'error':
      statusEl.textContent = 'Error — tap Analyze to continue manually'

# ── Score card render ──

DEFINE renderVoiceScore(score: SustainabilityScore):
  card   = document.getElementById('voice-result-card')
  badge  = document.getElementById('vc-grade-badge')
  species = document.getElementById('vc-species')
  fill   = document.getElementById('vc-score-fill')
  altsEl = document.getElementById('vc-alternatives')

  grade = score.grade
  emoji = GRADE_EMOJI[grade] ?? '•'
  label = GRADE_LABEL[grade] ?? ''
  color = SCORE_FILL_COLOR[grade] ?? '#6b7280'

  badge.className = 'grade-badge grade-' + grade
  badge.textContent = emoji + ' Grade ' + grade + '  ' + score.score + '/100'

  species.textContent = score.product_info.species ?? 'Seafood product'

  fill.style.width = score.score + '%'
  fill.style.background = color

  # Alternatives chips
  altsEl.innerHTML = ''
  IF score.alternatives.length > 0:
    altsEl.innerHTML = '<div style="font-size:11px;color:#6b7280;margin-top:6px">Try instead:</div>'
    score.alternatives.slice(0, 2).forEach(alt =>
      altsEl.innerHTML += '<span class="alt-chip">' + alt.species + ' ' + GRADE_EMOJI[alt.grade] + '</span>'
    )

  card.style.display = 'block'

# ── Session ended prompt ──

DEFINE showSessionEndedPrompt():
  statusEl = document.getElementById('voice-status')
  statusEl.innerHTML = '''
    Session ended (15 min limit).
    <button id="restart-voice-btn"
      style="color:#1a73e8;background:none;border:none;cursor:pointer;font-size:13px;">
      Restart
    </button>
  '''
  document.getElementById('restart-voice-btn')?.addEventListener('click', () => {
    resetVoiceView()
    document.getElementById('start-voice-btn').click()
  })

DEFINE resetVoiceView():
  document.getElementById('voice-result-card').style.display = 'none'
  document.getElementById('voice-indicator').className = 'voice-indicator'
  document.getElementById('voice-status').textContent = 'Connecting...'
  document.getElementById('vc-alternatives').innerHTML = ''
```

---

## UX State Machine

```
[idle view]
  click "Start Voice Mode"
  → request mic permission
  → if denied: stay in idle view, show tooltip "Microphone access needed"
  → if granted: open WebSocket
  → show [voice view] with "Connecting..." state

[voice view — connecting]
  WebSocket opens + Gemini session starts
  → state: "listening"

[voice view — listening]
  pulsing blue mic indicator
  user speaks naturally
  → Gemini detects seafood cue → tool call fired
  → state: "thinking"

[voice view — thinking]
  amber indicator (no pulse)
  backend: screenshot captured, pipeline run
  → score_result sent to browser → score card renders
  → tool response sent to Gemini → Gemini starts speaking
  → state: "speaking"

[voice view — speaking]
  green pulsing indicator
  audio plays from speaker
  score card visible
  → when Gemini stops speaking: state: "listening"

[voice view — ended]
  WebSocket closed (timeout or error)
  "Session ended" + Restart button shown
  click Restart → restart VoiceClient
  or click "End voice session" → idle view
```

---

## Success Criteria

### Automated
Manual testing only (browser UI).

### Manual
- [ ] Idle view shows both "Analyze This Page" and "Start Voice Mode" buttons
- [ ] Click "Start Voice Mode" → mic permission prompt → grant → side panel switches to voice view
- [ ] Voice view shows blue pulsing mic indicator and "Listening..." status
- [ ] Speak "what about this salmon?" on a Whole Foods product page:
  - [ ] Indicator turns amber ("Checking that product...")
  - [ ] Within ~3 seconds, score card appears in panel
  - [ ] Gemini speaks a response (audible from speakers)
  - [ ] Indicator turns green while Gemini speaks
  - [ ] Indicator returns to blue pulsing ("listening") when done
- [ ] Score card shows: correct grade emoji, score/100, species name, top 2 alternatives
- [ ] Navigate to a different product page → voice session remains active → can score the new product
- [ ] Click "End voice session" → returns to idle view → Analyze button works normally
- [ ] If mic permission denied: stays on idle view, no crash
