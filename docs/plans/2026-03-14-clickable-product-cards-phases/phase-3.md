# Phase 3: Extension UI — Clickable Product Names

## Depends on: Phase 1 (url field in response)

## Files Changed
- `extension/sidepanel.js` (`renderProductList` function only)

---

## Change: `renderProductList` in `sidepanel.js`

### Current product name rendering (line ~729)
```javascript
<div class="list-product-name" title="${product.product_name}">${product.product_name}</div>
```

### New: make name a link when URL is available

```javascript
const nameHtml = product.url
  ? `<a class="list-product-name list-product-link"
        title="${product.product_name}"
        href="${product.url}"
        data-product-url="${product.url}"
     >${product.product_name}</a>`
  : `<div class="list-product-name" title="${product.product_name}">${product.product_name}</div>`;
```

Replace `${product.product_name}` in `item.innerHTML` template with `${nameHtml}`.

### Add click handler for the link (after `item.innerHTML` is set)

After the existing expand/collapse click handler, add:

```javascript
// Navigate to product URL when name is clicked
const nameLink = item.querySelector('.list-product-link');
if (nameLink) {
  nameLink.addEventListener('click', async (e) => {
    e.preventDefault();
    e.stopPropagation(); // prevent header expand/collapse
    const url = nameLink.dataset.productUrl;
    if (!url) return;
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.id) chrome.tabs.update(tab.id, { url });
  });
}
```

---

## CSS — add to `sidepanel.html` stylesheet

The link should look like the existing product name (not a blue underlined browser default):

```css
.list-product-link {
  color: inherit;
  text-decoration: none;
  cursor: pointer;
}
.list-product-link:hover {
  text-decoration: underline;
  opacity: 0.85;
}
```

---

## Manual Verification

1. Analyze a product listing page (Amazon Fresh seafood or Whole Foods seafood section)
2. Product cards appear in the side panel
3. Hover over a product name — cursor changes to pointer, name underlines
4. Click a product name — current browser tab navigates to that product page
5. The expand/collapse chevron on the right still works independently (click chevron or rest of header)
6. Cards where URL matching failed render the name as plain text — no pointer cursor, no underline
7. No `undefined` or `null` values appear in the href
