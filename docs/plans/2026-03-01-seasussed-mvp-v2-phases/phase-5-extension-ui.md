# Phase 5: Extension UI Integration

**Days:** 8–11 | **Depends on:** Phase 2 (extension scaffold), Phase 4 (API contract) | **Blocks:** Phase 6

---

## Deliverable

Full side panel UI with all views implemented. User can: open the panel, analyze a Whole Foods seafood page, see the grade and breakdown, expand/correct the extracted data, view alternatives from the actual page, and recover from errors.

## Views in the Side Panel

1. **Onboarding** — first run, privacy disclosure (Phase 2 scaffold)
2. **Idle** — default state, Analyze button
3. **Loading** — spinner while backend processes
4. **Result** — grade badge, breakdown, explanation, alternatives, "Not right?" link
5. **Correction** — editable fields form, re-score via `/score`
6. **Non-seafood** — helpful tip + static mockup
7. **Error** — error message + retry

---

## Step 1: background.js — Full Implementation

```javascript
// extension/background.js (replaces Phase 2 scaffold)
importScripts('config.js');

const pendingTabs = new Set();

// Toolbar icon click → open side panel
chrome.action.onClicked.addListener((tab) => {
  chrome.sidePanel.open({ windowId: tab.windowId });
});

// Messages from sidepanel.js
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'ANALYZE_PAGE') {
    const tabId = msg.tabId;
    if (pendingTabs.has(tabId)) {
      sendResponse({ error: 'Analysis already in progress' });
      return true;
    }

    pendingTabs.add(tabId);
    handleAnalyze(tabId, msg.url)
      .then(result => {
        pendingTabs.delete(tabId);
        sendResponse(result);
      })
      .catch(err => {
        pendingTabs.delete(tabId);
        sendResponse({ error: err.message });
      });
    return true;
  }
});

async function handleAnalyze(tabId, url) {
  // 1. Capture screenshot
  const dataUrl = await new Promise((resolve, reject) => {
    chrome.tabs.captureVisibleTab(null, { format: 'png' }, (result) => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else resolve(result);
    });
  });
  const base64 = dataUrl.split(',')[1];

  // 2. Scrape related product titles from page DOM
  let relatedProducts = [];
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: scrapeRelatedProducts,
    });
    relatedProducts = results[0]?.result ?? [];
  } catch (_) {
    // DOM scraping is best-effort; don't fail the main analysis
  }

  // 3. Get page title for context
  let pageTitle = '';
  try {
    const titleResults = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => document.title,
    });
    pageTitle = titleResults[0]?.result ?? '';
  } catch (_) {}

  // 4. Call backend
  const response = await fetch(`${BACKEND_URL}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      screenshot: base64,
      url: url,
      page_title: pageTitle,
      related_products: relatedProducts,
    }),
    signal: AbortSignal.timeout(15000),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Backend error ${response.status}: ${text.substring(0, 120)}`);
  }

  return await response.json();
}

function scrapeRelatedProducts() {
  const selectors = [
    '[data-testid*="product"] h2', '[data-testid*="product"] h3',
    '.product-title', '.product-name',
    '[class*="ProductName"]', '[class*="product-title"]', '[class*="product-name"]',
    '[class*="ProductTitle"]',
    '[aria-label*="product"] h2', '[aria-label*="product"] h3',
    // Whole Foods specific
    '[data-ref*="product-name"]',
    '.w-pie--product-tile__content h2',
  ];

  const titles = new Set();
  for (const sel of selectors) {
    try {
      document.querySelectorAll(sel).forEach(el => {
        const text = el.innerText?.trim();
        if (text && text.length > 3 && text.length < 150) titles.add(text);
      });
    } catch (_) {}
  }

  return [...titles].slice(0, 15);
}
```

---

## Step 2: sidepanel.html — Full Layout

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>SeaSussed</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 14px; color: #1f2937; background: #f9fafb; min-height: 100vh;
    }
    .view { display: none; padding: 20px; }
    .view.active { display: block; }

    /* ---- Shared ---- */
    .btn-primary {
      width: 100%; padding: 12px; background: #0d6efd; color: white;
      border: none; border-radius: 8px; font-size: 15px; font-weight: 600;
      cursor: pointer; margin-top: 4px;
    }
    .btn-primary:hover { background: #0b5ed7; }
    .btn-secondary {
      width: 100%; padding: 10px; background: white; color: #374151;
      border: 1px solid #d1d5db; border-radius: 8px; font-size: 14px;
      cursor: pointer; margin-top: 8px;
    }
    .btn-secondary:hover { background: #f3f4f6; }
    .section-title {
      font-size: 11px; font-weight: 600; color: #9ca3af;
      text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;
    }

    /* ---- Onboarding ---- */
    .onboarding-icon { font-size: 48px; text-align: center; margin-bottom: 16px; }
    #view-onboarding h1 { font-size: 20px; font-weight: 700; margin-bottom: 8px; }
    #view-onboarding p { color: #6b7280; line-height: 1.5; margin-bottom: 12px; }
    .notice {
      background: #eff6ff; border: 1px solid #bfdbfe;
      border-radius: 8px; padding: 12px; font-size: 13px; color: #1d4ed8;
      margin-bottom: 20px; line-height: 1.5;
    }

    /* ---- Idle ---- */
    #view-idle { text-align: center; padding: 40px 20px; }
    #view-idle .icon { font-size: 40px; margin-bottom: 12px; }
    #view-idle h2 { font-size: 17px; margin-bottom: 8px; }
    #view-idle p { color: #6b7280; font-size: 13px; margin-bottom: 24px; line-height: 1.5; }

    /* ---- Loading ---- */
    #view-loading { text-align: center; padding: 48px 20px; }
    .spinner-wrap { display: flex; align-items: center; justify-content: center; gap: 12px; }
    .spin {
      width: 24px; height: 24px; border: 3px solid #e5e7eb;
      border-top-color: #3b82f6; border-radius: 50%;
      animation: rotate 0.8s linear infinite;
    }
    @keyframes rotate { to { transform: rotate(360deg); } }
    #view-loading p { color: #6b7280; font-size: 14px; margin-top: 16px; }

    /* ---- Result ---- */
    .grade-badge {
      display: flex; align-items: center; gap: 14px;
      background: white; border-radius: 12px;
      padding: 14px 16px; margin-bottom: 16px;
      box-shadow: 0 1px 4px rgba(0,0,0,0.08);
    }
    .grade-circle {
      width: 52px; height: 52px; border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-size: 24px; font-weight: 700; color: white; flex-shrink: 0;
    }
    .grade-info { flex: 1; }
    .grade-label { font-size: 12px; color: #6b7280; font-weight: 500; }
    .grade-score { font-size: 20px; font-weight: 700; color: #111; }
    .grade-subtitle { font-size: 12px; color: #9ca3af; margin-top: 1px; }

    .card {
      background: white; border-radius: 10px; padding: 14px;
      margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    .extraction-row { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
    .tag {
      background: #f3f4f6; border-radius: 20px; padding: 3px 10px;
      font-size: 12px; color: #374151;
    }
    .tag.cert { background: #d1fae5; color: #065f46; }

    .explanation { font-size: 13px; color: #374151; line-height: 1.6; }

    .score-row {
      display: flex; justify-content: space-between; align-items: center;
      padding: 6px 0; border-bottom: 1px solid #f3f4f6; font-size: 13px;
    }
    .score-row:last-child { border-bottom: none; }
    .score-label { color: #555; }
    .score-val { font-weight: 600; color: #1f2937; }
    .score-bar-wrap { width: 60px; height: 4px; background: #f3f4f6; border-radius: 2px; margin-left: 8px; }
    .score-bar { height: 100%; border-radius: 2px; }

    .alt-row {
      display: flex; justify-content: space-between; align-items: flex-start;
      padding: 8px 0; border-bottom: 1px solid #f3f4f6;
    }
    .alt-row:last-child { border-bottom: none; }
    .alt-name { font-size: 13px; font-weight: 500; color: #111; margin-bottom: 3px; }
    .alt-reason { font-size: 11px; color: #9ca3af; }
    .alt-from-page { font-size: 10px; color: #6b7280; font-style: italic; }
    .alt-badge {
      font-size: 11px; font-weight: 700; padding: 2px 7px; border-radius: 10px;
      color: white; flex-shrink: 0; margin-left: 10px; margin-top: 2px;
    }

    .not-right-link {
      display: block; text-align: center; font-size: 12px; color: #9ca3af;
      text-decoration: none; margin-top: 6px; cursor: pointer;
    }
    .not-right-link:hover { color: #6b7280; text-decoration: underline; }

    /* ---- Correction ---- */
    #view-correction h3 { font-size: 16px; font-weight: 600; margin-bottom: 4px; }
    #view-correction p { font-size: 13px; color: #6b7280; margin-bottom: 16px; }
    .form-group { margin-bottom: 12px; }
    .form-group label { display: block; font-size: 12px; font-weight: 600;
      color: #374151; margin-bottom: 4px; }
    .form-group input, .form-group select {
      width: 100%; padding: 8px 10px; border: 1px solid #d1d5db;
      border-radius: 6px; font-size: 14px; color: #1f2937; background: white;
    }
    .form-group input:focus, .form-group select:focus {
      outline: none; border-color: #3b82f6;
    }

    /* ---- Non-seafood ---- */
    #view-non-seafood { text-align: center; padding: 32px 20px; }
    #view-non-seafood .icon { font-size: 40px; margin-bottom: 12px; }
    #view-non-seafood h2 { font-size: 16px; margin-bottom: 8px; }
    #view-non-seafood p { color: #6b7280; font-size: 13px; line-height: 1.5; margin-bottom: 16px; }
    .mockup {
      background: white; border-radius: 10px; padding: 12px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08); text-align: left;
      opacity: 0.6; margin-bottom: 16px;
    }
    .mockup-badge {
      display: flex; align-items: center; gap: 10px; margin-bottom: 8px;
    }
    .mockup-grade {
      width: 36px; height: 36px; border-radius: 50%; background: #22c55e;
      display: flex; align-items: center; justify-content: center;
      color: white; font-weight: 700; font-size: 16px;
    }
    .mockup-text { font-size: 13px; }
    .mockup-score { font-weight: 600; }

    /* ---- Error ---- */
    #view-error { text-align: center; padding: 40px 20px; }
    #view-error .icon { font-size: 36px; margin-bottom: 12px; }
    #view-error h2 { font-size: 15px; margin-bottom: 8px; color: #ef4444; }
    #view-error p { color: #6b7280; font-size: 13px; margin-bottom: 20px; line-height: 1.5; }

    .footer {
      padding: 12px 20px; font-size: 11px; color: #d1d5db; text-align: center;
      border-top: 1px solid #f3f4f6; margin-top: 8px;
    }

    /* ---- Expandable breakdown rows ---- */
    .breakdown-row { border-bottom: 1px solid #f3f4f6; cursor: pointer; }
    .breakdown-row:last-child { border-bottom: none; }
    .breakdown-header {
      display: flex; justify-content: space-between; align-items: center;
      padding: 8px 0;
    }
    .breakdown-chevron {
      font-size: 10px; color: #9ca3af; transition: transform 0.15s ease;
      flex-shrink: 0; margin-left: 4px;
    }
    .breakdown-row.open .breakdown-chevron { transform: rotate(90deg); }
    .breakdown-detail {
      display: none; padding: 0 0 10px 0;
      font-size: 12px; color: #4b5563; line-height: 1.6;
    }
    .breakdown-row.open .breakdown-detail { display: block; }
    .breakdown-tip {
      margin-top: 6px; padding: 6px 8px;
      background: #fff7ed; border-left: 2px solid #f97316;
      border-radius: 0 4px 4px 0; font-size: 12px; color: #92400e; line-height: 1.5;
    }

    /* ---- Cert popover ---- */
    .tag.cert { cursor: pointer; }
    .cert-popover {
      position: fixed; background: white;
      border: 1px solid #e5e7eb; border-radius: 10px;
      padding: 12px 14px; width: 240px;
      box-shadow: 0 4px 16px rgba(0,0,0,0.14);
      font-size: 12px; color: #374151; line-height: 1.6;
      z-index: 1000; display: none;
    }
    .cert-popover.visible { display: block; }
    .cert-popover-title {
      font-weight: 600; font-size: 13px; margin-bottom: 6px;
      color: #111; padding-right: 16px;
    }
    .cert-popover-close {
      position: absolute; top: 8px; right: 10px;
      font-size: 16px; color: #9ca3af; cursor: pointer; line-height: 1;
    }
    .cert-popover-close:hover { color: #6b7280; }
  </style>
</head>
<body>

  <!-- View: Onboarding -->
  <div class="view" id="view-onboarding">
    <div class="onboarding-icon">🐟</div>
    <h1>Welcome to SeaSussed</h1>
    <p>Instant sustainability scores for seafood while you shop online.</p>
    <div class="notice">
      📷 When you click Analyze, a screenshot of the current tab is sent to SeaSussed's
      servers to identify the seafood product. Screenshots are not stored after analysis.
    </div>
    <p style="font-size:13px; color:#6b7280;">
      Works on any grocery website — Whole Foods, Amazon Fresh, Instacart, and more.
    </p>
    <br>
    <button class="btn-primary" id="onboarding-ok">Got it — Let's go</button>
  </div>

  <!-- View: Idle -->
  <div class="view" id="view-idle">
    <div class="icon">🐠</div>
    <h2>SeaSussed</h2>
    <p>Navigate to a seafood product page, then click Analyze to get a sustainability score.</p>
    <button class="btn-primary" id="analyze-btn">Analyze This Page</button>
  </div>

  <!-- View: Loading -->
  <div class="view" id="view-loading">
    <div class="spinner-wrap"><div class="spin"></div></div>
    <p>Analyzing seafood…</p>
  </div>

  <!-- View: Result -->
  <div class="view" id="view-result">
    <!-- Grade badge -->
    <div class="grade-badge" id="grade-badge">
      <div class="grade-circle" id="grade-circle">A</div>
      <div class="grade-info">
        <div class="grade-label" id="grade-emoji-label">🟢 Best Choice</div>
        <div class="grade-score" id="grade-score-text">84/100</div>
        <div class="grade-subtitle">SeaSussed Score</div>
      </div>
    </div>

    <!-- Extracted info tags -->
    <div class="card">
      <div class="section-title">What we found on the page</div>
      <div class="extraction-row" id="extraction-tags"></div>
      <div class="explanation" id="explanation-text"></div>
    </div>

    <!-- Score breakdown -->
    <div class="card">
      <div class="section-title">Score Breakdown</div>
      <div id="breakdown-rows"></div>
    </div>

    <!-- Alternatives -->
    <div class="card" id="alternatives-card" style="display:none">
      <div class="section-title" id="alternatives-title">Better Alternatives</div>
      <div id="alternatives-list"></div>
      <div id="category-page-tip" style="display:none; margin-top:10px; font-size:12px; color:#6b7280; line-height:1.5;"></div>
    </div>

    <!-- Not right link -->
    <a class="not-right-link" id="not-right-link">Not right? Correct the details</a>

    <!-- Analyze again -->
    <button class="btn-secondary" id="analyze-again-btn">Analyze Again</button>

    <div class="footer">Screenshots not stored · SeaSussed</div>
  </div>

  <!-- View: Correction -->
  <div class="view" id="view-correction">
    <h3>Correct the Details</h3>
    <p>Update the fields below. Score will recalculate based on your corrections.</p>

    <div class="form-group">
      <label for="corr-species">Species</label>
      <input type="text" id="corr-species" placeholder="e.g. Alaska sockeye salmon">
    </div>
    <div class="form-group">
      <label for="corr-wild-farmed">Wild or Farmed</label>
      <select id="corr-wild-farmed">
        <option value="unknown">Unknown</option>
        <option value="wild">Wild</option>
        <option value="farmed">Farmed</option>
      </select>
    </div>
    <div class="form-group">
      <label for="corr-method">Fishing / Farming Method</label>
      <select id="corr-method">
        <option value="">Unknown</option>
        <option value="Pole and line">Pole and line</option>
        <option value="Hook and line">Hook and line</option>
        <option value="Troll">Troll</option>
        <option value="Pot / Trap">Pot / Trap</option>
        <option value="Purse seine (without FAD)">Purse seine (without FAD)</option>
        <option value="Purse seine (with FAD)">Purse seine (with FAD)</option>
        <option value="Gillnet">Gillnet</option>
        <option value="Longline (surface)">Longline (surface)</option>
        <option value="Longline (demersal)">Longline (demersal)</option>
        <option value="Midwater trawl">Midwater trawl</option>
        <option value="Bottom trawl">Bottom trawl</option>
        <option value="Aquaculture (recirculating)">Aquaculture (recirculating)</option>
        <option value="Aquaculture (pond)">Aquaculture (pond)</option>
      </select>
    </div>
    <div class="form-group">
      <label for="corr-origin">Origin Region</label>
      <input type="text" id="corr-origin" placeholder="e.g. Bristol Bay, Alaska">
    </div>
    <div class="form-group">
      <label for="corr-certs">Certifications (comma-separated)</label>
      <input type="text" id="corr-certs" placeholder="e.g. MSC, ASC">
    </div>

    <button class="btn-primary" id="correction-submit-btn">Recalculate Score</button>
    <button class="btn-secondary" id="correction-cancel-btn">Cancel</button>
  </div>

  <!-- View: Non-seafood -->
  <div class="view" id="view-non-seafood">
    <div class="icon">🌊</div>
    <h2>No seafood detected</h2>
    <p>Navigate to a seafood product page and click Analyze to see a sustainability score.</p>

    <div class="mockup">
      <div class="section-title" style="margin-bottom:8px;">Example</div>
      <div class="mockup-badge">
        <div class="mockup-grade">A</div>
        <div class="mockup-text">
          <div class="mockup-score">84/100 · Best Choice 🟢</div>
          <div style="font-size:11px; color:#9ca3af;">Alaska Sockeye Salmon</div>
        </div>
      </div>
    </div>

    <button class="btn-secondary" id="non-seafood-back-btn">← Try another page</button>
  </div>

  <!-- View: Error -->
  <div class="view" id="view-error">
    <div class="icon">⚠️</div>
    <h2>Analysis Failed</h2>
    <p id="error-message">Something went wrong. Please try again.</p>
    <button class="btn-primary" id="error-retry-btn">Try Again</button>
    <button class="btn-secondary" id="error-back-btn">Back</button>
  </div>

  <!-- Cert definition popover (shared singleton) -->
  <div id="cert-popover" class="cert-popover">
    <span class="cert-popover-close" id="cert-popover-close">×</span>
    <div class="cert-popover-title" id="cert-popover-title"></div>
    <div id="cert-popover-body"></div>
  </div>

  <script src="sidepanel.js"></script>
</body>
</html>
```

---

## Step 3: sidepanel.js — Full Controller

```javascript
// extension/sidepanel.js

const STORAGE_KEY = 'seasussed_onboarded';
const GRADE_COLORS = { A: '#22c55e', B: '#eab308', C: '#f97316', D: '#ef4444' };
const GRADE_LABELS = { A: '🟢 Best Choice', B: '🟡 Good Alternative', C: '🟠 Use Caution', D: '🔴 Avoid' };
const BREAKDOWN_MAX = { biological: 20, practices: 25, management: 30, ecological: 25 };

// Cert definitions (frontend copy of cert_education.py — static, never Gemini-generated)
const CERT_DEFINITIONS = {
  'MSC': {
    full_name: 'Marine Stewardship Council',
    explanation: 'The MSC blue fish logo means this fishery was independently audited against science-based standards. To earn MSC, a fishery must show healthy fish stocks, minimal environmental impact, and effective management systems. Annual surveillance audits maintain the certification.',
  },
  'ASC': {
    full_name: 'Aquaculture Stewardship Council',
    explanation: 'The ASC teal logo certifies responsibly farmed seafood. ASC farms meet standards covering feed sourcing, disease and chemical use, water quality, ecosystem impacts, and worker welfare. Considered the gold standard for farmed seafood certification.',
  },
  'BAP': {
    full_name: 'Best Aquaculture Practices',
    explanation: 'BAP certifies farmed seafood across four supply chain areas: hatcheries, farms, processing, and feed mills. The number of stars shows how many components are certified — more stars means greater traceability and sustainability verification.',
  },
  'GLOBALG.A.P.': {
    full_name: 'GlobalG.A.P.',
    explanation: 'GlobalG.A.P. certifies farms against food safety, environmental sustainability, and worker welfare standards. Respected internationally but less seafood-specific than ASC or BAP.',
  },
  'FRIEND OF THE SEA': {
    full_name: 'Friend of the Sea',
    explanation: 'Certifies both wild-caught and farmed seafood against sustainability criteria including stock status, bycatch reduction, and no impact on endangered species or seabed. Widely recognized internationally.',
  },
  'FOS': {
    full_name: 'Friend of the Sea',
    explanation: 'Friend of the Sea (FOS) certifies both wild-caught and farmed seafood against sustainability criteria including stock status, bycatch reduction, and no impact on endangered species or seabed.',
  },
  'ASMI': {
    full_name: 'Alaska Seafood Marketing Institute',
    explanation: 'The Alaska Seafood logo indicates seafood from Alaska — one of the world\'s best-managed fisheries regions. All Alaska commercial fisheries operate under the Magnuson-Stevens Act with science-based catch limits and independent stock assessments.',
  },
  'SUSTAINABLY SOURCED': {
    full_name: 'Sustainably Sourced (retailer claim)',
    explanation: '\'Sustainably sourced\' is an unverified marketing claim — not backed by independent audit. Unlike MSC or ASC, there\'s no standard defining what it means. Look for the MSC blue fish logo or ASC teal logo for independently verified sustainability.',
  },
  'RESPONSIBLY FARMED': {
    full_name: 'Responsibly Farmed (retailer claim)',
    explanation: '\'Responsibly Farmed\' is a retailer-defined standard audited by the retailer itself, not an independent body. A step above no label, but not equivalent to ASC or BAP certification.',
  },
  'SEAFOOD WATCH': {
    full_name: 'Monterey Bay Aquarium Seafood Watch',
    explanation: 'Seafood Watch is a science-based consumer guide from the Monterey Bay Aquarium rating seafood as Best Choice, Good Alternative, or Avoid. It\'s a rating system, not a certification (no logo on packaging) — but widely respected by restaurants and retailers.',
  },
};

let currentResult = null;

// --- View management ---
function showView(id) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById(id)?.classList.add('active');
}

// --- Init ---
chrome.storage.local.get(STORAGE_KEY, (res) => {
  showView(res[STORAGE_KEY] ? 'view-idle' : 'view-onboarding');
});

// --- Onboarding ---
document.getElementById('onboarding-ok').addEventListener('click', () => {
  chrome.storage.local.set({ [STORAGE_KEY]: true });
  showView('view-idle');
});

// --- Analyze button ---
async function triggerAnalyze() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) return;

  showView('view-loading');

  chrome.runtime.sendMessage(
    { type: 'ANALYZE_PAGE', tabId: tab.id, url: tab.url },
    (result) => {
      if (chrome.runtime.lastError || result?.error) {
        showError(result?.error || chrome.runtime.lastError?.message || 'Unknown error');
        return;
      }
      if (!result.product_info?.is_seafood) {
        showView('view-non-seafood');
        return;
      }
      currentResult = result;
      renderResult(result);
    }
  );
}

document.getElementById('analyze-btn').addEventListener('click', triggerAnalyze);
document.getElementById('analyze-again-btn').addEventListener('click', triggerAnalyze);
document.getElementById('non-seafood-back-btn').addEventListener('click', () => showView('view-idle'));
document.getElementById('error-retry-btn').addEventListener('click', triggerAnalyze);
document.getElementById('error-back-btn').addEventListener('click', () => showView('view-idle'));

// --- Render Result ---
function renderResult(data) {
  const { score, grade, breakdown, alternatives, alternatives_label,
          explanation, score_factors, product_info } = data;
  const color = GRADE_COLORS[grade];

  // Grade badge
  document.getElementById('grade-circle').textContent = grade;
  document.getElementById('grade-circle').style.background = color;
  document.getElementById('grade-emoji-label').textContent = GRADE_LABELS[grade];
  document.getElementById('grade-score-text').textContent = `${score}/100`;

  // Extraction tags
  const tagsEl = document.getElementById('extraction-tags');
  tagsEl.innerHTML = '';
  if (product_info.species) tagsEl.innerHTML += `<span class="tag">${product_info.species}</span>`;
  if (product_info.wild_or_farmed !== 'unknown')
    tagsEl.innerHTML += `<span class="tag">${product_info.wild_or_farmed}</span>`;
  if (product_info.origin_region)
    tagsEl.innerHTML += `<span class="tag">${product_info.origin_region}</span>`;
  if (product_info.fishing_method)
    tagsEl.innerHTML += `<span class="tag">${product_info.fishing_method}</span>`;
  product_info.certifications?.forEach(c =>
    tagsEl.innerHTML += `<span class="tag cert" data-cert="${c}">${c}</span>`);

  // Cert tag → popover (delegated listener on each tag)
  tagsEl.querySelectorAll('.tag.cert').forEach(tag => {
    tag.addEventListener('click', (e) => showCertPopover(tag.dataset.cert, e));
  });

  // Explanation
  document.getElementById('explanation-text').textContent = explanation;

  // Breakdown rows — expandable with per-factor educational content
  const breakdownEl = document.getElementById('breakdown-rows');
  if (score_factors && score_factors.length > 0) {
    breakdownEl.innerHTML = score_factors.map(factor => {
      const pct = Math.round((factor.score / factor.max_score) * 100);
      const barColor = pct >= 70 ? '#22c55e' : pct >= 45 ? '#eab308' : '#ef4444';
      const tipHtml = factor.tip
        ? `<div class="breakdown-tip">💡 ${factor.tip}</div>` : '';
      return `
        <div class="breakdown-row">
          <div class="breakdown-header">
            <span class="score-label">${factor.category}</span>
            <div style="display:flex; align-items:center; gap:8px;">
              <div class="score-bar-wrap">
                <div class="score-bar" style="width:${pct}%; background:${barColor};"></div>
              </div>
              <span class="score-val">${Math.round(factor.score)}/${factor.max_score}</span>
              <span class="breakdown-chevron">▶</span>
            </div>
          </div>
          <div class="breakdown-detail">
            ${factor.explanation}
            ${tipHtml}
          </div>
        </div>`;
    }).join('');

    breakdownEl.querySelectorAll('.breakdown-header').forEach(header => {
      header.addEventListener('click', () => {
        header.parentElement.classList.toggle('open');
      });
    });
  } else {
    // Fallback: static breakdown rows (no score_factors in response)
    const practicesLabel = product_info.wild_or_farmed === 'farmed'
      ? 'Aquaculture Practices' : 'Fishing Practices';
    const rows = [
      ['Biological Status', breakdown.biological, BREAKDOWN_MAX.biological],
      [practicesLabel,      breakdown.practices,  BREAKDOWN_MAX.practices],
      ['Management',        breakdown.management, BREAKDOWN_MAX.management],
      ['Ecological',        breakdown.ecological, BREAKDOWN_MAX.ecological],
    ];
    breakdownEl.innerHTML = rows.map(([label, val, max]) => {
      const pct = Math.round((val / max) * 100);
      const barColor = pct >= 70 ? '#22c55e' : pct >= 45 ? '#eab308' : '#ef4444';
      return `
        <div class="score-row">
          <span class="score-label">${label}</span>
          <div style="display:flex; align-items:center; gap:8px;">
            <div class="score-bar-wrap">
              <div class="score-bar" style="width:${pct}%; background:${barColor};"></div>
            </div>
            <span class="score-val">${Math.round(val)}/${max}</span>
          </div>
        </div>`;
    }).join('');
  }

  // Alternatives
  const altsCard = document.getElementById('alternatives-card');
  const altsList = document.getElementById('alternatives-list');
  const altsTitle = document.getElementById('alternatives-title');

  if (alternatives && alternatives.length > 0) {
    altsCard.style.display = 'block';
    altsTitle.textContent = alternatives_label || 'Better alternatives';
    altsList.innerHTML = alternatives.map(alt => {
      const altColor = GRADE_COLORS[alt.grade];
      const fromPageNote = alt.from_page
        ? '' : '<div class="alt-from-page">(check if available on this site)</div>';
      return `
        <div class="alt-row">
          <div>
            <div class="alt-name">${alt.species}</div>
            <div class="alt-reason">${alt.reason}</div>
            ${fromPageNote}
          </div>
          <span class="alt-badge" style="background:${altColor}">${alt.grade}</span>
        </div>`;
    }).join('');

    // Category page escalation tip
    const tip = document.getElementById('category-page-tip');
    const hasSeedOnly = alternatives.every(a => !a.from_page);
    if (hasSeedOnly && grade !== 'A') {
      tip.style.display = 'block';
      tip.textContent = 'Want options available on this site? Navigate to the seafood section and click Analyze again.';
    } else {
      tip.style.display = 'none';
    }
  } else {
    altsCard.style.display = 'none';
  }

  showView('view-result');
}

// --- Cert popover ---
function showCertPopover(certName, event) {
  const certKey = certName.toUpperCase();
  let def = null;
  for (const [key, val] of Object.entries(CERT_DEFINITIONS)) {
    if (certKey === key || certKey.includes(key) || key.includes(certKey)) {
      def = val; break;
    }
  }
  if (!def) return;

  const popover = document.getElementById('cert-popover');
  document.getElementById('cert-popover-title').textContent = def.full_name;
  document.getElementById('cert-popover-body').textContent = def.explanation;

  const rect = event.currentTarget.getBoundingClientRect();
  const panelWidth = document.body.offsetWidth;
  let left = rect.left;
  if (left + 240 > panelWidth - 8) left = panelWidth - 248;
  if (left < 8) left = 8;
  popover.style.top = `${rect.bottom + 6}px`;
  popover.style.left = `${left}px`;
  popover.classList.add('visible');
  event.stopPropagation();
}

document.addEventListener('click', () => {
  document.getElementById('cert-popover')?.classList.remove('visible');
});
document.getElementById('cert-popover-close')?.addEventListener('click', (e) => {
  document.getElementById('cert-popover')?.classList.remove('visible');
  e.stopPropagation();
});

// --- "Not right?" correction ---
document.getElementById('not-right-link').addEventListener('click', () => {
  if (!currentResult) return;
  const p = currentResult.product_info;
  document.getElementById('corr-species').value = p.species || '';
  document.getElementById('corr-wild-farmed').value = p.wild_or_farmed || 'unknown';
  document.getElementById('corr-method').value = p.fishing_method || '';
  document.getElementById('corr-origin').value = p.origin_region || '';
  document.getElementById('corr-certs').value = (p.certifications || []).join(', ');
  showView('view-correction');
});

document.getElementById('correction-cancel-btn').addEventListener('click', () => {
  showView('view-result');
});

document.getElementById('correction-submit-btn').addEventListener('click', async () => {
  const certsRaw = document.getElementById('corr-certs').value;
  const certs = certsRaw.split(',').map(s => s.trim()).filter(Boolean);

  const correctedInfo = {
    is_seafood: true,
    species: document.getElementById('corr-species').value.trim() || null,
    wild_or_farmed: document.getElementById('corr-wild-farmed').value,
    fishing_method: document.getElementById('corr-method').value || null,
    origin_region: document.getElementById('corr-origin').value.trim() || null,
    certifications: certs,
  };

  showView('view-loading');

  try {
    const response = await fetch(`${BACKEND_URL}/score`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_info: correctedInfo }),
      signal: AbortSignal.timeout(10000),
    });

    if (!response.ok) throw new Error(`Backend error ${response.status}`);

    currentResult = await response.json();
    renderResult(currentResult);
  } catch (err) {
    showError(err.message);
  }
});

// --- Error ---
function showError(message) {
  document.getElementById('error-message').textContent =
    message || 'Something went wrong. Please try again.';
  showView('view-error');
}
```

---

## Automated Success Criteria

None (vanilla JS).

Manifest validation:
```bash
python3 -c "
import json
m = json.load(open('/Users/jordan/sussed/extension/manifest.json'))
assert m.get('side_panel'), 'missing side_panel config'
assert 'sidePanel' in m.get('permissions', []), 'missing sidePanel permission'
assert 'default_popup' not in m.get('action', {}), 'should not have default_popup'
print('manifest.json: valid side panel config')
"
```

## Manual Success Criteria

1. Load extension unpacked — no errors in `chrome://extensions`
2. Click toolbar icon → side panel opens on right
3. First run → onboarding view with privacy notice
4. Click "Got it" → idle view; reload panel → idle view (onboarding not shown again)
5. Navigate to a Whole Foods wild sockeye salmon product page
6. Click Analyze → loading spinner appears
7. Result appears within 8 seconds:
   - Grade badge shows A or B with correct color
   - "What we found on the page" tags show species + origin + any certs
   - Explanation text mentions what was visible (e.g. "wild-caught from Alaska")
   - Score breakdown shows 4 rows with bar indicators
8. Alternatives section shows products (from page DOM ideally; seed DB as fallback)
   - If seed DB fallback: notice "(check if available on this site)" shown
9. Click "Not right?" → correction form opens, pre-filled with extracted values
   - Change species to "bluefin tuna", click Recalculate → grade drops to D
   - "Not right?" link is visually subtle (gray, small)
10. Navigate to a non-seafood Whole Foods page → Analyze → non-seafood view appears
11. Backend disconnected → error view shows with helpful message, retry button works
12. "Analyze Again" button works from result view
13. Educational layer — cert popovers:
    - Product has MSC label → MSC cert tag is green and tappable
    - Tap MSC tag → popover appears with "Marine Stewardship Council" title and definition
    - Tap outside popover → popover closes
    - Tap × close button → popover closes
    - Unrecognized cert text → tap does nothing (no crash)
14. Educational layer — expandable breakdown rows:
    - Breakdown section shows 4 rows with chevron (▶) on each row
    - Click row header → row expands showing per-factor explanation text
    - Click row header again → row collapses
    - Multiple rows can be open simultaneously
    - Grade A or B product → expanded rows show explanation but no tip
    - Grade C or D product → at least one expanded row shows 💡 tip with actionable text
