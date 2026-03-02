// extension/sidepanel.js

const STORAGE_KEY_ONBOARDED = 'seasussed_onboarded';

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
