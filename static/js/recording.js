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

    const blob = new Blob(audioChunks, { type: 'audio/webm' });

    if (target === 'chat') {
      // Hand blob to chat.js — actual sending happens when user taps Send
      setChatAudioBlob(blob);
      setRecStatus(target, '');
    } else {
      // Journal: save raw audio; background job will transcribe + summarise tone
      setRecStatus(target, 'Saving…');
      const fd = new FormData();
      fd.append('file', blob, 'audio.webm');
      fd.append('mode', 'journal');
      try {
        const res = await fetch('/api/voice', { method: 'POST', body: fd });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || res.statusText);
        setRecStatus(target, 'Voice saved ✓');
        setTimeout(() => setRecStatus(target, ''), 2500);
      } catch (err) {
        setRecStatus(target, 'Save failed: ' + err.message, true);
      }
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
