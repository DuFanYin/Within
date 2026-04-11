'use strict';

function appendReflectBubble(role, text) {
  const log = document.getElementById('reflect-log');

  const row = document.createElement('div');
  row.className = 'bubble-row bubble-row-' + (role === 'user' ? 'user' : 'assistant');

  const bubble = document.createElement('div');
  bubble.className = 'bubble bubble-' + (role === 'user' ? 'user' : 'assistant');
  bubble.textContent = text;
  row.appendChild(bubble);

  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
  return bubble;
}

async function sendReflect() {
  const input   = document.getElementById('reflect-input');
  const sendBtn = document.getElementById('reflect-send');
  const status  = document.getElementById('reflect-status');
  const question = input.value.trim();
  if (!question) return;

  input.value = '';
  input.style.height = '';
  input.style.lineHeight = 'var(--btn-h)';
  input.style.padding = '0 0.875rem';
  input.style.overflowY = 'hidden';
  sendBtn.disabled = true;
  appendReflectBubble('user', question);
  status.textContent = 'Looking through your entries…';
  status.className = 'status-bar';

  // Create assistant bubble immediately for streaming
  const log = document.getElementById('reflect-log');
  const row = document.createElement('div');
  row.className = 'bubble-row bubble-row-assistant';
  const bubble = document.createElement('div');
  bubble.className = 'bubble bubble-assistant';
  bubble.textContent = '';
  row.appendChild(bubble);
  log.appendChild(row);

  try {
    const res = await fetch('/api/reflect/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
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
      buf = lines.pop();

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
      }
    }

    if (!bubble.textContent) bubble.textContent = '(empty)';

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
  const input = document.getElementById('reflect-input');

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendReflect(); }
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
