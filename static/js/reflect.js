'use strict';

// ── state ─────────────────────────────────────────────────────────────────────

let _activeTopic   = null;   // { label, question, rag_query, type }
let _chatHistory   = [];     // [{ role, content }] — used for reflect path
let _topicPicked   = false;
let _justChatSid   = null;   // session_id for just_chat continuity

let _reflectImageFile = null;
let _reflectAudioBlob = null;  // set by recording.js

// Expose to recording.js
Object.defineProperty(window, '_reflectSessionId', {
  get: () => _justChatSid,
  configurable: true,
});

// ── sessionStorage cache ──────────────────────────────────────────────────────

const _CACHE_KEY = 'reflect_cache_v1';

function _saveCache() {
  // Don't cache mid-stream (empty streaming bubble would restore broken)
  const log = document.getElementById('reflect-chat-log');
  if (!log) return;
  // Strip streaming bubbles before saving
  const clone = log.cloneNode(true);
  clone.querySelectorAll('.bubble-streaming').forEach(el => el.closest('.bubble-row')?.remove());
  // Don't cache if only the step indicator is present (still loading)
  if (clone.querySelector('.reflect-open-step')) return;
  try {
    sessionStorage.setItem(_CACHE_KEY, JSON.stringify({
      html:        clone.innerHTML,
      activeTopic: _activeTopic,
      topicPicked: _topicPicked,
      justChatSid: _justChatSid,
      chatHistory: _chatHistory,
    }));
  } catch {}
}

function _loadCache() {
  try {
    const raw = sessionStorage.getItem(_CACHE_KEY);
    if (!raw) return false;
    const c = JSON.parse(raw);
    if (!c.html) return false;

    const log   = document.getElementById('reflect-chat-log');
    const input = document.getElementById('reflect-input-wrap');
    log.innerHTML  = c.html;
    _activeTopic   = c.activeTopic  || null;
    _topicPicked   = c.topicPicked  || false;
    _justChatSid   = c.justChatSid  || null;
    _chatHistory   = c.chatHistory  || [];

    // Re-wire topic picker radio buttons (innerHTML loses event listeners)
    const picker = log.querySelector('.reflect-topic-picker');
    if (picker && !picker.classList.contains('reflect-topic-picker--locked')) {
      // Picker still active — easiest to just lock it since we can't recover topic refs
      picker.querySelectorAll('input[type=radio]').forEach(r => r.disabled = true);
      picker.classList.add('reflect-topic-picker--locked');
    }

    input.classList.remove('hidden');
    _updateAttachButtons();
    log.scrollTop = log.scrollHeight;
    return true;
  } catch {
    return false;
  }
}

function _clearCache() {
  sessionStorage.removeItem(_CACHE_KEY);
}

// ── entry point ───────────────────────────────────────────────────────────────

function loadReflectInsights() {
  const log = document.getElementById('reflect-chat-log');
  if (log && log.children.length) return;   // in-memory guard (tab switch)
  if (_loadCache()) return;                 // sessionStorage restore (page refresh)
  _openReflect();
}

function restartReflect() {
  _clearCache();
  _activeTopic  = null;
  _chatHistory  = [];
  _topicPicked  = false;
  _justChatSid  = null;
  clearReflectImage();
  clearReflectAudio();
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
    _saveCache();

  } catch (err) {
    stepEl.textContent = '⚠ ' + err.message;
  } finally {
    // Input always available — typing before picking a topic = just_chat
    const input = document.getElementById('reflect-input-wrap');
    input.classList.remove('hidden');
    _updateAttachButtons();
    document.getElementById('reflect-chat-input').focus();
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

  pickerEl.querySelectorAll('input[type=radio]').forEach(r => r.disabled = true);
  pickerEl.classList.add('reflect-topic-picker--locked');

  _activeTopic = topic;
  _chatHistory = [];

  if (topic.type === 'just_chat') {
    // Plain chat mode — show input immediately, no agent preamble
    const opener = "What's on your mind?";
    _appendBubble('assistant', opener);
    document.getElementById('reflect-input-wrap').classList.remove('hidden');
    document.getElementById('reflect-chat-input').focus();
    // Show voice/image buttons (already in HTML, just ensure visible)
    _updateAttachButtons();
  } else {
    // Reflect mode — agent opens first
    _agentOpen(topic);
  }
}

// ── agent opens the chosen topic (reflect mode) ───────────────────────────────

async function _agentOpen(topic) {
  const log    = document.getElementById('reflect-chat-log');
  const status = document.getElementById('reflect-chat-status');
  const input  = document.getElementById('reflect-input-wrap');

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
        topic_type:     topic.type,
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
    input.classList.remove('hidden');
    _updateAttachButtons();
    document.getElementById('reflect-chat-input').focus();
    _saveCache();
  }
}

// ── image attachment ──────────────────────────────────────────────────────────

function onReflectImagePicked(input) {
  const file = input.files[0];
  if (!file) return;
  _reflectImageFile = file;
  const url = URL.createObjectURL(file);
  document.getElementById('reflect-img-thumb').src = url;
  document.getElementById('reflect-img-preview').classList.add('visible');
}

function clearReflectImage() {
  _reflectImageFile = null;
  const inp = document.getElementById('reflect-img-input');
  if (inp) inp.value = '';
  const thumb = document.getElementById('reflect-img-thumb');
  if (thumb) thumb.src = '';
  const preview = document.getElementById('reflect-img-preview');
  if (preview) preview.classList.remove('visible');
}

// called by recording.js
function setReflectAudioBlob(blob) {
  _reflectAudioBlob = blob;
  const status = document.getElementById('reflect-chat-status');
  status.textContent = '🎙 Voice ready — tap Send';
  status.className = 'status-bar';
}

function clearReflectAudio() {
  _reflectAudioBlob = null;
}

// Show/hide voice+image buttons — visible whenever input is open,
// but only functional in just_chat mode (reflect topics hide them after pick)
function _updateAttachButtons() {
  const hideAttach = _activeTopic && _activeTopic.type !== 'just_chat';
  const recBtn = document.getElementById('reflect-rec-btn');
  const imgBtn = document.getElementById('reflect-img-btn');
  if (recBtn) recBtn.classList.toggle('hidden', hideAttach);
  if (imgBtn) imgBtn.classList.toggle('hidden', hideAttach);
}

// ── main send ─────────────────────────────────────────────────────────────────

async function sendReflectChat() {
  // No topic picked yet → treat as just_chat
  if (!_activeTopic) {
    _activeTopic = { label: 'Just talk', question: '', rag_query: '', type: 'just_chat' };
    _topicPicked = true;
    // Lock the picker if still visible
    const picker = document.getElementById('reflect-topic-picker');
    if (picker) {
      picker.querySelectorAll('input[type=radio]').forEach(r => r.disabled = true);
      picker.classList.add('reflect-topic-picker--locked');
    }
    _updateAttachButtons();
  }

  const inputEl  = document.getElementById('reflect-chat-input');
  const send     = document.getElementById('reflect-chat-send');
  const status   = document.getElementById('reflect-chat-status');
  const log      = document.getElementById('reflect-chat-log');

  const text      = inputEl.value.trim();
  const hasImage  = !!_reflectImageFile;
  const hasAudio  = !!_reflectAudioBlob;

  if (!text && !hasImage && !hasAudio) return;

  const imageFile = _reflectImageFile;
  const audioBlob = _reflectAudioBlob;
  const thumbSrc  = document.getElementById('reflect-img-thumb')?.src || '';

  inputEl.value = '';
  inputEl.style.height = '';
  send.disabled = true;
  status.textContent = '';
  clearReflectImage();
  clearReflectAudio();

  const bubble = _appendBubble('assistant', '');
  bubble.classList.add('bubble-streaming');

  try {
    if (_activeTopic.type === 'just_chat') {
      await _sendJustChat({ text, hasImage, hasAudio, imageFile, audioBlob, thumbSrc, bubble, log, status });
    } else {
      await _sendReflect({ text, bubble, log, status });
    }
  } finally {
    bubble.classList.remove('bubble-streaming');
    send.disabled = false;
    inputEl.focus();
    _saveCache();
  }
}

// ── just_chat send paths ──────────────────────────────────────────────────────

async function _sendJustChat({ text, hasImage, hasAudio, imageFile, audioBlob, thumbSrc, bubble, log, status }) {
  if (hasAudio) {
    _appendVoiceBubble();

    const fd = new FormData();
    fd.append('file', audioBlob, 'audio.webm');
    if (_justChatSid) fd.append('session_id', _justChatSid);

    const res = await fetch('/api/reflect/voice', { method: 'POST', body: fd });
    if (!res.ok) throw new Error(res.statusText);

    const { reply, sid } = await _streamInto(res, bubble, log, status);
    if (sid) _justChatSid = sid;

  } else if (hasImage) {
    _appendImageBubble(thumbSrc, text || null, log);
    if (text) _appendBubble('user', text);

    const imgFd = new FormData();
    imgFd.append('file', imageFile, imageFile.name);
    if (text) imgFd.append('note', text);
    imgFd.append('mode', 'chat');
    if (_justChatSid) imgFd.append('session_id', _justChatSid);
    fetch('/api/image', { method: 'POST', body: imgFd }).catch(() => {});

    const res = await fetch('/api/reflect/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        topic_label:    _activeTopic.label,
        topic_question: _activeTopic.question || '',
        rag_query:      '',
        topic_type:     'just_chat',
        history:        [],
        user_message:   text || '(User shared a photo)',
        session_id:     _justChatSid,
      }),
    });
    if (!res.ok) throw new Error(res.statusText);

    const { reply, sid } = await _streamInto(res, bubble, log, status);
    if (sid) _justChatSid = sid;

  } else {
    _appendBubble('user', text);

    const res = await fetch('/api/reflect/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        topic_label:    _activeTopic.label,
        topic_question: _activeTopic.question || '',
        rag_query:      '',
        topic_type:     'just_chat',
        history:        [],
        user_message:   text,
        session_id:     _justChatSid,
      }),
    });
    if (!res.ok) throw new Error(res.statusText);

    const { reply, sid } = await _streamInto(res, bubble, log, status);
    if (sid) _justChatSid = sid;
  }
}

// ── reflect send path ─────────────────────────────────────────────────────────

async function _sendReflect({ text, bubble, log, status }) {
  _appendBubble('user', text);
  _chatHistory.push({ role: 'user', content: text });

  const res = await fetch('/api/reflect/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      topic_label:    _activeTopic.label,
      topic_question: _activeTopic.question || '',
      rag_query:      _activeTopic.rag_query || _activeTopic.label,
      topic_type:     _activeTopic.type,
      history:        _chatHistory.slice(0, -1),
      user_message:   text,
    }),
  });
  if (!res.ok) throw new Error(res.statusText);

  const { reply } = await _streamInto(res, bubble, log, status);
  _chatHistory.push({ role: 'assistant', content: reply });
}

// ── shared SSE reader ─────────────────────────────────────────────────────────

async function _streamInto(res, bubble, log, status) {
  const reader  = res.body.getReader();
  const decoder = new TextDecoder();
  let buf   = '';
  let reply = '';
  let sid   = null;

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
        sid   = payload.session_id || null;
      }
    }
  }
  return { reply, sid };
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

function _appendImageBubble(src, caption, log) {
  const row = document.createElement('div');
  row.className = 'bubble-row bubble-row-user';
  const bubble = document.createElement('div');
  bubble.className = 'bubble bubble-user';
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

function _appendVoiceBubble() {
  const log = document.getElementById('reflect-chat-log');
  const row = document.createElement('div');
  row.className = 'bubble-row bubble-row-user';
  const bubble = document.createElement('div');
  bubble.className = 'bubble bubble-user';
  bubble.innerHTML = '<span style="opacity:.7">🎙 Voice message</span>';
  row.appendChild(bubble);
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
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
    input.style.padding = input.scrollHeight <= 40 ? '0 0.75rem' : '0.625rem 0.75rem';
  });
});
