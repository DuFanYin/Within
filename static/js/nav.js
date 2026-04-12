'use strict';

function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('page-' + name).classList.add('active');
  const nb = document.getElementById('nav-' + name);
  if (nb) nb.classList.add('active');

  if (name === 'history') loadHistory();
  if (name === 'insights') loadInsights();
  if (name === 'reflect') loadReflectInsights();
  if (name === 'journal') {
    document.getElementById('journal-date').textContent =
      new Date().toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
  }
}
