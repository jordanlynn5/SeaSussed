# Phase 5: Extension UI — Health + Carbon Cards

**Files modified:** `extension/sidepanel.html`, `extension/sidepanel.js`
**Depends on:** Phase 4 (API contract)

---

## Goal

Render health and carbon info cards in the sidepanel. Health appears instantly with the
score. Carbon fades in when it arrives. Score card smoothly updates if research enriches
the data.

---

## 1. HTML Changes (`extension/sidepanel.html`)

Add two card containers inside `#view-result`, between the grade badge and the
extraction info card:

```html
<!-- After grade-badge, before extraction card -->

<!-- Health card (mercury + omega-3) -->
<div class="card fade-in" id="health-card" style="display:none">
  <div style="display:flex; align-items:center; gap:8px; margin-bottom:6px;">
    <span style="font-size:16px;">🐟</span>
    <span class="section-title" style="margin-bottom:0;">Health Info</span>
  </div>
  <div id="health-card-body" style="font-size:13px; color:#374151; line-height:1.6;"></div>
</div>

<!-- Carbon footprint card -->
<div class="card fade-in" id="carbon-card" style="display:none">
  <div style="display:flex; align-items:center; gap:8px; margin-bottom:6px;">
    <span style="font-size:16px;">🌍</span>
    <span class="section-title" style="margin-bottom:0;">Carbon Footprint</span>
  </div>
  <div id="carbon-card-body" style="font-size:13px; color:#374151; line-height:1.6;"></div>
</div>
```

---

## 2. JS Changes (`extension/sidepanel.js`)

### New render functions

```javascript
function renderHealthCard(health) {
  if (!health) return;
  const card = document.getElementById('health-card');
  const body = document.getElementById('health-card-body');

  const gradeColors = { A: '#16a34a', B: '#ca8a04', C: '#ea580c', D: '#dc2626' };
  const color = gradeColors[health.health_grade] || '#6b7280';

  let html = `<div style="font-weight:600; color:${color}; margin-bottom:4px;">`;
  html += `${health.mercury_category}`;
  if (health.mercury_ppm != null) {
    html += ` <span style="font-weight:400; color:#9ca3af;">(${health.mercury_ppm} ppm mercury)</span>`;
  }
  html += `</div>`;
  if (health.omega3_note) {
    html += `<div>${health.omega3_note}</div>`;
  }
  if (health.serving_advice) {
    html += `<div style="color:#6b7280; font-size:12px; margin-top:2px;">${health.serving_advice}</div>`;
  }
  body.innerHTML = html;
  card.style.display = '';
}


function renderCarbonCard(carbon) {
  if (!carbon) return;
  const card = document.getElementById('carbon-card');
  const body = document.getElementById('carbon-card-body');

  let html = `<div style="font-weight:600; margin-bottom:4px;">`;
  html += `~${carbon.co2_kg_per_serving} kg CO₂ per serving`;
  html += `</div>`;
  html += `<div style="color:#6b7280; font-size:12px;">${carbon.comparison_text}</div>`;
  html += `<div style="color:#9ca3af; font-size:11px; margin-top:4px;">Source: ${carbon.source}</div>`;
  body.innerHTML = html;
  card.style.display = '';
}
```

### Update SSE handler

In the existing SSE event loop (the `fetch /analyze/stream` handler), add cases for
the new phases:

```javascript
// Inside the SSE reader loop, after handling "scored" phase:

if (event.phase === 'health') {
  renderHealthCard(event.health);
}

if (event.phase === 'carbon') {
  renderCarbonCard(event.carbon);
}

if (event.phase === 'enriched') {
  // Score was updated by web research — update the score card
  updateGradeBadge(event.score, event.grade);
  updateBreakdownRows(event.breakdown);
  // Optionally flash the grade badge to indicate update
  const badge = document.getElementById('grade-badge');
  badge.classList.remove('fade-in');
  void badge.offsetWidth;  // force reflow
  badge.classList.add('fade-in');
}
```

### Update `showResult` / `renderResult`

When rendering a complete result (from non-streaming `/analyze` or the final `complete`
SSE phase), also render health + carbon if present:

```javascript
// Inside renderResult or equivalent:
if (result.health) renderHealthCard(result.health);
if (result.carbon) renderCarbonCard(result.carbon);
```

### Reset cards on new analysis

When starting a new analysis, hide the cards:

```javascript
// In the analyze button handler, before fetching:
document.getElementById('health-card').style.display = 'none';
document.getElementById('carbon-card').style.display = 'none';
```

---

## 3. CSS (already available)

The `.card` and `.fade-in` classes are already defined in sidepanel.html. The new cards
use them directly. No new CSS needed.

---

## Success Criteria

### Automated
- Extension loads without console errors
- Health card hidden when `health` is null
- Carbon card hidden when `carbon` is null

### Manual
- Analyze a salmon product page:
  - Health card appears immediately: "Best Choice", omega-3 note, FDA advice
  - Carbon card fades in ~1s later with CO₂ estimate
  - If research enriches the score, grade badge smoothly updates
- Analyze a swordfish product:
  - Health card shows "Choices to Avoid" in red
- Analyze a non-seafood page:
  - Neither card appears
