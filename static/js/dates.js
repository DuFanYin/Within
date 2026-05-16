'use strict';

/** Local calendar date as YYYY-MM-DD (not UTC). */
function localDateStr(d = new Date()) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/** Local year-month as YYYY-MM. */
function localMonthStr(d = new Date()) {
  return localDateStr(d).slice(0, 7);
}
