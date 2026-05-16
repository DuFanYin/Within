'use strict';

// Home greeting
(function() {
  const hour = new Date().getHours();
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
  const el = document.getElementById('home-greeting-text');
  if (el) el.textContent = greeting;

  const dotsEl = document.getElementById('home-streak-dots');
  if (dotsEl) {
    [true,true,true,false,true,true,true].forEach(filled => {
      const d = document.createElement('div');
      d.className = 'streak-dot' + (filled ? ' filled' : '');
      dotsEl.appendChild(d);
    });
  }
})();

// Show banner while model loads, then ping /api/ready
(async function bootstrap() {
  showPage('home');

  const banner = document.getElementById('init-banner');
  banner.classList.add('visible');

  let ok = false;
  try {
    const res = await fetch('/api/warmup', { method: 'POST' });
    ok = res.ok;
    if (!ok) {
      const body = await res.json().catch(() => ({}));
      banner.textContent = `⚠ Model load failed (${res.status}${body.detail ? ': ' + body.detail : ''})`;
      banner.classList.add('visible');
      return;
    }
  } catch (err) {
    banner.textContent = '⚠ Cannot reach server — is uvicorn running?';
    banner.classList.add('visible');
    return;
  }

  if (ok) {
    await new Promise(r => setTimeout(r, 400));
    banner.classList.remove('visible');
  }
})();
