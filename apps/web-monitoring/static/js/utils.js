/**
 * utils.js — FERQUEUE Web Monitoring
 * Shared utilities: clock, number formatting, toast notifications.
 * Gunakan sebagai ES module (type="module").
 */

// Base URL untuk semua API calls
export const API_BASE_URL = window.location.origin;

// ----------------------------------------------------------------
// FORMAT WAKTU (locale Indonesia / WIB)
// ----------------------------------------------------------------
const _dateFmt = new Intl.DateTimeFormat('id-ID', {
  timeZone: 'Asia/Jakarta',
  day: '2-digit',
  month: 'short',
  year: 'numeric',
});

const _timeFmt = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Jakarta',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

const _timeShortFmt = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Jakarta',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

const _dayFmt = new Intl.DateTimeFormat('id-ID', {
  timeZone: 'Asia/Jakarta',
  day: '2-digit',
  month: 'short',
});

/**
 * Format tanggal lengkap untuk topbar.
 * Contoh: "17 Nov 2026 · 15:40:46 WIB"
 */
export function formatTopbarClock(date = new Date()) {
  return `${_dateFmt.format(date)} · ${_timeFmt.format(date)} WIB`;
}

/**
 * Format tanggal pendek untuk sidebar.
 * Contoh: "17 Nov 11:41 · UTC+7"
 */
export function formatSidebarClock(date = new Date()) {
  return `${_dayFmt.format(date)} ${_timeShortFmt.format(date)} · UTC+7`;
}

// ----------------------------------------------------------------
// UPDATE CLOCK — dipanggil tiap detik
// ----------------------------------------------------------------
let _clockInterval = null;

/**
 * Mulai update clock otomatis pada elemen #topbar-clock dan #sidebar-clock.
 * Panggil sekali saat DOMContentLoaded.
 */
export function startClock() {
  function tick() {
    const now = new Date();
    const topbar = document.getElementById('topbar-clock');
    const sidebar = document.getElementById('sidebar-clock');
    const syncClock = document.getElementById('sidebar-sync-clock');
    if (topbar) topbar.textContent = formatTopbarClock(now);
    if (sidebar) sidebar.textContent = formatSidebarClock(now);
    if (syncClock) {
      const timePart = now.toLocaleTimeString('en-GB', { timeZone: 'Asia/Jakarta', hour12: false });
      syncClock.textContent = `${timePart} UTC+7`;
    }
  }
  tick(); // langsung tampilkan
  if (_clockInterval) clearInterval(_clockInterval);
  _clockInterval = setInterval(tick, 1000);
}

// ----------------------------------------------------------------
// FORMAT ANGKA (locale Indonesia — ribuan dengan titik)
// ----------------------------------------------------------------
const _numFmt = new Intl.NumberFormat('id-ID');

/**
 * Format angka ke format ribuan Indonesia.
 * Contoh: formatNumber(1428) → "1.428"
 * @param {number} n
 * @returns {string}
 */
export function formatNumber(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '0';
  return _numFmt.format(Number(n));
}

/**
 * Format berat dalam gram ke format Indonesia.
 * Contoh: formatWeight(8450) → "8.450"
 * @param {number} grams
 * @param {number} [fractionDigits=0]
 * @returns {string}
 */
export function formatWeight(grams, fractionDigits = 0) {
  if (grams === null || grams === undefined || Number.isNaN(Number(grams))) return '0';
  return new Intl.NumberFormat('id-ID', {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(Number(grams));
}

/**
 * Format ISO datetime string ke tampilan lokal.
 * Contoh: "2026-11-17T05:32:00" → "17 Nov 2026 · 05:32:00 WIB"
 * @param {string} isoString
 * @returns {string}
 */
export function formatDateTime(isoString) {
  if (!isoString) return '—';
  const d = new Date(isoString);
  if (Number.isNaN(d.getTime())) return isoString;
  return `${_dateFmt.format(d)} · ${_timeFmt.format(d)} WIB`;
}

// ----------------------------------------------------------------
// TOAST NOTIFICATION
// ----------------------------------------------------------------
let _toastTimer = null;

/**
 * Tampilkan toast notification sementara.
 * @param {string} message  Pesan yang ditampilkan
 * @param {'info'|'success'|'error'|'warning'} [type='info']
 * @param {number} [duration=4000]  Durasi dalam ms
 */
export function toast(message, type = 'info', duration = 4000) {
  // Cari atau buat elemen toast
  let container = document.getElementById('fq-toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'fq-toast-container';
    Object.assign(container.style, {
      position: 'fixed',
      bottom: '24px',
      right: '24px',
      zIndex: '9999',
      display: 'flex',
      flexDirection: 'column',
      gap: '8px',
      pointerEvents: 'none',
    });
    document.body.appendChild(container);
  }

  const colors = {
    info: { bg: '#1E293B', border: '#0EA5E9', icon: 'ℹ' },
    success: { bg: '#14532D', border: '#16A34A', icon: '✓' },
    error: { bg: '#7F1D1D', border: '#DC2626', icon: '✕' },
    warning: { bg: '#78350F', border: '#F59E0B', icon: '⚠' },
  };
  const palette = colors[type] || colors.info;

  const toast = document.createElement('div');
  Object.assign(toast.style, {
    background: palette.bg,
    borderLeft: `4px solid ${palette.border}`,
    color: '#F8FAFC',
    padding: '12px 16px',
    borderRadius: '8px',
    fontSize: '14px',
    fontWeight: '500',
    boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    pointerEvents: 'auto',
    maxWidth: '360px',
    opacity: '0',
    transform: 'translateX(20px)',
    transition: 'opacity 0.2s ease, transform 0.2s ease',
  });
  toast.innerHTML = `<span>${palette.icon}</span><span>${message}</span>`;
  container.appendChild(toast);

  // Animasi masuk
  requestAnimationFrame(() => {
    toast.style.opacity = '1';
    toast.style.transform = 'translateX(0)';
  });

  // Auto-remove
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(20px)';
    setTimeout(() => toast.remove(), 250);
  }, duration);
}

// ----------------------------------------------------------------
// FETCH HELPER
// ----------------------------------------------------------------
/**
 * Fetch JSON dari endpoint dengan error handling.
 * @param {string} url
 * @param {RequestInit} [options]
 * @returns {Promise<any>}
 */
export async function fetchJSON(url, options = {}) {
  const res = await fetch(url, { cache: 'no-store', ...options });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  return res.json();
}
