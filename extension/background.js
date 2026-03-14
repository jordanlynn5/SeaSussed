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
        '#productDetails_detailBullets_sections1 tr, #productDetails_db_sections tr, ' +
        '#productOverview_feature_div tr, .product-details tr, ' +
        '[class*="ProductDetail"] tr, [class*="product-detail"] li, ' +
        '.a-expander-content tr'
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
  const rawRelated = relatedResult[0]?.result ?? [];
  const pageTitle = titleResult[0]?.result ?? '';

  // Split {title, url}[] into backward-compat string[] + new URL map (drop null-URL entries)
  const relatedProductsWithUrls = Array.isArray(rawRelated)
    ? rawRelated.filter(r => typeof r === 'object' && r !== null && r.url)
                .map(r => ({ ...r, url: cleanProductUrl(r.url) }))
    : [];
  const relatedProducts = Array.isArray(rawRelated)
    ? rawRelated.filter(r => typeof r === 'object' && r !== null).map(r => r.title)
    : [];

  // Fetch product gallery images in parallel (max 5, 5s timeout each)
  const imagePromises = imageUrls.slice(0, 5).map(u => fetchImageAsBase64(u));
  const imageResults = await Promise.all(imagePromises);
  const productImages = imageResults.filter(Boolean);

  console.log(`[SeaSussed] Captured: screenshot + ${productImages.length} gallery images + ${pageText.length} chars DOM text`);

  return {
    screenshot, pageTitle, pageText, productImages,
    relatedProducts, relatedProductsWithUrls, url,
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

  // 2. Scrape related product titles + URLs from page DOM
  let relatedProducts = [];
  let relatedProductsWithUrls = [];
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: scrapeRelatedProducts,
    });
    const rawRelated = results[0]?.result ?? [];
    relatedProductsWithUrls = Array.isArray(rawRelated)
      ? rawRelated.filter(r => typeof r === 'object' && r !== null && r.url)
                  .map(r => ({ ...r, url: cleanProductUrl(r.url) }))
      : [];
    relatedProducts = Array.isArray(rawRelated)
      ? rawRelated.filter(r => typeof r === 'object' && r !== null).map(r => r.title)
      : [];
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
      related_products_with_urls: relatedProductsWithUrls,
    }),
    signal: AbortSignal.timeout(45000),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Backend error ${response.status}: ${text.substring(0, 120)}`);
  }

  return await response.json();
}

// ── Clean product URLs (strip session tokens from Amazon Fresh URLs) ──
function cleanProductUrl(url) {
  if (!url) return url;
  try {
    const parsed = new URL(url);
    // Amazon: extract just the stable dp/ASIN path, strip all session tokens
    if (/amazon\.(com|co\.uk|ca|de|fr|es|it|co\.jp|com\.au)$/.test(parsed.hostname)) {
      const dpMatch = parsed.pathname.match(/\/(dp|gp\/product)\/([A-Z0-9]{10})/);
      if (dpMatch) return `https://${parsed.hostname}${dpMatch[0]}`;
    }
    return url;
  } catch (_) { return url; }
}

// ── Store search URL patterns ──
const SEARCH_URL_PATTERNS = {
  'www.wholefoodsmarket.com': (q) => `https://www.wholefoodsmarket.com/search?text=${encodeURIComponent(q)}`,
  'www.instacart.com': (q) => `https://www.instacart.com/store/search/${encodeURIComponent(q)}`,
  'www.walmart.com': (q) => `https://www.walmart.com/search?q=${encodeURIComponent(q)}`,
  'www.kroger.com': (q) => `https://www.kroger.com/search?query=${encodeURIComponent(q)}`,
  'www.safeway.com': (q) => `https://www.safeway.com/shop/search-results.html?q=${encodeURIComponent(q)}`,
  'www.target.com': (q) => `https://www.target.com/s?searchTerm=${encodeURIComponent(q)}`,
  'www.amazon.com': (q) => `https://www.amazon.com/s?k=${encodeURIComponent(q)}&i=grocery`,
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

  console.log('[SeaSussed] searchStoreForVoice — url:', searchUrl, 'query:', query);

  // Open search tab in background (invisible) — DOM-only, no screenshot needed
  const tab = await chrome.tabs.create({ url: searchUrl, active: false });

  try {
    // Wait for the tab to finish loading (max 12s)
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        chrome.tabs.onUpdated.removeListener(listener);
        console.log('[SeaSussed] Search tab load timed out (12s), scraping anyway');
        resolve(); // resolve anyway — we'll try scraping whatever is there
      }, 12000);

      function listener(tabId, info) {
        if (tabId === tab.id && info.status === 'complete') {
          chrome.tabs.onUpdated.removeListener(listener);
          clearTimeout(timeout);
          console.log('[SeaSussed] Search tab loaded');
          resolve();
        }
      }
      chrome.tabs.onUpdated.addListener(listener);
    });

    // Poll for SPA content to render (many grocery sites are React/Next.js)
    await new Promise((resolve) => {
      let elapsed = 0;
      const poll = setInterval(async () => {
        elapsed += 500;
        try {
          const [result] = await chrome.scripting.executeScript({
            target: { tabId: tab.id },
            func: () => {
              // Check if any product-like content has rendered
              const sels = [
                '[data-testid*="product"]', '[class*="product"]', '[class*="Product"]',
                '[data-component-type="s-search-result"]', 'main a img',
                // Whole Foods / grocery-specific
                '[class*="tile"]', '[class*="Tile"]', '[class*="item"]',
                '[class*="grid"] a[href*="/product"]',
              ];
              for (const sel of sels) {
                if (document.querySelectorAll(sel).length > 0) return true;
              }
              // Fallback: check if main content has substantial text
              const main = document.querySelector('main, [role="main"]');
              return main ? main.innerText.trim().length > 200 : false;
            },
          });
          if (result?.result || elapsed >= 8000) {
            clearInterval(poll);
            // Brief extra pause for final render
            setTimeout(resolve, 500);
          }
        } catch {
          if (elapsed >= 8000) { clearInterval(poll); resolve(); }
        }
      }, 500);
    });

    // Scrape product text + URLs from search results DOM
    const domResult = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const products = [];
        // Common product card selectors across grocery sites
        const cardSelectors = [
          '[data-testid*="product"]', '[class*="product-card"]', '[class*="ProductCard"]',
          '[class*="product-tile"]', '[class*="ProductTile"]', '[class*="product-item"]',
          '[class*="ProductItem"]', '.product', '[data-component-type="s-search-result"]',
          '[class*="search-result"]', 'li[class*="product"]',
          // Whole Foods / grocery-specific
          '[class*="tile"]', '[class*="Tile"]',
          '[role="listitem"]', '[data-testid*="item"]',
        ];
        let cards = [];
        for (const sel of cardSelectors) {
          cards = document.querySelectorAll(sel);
          if (cards.length > 0) break;
        }
        if (cards.length > 0) {
          cards.forEach(card => {
            const text = card.innerText?.trim();
            if (!text || text.length <= 5 || text.length >= 500) return;
            const link = card.querySelector('a[href]');
            const url = link ? link.href : null;
            products.push({ text, url });
          });
        }
        // Fallback 1: grab product title elements (often are links themselves)
        if (products.length === 0) {
          const titleSels = [
            '[data-testid*="product"] h2 a', '[data-testid*="product"] h3 a',
            '[data-testid*="product"] h2', '[data-testid*="product"] h3',
            '.product-title a', '.product-name a',
            '[class*="ProductName"] a', '[class*="product-title"] a',
            '[class*="ProductTitle"] a', 'h2 a', 'h3 a',
          ];
          for (const sel of titleSels) {
            document.querySelectorAll(sel).forEach(el => {
              const text = el.innerText?.trim();
              if (!text || text.length <= 3 || text.length >= 200) return;
              const url = el.href || el.closest('a')?.href || null;
              products.push({ text, url });
            });
            if (products.length > 0) break;
          }
        }
        // Fallback 2: all links in main content area that look like product pages
        if (products.length === 0) {
          const main = document.querySelector(
            'main, [role="main"], #main-content, #search-results, #content'
          );
          const container = main || document.body;
          container.querySelectorAll('a[href]').forEach(a => {
            const text = a.innerText?.trim();
            if (!text || text.length <= 5 || text.length >= 300) return;
            const href = a.href || '';
            // Skip navigation/utility links
            if (/\/(cart|login|account|help|faq|about|contact|sign)/i.test(href)) return;
            if (/^\s*(menu|sign in|log in|cart|help|close)\s*$/i.test(text)) return;
            // Favor links that look like product pages
            const isProductUrl = /\/(product|item|dp|p\/|pd\/|store\/)/i.test(href);
            // Also accept links with reasonable product-name-like text (has spaces, lowercase)
            const looksLikeProduct = text.includes(' ') && text.length >= 10;
            if (isProductUrl || looksLikeProduct) {
              products.push({ text, url: href });
            }
          });
        }
        // Final fallback: main content area text + any links found
        if (products.length === 0) {
          const container = document.querySelector(
            'main, [role="main"], #main-content, #search-results, #content'
          ) || document.body;
          const links = [];
          container.querySelectorAll('a[href]').forEach(a => {
            const t = a.innerText?.trim();
            if (t && t.length > 5 && t.length < 200 && a.href) {
              links.push({ name: t, url: a.href });
            }
          });
          return {
            page_text: 'SEARCH RESULTS:\n' + container.innerText.trim().substring(0, 5000),
            product_links: links.slice(0, 20),
          };
        }
        // Build page_text for Gemini analysis + product_links for navigation
        const pageText = 'SEARCH RESULTS:\n' + products.slice(0, 20).map(p => p.text).join('\n---\n');
        const productLinks = products.slice(0, 20)
          .filter(p => p.url)
          .map(p => ({ name: p.text.split('\n')[0].trim(), url: p.url }));
        return { page_text: pageText, product_links: productLinks };
      },
    }).catch(() => [{ result: { page_text: '', product_links: [] } }]);

    const title = (await chrome.tabs.get(tab.id)).title || '';
    const scraped = domResult[0]?.result ?? { page_text: '', product_links: [] };
    // Handle both old string format and new object format
    const pageText = typeof scraped === 'string' ? scraped : (scraped.page_text || '');
    const productLinks = (typeof scraped === 'object' ? (scraped.product_links || []) : [])
      .map(p => ({ ...p, url: cleanProductUrl(p.url) }));

    console.log('[SeaSussed] Search scraped:', pageText.length, 'chars text,', productLinks.length, 'links');
    if (pageText.length < 100) {
      console.warn('[SeaSussed] Search scrape looks thin! Text:', pageText.substring(0, 200));
    }

    return {
      screenshot: '',
      url: searchUrl,
      page_title: title,
      page_text: pageText,
      product_links: productLinks,
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
// Returns [{title: string, url: string | null}] for each product found.
function scrapeRelatedProducts() {
  const selectors = [
    // Amazon Fresh / Amazon search results
    '[data-component-type="s-search-result"] h2',
    '[data-asin] h2',
    // Generic data-testid patterns
    '[data-testid*="product"] h2', '[data-testid*="product"] h3',
    // Class-based patterns
    '.product-title', '.product-name',
    '[class*="ProductName"]', '[class*="product-title"]', '[class*="product-name"]',
    '[class*="ProductTitle"]',
    '[aria-label*="product"] h2', '[aria-label*="product"] h3',
    // Whole Foods specific
    '[data-ref*="product-name"]',
    '.w-pie--product-tile__content h2',
  ];

  const seen = new Set();
  const results = [];
  for (const sel of selectors) {
    try {
      document.querySelectorAll(sel).forEach(el => {
        const text = el.innerText?.trim();
        if (!text || text.length <= 3 || text.length >= 150) return;
        if (seen.has(text)) return;
        seen.add(text);
        // Find nearest <a> — look inside first (Amazon: <h2><a>title</a></h2>),
        // then walk up (Whole Foods: <a><div><h2>title</h2></div></a>),
        // then look inside the card container as last resort
        let url = null;
        const anchor = el.querySelector('a[href]') || el.closest('a[href]');
        if (anchor) {
          url = anchor.href || null;
        } else {
          const card = el.closest(
            '[data-component-type="s-search-result"], [data-asin], ' +
            '[data-testid*="product"], [class*="product-tile"], [class*="product-card"], ' +
            '[class*="ProductTile"], [class*="ProductCard"], li, article'
          );
          if (card) {
            const cardAnchor = card.querySelector('a[href]');
            if (cardAnchor) url = cardAnchor.href || null;
          }
        }
        // Skip nav/utility URLs and bare homepages
        if (url) {
          try {
            const parsed = new URL(url);
            const path = parsed.pathname.replace(/\/$/, '');
            if (path === '' || /\/(cart|login|account|help|faq|about|contact|sign)/i.test(url)) {
              url = null;
            }
          } catch (_) { url = null; }
        }
        results.push({ title: text, url });
      });
    } catch (_) {}
    if (results.length >= 15) break; // stop once we have enough
  }

  console.log('[SeaSussed] scrapeRelatedProducts:', results.length, 'items,',
    results.filter(r => r.url).length, 'with URLs', results.slice(0, 3));
  return results.slice(0, 15);
}
