'use strict';

let _journalImageFile = null;

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
  document.getElementById('journal-img-input').value = '';
  document.getElementById('journal-img-thumb').src = '';
  document.getElementById('journal-img-preview').classList.remove('visible');
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
