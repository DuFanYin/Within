'use strict';

let _journalImageFile = null;

document.addEventListener('DOMContentLoaded', () => {
  const ta = document.getElementById('journal-textarea');
  const wc = document.getElementById('journal-word-count');
  if (!ta || !wc) return;
  ta.addEventListener('input', () => {
    const words = ta.value.trim() ? ta.value.trim().split(/\s+/).length : 0;
    wc.textContent = words > 0 ? `${words} word${words !== 1 ? 's' : ''}` : '';
  });
});

function onJournalImagePicked(input) {
  const file = input.files[0];
  if (!file) return;
  _journalImageFile = file;
  const url = URL.createObjectURL(file);
  document.getElementById('journal-img-thumb').src = url;
  document.getElementById('journal-img-preview').classList.add('visible');
}

function clearJournalImage() {
  _journalImageFile = null;
  const inp = document.getElementById('journal-img-input');
  if (inp) inp.value = '';
  const thumb = document.getElementById('journal-img-thumb');
  if (thumb) thumb.src = '';
  const preview = document.getElementById('journal-img-preview');
  if (preview) preview.classList.remove('visible');
}

async function saveJournal() {
  const ta     = document.getElementById('journal-textarea');
  const btn    = document.getElementById('journal-save');
  const status = document.getElementById('journal-status');
  const text = ta.value.trim();

  if (!text && !_journalImageFile) return;

  btn.disabled = true;
  status.textContent = 'Saving…';
  status.className = 'status-bar';

  try {
    // If there is an image, upload it; also save text as a separate entry if present
    if (_journalImageFile) {
      const fd = new FormData();
      fd.append('file', _journalImageFile, _journalImageFile.name);
      fd.append('mode', 'journal');

      const res = await fetch('/api/image', { method: 'POST', body: fd });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || res.statusText);

      clearJournalImage();

      // Save text as its own journal entry so it gets emotion tagging
      if (text) {
        const r2 = await fetch('/api/journal', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text }),
        });
        const d2 = await r2.json().catch(() => ({}));
        if (!r2.ok) throw new Error(d2.detail || r2.statusText);
      }

      ta.value = '';
      status.textContent = 'Saved ✓';
      return;
    }

    // Text-only entry
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
