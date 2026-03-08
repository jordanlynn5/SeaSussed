# Phase WA-3: Extension UI Health Card

**Blocked by:** Phase WA-2 (requires `health` field in API response)

**Goal:** Render the health score card in the side panel. Card is only shown when `result.health` is not null. Matches the visual style of the existing sustainability score display.

---

## Files Changed

| File | Change |
|---|---|
| `extension/sidepanel.html` | Add `.health-card` CSS + health card HTML section |
| `extension/sidepanel.js` | Add `renderHealthCard()` function; call from result renderer |

No backend changes. No manifest changes.

---

## UI Design

The health card appears **below the sustainability score / grade badge** and **above the breakdown accordion**. It is a compact single-row card.

```
┌─────────────────────────────────────┐
│  Grade A  87/100                    │  ← existing sustainability score
│  Sustainability: Excellent Choice   │
├─────────────────────────────────────┤
│  🫀 Health   Best Choice  A 🟢      │  ← NEW health card (only when data available)
│  Mercury: 0.048 ppm · Omega-3: 892mg│
│  Source: Wolfram Alpha              │
├─────────────────────────────────────┤
│  ▼ Breakdown                        │  ← existing breakdown accordion
│  ...                                │
└─────────────────────────────────────┘
```

**Grade color coding** matches sustainability:
- A 🟢 `#16a34a` (green)
- B 🟡 `#ca8a04` (amber)
- C 🟠 `#ea580c` (orange)
- D 🔴 `#dc2626` (red)

**Source note** ("Wolfram Alpha") is shown in small muted text — transparency for the user about data origin.

---

## Implementation

### `extension/sidepanel.html` — CSS addition

Add inside the `<style>` block:

```css
/* Health card */
.health-card {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
  padding: 10px 14px;
  margin: 12px 0;
}
.health-card.grade-b { background: #fefce8; border-color: #fde047; }
.health-card.grade-c { background: #fff7ed; border-color: #fed7aa; }
.health-card.grade-d { background: #fef2f2; border-color: #fecaca; }

.health-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 13px;
  margin-bottom: 4px;
}
.health-grade-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 12px;
  color: white;
  background: #16a34a;
}
.health-grade-badge.grade-b { background: #ca8a04; }
.health-grade-badge.grade-c { background: #ea580c; }
.health-grade-badge.grade-d { background: #dc2626; }

.health-card-detail {
  font-size: 12px;
  color: #374151;
  margin-bottom: 2px;
}
.health-card-source {
  font-size: 11px;
  color: #9ca3af;
}
```

### `extension/sidepanel.html` — HTML addition

Add a placeholder div in the result view section (after the sustainability grade badge, before the breakdown accordion):

```html
<!-- Health card — only rendered when result.health is not null -->
<div id="health-card-container"></div>
```

---

### `extension/sidepanel.js` — `renderHealthCard()` function

```javascript
function renderHealthCard(health) {
  const container = document.getElementById('health-card-container');
  if (!container) return;

  // Hide if no health data
  if (!health) {
    container.innerHTML = '';
    return;
  }

  const grade = health.health_grade;
  const gradeClass = `grade-${grade.toLowerCase()}`;

  const mercuryText = health.mercury_ppm != null
    ? `Mercury: ${health.mercury_ppm} ppm`
    : (health.mercury_category ? `Mercury: ${health.mercury_category}` : null);

  const omega3Text = health.omega3_mg_per_serving != null
    ? `Omega-3: ${Math.round(health.omega3_mg_per_serving)}mg`
    : null;

  const detailParts = [mercuryText, omega3Text].filter(Boolean);

  container.innerHTML = `
    <div class="health-card ${gradeClass}">
      <div class="health-card-header">
        <span>🫀 Health</span>
        <span>${health.mercury_category || 'See details'}</span>
        <span class="health-grade-badge ${gradeClass}">${grade}</span>
      </div>
      ${detailParts.length ? `
        <div class="health-card-detail">${detailParts.join(' · ')}</div>
      ` : ''}
      <div class="health-card-source">Source: ${health.source_note}</div>
    </div>
  `;
}
```

Call `renderHealthCard(result.health)` inside the existing result rendering function after the sustainability score is rendered. If no result view renderer exists yet (Phase 5 is still pending), add a stub call where Phase 5 will hook in.

---

## Notes for Phase 5 Integration

Phase 5 (Extension UI Integration) will build the full result view. The health card slots in cleanly:

1. Add `<div id="health-card-container"></div>` in the result view HTML
2. Call `renderHealthCard(result.health)` after populating the rest of the result
3. The health card will automatically hide itself when `result.health === null`

No API changes needed — the `health` field is already in the response from Phase WA-2.

---

## Success Criteria

### Manual
- [ ] Whole Foods sockeye screenshot → health card renders with "Best Choice", grade A badge 🟢
- [ ] Swordfish product → health card renders with "Lower Choice" or "Avoid", grade C/D badge 🔴
- [ ] Pasta screenshot → `result.health` is null → health card container is empty (not visible)
- [ ] Health card style matches rest of side panel (font, border radius, spacing)
- [ ] "Source: Wolfram Alpha" appears in muted text at bottom of card
- [ ] On mobile-width side panel (360px), card does not overflow

### Automated
- No JS tests required (UI rendering); coverage provided by Phase WA-2 integration tests verifying the `health` field is populated correctly in the API response

### Pre-commit
- [ ] Full suite: `mypy . && ruff check . && pytest` all green (backend unchanged in this phase)
