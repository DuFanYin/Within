'use strict';

let mediaRecorder = null;
let audioChunks = [];
let recordingTarget = null; // 'chat' | 'journal'

async function toggleRecording(target) {
  if (mediaRecorder && mediaRecorder.state === 'recording') {
    mediaRecorder.stop();
    return;
  }

  recordingTarget = target;
  audioChunks = [];

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    setRecStatus(target, 'Microphone access denied', true);
    return;
  }

  mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
  mediaRecorder.ondataavailable = e => { if (e.data.size) audioChunks.push(e.data); };

  mediaRecorder.onstart = () => {
    setRecBtn(target, true);
    setRecStatus(target, 'Recording… tap again to stop');
  };

  mediaRecorder.onstop = async () => {
    stream.getTracks().forEach(t => t.stop());
    setRecBtn(target, false);
    setRecStatus(target, 'Transcribing…');

    const blob = new Blob(audioChunks, { type: 'audio/webm' });
    const fd = new FormData();
    fd.append('file', blob, 'audio.webm');

    try {
      const res = await fetch('/api/transcribe', { method: 'POST', body: fd });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || res.statusText);
      const text = (data.text || '').trim();
      if (target === 'chat') {
        const el = document.getElementById('chat-input');
        el.value = (el.value ? el.value + ' ' : '') + text;
      } else {
        const el = document.getElementById('journal-textarea');
        el.value = (el.value ? el.value + '\n' : '') + text;
      }
      setRecStatus(target, '');
    } catch (err) {
      setRecStatus(target, 'Transcribe failed: ' + err.message, true);
    }
  };

  mediaRecorder.start();
}

function setRecBtn(target, recording) {
  document.getElementById(target + '-rec-btn').classList.toggle('recording', recording);
}

function setRecStatus(target, msg, error = false) {
  const id = target === 'journal' ? 'journal-rec-status' : 'chat-status';
  const el = document.getElementById(id);
  el.textContent = msg;
  el.className = 'status-bar' + (error ? ' error' : '');
}
