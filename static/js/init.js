'use strict';

// Show banner while model loads, then ping /api/ready
(async function bootstrap() {
  showPage('home');

  const banner = document.getElementById('init-banner');
  banner.classList.add('visible');

  try {
    await fetch('/api/warmup', { method: 'POST' });
  } catch {}

  banner.classList.remove('visible');
})();
