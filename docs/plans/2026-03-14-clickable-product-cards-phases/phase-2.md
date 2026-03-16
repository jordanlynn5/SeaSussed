# Phase 2: Extension — Scraper + URL Passthrough [batch-eligible with Phase 1]

## Files Changed
- `extension/background.js`
- `extension/sidepanel.js` (fetch body only — `renderProductList` unchanged until Phase 3)

No backend changes. No new tests (JS, no test harness).

---

## Step 1 — Update `scrapeRelatedProducts` in `background.js`

### Current (line 592)
Returns `[title_string, ...]`

### New
Returns `[{title: string, url: string | null}, ...]`

```javascript
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

  const seen = new Set();
  const results = [];
  for (const sel of selectors) {
    try {
      document.querySelectorAll(sel).forEach(el => {
        const text = el.innerText?.trim();
        if (!text || text.length <= 3 || text.length >= 150) return;
        if (seen.has(text)) return;
        seen.add(text);
        // Walk up to find the nearest <a> ancestor, or look for one inside the
        // nearest product-card ancestor
        let url = null;
        const anchor = el.closest('a[href]') || el.querySelector('a[href]');
        if (anchor) {
          url = anchor.href || null;
        } else {
          // Look for <a> in closest product-card ancestor
          const card = el.closest(
            '[data-testid*="product"], [class*="product-tile"], [class*="product-card"], ' +
            '[class*="ProductTile"], [class*="ProductCard"], li, article'
          );
          if (card) {
            const cardAnchor = card.querySelector('a[href]');
            if (cardAnchor) url = cardAnchor.href || null;
          }
        }
        // Skip nav/utility URLs
        if (url && /\/(cart|login|account|help|faq|about|contact|sign)/i.test(url)) {
          url = null;
        }
        results.push({ title: text, url });
      });
    } catch (_) {}
  }
  return results.slice(0, 15);
}
```

---

## Step 2 — Update `capturePageData` in `background.js`

The function calls `scrapeRelatedProducts` and currently destructures the result as a string array. Update to handle the new `{title, url}[]` format:

```javascript
// After:
const relatedProducts = relatedResult[0]?.result ?? [];
// Add:
const relatedProductsWithUrls = Array.isArray(relatedProducts)
  ? relatedProducts.filter(r => typeof r === 'object' && r !== null)
  : [];
const relatedProductTitles = relatedProductsWithUrls.map(r => r.title);
```

Update the return value:
```javascript
return {
  screenshot, pageTitle, pageText, productImages,
  relatedProducts: relatedProductTitles,       // string[] — backward compat
  relatedProductsWithUrls,                     // {title, url}[] — new
  url,
};
```

---

## Step 3 — Update `handleAnalyze` in `background.js`

`handleAnalyze` uses the legacy `/analyze` endpoint and also calls `scrapeRelatedProducts`. Apply same extraction pattern:

```javascript
// After scraping:
const rawRelated = results[0]?.result ?? [];
const relatedProductsWithUrls = Array.isArray(rawRelated)
  ? rawRelated.filter(r => typeof r === 'object' && r !== null)
  : [];
const relatedProducts = relatedProductsWithUrls.map(r => r.title);

// In the fetch body:
body: JSON.stringify({
  screenshot: base64,
  url: url,
  page_title: pageTitle,
  related_products: relatedProducts,
  related_products_with_urls: relatedProductsWithUrls,   // ← NEW
}),
```

---

## Step 4 — Update `sidepanel.js` fetch body

In `triggerAnalyze()` (the SSE fetch, ~line 258):

```javascript
body: JSON.stringify({
  screenshot: pageData.screenshot,
  url: pageData.url,
  page_title: pageData.pageTitle,
  page_text: pageData.pageText,
  product_images: pageData.productImages,
  related_products: pageData.relatedProducts,
  related_products_with_urls: pageData.relatedProductsWithUrls ?? [],  // ← NEW
}),
```

---

## Step 5 — Manual Verification

1. Load extension locally (`extension/config.js` → `http://localhost:8000`)
2. Navigate to an Amazon Fresh seafood listing or Whole Foods seafood section
3. Click Analyze
4. Open DevTools → Network → check the `/analyze/stream` request body contains `related_products_with_urls` with `{title, url}` objects
5. Check the response `products` array — each item should have a `url` field (may be `null` for unmatched items)
