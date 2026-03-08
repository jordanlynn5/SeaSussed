// extension/content_script.js
// This script is injected into every page.
// Its only role is DOM scraping — it does NOT render any UI on the page.
// Actual scraping is done by chrome.scripting.executeScript in background.js.
// This file exists to satisfy the manifest content_scripts declaration and
// can be used for richer DOM access in future if needed.

console.log('[SeaSussed] Content script loaded on:', window.location.hostname);
