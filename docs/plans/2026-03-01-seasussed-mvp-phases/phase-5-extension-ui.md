# Phase 5: Extension UI Integration

**Days:** 5–8 | **Depends on:** Phase 2 (extension scaffold), Phase 4 (API contract) | **Blocks:** Phase 6

---

## Steps

### 1. Update background.js — Full Flow

```javascript
// extension/background.js (full version replacing scaffold)
importScripts('config.js');

// Track active analyses to prevent duplicate calls
const pendingTabs = new Set();

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'ANALYZE_PAGE') {
    const tabId = sender.tab?.id || msg.tabId;
    if (!tabId) return;
    if (pendingTabs.has(tabId)) return; // already analyzing

    pendingTabs.add(tabId);
    handleAnalyze(tabId, msg.url)
      .then(result => {
        pendingTabs.delete(tabId);
        if (result.product_info?.is_seafood === false) {
          chrome.tabs.sendMessage(tabId, { type: 'NOT_SEAFOOD' });
        } else {
          chrome.tabs.sendMessage(tabId, { type: 'SCORE_RESULT', data: result });
        }
        sendResponse(result);
      })
      .catch(err => {
        pendingTabs.delete(tabId);
        chrome.tabs.sendMessage(tabId, { type: 'SCORE_ERROR', error: err.message });
        sendResponse({ error: err.message });
      });
    return true;
  }
});

async function handleAnalyze(tabId, url) {
  // Notify content script: analysis starting
  chrome.tabs.sendMessage(tabId, { type: 'SCORE_LOADING' });

  const dataUrl = await new Promise((resolve, reject) => {
    chrome.tabs.captureVisibleTab(null, { format: 'png' }, (url) => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else resolve(url);
    });
  });

  const base64 = dataUrl.split(',')[1];

  const response = await fetch(`${BACKEND_URL}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ screenshot: base64, url: url }),
    signal: AbortSignal.timeout(15000), // 15s timeout
  });

  if (!response.ok) {
    const errText = await response.text();
    throw new Error(`Backend ${response.status}: ${errText.substring(0, 100)}`);
  }

  return await response.json();
}
```

### 2. content_script.js — Full Overlay

Use Shadow DOM to prevent CSS conflicts with the grocery site.

```javascript
// extension/content_script.js (full version)

let shadowHost = null;

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'SCORE_RESULT') renderOverlay(msg.data);
  if (msg.type === 'SCORE_LOADING') renderLoading();
  if (msg.type === 'SCORE_ERROR') renderError(msg.error);
  if (msg.type === 'NOT_SEAFOOD') removeOverlay();
});

function getOrCreateShadowHost() {
  if (shadowHost && document.body.contains(shadowHost)) return shadowHost;

  shadowHost = document.createElement('div');
  shadowHost.id = 'seasussed-root';
  shadowHost.style.cssText = `
    position: fixed;
    bottom: 24px;
    right: 24px;
    z-index: 2147483647;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  `;
  document.body.appendChild(shadowHost);
  return shadowHost;
}

function getOrCreateShadow() {
  const host = getOrCreateShadowHost();
  if (!host.shadowRoot) host.attachShadow({ mode: 'open' });
  return host.shadowRoot;
}

const GRADE_COLORS = { A: '#22c55e', B: '#eab308', C: '#f97316', D: '#ef4444' };
const GRADE_LABELS = { A: 'Best Choice', B: 'Good Alternative', C: 'Use Caution', D: 'Avoid' };
const GRADE_EMOJI  = { A: '🟢', B: '🟡', C: '🟠', D: '🔴' };

function renderLoading() {
  const shadow = getOrCreateShadow();
  shadow.innerHTML = `
    <style>
      .panel { background: white; border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.18);
               padding: 16px; min-width: 220px; }
      .spinner { display: flex; align-items: center; gap: 10px; color: #555; font-size: 14px; }
      .spin { width: 20px; height: 20px; border: 3px solid #e5e7eb;
              border-top-color: #3b82f6; border-radius: 50%;
              animation: rotate 0.8s linear infinite; }
      @keyframes rotate { to { transform: rotate(360deg); } }
    </style>
    <div class="panel">
      <div class="spinner"><div class="spin"></div> Analyzing seafood…</div>
    </div>
  `;
}

function renderError(message) {
  const shadow = getOrCreateShadow();
  shadow.innerHTML = `
    <style>
      .panel { background: white; border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.18);
               padding: 16px; max-width: 280px; cursor: pointer; }
      .err { color: #ef4444; font-size: 13px; }
    </style>
    <div class="panel" id="close-btn">
      <div class="err">⚠️ Analysis failed.<br><small>${message}</small></div>
    </div>
  `;
  shadow.getElementById('close-btn').addEventListener('click', removeOverlay);
}

function renderOverlay(data) {
  const shadow = getOrCreateShadow();
  const { score, grade, breakdown, alternatives, explanation, product_info } = data;
  const color = GRADE_COLORS[grade];
  const label = GRADE_LABELS[grade];
  const emoji = GRADE_EMOJI[grade];

  shadow.innerHTML = `
    <style>
      * { box-sizing: border-box; margin: 0; padding: 0; }
      .badge { display: flex; align-items: center; gap: 10px; background: white;
               border-radius: 50px; box-shadow: 0 4px 20px rgba(0,0,0,0.15);
               padding: 10px 16px; cursor: pointer; transition: box-shadow 0.2s; }
      .badge:hover { box-shadow: 0 6px 24px rgba(0,0,0,0.2); }
      .grade { width: 40px; height: 40px; border-radius: 50%; background: ${color};
               color: white; display: flex; align-items: center; justify-content: center;
               font-weight: 700; font-size: 18px; }
      .badge-text { display: flex; flex-direction: column; }
      .badge-label { font-size: 11px; color: #888; font-weight: 500; letter-spacing: 0.3px; }
      .badge-score { font-size: 14px; font-weight: 600; color: #1f2937; }
      .close-btn { margin-left: auto; color: #ccc; cursor: pointer; font-size: 18px; line-height: 1; }
      .close-btn:hover { color: #888; }

      .panel { background: white; border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.18);
               padding: 16px; max-width: 320px; margin-top: 8px; display: none; }
      .panel.open { display: block; }
      .species { font-size: 15px; font-weight: 600; color: #111; margin-bottom: 4px; }
      .sub { font-size: 12px; color: #888; margin-bottom: 12px; }
      .explanation { font-size: 13px; color: #374151; line-height: 1.5; margin-bottom: 12px;
                     padding: 10px; background: #f9fafb; border-radius: 8px; }

      .section-title { font-size: 11px; font-weight: 600; color: #888;
                       text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }
      .score-row { display: flex; justify-content: space-between; align-items: center;
                   padding: 4px 0; font-size: 13px; border-bottom: 1px solid #f3f4f6; }
      .score-row:last-child { border-bottom: none; }
      .score-label { color: #555; }
      .score-val { font-weight: 600; color: #1f2937; }

      .alts-title { font-size: 11px; font-weight: 600; color: #888;
                    text-transform: uppercase; letter-spacing: 0.5px;
                    margin-top: 12px; margin-bottom: 6px; }
      .alt { display: flex; justify-content: space-between; align-items: start;
             padding: 6px 0; border-bottom: 1px solid #f3f4f6; }
      .alt:last-child { border-bottom: none; }
      .alt-name { font-size: 13px; font-weight: 500; color: #1f2937; }
      .alt-reason { font-size: 11px; color: #888; margin-top: 2px; }
      .alt-grade { font-size: 12px; font-weight: 700; padding: 2px 6px; border-radius: 10px;
                   color: white; flex-shrink: 0; margin-left: 8px; }
    </style>

    <div class="badge" id="badge">
      <div class="grade">${grade}</div>
      <div class="badge-text">
        <span class="badge-label">${emoji} ${label}</span>
        <span class="badge-score">${score}/100 · SeaSussed</span>
      </div>
      <span class="close-btn" id="close">×</span>
    </div>

    <div class="panel" id="panel">
      <div class="species">${product_info.species || 'Unknown species'}</div>
      <div class="sub">
        ${product_info.wild_or_farmed !== 'unknown' ? product_info.wild_or_farmed + ' · ' : ''}
        ${product_info.origin_region || ''}
        ${product_info.fishing_method ? '· ' + product_info.fishing_method : ''}
      </div>

      <div class="explanation">${explanation}</div>

      <div class="section-title">Score Breakdown</div>
      ${renderBreakdownRows(breakdown, product_info.wild_or_farmed)}

      ${alternatives.length > 0 ? `
        <div class="alts-title">Better Alternatives</div>
        ${alternatives.map(alt => `
          <div class="alt">
            <div>
              <div class="alt-name">${alt.species}</div>
              <div class="alt-reason">${alt.reason}</div>
            </div>
            <span class="alt-grade" style="background:${GRADE_COLORS[alt.grade]}">${alt.grade}</span>
          </div>
        `).join('')}
      ` : ''}
    </div>
  `;

  // Toggle panel on badge click
  const badge = shadow.getElementById('badge');
  const panel = shadow.getElementById('panel');
  badge.addEventListener('click', (e) => {
    if (e.target.id === 'close') { removeOverlay(); return; }
    panel.classList.toggle('open');
  });
}

function renderBreakdownRows(breakdown, wildOrFarmed) {
  const practicesLabel = wildOrFarmed === 'farmed'
    ? 'Aquaculture Practices'
    : 'Fishing Practices';
  const rows = [
    ['Biological Status', breakdown.biological, 20],
    [practicesLabel, breakdown.practices, 25],
    ['Management', breakdown.management, 30],
    ['Ecological', breakdown.ecological, 25],
  ];
  return rows.map(([label, val, max]) => `
    <div class="score-row">
      <span class="score-label">${label}</span>
      <span class="score-val">${Math.round(val)}/${max}</span>
    </div>
  `).join('');
}

function removeOverlay() {
  if (shadowHost) {
    shadowHost.remove();
    shadowHost = null;
  }
}

// Auto-trigger analysis when navigating to a product page
// (heuristic: URL contains /product/ or /p/ or /item/)
function maybeAutoAnalyze() {
  const url = window.location.href;
  const isProductPage = /\/(product|products|p|item|items|shop|dp)\//.test(url);
  if (isProductPage) {
    setTimeout(() => {
      chrome.runtime.sendMessage({ type: 'ANALYZE_PAGE', url: url });
    }, 1500); // wait for page to settle
  }
}

// Trigger on initial load
maybeAutoAnalyze();

// Trigger on navigation (SPAs change URL without reload)
let lastUrl = location.href;
new MutationObserver(() => {
  const url = location.href;
  if (url !== lastUrl) {
    lastUrl = url;
    removeOverlay();
    maybeAutoAnalyze();
  }
}).observe(document, { subtree: true, childList: true });
```

### 3. Update BACKEND_URL for Production

When Cloud Run URL is known (from Phase 7):
```javascript
// extension/config.js
const BACKEND_URL = "https://seasussed-backend-<hash>-uc.a.run.app";
```

## Verification (Manual)

1. Load Whole Foods salmon page:
   - Badge appears in bottom-right within 4 seconds
   - Grade letter shown with correct color (A=green, B=yellow, C=orange, D=red)
   - Score number visible

2. Click badge:
   - Panel expands showing: species name, explanation, 4-row breakdown, 3 alternatives

3. Click badge again or × button:
   - Panel collapses or overlay removed

4. Load Amazon Fresh chicken page (non-seafood):
   - No badge appears

5. Navigate from seafood → non-seafood page on same site (SPA):
   - Old badge removed
   - New analysis triggered automatically

6. Loading state:
   - Spinner panel appears immediately when analysis starts
   - Replaced by result panel within ~4s
