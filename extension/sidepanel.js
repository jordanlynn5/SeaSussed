// extension/sidepanel.js

const STORAGE_KEY = 'seasussed_onboarded';

const GRADE_COLORS = { A: '#22c55e', B: '#eab308', C: '#f97316', D: '#ef4444' };
const GRADE_LABELS = { A: '🟢 Best Choice', B: '🟡 Good Alternative', C: '🟠 Use Caution', D: '🔴 Avoid' };
const GRADE_EMOJI  = { A: '🟢', B: '🟡', C: '🟠', D: '🔴' };
const BREAKDOWN_MAX = { biological: 20, practices: 25, management: 30, ecological: 25 };
const SCORE_FILL_COLOR = { A: '#16a34a', B: '#ca8a04', C: '#ea580c', D: '#dc2626' };

// Cert definitions (static — never Gemini-generated)
const CERT_DEFINITIONS = {
  'MSC': {
    full_name: 'Marine Stewardship Council',
    explanation: 'The MSC blue fish logo means this fishery was independently audited against science-based standards. To earn MSC, a fishery must show healthy fish stocks, minimal environmental impact, and effective management systems. Annual surveillance audits maintain the certification.',
  },
  'ASC': {
    full_name: 'Aquaculture Stewardship Council',
    explanation: 'The ASC teal logo certifies responsibly farmed seafood. ASC farms meet standards covering feed sourcing, disease and chemical use, water quality, ecosystem impacts, and worker welfare. Considered the gold standard for farmed seafood certification.',
  },
  'BAP': {
    full_name: 'Best Aquaculture Practices',
    explanation: 'BAP certifies farmed seafood across four supply chain areas: hatcheries, farms, processing, and feed mills. The number of stars shows how many components are certified — more stars means greater traceability and sustainability verification.',
  },
  'GLOBALG.A.P.': {
    full_name: 'GlobalG.A.P.',
    explanation: 'GlobalG.A.P. certifies farms against food safety, environmental sustainability, and worker welfare standards. Respected internationally but less seafood-specific than ASC or BAP.',
  },
  'FRIEND OF THE SEA': {
    full_name: 'Friend of the Sea',
    explanation: 'Certifies both wild-caught and farmed seafood against sustainability criteria including stock status, bycatch reduction, and no impact on endangered species or seabed. Widely recognized internationally.',
  },
  'FOS': {
    full_name: 'Friend of the Sea',
    explanation: 'Friend of the Sea (FOS) certifies both wild-caught and farmed seafood against sustainability criteria including stock status, bycatch reduction, and no impact on endangered species or seabed.',
  },
  'ASMI': {
    full_name: 'Alaska Seafood Marketing Institute',
    explanation: 'The Alaska Seafood logo indicates seafood from Alaska — one of the world\'s best-managed fisheries regions. All Alaska commercial fisheries operate under the Magnuson-Stevens Act with science-based catch limits and independent stock assessments.',
  },
  'SUSTAINABLY SOURCED': {
    full_name: 'Sustainably Sourced (retailer claim)',
    explanation: '\'Sustainably sourced\' is an unverified marketing claim — not backed by independent audit. Unlike MSC or ASC, there\'s no standard defining what it means. Look for the MSC blue fish logo or ASC teal logo for independently verified sustainability.',
  },
  'RESPONSIBLY FARMED': {
    full_name: 'Responsibly Farmed (retailer claim)',
    explanation: '\'Responsibly Farmed\' is a retailer-defined standard audited by the retailer itself, not an independent body. A step above no label, but not equivalent to ASC or BAP certification.',
  },
  'SEAFOOD WATCH': {
    full_name: 'Monterey Bay Aquarium Seafood Watch',
    explanation: 'Seafood Watch is a science-based consumer guide from the Monterey Bay Aquarium rating seafood as Best Choice, Good Alternative, or Avoid. It\'s a rating system, not a certification (no logo on packaging) — but widely respected by restaurants and retailers.',
  },
};

let currentResult = null;
let voiceClient = null;
let pendingVoiceData = null; // held while mic-permission popup is open

// Receive grant from mic-permission.html popup and start voice
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'MIC_PERMISSION_GRANTED' && pendingVoiceData) {
    const { data } = pendingVoiceData;
    pendingVoiceData = null;
    connectVoice(data);
  }
});

// ── View management ──
function showView(id) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById(id)?.classList.add('active');
}

// ── Init: check if onboarded ──
chrome.storage.local.get(STORAGE_KEY, (res) => {
  showView(res[STORAGE_KEY] ? 'view-idle' : 'view-onboarding');
});

// ── Onboarding ──
document.getElementById('onboarding-ok')?.addEventListener('click', () => {
  chrome.storage.local.set({ [STORAGE_KEY]: true });
  showView('view-idle');
});

// ── Voice bar (inside view-result) ──
function showVoiceBar(text) {
  const bar = document.getElementById('voice-bar');
  if (bar) bar.style.display = 'flex';
  const s = document.getElementById('voice-bar-status');
  if (s) s.textContent = text;
}

function updateVoiceBar(state) {
  const dot = document.getElementById('voice-bar-indicator');
  const status = document.getElementById('voice-bar-status');
  if (!dot || !status) return;
  dot.className = 'vbar-dot' + (state === 'speaking' ? ' speaking' : state === 'thinking' ? ' thinking' : '');
  const labels = { listening: 'Listening…', thinking: 'Thinking…', speaking: 'Speaking…' };
  if (labels[state]) status.textContent = labels[state];
  if (state === 'ended' || state === 'error') stopVoiceBar();
}

function stopVoiceBar() {
  if (voiceClient) { voiceClient.stop(); voiceClient = null; }
  const bar = document.getElementById('voice-bar');
  if (bar) bar.style.display = 'none';
}

document.getElementById('voice-bar-stop')?.addEventListener('click', stopVoiceBar);

async function connectVoice(data, preStream = null) {
  if (voiceClient !== null) {
    if (preStream) preStream.getTracks().forEach(t => t.stop());
    return;
  }
  voiceClient = new VoiceClient();
  voiceClient.onStatus = updateVoiceBar;
  voiceClient.onScoreResult = () => {};
  voiceClient.onError = () => stopVoiceBar();
  voiceClient.onAudioActivity = () => {
    const dot = document.getElementById('voice-bar-indicator');
    if (!dot) return;
    dot.classList.add('mic-active');
    clearTimeout(dot._activityTimer);
    dot._activityTimer = setTimeout(() => dot.classList.remove('mic-active'), 150);
  };
  showVoiceBar('Connecting…');
  try {
    await voiceClient.start(preStream);
    updateVoiceBar('listening');
    voiceClient.sendResultContext({
      score: data.score,
      grade: data.grade,
      species: data.product_info?.species ?? null,
      wild_or_farmed: data.product_info?.wild_or_farmed ?? 'unknown',
    });
  } catch (err) {
    console.warn('[SeaSussed] Voice start failed:', err.message);
    stopVoiceBar();
    voiceClient = null;
  }
}

async function startVoiceAfterResult(data) {
  // Check current mic permission state.
  // If already granted, connect directly.
  // If prompt/unknown, open a dedicated popup page — getUserMedia from the popup's
  // button-click handler is the most reliable way to trigger Chrome's permission dialog
  // (side panel pages don't reliably surface the prompt in all Chrome versions).
  let micState = 'prompt';
  try {
    const perm = await navigator.permissions.query({ name: 'microphone' });
    micState = perm.state;
  } catch (_) { /* Permissions API unavailable — assume prompt */ }

  if (micState === 'denied') return; // mic blocked — skip silently

  if (micState === 'granted') {
    connectVoice(data);
    return;
  }

  // 'prompt' — open mic-permission.html popup; it sends MIC_PERMISSION_GRANTED on success
  pendingVoiceData = { data };
  const bar = document.getElementById('voice-bar');
  const status = document.getElementById('voice-bar-status');
  if (bar) bar.style.display = 'flex';
  if (status) {
    status.innerHTML = '<button id="voice-enable-btn" class="vbar-enable">Enable Voice</button>';
    document.getElementById('voice-enable-btn')?.addEventListener('click', () => {
      // Open as a tab — Chrome reliably shows the getUserMedia permission prompt
      // for extension pages opened as tabs; popup windows can fail with NotFoundError.
      chrome.tabs.create({
        url: chrome.runtime.getURL('mic-permission.html'),
        active: true,
      });
    });
  }
}

// ── Analyze ──
async function triggerAnalyze() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) return;

  showView('view-loading');

  chrome.runtime.sendMessage(
    { type: 'ANALYZE_PAGE', tabId: tab.id, url: tab.url },
    (result) => {
      if (chrome.runtime.lastError) {
        showError(chrome.runtime.lastError?.message || 'Unknown error');
        return;
      }
      if (result?.error === 'duplicate') {
        showError("You've already scored this product. Navigate to a different product for a new score.");
        return;
      }
      if (result?.error === 'cooldown') {
        startCooldownUI(result.secondsRemaining);
        return;
      }
      if (result?.error) {
        showError(result.error);
        return;
      }

      const pageType = result.page_type;

      if (pageType === 'no_seafood') {
        showView('view-non-seafood');
      } else if (pageType === 'product_listing' && result.products?.length > 0) {
        renderProductList(result.products);
      } else if (result.result) {
        if (!result.result.product_info?.is_seafood) {
          showView('view-non-seafood');
          return;
        }
        currentResult = result.result;
        renderResult(result.result);
      } else {
        // Fallback for old backend response shape (no page_type)
        if (!result.product_info?.is_seafood) {
          showView('view-non-seafood');
        } else {
          currentResult = result;
          renderResult(result);
        }
      }
    }
  );
}

document.getElementById('analyze-btn')?.addEventListener('click', triggerAnalyze);
document.getElementById('analyze-again-btn')?.addEventListener('click', triggerAnalyze);
document.getElementById('list-analyze-again-btn')?.addEventListener('click', triggerAnalyze);
document.getElementById('non-seafood-back-btn')?.addEventListener('click', () => showView('view-idle'));
document.getElementById('error-retry-btn')?.addEventListener('click', triggerAnalyze);
document.getElementById('error-back-btn')?.addEventListener('click', () => showView('view-idle'));

// ── Render Product List (multi-product) ──
function renderProductList(products) {
  const container = document.getElementById('product-list');
  const badge = document.getElementById('list-count-badge');
  if (!container) return;

  badge.textContent = products.length;
  container.innerHTML = '';

  products.forEach(product => {
    const color = GRADE_COLORS[product.grade] || '#6b7280';
    const gradeLabel = GRADE_LABELS[product.grade] || '';

    const item = document.createElement('div');
    item.className = 'product-list-item';

    // Meta tags
    let metaHtml = '';
    if (product.species)
      metaHtml += `<span class="tag">${product.species}</span>`;
    if (product.wild_or_farmed && product.wild_or_farmed !== 'unknown')
      metaHtml += `<span class="tag">${product.wild_or_farmed}</span>`;
    if (product.certifications?.length > 0)
      product.certifications.forEach(c => { metaHtml += `<span class="tag cert">${c}</span>`; });

    // Breakdown bars
    const bd = product.breakdown;
    const rows = [
      ['Biological', bd.biological, BREAKDOWN_MAX.biological],
      ['Practices',  bd.practices,  BREAKDOWN_MAX.practices],
      ['Management', bd.management, BREAKDOWN_MAX.management],
      ['Ecological', bd.ecological, BREAKDOWN_MAX.ecological],
    ];
    const breakdownHtml = rows.map(([label, val, max]) => {
      const pct = Math.round((val / max) * 100);
      const barColor = pct >= 70 ? '#22c55e' : pct >= 45 ? '#eab308' : '#ef4444';
      return `
        <div class="score-row">
          <span class="score-label">${label}</span>
          <div style="display:flex; align-items:center; gap:8px;">
            <div class="score-bar-wrap">
              <div class="score-bar" style="width:${pct}%; background:${barColor};"></div>
            </div>
            <span class="score-val">${Math.round(val)}/${max}</span>
          </div>
        </div>`;
    }).join('');

    item.innerHTML = `
      <div class="list-header">
        <div class="list-grade-circle" style="background:${color}">${product.grade}</div>
        <div class="list-product-body">
          <div class="list-product-name" title="${product.product_name}">${product.product_name}</div>
          <div class="list-product-meta">${metaHtml}</div>
        </div>
        <span class="list-score-text">${product.score}</span>
        <span class="list-chevron">▶</span>
      </div>
      <div class="list-breakdown">${breakdownHtml}</div>`;

    // Toggle expand/collapse
    item.querySelector('.list-header').addEventListener('click', () => {
      item.classList.toggle('open');
    });

    container.appendChild(item);
  });

  showView('view-results-list');

  if (products.length > 0) {
    const best = products[0];
    startVoiceAfterResult({
      score: best.score,
      grade: best.grade,
      product_info: { species: best.species ?? null, wild_or_farmed: best.wild_or_farmed ?? 'unknown' },
    });
  }
}

// ── Render Result ──
function renderResult(data) {
  const { score, grade, breakdown, alternatives, alternatives_label,
          explanation, score_factors, product_info } = data;
  const color = GRADE_COLORS[grade];

  // Grade badge
  document.getElementById('grade-circle').textContent = grade;
  document.getElementById('grade-circle').style.background = color;
  document.getElementById('grade-emoji-label').textContent = GRADE_LABELS[grade];
  document.getElementById('grade-score-text').textContent = `${score}/100`;

  // Extraction tags
  const tagsEl = document.getElementById('extraction-tags');
  tagsEl.innerHTML = '';
  if (product_info.species)
    tagsEl.innerHTML += `<span class="tag">${product_info.species}</span>`;
  if (product_info.wild_or_farmed !== 'unknown')
    tagsEl.innerHTML += `<span class="tag">${product_info.wild_or_farmed}</span>`;
  if (product_info.origin_region)
    tagsEl.innerHTML += `<span class="tag">${product_info.origin_region}</span>`;
  if (product_info.fishing_method)
    tagsEl.innerHTML += `<span class="tag">${product_info.fishing_method}</span>`;
  product_info.certifications?.forEach(c =>
    tagsEl.innerHTML += `<span class="tag cert" data-cert="${c}">${c}</span>`);

  tagsEl.querySelectorAll('.tag.cert').forEach(tag => {
    tag.addEventListener('click', (e) => showCertPopover(tag.dataset.cert, e));
  });

  // Explanation
  document.getElementById('explanation-text').textContent = explanation;

  // Breakdown rows
  const breakdownEl = document.getElementById('breakdown-rows');
  if (score_factors && score_factors.length > 0) {
    breakdownEl.innerHTML = score_factors.map(factor => {
      const pct = Math.round((factor.score / factor.max_score) * 100);
      const barColor = pct >= 70 ? '#22c55e' : pct >= 45 ? '#eab308' : '#ef4444';
      const tipHtml = factor.tip
        ? `<div class="breakdown-tip">💡 ${factor.tip}</div>` : '';
      return `
        <div class="breakdown-row">
          <div class="breakdown-header">
            <span class="score-label">${factor.category}</span>
            <div style="display:flex; align-items:center; gap:8px;">
              <div class="score-bar-wrap">
                <div class="score-bar" style="width:${pct}%; background:${barColor};"></div>
              </div>
              <span class="score-val">${Math.round(factor.score)}/${factor.max_score}</span>
              <span class="breakdown-chevron">▶</span>
            </div>
          </div>
          <div class="breakdown-detail">
            ${factor.explanation}
            ${tipHtml}
          </div>
        </div>`;
    }).join('');

    breakdownEl.querySelectorAll('.breakdown-header').forEach(header => {
      header.addEventListener('click', () => {
        header.parentElement.classList.toggle('open');
      });
    });
  } else {
    // Fallback: static breakdown rows (no score_factors)
    const practicesLabel = product_info.wild_or_farmed === 'farmed'
      ? 'Aquaculture Practices' : 'Fishing Practices';
    const rows = [
      ['Biological Status', breakdown.biological, BREAKDOWN_MAX.biological],
      [practicesLabel,      breakdown.practices,  BREAKDOWN_MAX.practices],
      ['Management',        breakdown.management, BREAKDOWN_MAX.management],
      ['Ecological',        breakdown.ecological, BREAKDOWN_MAX.ecological],
    ];
    breakdownEl.innerHTML = rows.map(([label, val, max]) => {
      const pct = Math.round((val / max) * 100);
      const barColor = pct >= 70 ? '#22c55e' : pct >= 45 ? '#eab308' : '#ef4444';
      return `
        <div class="score-row">
          <span class="score-label">${label}</span>
          <div style="display:flex; align-items:center; gap:8px;">
            <div class="score-bar-wrap">
              <div class="score-bar" style="width:${pct}%; background:${barColor};"></div>
            </div>
            <span class="score-val">${Math.round(val)}/${max}</span>
          </div>
        </div>`;
    }).join('');
  }

  // Alternatives
  const altsCard  = document.getElementById('alternatives-card');
  const altsList  = document.getElementById('alternatives-list');
  const altsTitle = document.getElementById('alternatives-title');

  if (alternatives && alternatives.length > 0) {
    altsCard.style.display = 'block';
    altsTitle.textContent = alternatives_label || 'Better alternatives';
    altsList.innerHTML = alternatives.map(alt => {
      const altColor = GRADE_COLORS[alt.grade];
      const fromPageNote = alt.from_page
        ? '' : '<div class="alt-from-page">(check if available on this site)</div>';
      return `
        <div class="alt-row">
          <div>
            <div class="alt-name">${alt.species}</div>
            <div class="alt-reason">${alt.reason}</div>
            ${fromPageNote}
          </div>
          <span class="alt-badge" style="background:${altColor}">${alt.grade}</span>
        </div>`;
    }).join('');

    const tip = document.getElementById('category-page-tip');
    const hasSeedOnly = alternatives.every(a => !a.from_page);
    if (hasSeedOnly && grade !== 'A') {
      tip.style.display = 'block';
      tip.textContent = 'Want options available on this site? Navigate to the seafood section and click Analyze again.';
    } else {
      tip.style.display = 'none';
    }
  } else {
    altsCard.style.display = 'none';
  }

  showView('view-result');
  startVoiceAfterResult(data);
}

// ── Cert popover ──
function showCertPopover(certName, event) {
  const certKey = certName.toUpperCase();
  let def = null;
  for (const [key, val] of Object.entries(CERT_DEFINITIONS)) {
    if (certKey === key || certKey.includes(key) || key.includes(certKey)) {
      def = val; break;
    }
  }
  if (!def) return;

  const popover = document.getElementById('cert-popover');
  document.getElementById('cert-popover-title').textContent = def.full_name;
  document.getElementById('cert-popover-body').textContent = def.explanation;

  const rect = event.currentTarget.getBoundingClientRect();
  const panelWidth = document.body.offsetWidth;
  let left = rect.left;
  if (left + 240 > panelWidth - 8) left = panelWidth - 248;
  if (left < 8) left = 8;
  popover.style.top  = `${rect.bottom + 6}px`;
  popover.style.left = `${left}px`;
  popover.classList.add('visible');
  event.stopPropagation();
}

document.addEventListener('click', (e) => {
  if (e.target?.id !== 'cert-popover-close') {
    document.getElementById('cert-popover')?.classList.remove('visible');
  }
});
document.getElementById('cert-popover-close')?.addEventListener('click', (e) => {
  document.getElementById('cert-popover')?.classList.remove('visible');
  e.stopPropagation();
});

// ── "Not right?" correction ──
document.getElementById('not-right-link')?.addEventListener('click', () => {
  if (!currentResult) return;
  const p = currentResult.product_info;
  document.getElementById('corr-species').value      = p.species || '';
  document.getElementById('corr-wild-farmed').value  = p.wild_or_farmed || 'unknown';
  document.getElementById('corr-method').value       = p.fishing_method || '';
  document.getElementById('corr-origin').value       = p.origin_region || '';
  document.getElementById('corr-certs').value        = (p.certifications || []).join(', ');
  showView('view-correction');
});

document.getElementById('correction-cancel-btn')?.addEventListener('click', () => {
  showView('view-result');
});

document.getElementById('correction-submit-btn')?.addEventListener('click', async () => {
  const certsRaw = document.getElementById('corr-certs').value;
  const certs = certsRaw.split(',').map(s => s.trim()).filter(Boolean);

  const correctedInfo = {
    is_seafood: true,
    species:         document.getElementById('corr-species').value.trim() || null,
    wild_or_farmed:  document.getElementById('corr-wild-farmed').value,
    fishing_method:  document.getElementById('corr-method').value || null,
    origin_region:   document.getElementById('corr-origin').value.trim() || null,
    certifications:  certs,
  };

  showView('view-loading');

  try {
    const response = await fetch(`${BACKEND_URL}/score`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_info: correctedInfo }),
      signal: AbortSignal.timeout(10000),
    });

    if (!response.ok) throw new Error(`Backend error ${response.status}`);

    currentResult = await response.json();
    renderResult(currentResult);
  } catch (err) {
    showError(err.message);
  }
});

// ── Cooldown UI ──
function startCooldownUI(secondsRemaining) {
  const BUTTON_IDS = ['analyze-btn', 'analyze-again-btn', 'list-analyze-again-btn'];
  const ORIGINAL_LABELS = {
    'analyze-btn': 'Analyze This Page',
    'analyze-again-btn': 'Analyze Again',
    'list-analyze-again-btn': 'Analyze Again',
  };

  let secs = secondsRemaining;

  BUTTON_IDS.forEach(id => {
    const btn = document.getElementById(id);
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = `Wait ${secs}s…`;
  });

  const interval = setInterval(() => {
    secs -= 1;
    if (secs <= 0) {
      clearInterval(interval);
      BUTTON_IDS.forEach(id => {
        const btn = document.getElementById(id);
        if (!btn) return;
        btn.disabled = false;
        btn.textContent = ORIGINAL_LABELS[id];
      });
    } else {
      BUTTON_IDS.forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.textContent = `Wait ${secs}s…`;
      });
    }
  }, 1000);

  // Stay on current view — don't redirect to error
}

// ── Error ──
function showError(message) {
  document.getElementById('error-message').textContent =
    message || 'Something went wrong. Please try again.';
  showView('view-error');
}
