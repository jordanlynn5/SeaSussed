# Phase 3: Client-Side Navigation Guard

## Goal
Prevent duplicate `triggerAnalyze()` calls when `_navigateToUrl()` is called multiple times with the same URL.

## Files
- `extension/voice-client.js` — add navigation guard to `_navigateToUrl()`

## Changes

### voice-client.js — constructor (line ~9)

Add navigation tracking state:

```pseudo
+ this._pendingNavigateUrl = null;
+ this._navigateListener = null;
+ this._navigateTimeout = null;
```

### voice-client.js — _navigateToUrl (lines 288-310)

Add guard and cleanup previous listener:

```pseudo
  async _navigateToUrl(url) {
+   // Guard: skip if already navigating to this URL
+   if (this._pendingNavigateUrl === url) {
+     console.log('[SeaSussed] Skipping duplicate navigate to:', url);
+     return;
+   }
+
+   // Clean up any pending navigation listener
+   if (this._navigateListener) {
+     chrome.tabs.onUpdated.removeListener(this._navigateListener);
+     this._navigateListener = null;
+   }
+   if (this._navigateTimeout) {
+     clearTimeout(this._navigateTimeout);
+     this._navigateTimeout = null;
+   }
+
+   this._pendingNavigateUrl = url;

    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    const tab = tabs[0];
    if (!tab?.id || !url) return;
    await chrome.tabs.update(tab.id, { url });

    const tabId = tab.id;
-   const onUpdated = (updatedId, info) => {
+   this._navigateListener = (updatedId, info) => {
      if (updatedId === tabId && info.status === 'complete') {
-       chrome.tabs.onUpdated.removeListener(onUpdated);
-       clearTimeout(timeout);
+       chrome.tabs.onUpdated.removeListener(this._navigateListener);
+       clearTimeout(this._navigateTimeout);
+       this._navigateListener = null;
+       this._navigateTimeout = null;
+       this._pendingNavigateUrl = null;
        this._waitForProductContent(tabId).then(() => {
          if (typeof triggerAnalyze === 'function') triggerAnalyze();
        });
      }
    };
-   const timeout = setTimeout(() => {
-     chrome.tabs.onUpdated.removeListener(onUpdated);
+   this._navigateTimeout = setTimeout(() => {
+     chrome.tabs.onUpdated.removeListener(this._navigateListener);
+     this._navigateListener = null;
+     this._navigateTimeout = null;
+     this._pendingNavigateUrl = null;
    }, 15000);
-   chrome.tabs.onUpdated.addListener(onUpdated);
+   chrome.tabs.onUpdated.addListener(this._navigateListener);
  }
```

### voice-client.js — stop() (line ~101)

Clean up navigation state on stop:

```pseudo
  stop() {
+   if (this._navigateListener) {
+     chrome.tabs.onUpdated.removeListener(this._navigateListener);
+     this._navigateListener = null;
+   }
+   if (this._navigateTimeout) {
+     clearTimeout(this._navigateTimeout);
+     this._navigateTimeout = null;
+   }
+   this._pendingNavigateUrl = null;
    // ... existing cleanup ...
  }
```

## Success Criteria
- **Automated:** Extension loads without errors (no JS test suite for extension)
- **Manual:** Voice session search → navigate → only ONE `POST /analyze/stream` in backend logs
- **Manual:** Console shows `[SeaSussed] Skipping duplicate navigate to:` if Gemini tries to navigate twice
