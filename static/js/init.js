'use strict';

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
