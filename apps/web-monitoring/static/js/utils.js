/**
 * utils.js — FERQUEUE Web Monitoring
 * Shared utilities: clock, date/shift helpers, number/CSV formatting, topbar live sync, toast notifications.
 * Gunakan sebagai ES module (type="module").
 */

// Base URL untuk semua API calls
export const API_BASE_URL = window.location.origin;

// ----------------------------------------------------------------
// HTML ESCAPING
// ----------------------------------------------------------------
export function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

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

export function formatDateId(date = new Date()) {
  return _dateFmt.format(date);
}

export function getCurrentShiftWib(date = new Date()) {
  const hourStr = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Jakarta',
    hour: '2-digit',
    hour12: false,
  }).format(date);
  const hour = Number(hourStr) % 24;
  if (hour < 8) return 'Shift 1 (00:00 - 08:00)';
  if (hour < 16) return 'Shift 2 (08:00 - 16:00)';
  return 'Shift 3 (16:00 - 24:00)';
}

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
// TOPBAR LIVE STATUS & DROPDOWN MENUS
// ----------------------------------------------------------------
let _topbarInitialized = false;
let _topbarInterval = null;

async function syncTopbarStatus() {
  const gatePill = document.getElementById('topbar-gate-pill');
  const scalePill = document.getElementById('topbar-scale-pill');
  const cvPill = document.getElementById('topbar-cv-pill');
  const notifBadge = document.getElementById('topbar-notif-badge');
  const notifList = document.getElementById('topbar-notif-list');

  if (!gatePill && !scalePill && !cvPill && !notifBadge && !notifList) return;

  try {
    const res = await fetch(`${API_BASE_URL}/api/system-status`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const isLive = Boolean(data.sensor_live);
    const gerbang = String(data.gerbang || 'tutup').toLowerCase();
    const isOpen = gerbang.includes('buka') || gerbang.includes('open');

    if (gatePill) {
      gatePill.textContent = isOpen ? 'Gerbang Terbuka' : (isLive ? 'Gerbang Tertutup' : 'Gerbang: Standby');
      gatePill.classList.toggle('is-open-gate', isOpen);
    }

    if (scalePill) {
      scalePill.textContent = isLive ? 'Sensor Timbangan OK' : 'Timbangan: Standby';
      scalePill.classList.toggle('is-standby', !isLive);
      scalePill.classList.remove('is-offline');
    }

    if (cvPill) {
      const cvOnline = Boolean(data.cv_online);
      cvPill.textContent = cvOnline ? 'Kamera PCV Aktif' : 'Kamera PCV: Standby';
      cvPill.classList.toggle('is-standby', !cvOnline);
      cvPill.classList.remove('is-offline');
    }

    const list = Array.isArray(data.overweight_recent) ? data.overweight_recent : [];
    const totalOver = Number(data.overweight_count ?? list.length);
    if (notifBadge) {
      notifBadge.textContent = String(totalOver > 99 ? '99+' : totalOver);
      notifBadge.hidden = totalOver === 0;
    }
    if (notifList) {
      if (list.length === 0) {
        notifList.innerHTML = '<p class="topbar__popover-empty">Tidak ada peringatan Overweight saat ini.</p>';
      } else {
        notifList.innerHTML = list.slice(0, 5).map(item => `
          <a href="/ai-assistant" class="topbar__notif-item">
            <div class="topbar__notif-item-top">
              <span>${escapeHtml(item.id_pemeriksaan || 'Overweight')}</span>
              <span>+${escapeHtml(item.kelebihan_berat_gram ?? 0)} g</span>
            </div>
            <div class="topbar__notif-item-meta">
              ${escapeHtml(item.nama_pengemudi || 'Pengemudi')} · ${escapeHtml(item.jenis_kendaraan || 'Kendaraan')} (Gol. ${escapeHtml(item.golongan || '-')})
            </div>
          </a>
        `).join('');
      }
    }
  } catch {
    if (scalePill) {
      scalePill.textContent = 'Timbangan: Offline';
      scalePill.classList.remove('is-standby');
      scalePill.classList.add('is-offline');
    }
    if (cvPill) {
      cvPill.textContent = 'Kamera PCV: Offline';
      cvPill.classList.remove('is-standby');
      cvPill.classList.add('is-offline');
    }
    if (notifList) {
      notifList.innerHTML = '<p class="topbar__popover-empty">Gagal memuat notifikasi.</p>';
    }
  }
}

export function initTopbar() {
  if (_topbarInitialized) return;
  _topbarInitialized = true;

  const notifBtn = document.getElementById('btn-topbar-notif');
  const notifPanel = document.getElementById('topbar-notif-panel');
  const appsBtn = document.getElementById('btn-topbar-apps');
  const appsPanel = document.getElementById('topbar-apps-panel');

  const closeAll = () => {
    if (notifPanel) notifPanel.hidden = true;
    if (appsPanel) appsPanel.hidden = true;
    notifBtn?.setAttribute('aria-expanded', 'false');
    appsBtn?.setAttribute('aria-expanded', 'false');
  };

  notifBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    const opening = notifPanel ? notifPanel.hidden : false;
    closeAll();
    if (opening && notifPanel) {
      notifPanel.hidden = false;
      notifBtn.setAttribute('aria-expanded', 'true');
      syncTopbarStatus();
    }
  });

  appsBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    const opening = appsPanel ? appsPanel.hidden : false;
    closeAll();
    if (opening && appsPanel) {
      appsPanel.hidden = false;
      appsBtn.setAttribute('aria-expanded', 'true');
    }
  });

  document.addEventListener('click', (e) => {
    const target = e.target;
    if (!(target instanceof Node)) return;
    if (
      (notifPanel && !notifPanel.hidden && !notifPanel.contains(target) && !notifBtn?.contains(target)) ||
      (appsPanel && !appsPanel.hidden && !appsPanel.contains(target) && !appsBtn?.contains(target))
    ) {
      closeAll();
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeAll();
  });

  syncTopbarStatus();
  if (_topbarInterval) clearInterval(_topbarInterval);
  _topbarInterval = setInterval(syncTopbarStatus, 10000);
}

// ----------------------------------------------------------------
// UPDATE CLOCK — dipanggil tiap detik
// ----------------------------------------------------------------
let _clockInterval = null;

/**
 * Mulai update clock otomatis pada elemen #topbar-clock, #sidebar-clock, #sidebar-sync-clock
 * serta aktifkan sinkronisasi topbar.
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
  tick();
  if (_clockInterval) clearInterval(_clockInterval);
  _clockInterval = setInterval(tick, 1000);
  initTopbar();
}

// ----------------------------------------------------------------
// FORMAT ANGKA (locale Indonesia — ribuan dengan titik)
// ----------------------------------------------------------------
const _numFmt = new Intl.NumberFormat('id-ID');

export function formatNumber(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '0';
  return _numFmt.format(Number(n));
}

export function formatWeight(grams, fractionDigits = 0) {
  if (grams === null || grams === undefined || Number.isNaN(Number(grams))) return '0';
  return new Intl.NumberFormat('id-ID', {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(Number(grams));
}

export function formatDateTime(isoString) {
  if (!isoString) return '—';
  const d = new Date(isoString);
  if (Number.isNaN(d.getTime())) return isoString;
  return `${_dateFmt.format(d)} · ${_timeFmt.format(d)} WIB`;
}

// ----------------------------------------------------------------
// CSV EXPORT HELPER (dengan UTF-8 BOM dan escaping aman)
// ----------------------------------------------------------------
export function downloadCsv(filename, headers, rows) {
  const escapeCell = (val) => `"${String(val ?? '').replace(/"/g, '""')}"`;
  const lines = [
    headers.map(escapeCell).join(','),
    ...rows.map(row => row.map(escapeCell).join(',')),
  ];
  const blob = new Blob(['\uFEFF' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ----------------------------------------------------------------
// TOAST NOTIFICATION
// ----------------------------------------------------------------
export function toast(message, type = 'info', duration = 4000) {
  let container = document.getElementById('toast-container') || document.getElementById('fq-toast-container');
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

  const toastEl = document.createElement('div');
  Object.assign(toastEl.style, {
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

  const iconSpan = document.createElement('span');
  iconSpan.textContent = palette.icon;
  const textSpan = document.createElement('span');
  textSpan.textContent = String(message ?? '');
  toastEl.append(iconSpan, textSpan);
  container.appendChild(toastEl);

  requestAnimationFrame(() => {
    toastEl.style.opacity = '1';
    toastEl.style.transform = 'translateX(0)';
  });

  setTimeout(() => {
    toastEl.style.opacity = '0';
    toastEl.style.transform = 'translateX(20px)';
    setTimeout(() => toastEl.remove(), 250);
  }, duration);
}

// ----------------------------------------------------------------
// FETCH HELPER
// ----------------------------------------------------------------
export async function fetchJSON(url, options = {}) {
  const res = await fetch(url, { cache: 'no-store', ...options });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  return res.json();
}
