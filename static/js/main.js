/* ═══════════════════════════════════
   SONAR — main.js
   ═══════════════════════════════════ */

// ── Theme toggle ─────────────────────
(function () {
  const html = document.documentElement;
  const saved = localStorage.getItem('sonar-theme');
  if (saved === 'dark') html.dataset.theme = 'dark';
  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('theme-toggle')?.addEventListener('click', () => {
      const isDark = html.dataset.theme === 'dark';
      html.dataset.theme = isDark ? '' : 'dark';
      localStorage.setItem('sonar-theme', isDark ? '' : 'dark');
    });
  });
})();

// ── Video background ─────────────────
(function () {
  const video      = document.getElementById('bg-video');
  const toggleBtn  = document.getElementById('video-toggle-btn');
  const btnIcon    = toggleBtn?.querySelector('.vbtn-icon');
  const btnLabel   = toggleBtn?.querySelector('.vbtn-label');

  if (!video) return;

  let videoPaused = false;

  // Respect user's reduced-motion preference — don't autoplay
  const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (prefersReduced) {
    video.pause();
    videoPaused = true;
    if (toggleBtn) toggleBtn.style.display = 'none';
    return;
  }

  // Fade video in once it can play
  function onCanPlay() {
    video.classList.add('ready');
    document.body.classList.add('video-playing');
  }
  video.addEventListener('canplay', onCanPlay, { once: true });

  // If already ready (cached)
  if (video.readyState >= 3) onCanPlay();

  // Pause/resume toggle
  if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      if (videoPaused) {
        video.play().catch(() => {});
        videoPaused = false;
        btnIcon.textContent  = '⏸';
        btnLabel.textContent = 'Pause BG';
        document.body.classList.add('video-playing');
      } else {
        video.pause();
        videoPaused = true;
        btnIcon.textContent  = '▶';
        btnLabel.textContent = 'Play BG';
        document.body.classList.remove('video-playing');
      }
    });
  }

  // Pause video when tab is hidden (saves CPU/battery)
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      video.pause();
    } else if (!videoPaused) {
      video.play().catch(() => {});
    }
  });
})();

// ── Noise canvas ─────────────────────
(function () {
  const canvas = document.getElementById('noise-canvas');
  const ctx = canvas.getContext('2d');
  function resize() { canvas.width = window.innerWidth; canvas.height = window.innerHeight; }
  function makeNoise() {
    const img = ctx.createImageData(canvas.width, canvas.height);
    const d = img.data;
    for (let i = 0; i < d.length; i += 4) {
      const v = Math.random() * 255 | 0;
      d[i] = d[i+1] = d[i+2] = v; d[i+3] = 255;
    }
    ctx.putImageData(img, 0, 0);
  }
  resize(); makeNoise();
  window.addEventListener('resize', () => { resize(); makeNoise(); });
})();

// ── DOM refs ────────────────────────
const promptInput   = document.getElementById('prompt-input');
const charCount     = document.getElementById('char-count');
const generateBtn   = document.getElementById('generate-btn');
const outputIdle    = document.getElementById('output-idle');
const outputLoading = document.getElementById('output-loading');
const outputResult  = document.getElementById('output-result');
const outputError   = document.getElementById('output-error');
const loadingText   = document.getElementById('loading-text');
const progressFill  = document.getElementById('progress-fill');
const resultImg     = document.getElementById('result-img');
const metaPrompt    = document.getElementById('meta-prompt');
const errorMsg      = document.getElementById('error-msg');
const downloadBtn   = document.getElementById('download-btn');
const shareBtn      = document.getElementById('share-btn');
const regenerateBtn = document.getElementById('regenerate-btn');
const retryBtn      = document.getElementById('retry-btn');
const statusDot     = document.getElementById('status-dot');
const suggChips     = document.querySelectorAll('.sugg-chip');
const navBtns       = document.querySelectorAll('.nav-btn');
const historyGrid   = document.getElementById('history-grid');
const modelPills    = document.querySelectorAll('.pill');

// ── State ───────────────────────────
let lastPrompt   = '';
let lastDataUrl  = '';
let isGenerating = false;

// ── Tab switching ────────────────────
navBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    navBtns.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
    if (btn.dataset.tab === 'history') loadHistory();
  });
});

// ── Model pills ──────────────────────
modelPills.forEach(pill => {
  pill.addEventListener('click', () => {
    modelPills.forEach(p => p.classList.remove('active'));
    pill.classList.add('active');
  });
});
function getModel() {
  return document.querySelector('.pill.active input')?.value || 'sd21';
}

// ── Char counter ─────────────────────
promptInput.addEventListener('input', () => {
  const len = promptInput.value.length;
  charCount.textContent = `${len} / 500`;
  charCount.style.color = len > 450 ? 'var(--danger)' : '';
});

// ── Suggestion chips ─────────────────
suggChips.forEach(chip => {
  chip.addEventListener('click', () => {
    promptInput.value = chip.textContent;
    promptInput.dispatchEvent(new Event('input'));
    promptInput.focus();
  });
});

// ── State helpers ────────────────────
function showState(state) {
  [outputIdle, outputLoading, outputResult, outputError].forEach(el => el.classList.add('hidden'));
  const map = { idle: outputIdle, loading: outputLoading, result: outputResult, error: outputError };
  map[state]?.classList.remove('hidden');
}

// ── Progress simulation ──────────────
let progressInterval;
const loadingMessages = [
  'Initialising model…',
  'Encoding prompt…',
  'Generating latents…',
  'Denoising image…',
  'Decoding pixels…',
  'Almost ready…',
];
function startProgress() {
  let pct = 0; let msgIdx = 0;
  progressFill.style.width = '0%';
  loadingText.textContent = loadingMessages[0];
  progressInterval = setInterval(() => {
    pct = Math.min(pct + (Math.random() * 4 + 1), 92);
    progressFill.style.width = pct + '%';
    const newIdx = Math.min(Math.floor(pct / 18), loadingMessages.length - 1);
    if (newIdx !== msgIdx) { msgIdx = newIdx; loadingText.textContent = loadingMessages[msgIdx]; }
  }, 300);
}
function finishProgress(cb) {
  clearInterval(progressInterval);
  progressFill.style.width = '100%';
  setTimeout(cb, 400);
}

// ── Generate ─────────────────────────
async function generate(prompt) {
  if (isGenerating) return;
  prompt = prompt.trim();
  if (!prompt) { promptInput.focus(); return; }

  isGenerating = true;
  lastPrompt = prompt;
  generateBtn.disabled = true;
  showState('loading');
  startProgress();

  try {
    const res = await fetch('/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, model: getModel() }),
    });
    const data = await res.json();

    finishProgress(() => {
      if (res.ok && data.image_url) {
        // New response format: image_url instead of base64 data URL
        lastDataUrl = data.image_url;
        resultImg.src = data.image_url;
        metaPrompt.textContent = data.prompt;
        
        // Show fallback warning if applicable
        if (data.fallback && data.fallback_reason) {
          metaPrompt.textContent += ` (⚠️ Fallback mode: ${data.fallback_reason})`;
        }
        
        showState('result');
        statusDot.className = 'status-dot online';
      } else {
        errorMsg.textContent = data.error || 'Unknown error occurred.';
        showState('error');
        statusDot.className = 'status-dot offline';
      }
      isGenerating = false;
      generateBtn.disabled = false;
    });
  } catch (err) {
    finishProgress(() => {
      errorMsg.textContent = 'Network error — check your connection and try again.';
      showState('error');
      isGenerating = false;
      generateBtn.disabled = false;
    });
  }
}

generateBtn.addEventListener('click', () => generate(promptInput.value));
promptInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) generate(promptInput.value);
});
regenerateBtn.addEventListener('click', () => generate(lastPrompt));
retryBtn.addEventListener('click', () => generate(lastPrompt));

// ── Download ────────────────────────
downloadBtn.addEventListener('click', async () => {
  if (!lastDataUrl) return;
  try {
    // Fetch the image as a blob so the browser triggers a real download
    const blob = await (await fetch(lastDataUrl)).blob();
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objectUrl;
    a.download = `sonar_${Date.now()}.png`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 5000);
  } catch {
    // Fallback: direct link
    const a = document.createElement('a');
    a.href = lastDataUrl;
    a.download = `sonar_${Date.now()}.png`;
    a.click();
  }
});

// ── Share (copy to clipboard) ────────
shareBtn.addEventListener('click', async () => {
  try {
    const blob = await (await fetch(lastDataUrl)).blob();
    await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
    shareBtn.querySelector('svg').style.stroke = 'var(--success)';
    setTimeout(() => shareBtn.querySelector('svg').style.stroke = '', 1500);
  } catch {
    // Fallback: copy prompt text
    navigator.clipboard.writeText(lastPrompt).catch(() => {});
  }
});

// ── History ──────────────────────────
async function loadHistory() {
  historyGrid.innerHTML = `<div class="history-loading"><div class="mini-spinner"></div><span>Loading history…</span></div>`;
  try {
    const res = await fetch('/history');
    const data = await res.json();
    if (!data.items || data.items.length === 0) {
      historyGrid.innerHTML = `<div class="history-empty">No history yet. Generate your first image!</div>`;
      return;
    }
    historyGrid.innerHTML = '';
    data.items.forEach((item, i) => {
      const el = document.createElement('div');
      el.className = 'history-item';
      el.style.animationDelay = `${i * 0.05}s`;
      const timeStr = item.created_at ? new Date(item.created_at).toLocaleString() : '—';
      const modelLabel = item.model_key || item.model || 'sd21';
      const modeLabel  = item.model_used === 'local' ? '⚠️ fallback' : '✅ api';
      const imgContent = item.image_url
        ? `<img src="${item.image_url}" alt="Generated image" loading="lazy" style="width:100%;aspect-ratio:1;object-fit:cover;" />`
        : `<div style="aspect-ratio:1;background:var(--surface2);display:flex;align-items:center;justify-content:center;color:var(--text3);font-size:11px;padding:12px;text-align:center;">No image</div>`;
      // Use textContent for prompt to prevent XSS
      const promptEl = document.createElement('div');
      promptEl.className = 'history-item-prompt';
      promptEl.textContent = item.prompt;
      const timeEl = document.createElement('div');
      timeEl.className = 'history-item-time';
      timeEl.textContent = `${timeStr} · ${modelLabel} · ${modeLabel}`;
      el.innerHTML = imgContent;
      const meta = document.createElement('div');
      meta.className = 'history-item-meta';
      meta.appendChild(promptEl);
      meta.appendChild(timeEl);
      el.appendChild(meta);
      el.addEventListener('click', () => {
        promptInput.value = item.prompt;
        promptInput.dispatchEvent(new Event('input'));
        navBtns[0].click();
      });
      historyGrid.appendChild(el);
    });
  } catch {
    historyGrid.innerHTML = `<div class="history-empty">Could not load history.</div>`;
  }
}

// ── Status probe ─────────────────────
(async function checkStatus() {
  try {
    const r = await fetch('/health', { signal: AbortSignal.timeout(4000) });
    const data = await r.json().catch(() => ({}));
    if (r.ok && data.api_key) {
      statusDot.className = 'status-dot online';
      statusDot.title = `API ready · DB: ${data.database ? 'connected' : 'offline'}`;
    } else {
      statusDot.className = 'status-dot offline';
      statusDot.title = data.api_key === false ? 'API key missing' : 'API offline';
    }
  } catch {
    statusDot.className = 'status-dot offline';
    statusDot.title = 'Server unreachable';
  }
})();
