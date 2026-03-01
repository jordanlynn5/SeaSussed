# Phase 2: Chrome Extension Scaffold

**Days:** 2–3 | **Depends on:** nothing | **Blocks:** Phase 5

---

## Deliverable

Extension loads in Chrome, opens a side panel when the toolbar icon is clicked, shows an idle state with an Analyze button, captures a screenshot when clicked, and logs the base64 + DOM product titles to console. No backend call required yet.

---

## Key Architecture Decisions

- **Chrome Side Panel API** (`chrome.sidePanel`): introduced Chrome 114 (June 2023). The side panel is a persistent surface that stays open as the user browses.
- **No `default_popup`** in manifest: when `default_popup` is absent, clicking the toolbar icon fires `chrome.action.onClicked`. We use this event to open the side panel.
- **content_script.js** is injected into all pages to scrape related product titles from the DOM. It does NOT render any UI on the page.
- **Onboarding**: the side panel detects first run via `chrome.storage.local` and shows a disclosure screen before allowing analysis.

---

## Steps

### 1. Directory Structure

```
extension/
├── manifest.json
├── config.js             # BACKEND_URL constant (edit before loading)
├── background.js         # service worker
├── content_script.js     # DOM scraping only — no overlay
├── sidepanel.html        # persistent side panel
├── sidepanel.js          # side panel controller
└── icons/
    ├── icon16.png
    ├── icon48.png
    └── icon128.png
```

### 2. manifest.json

```json
{
  "manifest_version": 3,
  "name": "SeaSussed",
  "version": "0.1.0",
  "description": "Real-time seafood sustainability scores while you shop",
  "permissions": [
    "activeTab",
    "scripting",
    "storage",
    "sidePanel"
  ],
  "host_permissions": [
    "<all_urls>"
  ],
  "background": {
    "service_worker": "background.js"
  },
  "content_scripts": [
    {
      "matches": ["<all_urls>"],
      "js": ["content_script.js"],
      "run_at": "document_idle"
    }
  ],
  "action": {
    "default_icon": {
      "16": "icons/icon16.png",
      "48": "icons/icon48.png",
      "128": "icons/icon128.png"
    }
  },
  "side_panel": {
    "default_path": "sidepanel.html"
  }
}
```

**Note:** No `default_popup` — clicking the toolbar icon fires `chrome.action.onClicked`.

### 3. config.js

```javascript
// extension/config.js
// Set BACKEND_URL to your Cloud Run URL before loading in Chrome
const BACKEND_URL = "http://localhost:8000";
```

### 4. background.js (scaffold)

```javascript
// extension/background.js
importScripts('config.js');

// Toolbar icon click → open side panel
chrome.action.onClicked.addListener((tab) => {
  chrome.sidePanel.open({ windowId: tab.windowId });
});

// Listen for analyze request from side panel
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'ANALYZE_PAGE') {
    handleAnalyze(msg.tabId, msg.url)
      .then(sendResponse)
      .catch(err => sendResponse({ error: err.message }));
    return true; // keep channel open for async response
  }
});

async function handleAnalyze(tabId, url) {
  // 1. Capture screenshot
  const dataUrl = await new Promise((resolve, reject) => {
    chrome.tabs.captureVisibleTab(null, { format: 'png' }, (result) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve(result);
      }
    });
  });
  const base64 = dataUrl.split(',')[1];

  // 2. Scrape related product titles from the page DOM
  const domData = await chrome.scripting.executeScript({
    target: { tabId },
    func: scrapeRelatedProducts,
  });
  const relatedProducts = domData[0]?.result ?? [];

  // Phase 4 will add the backend call here
  // For now: log and return mock data for scaffolding
  console.log('[SeaSussed] Screenshot captured, length:', base64.length);
  console.log('[SeaSussed] Related products found:', relatedProducts);

  return { _scaffold: true, screenshot_length: base64.length, related_products: relatedProducts };
}

// Injected function — runs in page context
function scrapeRelatedProducts() {
  const titleSelectors = [
    '[data-testid*="product"] h2',
    '[data-testid*="product"] h3',
    '.product-title',
    '.product-name',
    '[class*="ProductName"]',
    '[class*="product-title"]',
    '[class*="product-name"]',
    '[aria-label*="product"] h2',
    '[aria-label*="product"] h3',
  ];

  const titles = new Set();
  for (const selector of titleSelectors) {
    document.querySelectorAll(selector).forEach(el => {
      const text = el.innerText?.trim();
      if (text && text.length > 3 && text.length < 150) {
        titles.add(text);
      }
    });
  }

  return [...titles].slice(0, 15); // max 15 candidates
}
```

### 5. content_script.js (scaffold)

```javascript
// extension/content_script.js
// This script is injected into every page.
// Its only role is DOM scraping — it does NOT render any UI on the page.
// Actual scraping is done by chrome.scripting.executeScript in background.js.
// This file exists to satisfy the manifest content_scripts declaration and
// can be used for richer DOM access in future if needed.

console.log('[SeaSussed] Content script loaded on:', window.location.hostname);
```

### 6. sidepanel.html (scaffold)

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
      font-size: 14px;
      color: #1f2937;
      background: #f9fafb;
      min-height: 100vh;
    }
    .view { display: none; padding: 20px; }
    .view.active { display: block; }

    /* Onboarding */
    .onboarding-icon { font-size: 48px; text-align: center; margin-bottom: 16px; }
    .onboarding h1 { font-size: 20px; font-weight: 700; margin-bottom: 8px; }
    .onboarding p { color: #6b7280; line-height: 1.5; margin-bottom: 12px; }
    .onboarding .notice {
      background: #eff6ff; border: 1px solid #bfdbfe;
      border-radius: 8px; padding: 12px; font-size: 13px; color: #1d4ed8;
      margin-bottom: 20px;
    }
    .btn-primary {
      width: 100%; padding: 12px; background: #0d6efd; color: white;
      border: none; border-radius: 8px; font-size: 15px; font-weight: 600;
      cursor: pointer;
    }
    .btn-primary:hover { background: #0b5ed7; }

    /* Idle */
    .idle { text-align: center; padding: 40px 20px; }
    .idle h2 { font-size: 16px; margin-bottom: 8px; }
    .idle p { color: #6b7280; font-size: 13px; margin-bottom: 24px; }
  </style>
</head>
<body>

  <!-- Onboarding view (first run only) -->
  <div class="view onboarding" id="view-onboarding">
    <div class="onboarding-icon">🐟</div>
    <h1>Welcome to SeaSussed</h1>
    <p>Get instant sustainability scores for seafood while you shop online.</p>
    <div class="notice">
      📷 When you click Analyze, a screenshot of the current page is sent to
      SeaSussed's servers to identify the seafood product. Screenshots are not stored.
    </div>
    <p>Works on any grocery website — Whole Foods, Amazon Fresh, Instacart, and more.</p>
    <br>
    <button class="btn-primary" id="onboarding-ok">Got it — Let's go</button>
  </div>

  <!-- Idle view (default after onboarding) -->
  <div class="view idle" id="view-idle">
    <div style="font-size:36px; margin-bottom:12px;">🐠</div>
    <h2>SeaSussed</h2>
    <p>Navigate to a seafood product page<br>and click Analyze.</p>
    <button class="btn-primary" id="analyze-btn">Analyze This Page</button>
  </div>

  <!-- Other views: loading, result, correction, non-seafood, error -->
  <!-- Phase 5 will implement these views fully -->

  <script src="sidepanel.js"></script>
</body>
</html>
```

### 7. sidepanel.js (scaffold)

```javascript
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
```

---

## Automated Success Criteria

None (vanilla JS extension — no test runner in Phase 2).

Chrome validation check:
```bash
# Check manifest is valid JSON
python3 -c "import json; json.load(open('/Users/jordan/sussed/extension/manifest.json')); print('manifest.json: valid JSON')"
```

## Manual Success Criteria

1. Open `chrome://extensions`, enable Developer mode, click **Load unpacked** → select `extension/`
   - No red errors shown

2. Click the SeaSussed toolbar icon:
   - Side panel opens on the right side of the browser

3. First time: **onboarding screen** appears with the privacy disclosure and "Got it" button
   - Click "Got it" → transitions to idle view
   - Reload the side panel → goes directly to idle (onboarding not shown again)

4. Navigate to any webpage, open side panel, click **Analyze This Page**
   - Check background service worker DevTools console:
     - `[SeaSussed] Screenshot captured, length: <big number>` appears
     - `[SeaSussed] Related products found: [...]` appears (array may be empty on non-product pages)

5. Navigate to a Whole Foods product page:
   - Confirm `related_products` array is non-empty in the console log

### Smoke test (paste in background service worker DevTools):
```javascript
chrome.tabs.captureVisibleTab(null, { format: 'png' }, (dataUrl) => {
  console.log('Screenshot length:', dataUrl.length);
  console.log('Prefix:', dataUrl.substring(0, 50));
});
// Expected: "Screenshot length: <big number>"
// Expected prefix: "data:image/png;base64,iVBORw0KGgo..."
```
