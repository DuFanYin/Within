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

  try {
    await fetch('/api/warmup', { method: 'POST' });
  } catch {}

  // Brief pause so the transition is visible, then collapse
  await new Promise(r => setTimeout(r, 400));
  banner.classList.remove('visible');
})();
