# Phase 2: Chrome Extension Scaffold [batch-eligible]

**Days:** 1–2 | **Depends on:** nothing | **Blocks:** Phase 5

---

## Steps

### 1. Directory Structure

```
extension/
├── manifest.json
├── background.js       # MV3 service worker
├── content_script.js   # Injected into product pages
├── popup.html
├── popup.js
├── config.js           # BACKEND_URL constant (edit before loading)
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
    "storage"
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
    "default_popup": "popup.html",
    "default_icon": {
      "16": "icons/icon16.png",
      "48": "icons/icon48.png",
      "128": "icons/icon128.png"
    }
  }
}
```

### 3. config.js

```javascript
// extension/config.js
// Update BACKEND_URL before deploying or testing against Cloud Run
const BACKEND_URL = "http://localhost:8000"; // dev default
```

### 4. background.js (Service Worker)

```javascript
// extension/background.js
importScripts('config.js');

// Listen for analyze requests from content script or popup
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'ANALYZE_PAGE') {
    handleAnalyze(msg.tabId || sender.tab.id, msg.url)
      .then(sendResponse)
      .catch(err => sendResponse({ error: err.message }));
    return true; // keep message channel open for async response
  }
});

async function handleAnalyze(tabId, url) {
  // Capture visible tab as base64 PNG
  const dataUrl = await chrome.tabs.captureVisibleTab(null, { format: 'png' });
  const base64 = dataUrl.split(',')[1]; // strip "data:image/png;base64,"

  // Send to backend
  const response = await fetch(`${BACKEND_URL}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      screenshot: base64,
      url: url,
    }),
  });

  if (!response.ok) {
    throw new Error(`Backend error: ${response.status}`);
  }

  return await response.json();
}
```

### 5. content_script.js (Skeleton)

```javascript
// extension/content_script.js
// Injected into every page. Listens for analysis results and renders the overlay.

let overlayRoot = null;

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'SCORE_RESULT') {
    renderOverlay(msg.data);
  }
  if (msg.type === 'SCORE_LOADING') {
    renderLoadingState();
  }
  if (msg.type === 'SCORE_ERROR') {
    renderErrorState(msg.error);
  }
  if (msg.type === 'NOT_SEAFOOD') {
    removeOverlay();
  }
});

function renderOverlay(data) {
  // Phase 5 will implement the full overlay
  // For now: log to console to verify message passing works
  console.log('[SeaSussed] Score result received:', data);
}

function renderLoadingState() {
  console.log('[SeaSussed] Analysis in progress...');
}

function renderErrorState(error) {
  console.error('[SeaSussed] Error:', error);
}

function removeOverlay() {
  if (overlayRoot) {
    overlayRoot.remove();
    overlayRoot = null;
  }
}
```

### 6. popup.html

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body { width: 280px; padding: 16px; font-family: system-ui; }
    button { width: 100%; padding: 10px; background: #0d6efd; color: white;
             border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }
    button:hover { background: #0b5ed7; }
    #status { margin-top: 12px; font-size: 13px; color: #555; text-align: center; }
  </style>
</head>
<body>
  <h3 style="margin:0 0 12px">🐟 SeaSussed</h3>
  <button id="analyzeBtn">Analyze This Page</button>
  <div id="status"></div>
  <script src="popup.js"></script>
</body>
</html>
```

### 7. popup.js

```javascript
// extension/popup.js
document.getElementById('analyzeBtn').addEventListener('click', async () => {
  const status = document.getElementById('status');
  status.textContent = 'Analyzing...';

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

  // Notify content script: loading
  chrome.tabs.sendMessage(tab.id, { type: 'SCORE_LOADING' });

  chrome.runtime.sendMessage(
    { type: 'ANALYZE_PAGE', tabId: tab.id, url: tab.url },
    (result) => {
      if (chrome.runtime.lastError || result?.error) {
        chrome.tabs.sendMessage(tab.id, {
          type: 'SCORE_ERROR',
          error: result?.error || 'Unknown error'
        });
        status.textContent = '❌ Analysis failed.';
        return;
      }

      if (!result.product_info?.is_seafood) {
        chrome.tabs.sendMessage(tab.id, { type: 'NOT_SEAFOOD' });
        status.textContent = 'No seafood product detected.';
        return;
      }

      chrome.tabs.sendMessage(tab.id, { type: 'SCORE_RESULT', data: result });
      status.textContent = `Grade ${result.grade} — Score ${result.score}/100`;
    }
  );
});
```

## Verification

### Manual Checks
1. Load `extension/` as unpacked in `chrome://extensions` — no red errors
2. Open any webpage, click extension popup → "Analyze This Page"
3. Check Chrome DevTools Console on the tab: `[SeaSussed] Analysis in progress...` should appear
4. Check background service worker console: screenshot base64 logged (or backend call attempted)

### Smoke Test Script (run from extension/ context)
```javascript
// Paste in background service worker DevTools console:
chrome.tabs.captureVisibleTab(null, { format: 'png' }, (dataUrl) => {
  console.log('Screenshot captured, length:', dataUrl.length);
  console.log('First 50 chars:', dataUrl.substring(0, 50));
});
// Expected: "Screenshot captured, length: <big number>"
// Expected: "First 50 chars: data:image/png;base64,iVBORw0KGgo..."
```
