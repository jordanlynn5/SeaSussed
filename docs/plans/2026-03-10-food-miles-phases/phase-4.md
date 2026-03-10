# Phase 4: Extension UI

**Status:** pending
**Depends on:** Phase 3

---

## Goal

Replace the carbon footprint card in the extension UI with a food miles card. Handle the new `food_miles` SSE phase.

---

## Modified Files

### `extension/sidepanel.html`

**Replace carbon card (lines 366-373):**

```html
<!-- was: Carbon footprint card -->
<!-- now: Food miles card -->
<div class="card fade-in" id="food-miles-card" style="display:none">
  <div style="display:flex; align-items:center; gap:8px; margin-bottom:6px;">
    <span style="font-size:16px;">🌊</span>
    <span class="section-title" style="margin-bottom:0;">Food Miles</span>
  </div>
  <div id="food-miles-card-body" style="font-size:13px; color:#374151; line-height:1.6;"></div>
</div>
```

### `extension/sidepanel.js`

**Replace `renderCarbonCard` with `renderFoodMilesCard`:**

```javascript
function renderFoodMilesCard(foodMiles) {
  if (!foodMiles) return;
  const card = document.getElementById('food-miles-card');
  const body = document.getElementById('food-miles-card-body');

  // Format distance with commas (e.g., 4,213)
  const distFormatted = foodMiles.distance_miles.toLocaleString();

  let html = `<div style="font-weight:600; margin-bottom:4px;">`;
  html += `~${distFormatted} miles`;
  html += `</div>`;
  html += `<div style="color:#6b7280; font-size:12px;">`;
  html += `${foodMiles.origin} → ${foodMiles.destination}`;
  html += `</div>`;
  html += `<div style="color:#9ca3af; font-size:11px; margin-top:4px;">Source: ${foodMiles.source}</div>`;
  body.innerHTML = html;
  card.style.display = '';
}
```

**Update `handleSSEEvent`:**

```javascript
// Replace:
if (data.phase === 'carbon') {
  renderCarbonCard(data.carbon);
  return;
}

// With:
if (data.phase === 'food_miles') {
  renderFoodMilesCard(data.food_miles);
  return;
}
```

**Update `triggerAnalyze` — reset card:**

```javascript
// Replace:
document.getElementById('carbon-card').style.display = 'none';

// With:
document.getElementById('food-miles-card').style.display = 'none';
```

**Update `renderResult` — render from complete result:**

```javascript
// Replace:
if (data.carbon) renderCarbonCard(data.carbon);

// With:
if (data.food_miles) renderFoodMilesCard(data.food_miles);
```

---

## Success Criteria

### Automated
- No backend tests affected (extension has no test suite)

### Manual
- Analyze a seafood product with known origin (e.g., "Norway") → food miles card appears with distance
- Analyze a product with no origin → food miles card stays hidden
- Card formats distance with commas (e.g., "4,213 miles")
- Card shows origin → destination (e.g., "Norway → Chicago, IL")
- Progressive loading: food miles card appears before alternatives/explanation
- Voice mode mentions food miles when relevant
