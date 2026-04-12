'use strict';

// ── state ─────────────────────────────────────────────────────────────────────

let _activeTopic  = null;   // { label, question, rag_query, type }
let _chatHistory  = [];     // [{ role, content }]
let _topicPicked  = false;

// ── entry point ───────────────────────────────────────────────────────────────

function loadReflectInsights() {
  const log = document.getElementById('reflect-chat-log');
  if (log && log.children.length) return;
  _openReflect();
}

async function _openReflect() {
  const log   = document.getElementById('reflect-chat-log');
  const input = document.getElementById('reflect-input-wrap');
  log.innerHTML = '';
  input.classList.add('hidden');

  const stepEl = document.createElement('div');
  stepEl.className = 'reflect-open-step';
  stepEl.textContent = 'Starting…';
  log.appendChild(stepEl);

  try {
    const res = await fetch('/api/reflect/open');
    if (!res.ok) throw new Error(res.statusText);

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buf  = '';
    let data = null;

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

        if (payload.step)   stepEl.textContent = payload.step;
        if (payload.result) data = payload.result;
        if (payload.error)  { stepEl.textContent = '⚠ ' + payload.error; return; }
      }
    }

    stepEl.remove();
    if (!data) return;

    _appendBubble('assistant', data.greeting);
    _appendTopicPicker(data.topics);

  } catch (err) {
    stepEl.textContent = '⚠ ' + err.message;
  }
}

// ── topic picker ──────────────────────────────────────────────────────────────

function _appendTopicPicker(topics) {
  const log  = document.getElementById('reflect-chat-log');
  const wrap = document.createElement('div');
  wrap.id        = 'reflect-topic-picker';
  wrap.className = 'reflect-topic-picker';

  topics.forEach((topic, i) => {
    const label = document.createElement('label');
    label.className = 'reflect-topic-option';

    const radio = document.createElement('input');
    radio.type  = 'radio';
    radio.name  = 'reflect-topic';
    radio.value = String(i);
    radio.addEventListener('change', () => _pickTopic(topic, wrap));

    const text = document.createElement('span');
    // Show the conversational question as the option text
    text.textContent = topic.question || topic.label;

    label.appendChild(radio);
    label.appendChild(text);
    wrap.appendChild(label);
  });

  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;
}

function _pickTopic(topic, pickerEl) {
  if (_topicPicked) return;
  _topicPicked = true;

  // Lock picker
  pickerEl.querySelectorAll('input[type=radio]').forEach(r => r.disabled = true);
  pickerEl.classList.add('reflect-topic-picker--locked');

  _activeTopic = topic;
  _chatHistory = [];

  if (topic.type === 'free') {
    const opener = "What's on your mind? It can be a feeling, something that happened, or whatever you want to get out.";
    _appendBubble('assistant', opener);
    _chatHistory.push({ role: 'assistant', content: opener });
    // Show input immediately for free-form
    document.getElementById('reflect-input-wrap').classList.remove('hidden');
    document.getElementById('reflect-chat-input').focus();
  } else {
    // Agent opens first — input shown only after agent replies
    _agentOpen(topic);
  }
}

// ── agent opens the chosen topic ──────────────────────────────────────────────

async function _agentOpen(topic) {
  const log    = document.getElementById('reflect-chat-log');
  const status = document.getElementById('reflect-chat-status');
  const input  = document.getElementById('reflect-input-wrap');

  // The topic question becomes the user's implicit opening message
  const seed = topic.question || topic.label;
  _chatHistory.push({ role: 'user', content: seed });

  const bubble = _appendBubble('assistant', '');
  bubble.classList.add('bubble-streaming');

  try {
    const res = await fetch('/api/reflect/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        topic_label:    topic.label,
        topic_question: topic.question || '',
        rag_query:      topic.rag_query || topic.label,
        history:        [],
        user_message:   seed,
      }),
    });
    if (!res.ok) throw new Error(res.statusText);

    const { reply } = await _streamInto(res, bubble, log, status);
    _chatHistory.push({ role: 'assistant', content: reply });

  } catch (err) {
    status.textContent = err.message;
    bubble.remove();
  } finally {
    bubble.classList.remove('bubble-streaming');
    // Show input only after agent has finished its first reply
    input.classList.remove('hidden');
    document.getElementById('reflect-chat-input').focus();
  }
}

// ── user sends a message ──────────────────────────────────────────────────────

async function sendReflectChat() {
  if (!_activeTopic) return;

  const input  = document.getElementById('reflect-chat-input');
  const send   = document.getElementById('reflect-chat-send');
  const status = document.getElementById('reflect-chat-status');
  const log    = document.getElementById('reflect-chat-log');

  const text = input.value.trim();
  if (!text) return;

  input.value = '';
  input.style.height = '';
  send.disabled = true;
  status.textContent = '';

  _appendBubble('user', text);
  _chatHistory.push({ role: 'user', content: text });

  const bubble = _appendBubble('assistant', '');
  bubble.classList.add('bubble-streaming');

  try {
    const res = await fetch('/api/reflect/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        topic_label:    _activeTopic.label,
        topic_question: _activeTopic.question || '',
        rag_query:      _activeTopic.rag_query || _activeTopic.label,
        history:        _chatHistory.slice(0, -1),
        user_message:   text,
      }),
    });
    if (!res.ok) throw new Error(res.statusText);

    const { reply } = await _streamInto(res, bubble, log, status);
    _chatHistory.push({ role: 'assistant', content: reply });

  } catch (err) {
    status.textContent = err.message;
    bubble.remove();
  } finally {
    bubble.classList.remove('bubble-streaming');
    send.disabled = false;
    input.focus();
  }
}

// ── shared SSE reader ─────────────────────────────────────────────────────────

async function _streamInto(res, bubble, log, status) {
  const reader  = res.body.getReader();
  const decoder = new TextDecoder();
  let buf   = '';
  let reply = '';

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
      }
      if (payload.tool_call) {
        _appendToolStep(log, payload.tool_call);
      }
      if (payload.token) {
        reply += payload.token;
        bubble.textContent = reply;
        log.scrollTop = log.scrollHeight;
      }
      if (payload.done) {
        reply = payload.reply || reply;
      }
    }
  }
  return { reply };
}

// ── DOM helpers ───────────────────────────────────────────────────────────────

function _appendBubble(role, text) {
  const log = document.getElementById('reflect-chat-log');
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

function _appendToolStep(log, label) {
  const row = document.createElement('div');
  row.className = 'bubble-row bubble-row-assistant';
  const el = document.createElement('div');
  el.className = 'reflect-tool-step';
  el.textContent = label;
  row.appendChild(el);
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
}

// ── keyboard ──────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('reflect-chat-input');
  if (!input) return;
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendReflectChat(); }
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
