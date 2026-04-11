'use strict';

let sessionId = null;

function newChatSession() {
  sessionId = null;
  document.getElementById('chat-log').innerHTML = '';
  document.getElementById('chat-status').textContent = '';
}

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
  return bubble;  // return bubble element for streaming updates
}

async function sendChat() {
  const input   = document.getElementById('chat-input');
  const sendBtn = document.getElementById('chat-send');
  const status  = document.getElementById('chat-status');
  const text = input.value.trim();
  if (!text) return;

  input.value = '';
  input.style.height = '';
  input.style.lineHeight = 'var(--btn-h)';
  input.style.padding = '0 0.875rem';
  input.style.overflowY = 'hidden';
  sendBtn.disabled = true;
  appendBubble('user', text);
  status.textContent = 'Thinking…';
  status.className = 'status-bar';

  // Create the assistant bubble immediately (empty) for streaming
  const log = document.getElementById('chat-log');
  const row = document.createElement('div');
  row.className = 'bubble-row bubble-row-assistant';
  const bubble = document.createElement('div');
  bubble.className = 'bubble bubble-assistant';
  bubble.textContent = '';
  row.appendChild(bubble);
  const metaEl = document.createElement('div');
  metaEl.className = 'bubble-meta';
  row.appendChild(metaEl);
  log.appendChild(row);

  try {
    const res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, session_id: sessionId }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || res.statusText);
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
      buf = lines.pop();  // keep incomplete last line

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let payload;
        try { payload = JSON.parse(line.slice(6)); } catch { continue; }

        if (payload.error) {
          status.textContent = payload.error;
          status.className = 'status-bar error';
          break;
        }

        if (payload.token !== undefined) {
          bubble.textContent += payload.token;
          log.scrollTop = log.scrollHeight;
        }

        if (payload.done) {
          sessionId = payload.session_id;
          if (payload.meta) {
            const m = payload.meta;
            const ttft = m.time_to_first_token_ms ? `${Math.round(m.time_to_first_token_ms)}ms ttft` : '';
            const tps  = m.decode_tps ? `· ${Math.round(m.decode_tps)} tps` : '';
            metaEl.textContent = [ttft, tps].filter(Boolean).join(' ');
          }
        }
      }
    }

    // Remove empty bubble if nothing arrived
    if (!bubble.textContent) {
      bubble.textContent = '(empty)';
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

  // Enter to send, Shift+Enter for newline
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
  });

  // Auto-expand height as user types
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    const max = parseFloat(getComputedStyle(input).maxHeight);
    input.style.height = Math.min(input.scrollHeight, max) + 'px';
    input.style.lineHeight = input.scrollHeight <= 40 ? 'var(--btn-h)' : '1.5';
    input.style.overflowY = input.scrollHeight > max ? 'auto' : 'hidden';
    input.style.padding = input.scrollHeight <= 40 ? '0 0.875rem' : '0.625rem 0.875rem';
  });
});
