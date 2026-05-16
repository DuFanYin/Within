'use strict';

// CATEGORY_META is defined in history.js (loaded before this file).

const TAG_BAR_HUES = [45, 145, 255, 20, 55, 300, 180, 10];

// ── colour helpers ────────────────────────────────────────────────────────────

// valence ∈ [-1, 1]  →  hsl colour
// negative: cool blue-purple, neutral: warm sand, positive: soft green
function valenceToHsl(valence, intensity) {
  // hue: -1 → 240 (blue), 0 → 35 (sand), 1 → 145 (green)
  const hue = valence < 0
    ? 240 + valence * (240 - 35)      // 240..35 as valence goes -1..0
    : 35  + valence * (145 - 35);     // 35..145 as valence goes 0..1
  const sat = 40 + intensity * 35;
  const lit = 75 - intensity * 25;
  return `hsl(${Math.round(hue)}, ${Math.round(sat)}%, ${Math.round(lit)}%)`;
}

// ── heatmap ───────────────────────────────────────────────────────────────────

function buildHeatmap(daily) {
  const wrap = document.getElementById('heatmap-wrap');
  wrap.innerHTML = '';

  if (!daily.length) {
    wrap.innerHTML = '<p class="insights-empty">No data yet — keep journaling!</p>';
    return;
  }

  // Build a map: day string → {valence, intensity, count}
  const byDay = {};
  for (const d of daily) byDay[d.day] = d;

  // Always show a fixed window: 3 months back to 2 weeks ahead
  const today = new Date();
  const todayStr = localDateStr(today);

  const startDate = new Date(today);
  startDate.setDate(startDate.getDate() - 100);

  const endDate = new Date(today);

  // Rewind startDate to the nearest Monday
  const dow = startDate.getDay();
  startDate.setDate(startDate.getDate() - (dow === 0 ? 6 : dow - 1));

  // Build week columns
  const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  const grid = document.createElement('div');
  grid.className = 'heatmap-grid';

  // Day-of-week label column
  const labelCol = document.createElement('div');
  labelCol.className = 'heatmap-dow-labels';
  for (const l of DAY_LABELS) {
    const s = document.createElement('span');
    s.textContent = l;
    labelCol.appendChild(s);
  }
  grid.appendChild(labelCol);

  const scrollArea = document.createElement('div');
  scrollArea.className = 'heatmap-scroll';

  let cur = new Date(startDate);
  let weekCol = null;
  let monthLabel = null;

  while (cur <= endDate) {
    const dowIdx = (cur.getDay() + 6) % 7; // 0=Mon

    if (dowIdx === 0) {
      // New week column
      weekCol = document.createElement('div');
      weekCol.className = 'heatmap-week';

      // Month label above first week of each month
      const isFirst = cur.getDate() <= 7;
      const label = document.createElement('div');
      label.className = 'heatmap-month-label';
      label.textContent = isFirst
        ? cur.toLocaleDateString('en', { month: 'short' })
        : '';
      weekCol.appendChild(label);

      scrollArea.appendChild(weekCol);
    }

    const dayStr = localDateStr(cur);
    const data   = byDay[dayStr];

    const cell = document.createElement('div');
    cell.className = 'heatmap-cell' + (data ? ' heatmap-cell-data' : '');
    if (data) {
      cell.style.background = valenceToHsl(data.valence, data.intensity);
      cell.title = `${dayStr}\nMood: ${data.valence > 0 ? '+' : ''}${data.valence.toFixed(2)}  Intensity: ${data.intensity.toFixed(2)}\n${data.count} entr${data.count === 1 ? 'y' : 'ies'}`;
    }
    if (dayStr === todayStr) {
      cell.style.outline = '2px solid var(--neg)';
      cell.style.outlineOffset = '1px';
    }
    weekCol.appendChild(cell);

    cur.setDate(cur.getDate() + 1);
  }

  grid.appendChild(scrollArea);
  wrap.appendChild(grid);

  // Scroll to the right (most recent)
  requestAnimationFrame(() => { scrollArea.scrollLeft = scrollArea.scrollWidth; });

  // Legend
  const legend = document.createElement('div');
  legend.className = 'heatmap-legend';
  legend.innerHTML = `
    <span class="legend-item"><span class="legend-dot" style="background:hsl(240,60%,62%)"></span>Low mood</span>
    <span class="legend-item"><span class="legend-dot" style="background:hsl(35,50%,72%)"></span>Neutral</span>
    <span class="legend-item"><span class="legend-dot" style="background:hsl(145,65%,55%)"></span>Positive</span>
  `;
  wrap.appendChild(legend);
}

// ── bar charts (categories + tags) ────────────────────────────────────────────

function buildBarChart(wrapId, rows, emptyMsg) {
  const wrap = document.getElementById(wrapId);
  wrap.innerHTML = '';
  if (!rows.length) {
    wrap.innerHTML = `<p class="insights-empty">${emptyMsg}</p>`;
    return;
  }

  const max = Math.max(...rows.map((r) => r.count));
  const chart = document.createElement('div');
  chart.className = 'bar-chart';

  for (const { label, count, barBackground } of rows) {
    const row = document.createElement('div');
    row.className = 'bar-row';

    const labelEl = document.createElement('span');
    labelEl.className = 'bar-label';
    labelEl.textContent = label;

    const barWrap = document.createElement('div');
    barWrap.className = 'bar-track';

    const bar = document.createElement('div');
    bar.className = 'bar-fill';
    bar.style.width = (max && count ? Math.max(4, Math.round((count / max) * 100)) : 0) + '%';
    bar.style.background = barBackground;

    const countEl = document.createElement('span');
    countEl.className = 'bar-count';
    countEl.textContent = count;

    barWrap.appendChild(bar);
    row.appendChild(labelEl);
    row.appendChild(barWrap);
    row.appendChild(countEl);
    chart.appendChild(row);
  }

  wrap.appendChild(chart);
}

function buildCategoryChart(categories) {
  const rows = (categories || []).map(({ category, count }) => {
    const meta = CATEGORY_META[category] || { label: category, color: '#8b7355' };
    return { label: meta.label, count, barBackground: meta.color };
  });
  buildBarChart('categories-wrap', rows, 'No category data yet.');
}

function buildTagChart(tags) {
  const rows = (tags || []).map(({ tag, count }, i) => ({
    label: tag,
    count,
    barBackground: `hsl(${TAG_BAR_HUES[i % TAG_BAR_HUES.length]}, 48%, 52%)`,
  }));
  buildBarChart('tags-wrap', rows, 'No emotion tags yet.');
}

// ── stats helpers ─────────────────────────────────────────────────────────────

function _computeStats(daily) {
  const today = localDateStr();
  const thisMonth = localMonthStr();

  // entries this month
  const monthEntries = daily
    .filter(d => d.day.startsWith(thisMonth))
    .reduce((s, d) => s + d.count, 0);

  // streak: consecutive days with entries up to today
  const daySet = new Set(daily.map(d => d.day));
  let streak = 0;
  const cur = new Date();
  while (true) {
    const key = localDateStr(cur);
    if (!daySet.has(key)) break;
    streak++;
    cur.setDate(cur.getDate() - 1);
  }

  // mood vs last month: compare avg valence
  const lastMonth = new Date();
  lastMonth.setMonth(lastMonth.getMonth() - 1);
  const lastMonthStr = localMonthStr(lastMonth);
  const thisRows = daily.filter(d => d.day.startsWith(thisMonth));
  const lastRows = daily.filter(d => d.day.startsWith(lastMonthStr));
  const thisAvg = thisRows.length ? thisRows.reduce((s, r) => s + r.valence, 0) / thisRows.length : null;
  const lastAvg = lastRows.length ? lastRows.reduce((s, r) => s + r.valence, 0) / lastRows.length : null;
  let moodTrend = '—';
  if (thisAvg !== null && lastAvg !== null && lastAvg !== 0) {
    const pct = Math.round(((thisAvg - lastAvg) / Math.abs(lastAvg)) * 100);
    moodTrend = (pct >= 0 ? '↑' : '↓') + Math.abs(pct) + '%';
  }

  return { monthEntries, streak, moodTrend, moodPositive: thisAvg !== null && lastAvg !== null && thisAvg >= lastAvg };
}

function buildSparkline(daily) {
  const wrap = document.getElementById('sparkline-wrap');
  if (!wrap) return;
  wrap.innerHTML = '';

  const last14 = [...daily].sort((a, b) => a.day < b.day ? -1 : 1).slice(-14);
  if (last14.length < 2) return;

  const W = 330, H = 60;
  const points = last14.map((d, i) => {
    const norm = (d.valence + 1) / 2; // -1..1 → 0..1
    const x = (i / (last14.length - 1)) * W;
    const y = H - norm * H * 0.8 - 4;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.style.cssText = 'width:100%;height:60px;';

  svg.innerHTML = `
    <defs>
      <linearGradient id="sparkGrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="oklch(0.48 0.07 45)" stop-opacity="0.25"/>
        <stop offset="100%" stop-color="oklch(0.48 0.07 45)" stop-opacity="0"/>
      </linearGradient>
    </defs>
    <polyline points="${points}" fill="none" stroke="oklch(0.48 0.07 45)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    <polygon points="0,${H} ${points} ${W},${H}" fill="url(#sparkGrad)"/>
  `;
  wrap.appendChild(svg);
}

// ── load ──────────────────────────────────────────────────────────────────────

async function loadInsights() {
  try {
    const res  = await fetch('/api/stats');
    const data = await res.json();
    const daily = data.daily || [];

    const stats = _computeStats(daily);
    const entryEl = document.getElementById('stat-entries');
    const streakEl = document.getElementById('stat-streak');
    const moodEl  = document.getElementById('stat-mood');
    if (entryEl) entryEl.textContent = stats.monthEntries || '0';
    if (streakEl) streakEl.textContent = stats.streak || '0';
    if (moodEl) {
      moodEl.textContent = stats.moodTrend;
      moodEl.style.color = stats.moodPositive ? 'var(--positive)' : 'var(--neg)';
    }

    buildSparkline(daily);
    buildHeatmap(daily);
    buildCategoryChart(data.categories || []);
    buildTagChart(data.tags || []);
  } catch (e) {
    console.error('loadInsights failed:', e);
    const msg = '<p class="insights-empty">Could not load data.</p>';
    for (const id of ['heatmap-wrap', 'categories-wrap', 'tags-wrap', 'sparkline-wrap']) {
      const el = document.getElementById(id);
      if (el) el.innerHTML = msg;
    }
  }

  // Narrative — load async, show when ready
  const narrativeEl = document.getElementById('insights-narrative');
  const narrativeSection = document.getElementById('narrative-section');
  if (narrativeEl && narrativeSection) {
    narrativeEl.className = 'narrative-card loading';
    narrativeEl.textContent = 'Reflecting on your entries…';
    narrativeSection.style.display = '';
    try {
      const r = await fetch('/api/insights/narrative');
      const d = await r.json();
      if (d.narrative) {
        narrativeEl.className = 'narrative-card';
        narrativeEl.textContent = d.narrative;
      } else {
        narrativeSection.style.display = 'none';
      }
    } catch (_) {
      narrativeSection.style.display = 'none';
    }
  }
}

