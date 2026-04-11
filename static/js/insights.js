'use strict';

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
  const todayStr = today.toISOString().slice(0, 10);

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

    const dayStr = cur.toISOString().slice(0, 10);
    const data   = byDay[dayStr];

    const cell = document.createElement('div');
    cell.className = 'heatmap-cell' + (data ? ' heatmap-cell-data' : '');
    if (data) {
      cell.style.background = valenceToHsl(data.valence, data.intensity);
      cell.title = `${dayStr}\nMood: ${data.valence > 0 ? '+' : ''}${data.valence.toFixed(2)}  Intensity: ${data.intensity.toFixed(2)}\n${data.count} entr${data.count === 1 ? 'y' : 'ies'}`;
    }
    if (dayStr === todayStr) {
      cell.style.outline = '2px solid var(--negative)';
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
    <span class="legend-item"><span class="legend-swatch" style="background:hsl(240,60%,62%)"></span>Negative</span>
    <span class="legend-item"><span class="legend-swatch" style="background:hsl(35,50%,72%)"></span>Neutral</span>
    <span class="legend-item"><span class="legend-swatch" style="background:hsl(145,65%,55%)"></span>Positive</span>
  `;
  wrap.appendChild(legend);
}

// ── category breakdown ────────────────────────────────────────────────────────

function buildCategoryChart(categories) {
  const wrap = document.getElementById('categories-wrap');
  wrap.innerHTML = '';

  if (!categories || !categories.length) {
    wrap.innerHTML = '<p class="insights-empty">No category data yet.</p>';
    return;
  }

  const max = categories[0].count;
  const chart = document.createElement('div');
  chart.className = 'tag-chart';

  for (const { category, count } of categories) {
    const meta = CATEGORY_META[category] || { label: category, color: 'var(--accent)', text: '#fff' };
    const row = document.createElement('div');
    row.className = 'tag-row';

    const label = document.createElement('span');
    label.className = 'tag-label';
    label.textContent = meta.label;

    const barWrap = document.createElement('div');
    barWrap.className = 'tag-bar-wrap';

    const bar = document.createElement('div');
    bar.className = 'tag-bar';
    bar.style.width = Math.round((count / max) * 100) + '%';
    bar.style.background = meta.color;

    const countEl = document.createElement('span');
    countEl.className = 'tag-count';
    countEl.textContent = count;

    barWrap.appendChild(bar);
    row.appendChild(label);
    row.appendChild(barWrap);
    row.appendChild(countEl);
    chart.appendChild(row);
  }

  wrap.appendChild(chart);
}

// ── tag bar chart ─────────────────────────────────────────────────────────────

function buildTagChart(tags) {
  const wrap = document.getElementById('tags-wrap');
  wrap.innerHTML = '';

  if (!tags.length) {
    wrap.innerHTML = '<p class="insights-empty">No emotion tags yet.</p>';
    return;
  }

  const max = tags[0].count;
  const chart = document.createElement('div');
  chart.className = 'tag-chart';

  for (const { tag, count } of tags) {
    const row = document.createElement('div');
    row.className = 'tag-row';

    const label = document.createElement('span');
    label.className = 'tag-label';
    label.textContent = tag;

    const barWrap = document.createElement('div');
    barWrap.className = 'tag-bar-wrap';

    const bar = document.createElement('div');
    bar.className = 'tag-bar';
    bar.style.width = Math.round((count / max) * 100) + '%';

    const countEl = document.createElement('span');
    countEl.className = 'tag-count';
    countEl.textContent = count;

    barWrap.appendChild(bar);
    row.appendChild(label);
    row.appendChild(barWrap);
    row.appendChild(countEl);
    chart.appendChild(row);
  }

  wrap.appendChild(chart);
}

// ── load ──────────────────────────────────────────────────────────────────────

async function loadInsights() {
  try {
    const res  = await fetch('/api/stats');
    const data = await res.json();
    buildHeatmap(data.daily || []);
    buildCategoryChart(data.categories || []);
    buildTagChart(data.tags  || []);
  } catch (e) {
    document.getElementById('heatmap-wrap').innerHTML =
      '<p class="insights-empty">Could not load data.</p>';
  }
}

