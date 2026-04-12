'use strict';

let sessionId = null;
let _chatImageFile = null;
let _chatAudioBlob = null;   // set by recording.js when recording stops

// Expose sessionId to recording.js via window._chatSessionId
Object.defineProperty(window, '_chatSessionId', {
  get: () => sessionId,
  set: v => { sessionId = v; },
  configurable: true,
});

function newChatSession() {
  sessionId = null;
  _chatAudioBlob = null;
  clearChatImage();
  clearChatAudio();
  document.getElementById('chat-log').innerHTML = '';
  document.getElementById('chat-status').textContent = '';
}

// ── image attachment ──────────────────────────────────────────────────────────

function onChatImagePicked(input) {
  const file = input.files[0];
  if (!file) return;
  _chatImageFile = file;
  const url = URL.createObjectURL(file);
  document.getElementById('chat-img-thumb').src = url;
  document.getElementById('chat-img-preview').classList.add('visible');
}

function clearChatImage() {
  _chatImageFile = null;
  const inp = document.getElementById('chat-img-input');
  if (inp) inp.value = '';
  const thumb = document.getElementById('chat-img-thumb');
  if (thumb) thumb.src = '';
  const preview = document.getElementById('chat-img-preview');
  if (preview) preview.classList.remove('visible');
}

// ── audio attachment (called by recording.js) ─────────────────────────────────

function setChatAudioBlob(blob) {
  _chatAudioBlob = blob;
  // Show a pending indicator in the input area
  const status = document.getElementById('chat-status');
  status.textContent = '🎙 Voice ready — tap Send';
  status.className = 'status-bar';
}

function clearChatAudio() {
  _chatAudioBlob = null;
}

// ── bubble helpers ────────────────────────────────────────────────────────────

function appendBubble(role, text, meta) {
  const log = document.getElementById('chat-log');
  const row = document.createElement('div');
  row.className = 'bubble-row bubble-row-' + (role === 'user' ? 'user' : 'assistant');
  const bubble = document.createElement('div');
  bubble.className = 'bubble bubble-' + (role === 'user' ? 'user' : 'assistant');
  bubble.textContent = text;
  row.appendChild(bubble);
  if (meta && role === 'assistant') {
    const m = document.createElement('div');
    m.className = 'bubble-meta';
    const ttft = meta.time_to_first_token_ms ? `${Math.round(meta.time_to_first_token_ms)}ms ttft` : '';
    const tps  = meta.decode_tps ? `· ${Math.round(meta.decode_tps)} tps` : '';
    m.textContent = [ttft, tps].filter(Boolean).join(' ');
    row.appendChild(m);
  }
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
  return bubble;
}

function appendImageBubble(src, caption) {
  const log = document.getElementById('chat-log');
  const row = document.createElement('div');
  row.className = 'bubble-row bubble-row-user';
  const bubble = document.createElement('div');
  bubble.className = 'bubble bubble-user bubble-image';
  const img = document.createElement('img');
  img.src = src;
  img.style.cssText = 'max-width:100%; max-height:12rem; border-radius:var(--radius-xs); display:block; object-fit:cover;';
  bubble.appendChild(img);
  if (caption) {
    const cap = document.createElement('div');
    cap.style.cssText = 'font-size:.8rem; margin-top:.3rem; opacity:.8;';
    cap.textContent = caption;
    bubble.appendChild(cap);
  }
  row.appendChild(bubble);
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
}

function appendVoiceBubble() {
  const log = document.getElementById('chat-log');
  const row = document.createElement('div');
  row.className = 'bubble-row bubble-row-user';
  const bubble = document.createElement('div');
  bubble.className = 'bubble bubble-user';
  bubble.innerHTML = '<span style="opacity:.7">🎙 Voice message</span>';
  row.appendChild(bubble);
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
}

// ── streaming helper ──────────────────────────────────────────────────────────

async function _streamResponse(fetchPromise, bubble, metaEl, status) {
  const res = await fetchPromise;
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || res.statusText);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  status.textContent = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop();
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      let payload;
      try { payload = JSON.parse(line.slice(6)); } catch { continue; }
      if (payload.error) throw new Error(payload.error);
      if (payload.token !== undefined) {
        bubble.textContent += payload.token;
        bubble.closest('.bubble-row').nextSibling?.scrollIntoView?.({ block: 'nearest' });
        document.getElementById('chat-log').scrollTop = document.getElementById('chat-log').scrollHeight;
      }
      if (payload.done) {
        sessionId = payload.session_id;
        if (payload.meta && metaEl) {
          const m = payload.meta;
          const ttft = m.time_to_first_token_ms ? `${Math.round(m.time_to_first_token_ms)}ms ttft` : '';
          const tps  = m.decode_tps ? `· ${Math.round(m.decode_tps)} tps` : '';
          metaEl.textContent = [ttft, tps].filter(Boolean).join(' ');
        }
      }
    }
  }
  if (!bubble.textContent) bubble.textContent = '(empty)';
}

// ── send ──────────────────────────────────────────────────────────────────────

async function sendChat() {
  const input   = document.getElementById('chat-input');
  const sendBtn = document.getElementById('chat-send');
  const status  = document.getElementById('chat-status');
  const text    = input.value.trim();
  const hasImage = !!_chatImageFile;
  const hasAudio = !!_chatAudioBlob;

  if (!text && !hasImage && !hasAudio) return;

  // Snapshot and clear pending attachments immediately
  const imageFile  = _chatImageFile;
  const audioBlob  = _chatAudioBlob;
  const thumbSrc   = document.getElementById('chat-img-thumb')?.src || '';

  input.value = '';
  input.style.height = '';
  input.style.lineHeight = 'var(--btn-h)';
  input.style.padding = '0 0.875rem';
  input.style.overflowY = 'hidden';
  clearChatImage();
  clearChatAudio();
  sendBtn.disabled = true;
  status.textContent = 'Thinking…';
  status.className = 'status-bar';

  // Create assistant bubble for streaming
  const log = document.getElementById('chat-log');
  const row = document.createElement('div');
  row.className = 'bubble-row bubble-row-assistant';
  const bubble = document.createElement('div');
  bubble.className = 'bubble bubble-assistant';
  row.appendChild(bubble);
  const metaEl = document.createElement('div');
  metaEl.className = 'bubble-meta';
  row.appendChild(metaEl);

  try {
    if (hasAudio) {
      // ── Voice path: send audio directly to Gemma 4 ───────────────────────
      appendVoiceBubble();
      log.appendChild(row);

      const fd = new FormData();
      fd.append('file', audioBlob, 'audio.webm');
      if (sessionId) fd.append('session_id', sessionId);

      await _streamResponse(
        fetch('/api/voice/stream', { method: 'POST', body: fd }),
        bubble, metaEl, status,
      );

    } else if (hasImage) {
      // ── Image + optional text path ────────────────────────────────────────
      // 1. Upload image to get image_id (stored for RAG), then chat with text
      appendImageBubble(thumbSrc, text || null);
      if (text) appendBubble('user', text);
      log.appendChild(row);

      // Upload image (fire-and-forget for storage; don't block chat on caption)
      const imgFd = new FormData();
      imgFd.append('file', imageFile, imageFile.name);
      if (text) imgFd.append('note', text);
      imgFd.append('mode', 'chat');
      if (sessionId) imgFd.append('session_id', sessionId);
      fetch('/api/image', { method: 'POST', body: imgFd }).catch(() => {});

      // Chat with text (if any), or a generic prompt inviting the model to respond
      const chatText = text || '(User shared a photo)';
      await _streamResponse(
        fetch('/api/chat/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: chatText, session_id: sessionId }),
        }),
        bubble, metaEl, status,
      );

    } else {
      // ── Text-only path ────────────────────────────────────────────────────
      appendBubble('user', text);
      log.appendChild(row);

      await _streamResponse(
        fetch('/api/chat/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text, session_id: sessionId }),
        }),
        bubble, metaEl, status,
      );
    }

  } catch (err) {
    status.textContent = err.message;
    status.className = 'status-bar error';
    if (!bubble.textContent) row.remove();
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('chat-input');
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
  });
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    const max = parseFloat(getComputedStyle(input).maxHeight);
    input.style.height = Math.min(input.scrollHeight, max) + 'px';
    input.style.lineHeight = input.scrollHeight <= 40 ? 'var(--btn-h)' : '1.5';
    input.style.overflowY = input.scrollHeight > max ? 'auto' : 'hidden';
    input.style.padding = input.scrollHeight <= 40 ? '0 0.875rem' : '0.625rem 0.875rem';
  });
});
