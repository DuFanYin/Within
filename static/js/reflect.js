'use strict';

// ── state ─────────────────────────────────────────────────────────────────────

let _activeTopic   = null;   // { label, question, rag_query, type }
let _topicPicked   = false;
let _companionSid  = null;   // session_id for all companion turns

let _reflectImageFile = null;
let _reflectAudioBlob = null;  // set by recording.js

// Expose to recording.js
Object.defineProperty(window, '_reflectSessionId', {
  get: () => _companionSid,
  configurable: true,
});

// ── sessionStorage cache ──────────────────────────────────────────────────────

const _CACHE_KEY = 'companion_cache_v1';

function _saveCache() {
  const log = document.getElementById('reflect-chat-log');
  if (!log) return;
  const clone = log.cloneNode(true);
  clone.querySelectorAll('.bubble-streaming').forEach(el => el.closest('.bubble-row')?.remove());
  if (clone.querySelector('.reflect-open-step')) return;
  try {
    sessionStorage.setItem(_CACHE_KEY, JSON.stringify({
      html:         clone.innerHTML,
      activeTopic:  _activeTopic,
      topicPicked:  _topicPicked,
      companionSid: _companionSid,
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
    _companionSid  = c.companionSid || null;

    const picker = log.querySelector('.reflect-topic-picker');
    if (picker && !picker.classList.contains('reflect-topic-picker--locked')) {
      picker.querySelectorAll('.reflect-topic-option').forEach(b => b.disabled = true);
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
  if (log && log.children.length) return;
  if (_loadCache()) return;
  _openReflect();
}

function restartReflect() {
  _clearCache();
  _activeTopic  = null;
  _topicPicked  = false;
  _companionSid = null;
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
  stepEl.textContent = 'Catching up on your entries…';
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
    const btn = document.createElement('button');
    btn.className = 'reflect-topic-option';
    btn.addEventListener('click', () => _pickTopic(topic, wrap, btn));

    const iconEl = document.createElement('div');
    iconEl.className = 'reflect-topic-icon';
    iconEl.style.background = topic.bgColor || 'var(--surface-alt)';
    iconEl.style.color = topic.color || 'var(--ink-mid)';
    iconEl.innerHTML = _topicIconSvg(topic.type);

    const textWrap = document.createElement('div');
    const title = document.createElement('div');
    title.className = 'reflect-topic-title';
    title.textContent = topic.label;
    const sub = document.createElement('div');
    sub.className = 'reflect-topic-sub';
    sub.textContent = topic.question || '';
    textWrap.appendChild(title);
    textWrap.appendChild(sub);

    btn.appendChild(iconEl);
    btn.appendChild(textWrap);
    wrap.appendChild(btn);
  });

  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;
}

function _topicIconSvg(type) {
  if (type === 'just_chat') return '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';
  if (type === 'reflect')   return '<svg viewBox="0 0 24 24"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-3.5"/></svg>';
  return '<svg viewBox="0 0 24 24"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/></svg>';
}

function _pickTopic(topic, pickerEl, btnEl) {
  if (_topicPicked) return;
  _topicPicked = true;

  pickerEl.querySelectorAll('.reflect-topic-option').forEach(b => b.disabled = true);
  if (btnEl) btnEl.classList.add('selected');
  pickerEl.classList.add('reflect-topic-picker--locked');

  _activeTopic = topic;

  if (topic.type === 'just_chat') {
    const opener = "I'm here — what would you like to talk about?";
    _appendBubble('assistant', opener);
    document.getElementById('reflect-input-wrap').classList.remove('hidden');
    document.getElementById('reflect-chat-input').focus();
    _updateAttachButtons();
  } else {
    _agentOpen(topic);
  }
}

// ── agent opens the chosen topic ──────────────────────────────────────────────

async function _agentOpen(topic) {
  const log    = document.getElementById('reflect-chat-log');
  const status = document.getElementById('reflect-chat-status');
  const input  = document.getElementById('reflect-input-wrap');

  const seed = topic.question || topic.label;
  const message = `[Context: ${topic.question || topic.label}]\n${seed}`;

  const bubble = _appendBubble('assistant', '');
  bubble.classList.add('bubble-streaming');

  try {
    const sid = _companionSid || null;
    const res = await fetch('/api/companion/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, session_id: sid }),
    });
    if (!res.ok) throw new Error(res.statusText);

    const { reply, sid: newSid } = await _streamInto(res, bubble, log, status);
    if (newSid) _companionSid = newSid;

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

// Image button always visible; voice always available
function _updateAttachButtons() {
  const imgBtn = document.getElementById('reflect-img-btn');
  if (imgBtn) imgBtn.classList.remove('hidden');
}

// ── main send ─────────────────────────────────────────────────────────────────

async function sendReflectChat() {
  if (!_activeTopic) {
    _activeTopic = { label: 'Just talk', question: '', rag_query: '', type: 'just_chat' };
    _topicPicked = true;
    const picker = document.getElementById('reflect-topic-picker');
    if (picker) {
      picker.querySelectorAll('.reflect-topic-option').forEach(b => b.disabled = true);
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
    if (hasAudio) {
      await _sendVoice({ audioBlob, bubble, log, status });
    } else if (hasImage) {
      await _sendWithImage({ text, imageFile, thumbSrc, bubble, log, status });
    } else {
      await _sendText({ text, bubble, log, status });
    }
  } finally {
    bubble.classList.remove('bubble-streaming');
    send.disabled = false;
    inputEl.focus();
    _saveCache();
  }
}

// ── send paths ────────────────────────────────────────────────────────────────

async function _sendText({ text, bubble, log, status }) {
  _appendBubble('user', text);

  const message = _activeTopic && _activeTopic.type !== 'just_chat'
    ? `[Context: ${_activeTopic.question}]\n${text}`
    : text;

  const res = await fetch('/api/companion/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: _companionSid }),
  });
  if (!res.ok) throw new Error(res.statusText);

  const { reply, sid } = await _streamInto(res, bubble, log, status);
  if (sid) _companionSid = sid;
}

async function _sendVoice({ audioBlob, bubble, log, status }) {
  _appendVoiceBubble();

  const fd = new FormData();
  fd.append('file', audioBlob, 'audio.webm');
  if (_companionSid) fd.append('session_id', _companionSid);

  const res = await fetch('/api/companion/voice', { method: 'POST', body: fd });
  if (!res.ok) throw new Error(res.statusText);

  const { reply, sid } = await _streamInto(res, bubble, log, status);
  if (sid) _companionSid = sid;
}

async function _sendWithImage({ text, imageFile, thumbSrc, bubble, log, status }) {
  _appendImageBubble(thumbSrc, text || null, log);

  const imgFd = new FormData();
  imgFd.append('file', imageFile, imageFile.name);
  if (text) imgFd.append('note', text);
  imgFd.append('mode', 'companion');
  if (_companionSid) imgFd.append('session_id', _companionSid);
  fetch('/api/image', { method: 'POST', body: imgFd }).catch(() => {});

  const message = text || '(User shared a photo)';
  const res = await fetch('/api/companion/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: _companionSid }),
  });
  if (!res.ok) throw new Error(res.statusText);

  const { reply, sid } = await _streamInto(res, bubble, log, status);
  if (sid) _companionSid = sid;
}

// ── shared SSE reader ─────────────────────────────────────────────────────────

async function _streamInto(res, bubble, log, status) {
  const reader  = res.body.getReader();
  const decoder = new TextDecoder();
  let buf        = '';
  let reply      = '';
  let sid        = null;

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
    const max = parseFloat(getComputedStyle(input).maxHeight) || 120;
    input.style.height = Math.min(input.scrollHeight, max) + 'px';
    input.style.overflowY = input.scrollHeight > max ? 'auto' : 'hidden';
  });
});
