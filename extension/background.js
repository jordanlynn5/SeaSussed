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
