// extension/background.js
importScripts('config.js');

const pendingTabs = new Set();
const COOLDOWN_MS = 15_000;
const lastAnalyzedAt = {};   // tabId → timestamp (ms)
const lastAnalyzedUrl = {};  // tabId → URL string

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

    const url = msg.url;

    if (lastAnalyzedUrl[tabId] === url) {
      sendResponse({ error: 'duplicate' });
      return true;
    }

    const elapsed = Date.now() - (lastAnalyzedAt[tabId] ?? 0);
    if (elapsed < COOLDOWN_MS) {
      const secondsRemaining = Math.ceil((COOLDOWN_MS - elapsed) / 1000);
      sendResponse({ error: 'cooldown', secondsRemaining });
      return true;
    }

    pendingTabs.add(tabId);
    handleAnalyze(tabId, url)
      .then(result => {
        pendingTabs.delete(tabId);
        lastAnalyzedAt[tabId] = Date.now();
        lastAnalyzedUrl[tabId] = url;
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

  if (msg.type === 'SEARCH_STORE_FOR_VOICE') {
    searchStoreForVoice(msg.url, msg.query)
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

// ── Store search URL patterns ──
const SEARCH_URL_PATTERNS = {
  'www.wholefoodsmarket.com': (q) => `https://www.wholefoodsmarket.com/search?text=${encodeURIComponent(q)}`,
  'www.instacart.com': (q) => `https://www.instacart.com/store/search/${encodeURIComponent(q)}`,
  'www.walmart.com': (q) => `https://www.walmart.com/search?q=${encodeURIComponent(q)}`,
  'www.kroger.com': (q) => `https://www.kroger.com/search?query=${encodeURIComponent(q)}`,
  'www.safeway.com': (q) => `https://www.safeway.com/shop/search-results.html?q=${encodeURIComponent(q)}`,
  'www.target.com': (q) => `https://www.target.com/s?searchTerm=${encodeURIComponent(q)}`,
  'www.amazon.com': (q) => `https://www.amazon.com/s?k=${encodeURIComponent(q)}&i=amazonfresh`,
};

function buildSearchUrl(siteUrl, query) {
  try {
    const hostname = new URL(siteUrl).hostname;
    const builder = SEARCH_URL_PATTERNS[hostname];
    if (builder) return builder(query);
    // Fallback: try common /search?q= pattern on same origin
    const origin = new URL(siteUrl).origin;
    return `${origin}/search?q=${encodeURIComponent(query)}`;
  } catch (_) {
    return null;
  }
}

async function searchStoreForVoice(currentUrl, query) {
  const searchUrl = buildSearchUrl(currentUrl, query);
  if (!searchUrl) throw new Error('Cannot determine search URL for this site');

  // Open a background tab, wait for load, capture, close
  const tab = await chrome.tabs.create({ url: searchUrl, active: false });

  try {
    // Wait for the tab to finish loading (max 12s)
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        chrome.tabs.onUpdated.removeListener(listener);
        reject(new Error('Search page load timed out'));
      }, 12000);

      function listener(tabId, info) {
        if (tabId === tab.id && info.status === 'complete') {
          chrome.tabs.onUpdated.removeListener(listener);
          clearTimeout(timeout);
          // Small delay for dynamic content to render
          setTimeout(resolve, 1500);
        }
      }
      chrome.tabs.onUpdated.addListener(listener);
    });

    // Capture the search results page
    const dataUrl = await new Promise((resolve, reject) => {
      chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' }, (result) => {
        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
        else resolve(result);
      });
    });

    const base64 = dataUrl.split(',')[1];
    const title = (await chrome.tabs.get(tab.id)).title || '';

    return {
      screenshot: base64,
      url: searchUrl,
      page_title: title,
    };
  } finally {
    // Always close the background tab
    try { chrome.tabs.remove(tab.id); } catch (_) {}
  }
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
