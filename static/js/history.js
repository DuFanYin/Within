'use strict';

let historyView = 'timeline';

function switchView(v) {
  historyView = v;
  document.getElementById('btn-timeline').classList.toggle('active', v === 'timeline');
  document.getElementById('btn-calendar').classList.toggle('active', v === 'calendar');
  document.getElementById('view-timeline').style.display = v === 'timeline' ? 'block' : 'none';
  document.getElementById('view-calendar').style.display = v === 'calendar' ? 'flex' : 'none';
  loadHistory();
}

async function loadHistory() {
  if (historyView === 'timeline') await loadTimeline();
  else await loadCalendar();
}

// ── helpers ──────────────────────────────────────────────────────────────────

const CATEGORY_META = {
  positive: { label: 'Positive',   color: '#FFD93D', text: '#5a4a00' },
  stress:   { label: 'Stress',   color: '#FF8C42', text: '#fff' },
  anxiety:  { label: 'Anxiety',   color: '#7B61FF', text: '#fff' },
  low_mood: { label: 'Low mood',   color: '#4A90E2', text: '#fff' },
  anger:    { label: 'Anger',   color: '#FF4C4C', text: '#fff' },
  social:   { label: 'Social',   color: '#4CAF7D', text: '#fff' },
};

function valenceColor(v) {
  if (v === null || v === undefined) return 'var(--ink-muted)';
  if (v > 0.15) return 'var(--positive)';
  if (v < -0.15) return 'var(--negative)';
  return 'var(--ink-muted)';
}

function formatTime(iso) {
  if (!iso) return '';
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function renderEntryCard(e, container) {
  const card = document.createElement('div');
  card.className = 'entry-card';

  // header row
  const header = document.createElement('div');
  header.className = 'entry-header';

  const modeTag = document.createElement('span');
  modeTag.className = 'entry-mode mode-' + e.mode;
  modeTag.textContent = e.mode === 'chat' ? 'Chat' : 'Journal';
  header.appendChild(modeTag);

  if (e.source === 'voice') {
    const v = document.createElement('span');
    v.className = 'voice-badge';
    v.textContent = '🎙 Voice';
    v.style.fontSize = '.75rem';
    v.style.opacity = '.8';
    header.appendChild(v);
  } else if (e.source === 'image') {
    const v = document.createElement('span');
    v.textContent = '📷 Photo';
    v.style.fontSize = '.75rem';
    v.style.opacity = '.8';
    header.appendChild(v);
  }

  const time = document.createElement('span');
  time.className = 'entry-time';
  time.textContent = formatTime(e.created_at);
  header.appendChild(time);
  card.appendChild(header);

  // content area
  const text = document.createElement('div');
  text.className = 'entry-text collapsed';

  if (e.source === 'image') {
    // Thumbnail
    if (e.image_id) {
      const img = document.createElement('img');
      img.src = `/api/image/${e.image_id}/file`;
      img.style.cssText = 'width:100%;max-height:12rem;object-fit:cover;border-radius:var(--radius-xs);margin-bottom:.4rem;display:block;';
      img.alt = 'Attached photo';
      text.appendChild(img);
    }
    // Note text (if user wrote one)
    if (e.content) {
      const note = document.createElement('div');
      note.textContent = e.content;
      text.appendChild(note);
    }
    // AI caption
    if (e.image_caption) {
      const cap = document.createElement('div');
      cap.style.cssText = 'margin-top:.4rem;font-size:.8rem;opacity:.7;font-style:italic;border-left:2px solid var(--ink-muted);padding-left:.5rem;';
      cap.textContent = e.image_caption;
      text.appendChild(cap);
    }
  } else if (e.source === 'voice') {
    // transcript filled by background ASR job; show pending if not ready yet
    if (e.tone_summary || e.content) {
      if (e.content) {
        const t = document.createElement('div');
        t.textContent = e.content;
        text.appendChild(t);
      }
      if (e.tone_summary) {
        const tone = document.createElement('div');
        tone.style.cssText = 'margin-top:.5rem;font-size:.8rem;opacity:.75;font-style:italic;border-left:2px solid var(--ink-muted);padding-left:.5rem;';
        tone.textContent = e.tone_summary;
        text.appendChild(tone);
      }
    } else {
      text.innerHTML = '<em style="opacity:.6">🎙 Voice — transcript processing…</em>';
    }
  } else {
    text.textContent = e.content;
  }

  card.appendChild(text);

  let expanded = false;
  card.addEventListener('click', () => {
    expanded = !expanded;
    text.classList.toggle('collapsed', !expanded);
  });

  // emotion tags
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

  // valence bar
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

// ── timeline ─────────────────────────────────────────────────────────────────

async function loadTimeline(day) {
  const container = document.getElementById('timeline');
  container.innerHTML = '<div style="color:var(--ink-muted);font-size:.85rem;padding:.5rem 0;">Loading…</div>';
  try {
    const url = day ? `/api/history?day=${day}` : '/api/history';
    const res = await fetch(url);
    const data = await res.json();
    container.innerHTML = '';
    if (!data.entries || !data.entries.length) {
      container.innerHTML = '<div style="color:var(--ink-muted);font-size:.875rem;padding:2rem 0;text-align:center;">No entries yet.<br>Start by talking or journaling.</div>';
      return;
    }
    data.entries.forEach(e => renderEntryCard(e, container));
  } catch (err) {
    container.innerHTML = '<div style="color:#f43f5e;font-size:.85rem;">' + err.message + '</div>';
  }
}

// ── calendar ─────────────────────────────────────────────────────────────────

async function loadCalendar() {
  const grid  = document.getElementById('calendar-grid');
  const label = document.getElementById('cal-month-label');
  grid.innerHTML = '';

  const now = new Date();
  label.textContent = now.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });

  let counts = {};
  try {
    const res  = await fetch('/api/history?view=calendar');
    const data = await res.json();
    (data.entries || []).forEach(r => { counts[r.day] = r.count; });
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
    if (counts[dayStr]) cell.classList.add('has-entries');
    if (d === today) cell.style.outline = '2px solid var(--accent)';

    const num = document.createElement('span');
    num.textContent = d;
    cell.appendChild(num);

    if (counts[dayStr]) {
      const dot = document.createElement('div');
      dot.className = 'dot';
      cell.appendChild(dot);
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
    container.innerHTML = '<div style="color:#f43f5e;font-size:.85rem;">' + err.message + '</div>';
  }
}
