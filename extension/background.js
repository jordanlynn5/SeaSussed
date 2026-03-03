// extension/background.js
importScripts('config.js');

const pendingTabs = new Set();

// Toolbar icon click → open side panel
chrome.action.onClicked.addListener((tab) => {
  chrome.sidePanel.open({ windowId: tab.windowId });
});

// Messages from sidepanel.js and voice-client.js
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

  if (msg.type === 'CAPTURE_SCREENSHOT_FOR_VOICE') {
    captureScreenshotForVoice(msg.tabId, msg.url, msg.pageTitle)
      .then(sendResponse)
      .catch(err => sendResponse({ error: err.message }));
    return true;
  }
});

async function captureVisibleTab(tabId) {
  const tab = await chrome.tabs.get(tabId);
  return new Promise((resolve, reject) => {
    chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' }, (result) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve(result);
      }
    });
  });
}

async function captureScreenshotForVoice(tabId, url, pageTitle) {
  const dataUrl = await captureVisibleTab(tabId);
  const base64 = dataUrl.split(',')[1];

  let relatedProducts = [];
  try {
    const domData = await chrome.scripting.executeScript({
      target: { tabId },
      func: scrapeRelatedProducts,
    });
    relatedProducts = domData[0]?.result ?? [];
  } catch (_) {}

  return {
    screenshot: base64,
    url,
    page_title: pageTitle,
    related_products: relatedProducts,
  };
}

async function handleAnalyze(tabId, url) {
  // 1. Capture screenshot
  const dataUrl = await captureVisibleTab(tabId);
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
    signal: AbortSignal.timeout(45000),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Backend error ${response.status}: ${text.substring(0, 120)}`);
  }

  return await response.json();
}

// Injected function — runs in page context
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
