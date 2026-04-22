'use strict';

let historyView = 'timeline';

function switchView(v) {
  historyView = v;
  document.getElementById('btn-timeline').classList.toggle('active', v === 'timeline');
  document.getElementById('btn-calendar').classList.toggle('active', v === 'calendar');
  document.getElementById('view-timeline').style.display = v === 'timeline' ? 'block' : 'none';
  document.getElementById('view-calendar').style.display = v === 'calendar' ? 'block' : 'none';
  loadHistory();
}

async function loadHistory() {
  if (historyView === 'timeline') await loadTimeline();
  else await loadCalendar();
}

// ── helpers ───────────────────────────────────────────────────────────────────

const CATEGORY_META = {
  positive: { label: 'Positive', color: '#FFD93D', text: '#5a4a00' },
  stress:   { label: 'Stress',   color: '#FF8C42', text: '#fff' },
  anxiety:  { label: 'Anxiety',  color: '#7B61FF', text: '#fff' },
  low_mood: { label: 'Low mood', color: '#4A90E2', text: '#fff' },
  anger:    { label: 'Anger',    color: '#FF4C4C', text: '#fff' },
  social:   { label: 'Social',   color: '#4CAF7D', text: '#fff' },
  _none:    { label: '—',        color: '#c5cad4', text: '#333' },
};

const CAL_CATEGORY_ORDER = ['positive', 'stress', 'anxiety', 'low_mood', 'anger', 'social', '_none'];

function _hashDaySeed(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

// ── Seeded LCG RNG (deterministic per day) ────────────────────────────────────

function _makePrng(seed) {
  let s = seed >>> 0 || 1;
  return function () {
    s = Math.imul(1664525, s) + 1013904223 >>> 0;
    return s / 4294967296;
  };
}

// Parse "#rrggbb" / "#rgb" hex to [r,g,b] 0-255
function _hexToRgb(hex) {
  const h = hex.replace('#', '');
  if (h.length === 3) {
    return [
      parseInt(h[0] + h[0], 16),
      parseInt(h[1] + h[1], 16),
      parseInt(h[2] + h[2], 16),
    ];
  }
  return [parseInt(h.slice(0,2),16), parseInt(h.slice(2,4),16), parseInt(h.slice(4,6),16)];
}

/**
 * Draw an organic memory-orb onto a canvas element.
 * Each colour gets blobs proportional to its count; blobs are randomly
 * placed soft radial gradients, creating a lava-lamp / ink-in-water look.
 * The seed ensures the same day always renders identically.
 */
function _buildOrbSvg(ordered, total, seed) {
  const NS = 'http://www.w3.org/2000/svg';
  const W = 100, H = 100; // viewBox units
  const rng = _makePrng(seed);
  const STEPS = 7; // points per wavy boundary
  const AMP   = 8; // ±px horizontal jitter

  // Cumulative x splits (0..100) between colour bands
  const splits = [];
  let acc = 0;
  for (let i = 0; i < ordered.length - 1; i++) {
    acc += (ordered[i].count / total) * W;
    splits.push(acc);
  }

  // Generate a wavy vertical boundary at xBase
  function wavyBoundary(xBase) {
    return Array.from({ length: STEPS + 1 }, (_, i) => {
      const y = (i / STEPS) * H;
      const x = Math.max(1, Math.min(W - 1, xBase + (rng() - 0.5) * 2 * AMP));
      return [x, y];
    });
  }

  const boundaries = splits.map(x => wavyBoundary(x));

  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('preserveAspectRatio', 'none');

  ordered.forEach((o, i) => {
    // Left edge: prev boundary (top→bottom) or left wall
    const left  = i === 0 ? [[0,0],[0,H]] : boundaries[i-1];
    // Right edge: next boundary (bottom→top) or right wall
    const right = i === ordered.length - 1 ? [[W,H],[W,0]] : [...boundaries[i]].reverse();

    const pts = [...left, ...right]
      .map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');

    const poly = document.createElementNS(NS, 'polygon');
    poly.setAttribute('points', pts);
    poly.setAttribute('fill', o.meta.color);
    svg.appendChild(poly);
  });

  return svg;
}

function appendCalMosaicSegments(mosaic, categories, dayStr) {
  const cats = categories || {};

  // Exclude _none — untagged entries don't contribute colour
  const ordered = [];
  const seen = new Set();
  for (const k of CAL_CATEGORY_ORDER) {
    if (k === '_none') continue;
    const n = cats[k];
    if (!n) continue;
    seen.add(k);
    ordered.push({ key: k, count: n, meta: CATEGORY_META[k] || { color: '#c5cad4' } });
  }
  for (const k of Object.keys(cats)) {
    if (k === '_none' || seen.has(k) || !cats[k]) continue;
    ordered.push({ key: k, count: cats[k], meta: CATEGORY_META[k] || { color: '#c5cad4' } });
  }

  const total = ordered.reduce((s, o) => s + o.count, 0);
  const seed  = _hashDaySeed(dayStr || 'cal');
  const list  = (!ordered.length || total <= 0)
    ? [{ key: '_', count: 1, meta: { color: '#efe8de' } }]
    : ordered;

  const svgEl = _buildOrbSvg(list, list.reduce((s,o)=>s+o.count,0), seed);
  svgEl.classList.add('cal-day-orb');
  mosaic.appendChild(svgEl);
}

function valenceColor(v) {
  if (v === null || v === undefined) return 'var(--ink-muted)';
  if (v > 0.15) return 'var(--positive)';
  if (v < -0.15) return 'var(--neg)';
  return 'var(--ink-muted)';
}

function formatTime(iso) {
  if (!iso) return '';
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

// ── timeline ──────────────────────────────────────────────────────────────────

function _teardownTimeline() {}
function _setupScroll() {}

function renderTimelineItem(e, idx) {
  const catMeta = e.category && CATEGORY_META[e.category] ? CATEGORY_META[e.category] : null;
  const dotColor = catMeta ? catMeta.color : 'var(--border)';
  const mode = e.mode || 'journal';
  const modeLabel = mode.charAt(0).toUpperCase() + mode.slice(1);

  const sourceIcon = e.source === 'voice' ? '<span style="font-size:0.75rem">🎙</span>'
    : e.source === 'image' ? '<span style="font-size:0.75rem">📷</span>' : '';

  const imgHtml = (e.source === 'image' && e.image_id)
    ? `<img src="/api/image/${e.image_id}/file" style="width:100%;max-height:7rem;object-fit:cover;border-radius:var(--radius-xs);display:block;margin-bottom:6px;">`
    : '';

  const text = document.createElement('div');
  text.className = 'tl-text';
  text.textContent = e.content || '';

  const subTags = (e.sub_tags || []).map(t => {
    const s = document.createElement('span');
    s.className = 'tl-tag';
    s.textContent = t;
    return s.outerHTML;
  }).join('');
  const tagsHtml = subTags ? `<div class="tl-tags">${subTags}</div>` : '';

  const moodHtml = (e.valence != null)
    ? `<div class="mood-bar"><div class="mood-fill" style="width:${Math.round(((e.valence + 1) / 2) * 100)}%;background:${dotColor}"></div></div>`
    : '';

  const item = document.createElement('div');
  item.className = 'tl-item';
  item.dataset.idx = idx;
  item.innerHTML = `
    <div class="tl-dot-wrap"><div class="tl-dot" style="background:${dotColor}"></div></div>
    <div class="tl-card">
      <div class="tl-meta">
        <span class="tl-mode-chip chip-${mode}">${modeLabel}</span>
        ${sourceIcon}
        <span class="tl-time">${formatTime(e.created_at)}</span>
      </div>
      ${imgHtml}
    </div>`;

  const card = item.querySelector('.tl-card');
  card.appendChild(text);
  if (tagsHtml) {
    const tagsDiv = document.createElement('div');
    tagsDiv.className = 'tl-tags';
    (e.sub_tags || []).forEach(t => {
      const s = document.createElement('span');
      s.className = 'tl-tag';
      s.textContent = t;
      tagsDiv.appendChild(s);
    });
    card.appendChild(tagsDiv);
  }
  if (moodHtml) {
    const bar = document.createElement('div');
    bar.className = 'mood-bar';
    const fill = document.createElement('div');
    fill.className = 'mood-fill';
    fill.style.width = Math.round(((e.valence + 1) / 2) * 100) + '%';
    fill.style.background = dotColor;
    bar.appendChild(fill);
    card.appendChild(bar);
  }

  return item;
}

async function loadTimeline(day) {
  _teardownTimeline();

  const container = document.getElementById('timeline');
  container.innerHTML = '<div style="color:var(--ink-muted);font-size:.85rem;padding:.5rem 0 .5rem 1rem;">Loading…</div>';

  try {
    const url  = day ? `/api/history?day=${day}` : '/api/history';
    const res  = await fetch(url);
    const data = await res.json();
    container.innerHTML = '';

    if (!data.entries || !data.entries.length) {
      container.innerHTML = '<div style="color:var(--ink-muted);font-size:.875rem;padding:2rem 0 2rem 2.5rem;text-align:center;">No entries yet.<br>Start by talking or journaling.</div>';
      return;
    }

    const today = new Date().toDateString();
    const yesterday = new Date(Date.now() - 864e5).toDateString();
    let lastLabel = null;

    data.entries.forEach((e, i) => {
      const d = e.created_at ? new Date(e.created_at.endsWith('Z') ? e.created_at : e.created_at + 'Z') : null;
      const ds = d ? d.toDateString() : null;
      let groupLabel = ds === today ? 'Today' : ds === yesterday ? 'Yesterday' : d ? d.toLocaleDateString(undefined, { month:'short', day:'numeric' }) : null;
      if (groupLabel && groupLabel !== lastLabel) {
        lastLabel = groupLabel;
        const lbl = document.createElement('div');
        lbl.className = 'tl-date-label';
        lbl.textContent = groupLabel;
        container.appendChild(lbl);
      }
      const el = renderTimelineItem(e, i);
      container.appendChild(el);
    });

  } catch (err) {
    container.innerHTML = `<div style="color:#f43f5e;font-size:.85rem;padding-left:2.5rem;">${err.message}</div>`;
  }
}

// ── calendar ──────────────────────────────────────────────────────────────────

async function loadCalendar() {
  const grid  = document.getElementById('calendar-grid');
  const label = document.getElementById('cal-month-label');
  grid.innerHTML = '';

  const now = new Date();
  label.textContent = now.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });

  const dayMap = {};
  try {
    const res  = await fetch('/api/history?view=calendar');
    const data = await res.json();
    (data.entries || []).forEach((r) => { dayMap[r.day] = r; });
  } catch {}

  ['Su','Mo','Tu','We','Th','Fr','Sa'].forEach(d => {
    const h = document.createElement('div');
    h.className = 'cal-header';
    h.textContent = d;
    grid.appendChild(h);
  });

  const year = now.getFullYear();
  const month = now.getMonth();
  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const today = now.getDate();

  for (let i = 0; i < firstDay; i++) {
    const cell = document.createElement('div');
    cell.className = 'cal-day empty';
    grid.appendChild(cell);
  }

  for (let d = 1; d <= daysInMonth; d++) {
    const dayStr = `${year}-${String(month+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
    const cell = document.createElement('div');
    cell.className = 'cal-day';
    const dayRow = dayMap[dayStr];
    const hasEntries = dayRow && dayRow.count > 0;
    if (hasEntries) cell.classList.add('has-entries', 'cal-day--mosaic');
    if (d === today) cell.style.outline = '2px solid var(--accent)';

    const num = document.createElement('span');
    num.textContent = d;

    if (hasEntries) {
      const mosaic = document.createElement('div');
      mosaic.className = 'cal-day-mosaic';
      appendCalMosaicSegments(mosaic, dayRow.categories, dayStr);
      const inner = document.createElement('div');
      inner.className = 'cal-day-inner';
      inner.appendChild(num);
      cell.appendChild(mosaic);
      cell.appendChild(inner);
    } else {
      cell.appendChild(num);
    }

    cell.addEventListener('click', () => {
      document.querySelectorAll('.cal-day').forEach(c => c.classList.remove('selected'));
      cell.classList.add('selected');
      loadCalendarDay(dayStr);
    });
    grid.appendChild(cell);
  }
}

async function loadCalendarDay(day) {
  const container = document.getElementById('cal-day-entries');
  container.innerHTML = '<div style="color:var(--ink-muted);font-size:.85rem;padding:.5rem 0;">Loading…</div>';
  try {
    const res  = await fetch(`/api/history?day=${day}`);
    const data = await res.json();
    container.innerHTML = '';
    if (!data.entries || !data.entries.length) {
      container.innerHTML = '<div style="color:var(--ink-muted);font-size:.85rem;padding:.5rem 0;">No entries on this day.</div>';
      return;
    }
    const heading = document.createElement('div');
    heading.style.cssText = 'font-size:.8rem;font-weight:600;color:var(--ink-muted);margin:.5rem 0;';
    heading.textContent = new Date(day + 'T12:00:00').toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' });
    container.appendChild(heading);
    data.entries.forEach(e => renderEntryCard(e, container));
  } catch (err) {
    container.innerHTML = `<div style="color:#f43f5e;font-size:.85rem;">${err.message}</div>`;
  }
}

// ── full card (calendar day view) ─────────────────────────────────────────────

function renderEntryCard(e, container) {
  const card = document.createElement('div');
  card.className = 'entry-card';

  const header = document.createElement('div');
  header.className = 'entry-header';

  const modeTag = document.createElement('span');
  modeTag.className = 'entry-mode mode-' + e.mode;
  modeTag.textContent = e.mode === 'chat' ? 'Chat' : 'Journal';
  header.appendChild(modeTag);

  if (e.source === 'voice') {
    const v = document.createElement('span');
    v.textContent = '🎙 Voice';
    v.style.cssText = 'font-size:.75rem;opacity:.8;';
    header.appendChild(v);
  } else if (e.source === 'image') {
    const v = document.createElement('span');
    v.textContent = '📷 Photo';
    v.style.cssText = 'font-size:.75rem;opacity:.8;';
    header.appendChild(v);
  }

  const time = document.createElement('span');
  time.className = 'entry-time';
  time.textContent = formatTime(e.created_at);
  header.appendChild(time);
  card.appendChild(header);

  const text = document.createElement('div');
  text.className = 'entry-text collapsed';

  if (e.source === 'image') {
    if (e.image_id) {
      const img = document.createElement('img');
      img.src = `/api/image/${e.image_id}/file`;
      img.style.cssText = 'width:100%;max-height:12rem;object-fit:cover;border-radius:var(--radius-xs);margin-bottom:.4rem;display:block;';
      text.appendChild(img);
    }
    if (e.content) { const n = document.createElement('div'); n.textContent = e.content; text.appendChild(n); }
    if (e.image_caption) {
      const cap = document.createElement('div');
      cap.style.cssText = 'margin-top:.4rem;font-size:.8rem;opacity:.7;font-style:italic;border-left:2px solid var(--ink-muted);padding-left:.5rem;';
      cap.textContent = e.image_caption;
      text.appendChild(cap);
    }
  } else if (e.source === 'voice') {
    if (e.content) { const t = document.createElement('div'); t.textContent = e.content; text.appendChild(t); }
    if (e.tone_summary) {
      const tone = document.createElement('div');
      tone.style.cssText = 'margin-top:.5rem;font-size:.8rem;opacity:.75;font-style:italic;border-left:2px solid var(--ink-muted);padding-left:.5rem;';
      tone.textContent = e.tone_summary;
      text.appendChild(tone);
    }
    if (!e.content && !e.tone_summary) text.innerHTML = '<em style="opacity:.6">🎙 Voice — transcript processing…</em>';
  } else {
    text.textContent = e.content;
  }

  card.appendChild(text);
  let expanded = false;
  card.addEventListener('click', () => { expanded = !expanded; text.classList.toggle('collapsed', !expanded); });

  if (e.category) {
    const tagWrap = document.createElement('div');
    tagWrap.className = 'entry-tags';
    const meta = CATEGORY_META[e.category];
    if (meta) {
      const chip = document.createElement('span');
      chip.className = 'tag-category';
      chip.textContent = meta.label;
      chip.style.background = meta.color;
      chip.style.color = meta.text;
      tagWrap.appendChild(chip);
    }
    (e.sub_tags || []).forEach(t => {
      const span = document.createElement('span');
      span.className = 'tag-sub';
      span.textContent = t;
      tagWrap.appendChild(span);
    });
    card.appendChild(tagWrap);
  }

  if (e.valence !== null && e.valence !== undefined) {
    const bar = document.createElement('div');
    bar.className = 'valence-bar';
    const fill = document.createElement('div');
    fill.className = 'valence-fill';
    fill.style.width = Math.round(((e.valence + 1) / 2) * 100) + '%';
    fill.style.background = valenceColor(e.valence);
    bar.appendChild(fill);
    card.appendChild(bar);
  }

  container.appendChild(card);
}
