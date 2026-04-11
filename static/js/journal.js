'use strict';

async function saveJournal() {
  const ta     = document.getElementById('journal-textarea');
  const btn    = document.getElementById('journal-save');
  const status = document.getElementById('journal-status');
  const text = ta.value.trim();
  if (!text) return;

  btn.disabled = true;
  status.textContent = 'Saving…';
  status.className = 'status-bar';

  try {
    const res = await fetch('/api/journal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || res.statusText);
    ta.value = '';
    status.textContent = 'Saved ✓';
  } catch (err) {
    status.textContent = err.message;
    status.className = 'status-bar error';
  } finally {
    btn.disabled = false;
  }
}
