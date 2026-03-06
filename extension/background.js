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

  if (msg.type === 'CAPTURE_PAGE_DATA') {
    capturePageData(msg.tabId, msg.url)
      .then(sendResponse)
      .catch(err => sendResponse({ error: err.message }));
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

async function capturePageData(tabId, url) {
  // Capture screenshot + DOM text + product image URLs in parallel
  const screenshotPromise = captureVisibleTab(tabId);
  const domPromise = chrome.scripting.executeScript({
    target: { tabId },
    func: () => {
      // We need the functions in page context, so inline them
      const sections = [];
      const title = document.querySelector(
        '#productTitle, #title, h1, [data-testid*="product-title"], [class*="ProductTitle"]'
      );
      if (title) sections.push('TITLE: ' + title.innerText.trim());
      const bullets = document.querySelector('#feature-bullets');
      if (bullets) sections.push('FEATURES: ' + bullets.innerText.trim());
      const descSels = ['#productDescription', '#product-description', '[data-testid*="description"]',
        '[class*="product-description"]', '.product-description'];
      for (const sel of descSels) {
        const el = document.querySelector(sel);
        if (el && el.innerText.trim().length > 20) { sections.push('DESCRIPTION: ' + el.innerText.trim()); break; }
      }
      const rows = document.querySelectorAll(
        '#productDetails_techSpec_section_1 tr, #detailBullets_feature_div li, ' +
        '#productDetails_detailBullets_sections1 tr, .product-details tr, ' +
        '[class*="ProductDetail"] tr, [class*="product-detail"] li'
      );
      if (rows.length) {
        sections.push('DETAILS: ' + [...rows].map(e => e.innerText.trim()).filter(Boolean).join('\n'));
      }
      const important = document.querySelector('#important-information');
      if (important) sections.push('IMPORTANT INFO: ' + important.innerText.trim());
      const ingr = document.querySelector('#ingredients, [class*="ingredient"], [data-testid*="ingredient"]');
      if (ingr && ingr.innerText.trim().length > 10) sections.push('INGREDIENTS: ' + ingr.innerText.trim());
      if (sections.length < 2) {
        const main = document.querySelector('main, #main-content, [role="main"], #dp-container');
        if (main) sections.push('PAGE CONTENT: ' + main.innerText.trim().substring(0, 3000));
      }
      return sections.join('\n\n').substring(0, 5000);
    },
  }).catch(() => [{ result: '' }]);

  const imageUrlsPromise = chrome.scripting.executeScript({
    target: { tabId },
    func: scrapeProductImageUrls,
  }).catch(() => [{ result: [] }]);

  const relatedPromise = chrome.scripting.executeScript({
    target: { tabId },
    func: scrapeRelatedProducts,
  }).catch(() => [{ result: [] }]);

  const titlePromise = chrome.scripting.executeScript({
    target: { tabId },
    func: () => document.title,
  }).catch(() => [{ result: '' }]);

  const [dataUrl, domResult, imageUrlsResult, relatedResult, titleResult] =
    await Promise.all([screenshotPromise, domPromise, imageUrlsPromise, relatedPromise, titlePromise]);

  const screenshot = dataUrl.split(',')[1];
  const pageText = domResult[0]?.result ?? '';
  const imageUrls = imageUrlsResult[0]?.result ?? [];
  const relatedProducts = relatedResult[0]?.result ?? [];
  const pageTitle = titleResult[0]?.result ?? '';

  // Fetch product gallery images in parallel (max 5, 5s timeout each)
  const imagePromises = imageUrls.slice(0, 5).map(u => fetchImageAsBase64(u));
  const imageResults = await Promise.all(imagePromises);
  const productImages = imageResults.filter(Boolean);

  console.log(`[SeaSussed] Captured: screenshot + ${productImages.length} gallery images + ${pageText.length} chars DOM text`);

  return {
    screenshot, pageTitle, pageText, productImages, relatedProducts, url,
  };
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

// ── Product image extraction (injected into page) ──
function scrapeProductImageUrls() {
  const urls = new Set();

  // Amazon: data-a-dynamic-image attribute (JSON with URL→[w,h] mapping)
  document.querySelectorAll('[data-a-dynamic-image]').forEach(el => {
    try {
      const obj = JSON.parse(el.getAttribute('data-a-dynamic-image'));
      // Pick the largest image URL (highest width)
      let best = null, bestW = 0;
      for (const [url, dims] of Object.entries(obj)) {
        const w = Array.isArray(dims) ? dims[0] : 0;
        if (w > bestW) { bestW = w; best = url; }
      }
      if (best) urls.add(best);
    } catch {}
  });

  // Amazon: thumbnail images in #altImages that link to full-size
  document.querySelectorAll('#altImages img').forEach(img => {
    const src = img.src || '';
    if (!src || src.includes('sprite') || src.includes('icon')) return;
    // Convert thumbnail URL to large version
    const large = src.replace(/\._[A-Z]{2}_[A-Z0-9_.]+_\./, '._AC_SL1500_.');
    if (large !== src) urls.add(large);
    else urls.add(src);
  });

  // Amazon: main product image
  const mainImg = document.querySelector('#landingImage, #imgBlkFront');
  if (mainImg) {
    const hires = mainImg.getAttribute('data-old-hires');
    if (hires) urls.add(hires);
  }

  // Whole Foods
  document.querySelectorAll('[class*="ProductImage"] img, [class*="product-image"] img').forEach(img => {
    const src = img.currentSrc || img.src;
    if (src && src.startsWith('http')) urls.add(src);
  });

  // Generic: large images likely to be product photos
  document.querySelectorAll('img').forEach(img => {
    if (img.naturalWidth >= 250 && img.naturalHeight >= 250) {
      const src = img.currentSrc || img.src;
      if (src && src.startsWith('http') && !urls.has(src)) {
        const lower = src.toLowerCase();
        if (!lower.includes('icon') && !lower.includes('sprite') &&
            !lower.includes('logo') && !lower.includes('badge') &&
            !lower.includes('star') && !lower.includes('rating') &&
            !lower.includes('avatar')) {
          urls.add(src);
        }
      }
    }
  });

  return [...urls].slice(0, 8);
}

// ── Page text extraction (injected into page) ──
function scrapePageText() {
  const sections = [];

  // Product title
  const title = document.querySelector(
    '#productTitle, #title, h1, [data-testid*="product-title"], [class*="ProductTitle"]'
  );
  if (title) sections.push('TITLE: ' + title.innerText.trim());

  // Feature bullets (Amazon)
  const bullets = document.querySelector('#feature-bullets');
  if (bullets) sections.push('FEATURES: ' + bullets.innerText.trim());

  // Product description
  const descSelectors = [
    '#productDescription', '#product-description', '[data-testid*="description"]',
    '[class*="product-description"]', '.product-description',
  ];
  for (const sel of descSelectors) {
    const el = document.querySelector(sel);
    if (el && el.innerText.trim().length > 20) {
      sections.push('DESCRIPTION: ' + el.innerText.trim());
      break;
    }
  }

  // Product details tables (Amazon, Walmart, etc.)
  const detailRows = document.querySelectorAll(
    '#productDetails_techSpec_section_1 tr, #detailBullets_feature_div li, ' +
    '#productDetails_detailBullets_sections1 tr, .product-details tr, ' +
    '[class*="ProductDetail"] tr, [class*="product-detail"] li'
  );
  if (detailRows.length) {
    const detailText = [...detailRows].map(el => el.innerText.trim()).filter(Boolean).join('\n');
    sections.push('DETAILS: ' + detailText);
  }

  // Important information section (Amazon)
  const important = document.querySelector('#important-information');
  if (important) sections.push('IMPORTANT INFO: ' + important.innerText.trim());

  // Ingredients section
  const ingredientSelectors = [
    '#ingredients', '[class*="ingredient"]', '[data-testid*="ingredient"]',
  ];
  for (const sel of ingredientSelectors) {
    const el = document.querySelector(sel);
    if (el && el.innerText.trim().length > 10) {
      sections.push('INGREDIENTS: ' + el.innerText.trim());
      break;
    }
  }

  // Fallback: main content area if we got very little
  if (sections.length < 2) {
    const main = document.querySelector('main, #main-content, [role="main"], #dp-container');
    if (main) sections.push('PAGE CONTENT: ' + main.innerText.trim().substring(0, 3000));
  }

  return sections.join('\n\n').substring(0, 5000);
}

// ── Fetch an image URL and return base64 ──
async function fetchImageAsBase64(url) {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(5000) });
    if (!response.ok) return null;
    const blob = await response.blob();
    // Skip tiny images (< 5KB, likely icons) and huge ones (> 2MB)
    if (blob.size < 5000 || blob.size > 2_000_000) return null;

    const buffer = await blob.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    const chunks = [];
    const chunkSize = 8192;
    for (let i = 0; i < bytes.length; i += chunkSize) {
      chunks.push(String.fromCharCode(...bytes.subarray(i, i + chunkSize)));
    }
    return btoa(chunks.join(''));
  } catch {
    return null;
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
