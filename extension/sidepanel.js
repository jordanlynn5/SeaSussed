// extension/sidepanel.js

const STORAGE_KEY_ONBOARDED = 'seasussed_onboarded';

// ── Voice mode state ──
let voiceClient = null;

// ── Grade helpers ──
const GRADE_EMOJI       = { A: '🟢', B: '🟡', C: '🟠', D: '🔴' };
const SCORE_FILL_COLOR  = { A: '#16a34a', B: '#ca8a04', C: '#ea580c', D: '#dc2626' };

// --- View management ---
function showView(id) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById(id)?.classList.add('active');
}

// --- Init: check if onboarded ---
chrome.storage.local.get(STORAGE_KEY_ONBOARDED, (result) => {
  if (result[STORAGE_KEY_ONBOARDED]) {
    showView('view-idle');
  } else {
    showView('view-onboarding');
  }
});

// --- Onboarding: mark complete ---
document.getElementById('onboarding-ok')?.addEventListener('click', () => {
  chrome.storage.local.set({ [STORAGE_KEY_ONBOARDED]: true });
  showView('view-idle');
});

// ── Voice mode: start ──
document.getElementById('start-voice-btn')?.addEventListener('click', async () => {
  if (voiceClient !== null) return; // already running

  voiceClient = new VoiceClient();
  voiceClient.onStatus = (state) => updateVoiceStatus(state);
  voiceClient.onScoreResult = (score) => renderVoiceScore(score);
  voiceClient.onError = (msg) => {
    updateVoiceStatus('error');
    stopVoiceMode();
    showView('view-idle');
  };

  showView('view-voice');
  updateVoiceStatus('connecting');

  try {
    await voiceClient.start();
    updateVoiceStatus('listening');
  } catch (err) {
    console.error('[SeaSussed] Voice start failed:', err.message);
    stopVoiceMode();
    showView('view-idle');
  }
});

// ── Voice mode: stop ──
document.getElementById('stop-voice-btn')?.addEventListener('click', () => {
  stopVoiceMode();
  showView('view-idle');
});

function stopVoiceMode() {
  if (voiceClient) {
    voiceClient.stop();
    voiceClient = null;
  }
  resetVoiceView();
}

// ── Status display ──
function updateVoiceStatus(state) {
  const indicator = document.getElementById('voice-indicator');
  const statusEl  = document.getElementById('voice-status');
  if (!indicator || !statusEl) return;

  switch (state) {
    case 'connecting':
      indicator.className = 'voice-indicator';
      statusEl.textContent = 'Connecting...';
      break;
    case 'listening':
      indicator.className = 'voice-indicator';
      statusEl.textContent = 'Listening — tell me about anything on the page';
      break;
    case 'thinking':
      indicator.className = 'voice-indicator thinking';
      statusEl.textContent = 'Checking that product...';
      break;
    case 'speaking':
      indicator.className = 'voice-indicator speaking';
      statusEl.textContent = 'SeaSussed is speaking...';
      break;
    case 'ended':
      voiceClient = null; // session is dead; allow restart
      showSessionEndedPrompt();
      break;
    case 'error':
      statusEl.textContent = 'Error — tap Analyze to continue manually';
      break;
  }
}

// ── Score card render ──
function renderVoiceScore(score) {
  const card    = document.getElementById('voice-result-card');
  const badge   = document.getElementById('vc-grade-badge');
  const species = document.getElementById('vc-species');
  const fill    = document.getElementById('vc-score-fill');
  const altsEl  = document.getElementById('vc-alternatives');
  if (!card || !badge || !species || !fill || !altsEl) return;

  const grade = score.grade;
  const emoji = GRADE_EMOJI[grade] ?? '•';
  const color = SCORE_FILL_COLOR[grade] ?? '#6b7280';

  badge.className  = 'grade-badge grade-' + grade;
  badge.textContent = emoji + ' Grade ' + grade + '  ' + score.score + '/100';

  species.textContent = score.product_info?.species ?? 'Seafood product';

  fill.style.width      = score.score + '%';
  fill.style.background = color;

  altsEl.innerHTML = '';
  if (score.alternatives?.length > 0) {
    const label = document.createElement('div');
    label.className = 'alt-label';
    label.textContent = 'Try instead:';
    altsEl.appendChild(label);
    score.alternatives.slice(0, 2).forEach(alt => {
      const chip = document.createElement('span');
      chip.className = 'alt-chip';
      chip.textContent = alt.species + ' ' + (GRADE_EMOJI[alt.grade] ?? '');
      altsEl.appendChild(chip);
    });
  }

  card.style.display = 'block';
}

// ── Session ended prompt ──
// Event delegation: restart-voice-btn is injected dynamically; listen at document level.
document.addEventListener('click', (e) => {
  if (e.target?.id === 'restart-voice-btn') {
    resetVoiceView();
    document.getElementById('start-voice-btn')?.click();
  }
});

function showSessionEndedPrompt() {
  const statusEl = document.getElementById('voice-status');
  if (!statusEl) return;
  statusEl.innerHTML =
    'Session ended (15 min limit). ' +
    '<button id="restart-voice-btn" class="btn-text-link">Restart</button>';
}

function resetVoiceView() {
  const card      = document.getElementById('voice-result-card');
  const indicator = document.getElementById('voice-indicator');
  const statusEl  = document.getElementById('voice-status');
  const altsEl    = document.getElementById('vc-alternatives');
  if (card)      card.style.display      = 'none';
  if (indicator) indicator.className     = 'voice-indicator';
  if (statusEl)  statusEl.textContent    = 'Connecting...';
  if (altsEl)    altsEl.innerHTML        = '';
}

// --- Analyze button ---
document.getElementById('analyze-btn')?.addEventListener('click', async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) return;

  // Phase 5 will show a loading view here
  console.log('[SeaSussed] Analyze clicked for tab:', tab.id, tab.url);

  chrome.runtime.sendMessage(
    { type: 'ANALYZE_PAGE', tabId: tab.id, url: tab.url },
    (result) => {
      if (chrome.runtime.lastError) {
        console.error('[SeaSussed] Error:', chrome.runtime.lastError.message);
        return;
      }
      // Phase 5 will render the result here
      console.log('[SeaSussed] Result:', result);
    }
  );
});
