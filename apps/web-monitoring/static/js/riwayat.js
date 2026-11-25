/**
 * riwayat.js — FERQUEUE Web Monitoring
 * Riwayat Page: Real API sync, stat cards, search, date/class/status filters,
 * real pagination, CSV export, print summary, and photo lightbox.
 */

import {
  startClock,
  formatNumber,
  formatDateId,
  escapeHtml,
  downloadCsv,
  toast,
  API_BASE_URL,
} from './utils.js';

let items = [];
let filteredItems = [];
let currentPage = 1;
const PER_PAGE = 10;

function openPhotoDialog(item) {
  const dialog = document.getElementById('photo-preview-dialog');
  const img = document.getElementById('photo-dialog-img');
  const title = document.getElementById('photo-dialog-title');
  const meta = document.getElementById('photo-dialog-meta');
  if (!dialog || !img || !item?.foto_url) return;

  img.src = item.foto_url;
  img.alt = `Foto kendaraan ${item.nomor}`;
  if (title) title.textContent = `${item.nomor} · ${item.pengemudi}`;
  if (meta) meta.textContent = `${item.golongan} · P: ${item.p} × T: ${item.t} · Berat: ${item.berat} · ${item.status}`;
  if (typeof dialog.showModal === 'function') {
    dialog.showModal();
  } else {
    dialog.setAttribute('open', '');
  }
}

function updateStatCards(sourceRows) {
  const total = sourceRows.length;
  const overweight = sourceRows.filter(r => r.status.toLowerCase().includes('over')).length;
  const normal = total - overweight;
  const passPct = total > 0 ? ((normal / total) * 100).toFixed(1).replace('.', ',') : '0';

  const setEl = (id, text) => {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  };
  setEl('stat-total', formatNumber(total));
  setEl('stat-normal', formatNumber(normal));
  setEl('stat-normal-badge', `${passPct}% Lolos`);
  setEl('stat-overdimensi', formatNumber(overweight));
}

function renderTable(pageRows) {
  const tbody = document.getElementById('riwayat-tbody');
  if (!tbody) return;

  if (!pageRows.length) {
    const emptyMsg = items.length === 0
      ? 'Belum ada transaksi pemeriksaan tercatat.'
      : 'Tidak ada transaksi yang cocok dengan filter pencarian.';
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;padding:32px;color:#94A3B8;">${emptyMsg}</td></tr>`;
    return;
  }

  tbody.innerHTML = pageRows.map((r, idx) => {
    const isOver = r.status.toLowerCase().includes('over');
    const avatarClass = isOver ? 'cell-avatar cell-avatar--red' : 'cell-avatar';
    const dimsClass = isOver ? 'cell-dims is-danger' : 'cell-dims';
    const beratClass = isOver ? 'cell-berat is-danger' : 'cell-berat';
    const statusLabel = escapeHtml(r.status);
    const statusPill = isOver
      ? `<span class="pill-status-over">⚠ ${statusLabel}</span>`
      : '<span class="pill-status-normal">✓ Normal</span>';

    const photoCell = r.foto_url
      ? `<button type="button" class="cell-photo-btn" data-photo-idx="${idx}" title="Klik untuk perbesar foto">
           <img class="cell-photo-thumb" src="${escapeHtml(r.foto_url)}" alt="Foto ${escapeHtml(r.nomor)}" loading="lazy" />
         </button>`
      : '<span class="cell-photo-empty" title="Tidak ada foto">—</span>';

    return `
      <tr>
        <td>${photoCell}</td>
        <td><span class="cell-ticket-no">${escapeHtml(r.nomor)}</span></td>
        <td>
          <div class="cell-time-date">${escapeHtml(r.date)}</div>
          <div class="cell-time-hour">${escapeHtml(r.time)}</div>
        </td>
        <td>
          <div class="cell-driver">
            <div class="${avatarClass}">${escapeHtml(r.initial)}</div>
            <span>${escapeHtml(r.pengemudi)}</span>
          </div>
        </td>
        <td>
          <div class="cell-petugas">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="13" height="13">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
            </svg>
            <span>${escapeHtml(r.petugas)}</span>
          </div>
        </td>
        <td><span class="cell-golongan-pill">${escapeHtml(r.golongan)}</span></td>
        <td>
          <div class="${dimsClass}">P: ${escapeHtml(r.p)}</div>
          <div class="${dimsClass}">T: ${escapeHtml(r.t)}</div>
        </td>
        <td><span class="${beratClass}">${escapeHtml(r.berat)}</span></td>
        <td>${statusPill}</td>
      </tr>
    `;
  }).join('');

  tbody.querySelectorAll('.cell-photo-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = Number(btn.dataset.photoIdx);
      if (Number.isInteger(idx) && pageRows[idx]) {
        openPhotoDialog(pageRows[idx]);
      }
    });
  });
}

function buildPageList(totalPages, activePage) {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }
  const pages = new Set([1, totalPages, activePage, activePage - 1, activePage + 1]);
  const sorted = [...pages].filter(p => p >= 1 && p <= totalPages).sort((a, b) => a - b);
  const out = [];
  for (let i = 0; i < sorted.length; i += 1) {
    if (i > 0 && sorted[i] - sorted[i - 1] > 1) out.push('...');
    out.push(sorted[i]);
  }
  return out;
}

function renderPagination(total, page) {
  const container = document.getElementById('pagination');
  const info = document.getElementById('pagination-info');
  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));
  const safePage = Math.min(Math.max(1, page), totalPages);
  currentPage = safePage;

  const startIdx = total === 0 ? 0 : (safePage - 1) * PER_PAGE + 1;
  const endIdx = Math.min(total, safePage * PER_PAGE);

  if (info) {
    info.textContent = `Menampilkan ${formatNumber(startIdx)} - ${formatNumber(endIdx)} dari ${formatNumber(total)} transaksi terverifikasi`;
  }
  if (!container) return;

  const pageTokens = buildPageList(totalPages, safePage);
  const buttonsHtml = pageTokens.map(token => {
    if (token === '...') {
      return '<span style="padding: 0 4px; color: #94A3B8;">...</span>';
    }
    const activeCls = token === safePage ? ' is-active' : '';
    return `<button type="button" class="riwayat-page-btn${activeCls}" data-page="${token}">${token}</button>`;
  }).join('');

  container.innerHTML = `
    <button type="button" class="riwayat-page-btn-text" data-page="${safePage - 1}" ${safePage <= 1 ? 'disabled' : ''}>‹ Sebelumnya</button>
    ${buttonsHtml}
    <button type="button" class="riwayat-page-btn-text" data-page="${safePage + 1}" ${safePage >= totalPages ? 'disabled' : ''}>Selanjutnya ›</button>
  `;

  container.querySelectorAll('button[data-page]').forEach(btn => {
    btn.addEventListener('click', () => {
      const target = Number(btn.dataset.page);
      if (Number.isInteger(target) && target >= 1 && target <= totalPages && target !== currentPage) {
        currentPage = target;
        renderCurrentPage();
      }
    });
  });
}

function renderCurrentPage() {
  const totalPages = Math.max(1, Math.ceil(filteredItems.length / PER_PAGE));
  if (currentPage > totalPages) currentPage = totalPages;
  const start = (currentPage - 1) * PER_PAGE;
  const pageRows = filteredItems.slice(start, start + PER_PAGE);
  renderTable(pageRows);
  renderPagination(filteredItems.length, currentPage);
}

function isSameWibDay(tsA, tsB) {
  const fmt = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jakarta' });
  return fmt.format(new Date(tsA)) === fmt.format(new Date(tsB));
}

function filterData({ resetPage = true } = {}) {
  const query = (document.getElementById('search-input')?.value || '').toLowerCase().trim();
  const dateRange = document.getElementById('filter-tanggal')?.value || '';
  const gol = document.getElementById('filter-golongan')?.value || '';
  const st = document.getElementById('filter-status')?.value || '';
  const nowMs = Date.now();

  filteredItems = items.filter(r => {
    const textMatch = !query ||
      r.nomor.toLowerCase().includes(query) ||
      r.idPemeriksaan.toLowerCase().includes(query) ||
      r.pengemudi.toLowerCase().includes(query) ||
      r.petugas.toLowerCase().includes(query) ||
      r.jenis.toLowerCase().includes(query);

    const golMatch = !gol || r.golongan.toLowerCase() === gol.toLowerCase();
    const stMatch = !st || r.status.toLowerCase() === st.toLowerCase();

    let dateMatch = true;
    if (dateRange && Number.isFinite(r.timestampMs)) {
      if (dateRange === 'today') {
        dateMatch = isSameWibDay(r.timestampMs, nowMs);
      } else {
        const days = Number(dateRange);
        if (Number.isFinite(days) && days > 0) {
          dateMatch = (nowMs - r.timestampMs) <= days * 24 * 60 * 60 * 1000;
        }
      }
    }

    return textMatch && golMatch && stMatch && dateMatch;
  });

  if (resetPage) currentPage = 1;
  renderCurrentPage();
}

function exportCsv() {
  if (!filteredItems.length) {
    toast('Tidak ada data riwayat untuk diekspor.', 'info');
    return;
  }
  const headers = ['No. Tiket', 'ID Pemeriksaan', 'Tanggal', 'Waktu', 'Pengemudi', 'Petugas', 'Golongan', 'Panjang', 'Tinggi', 'Berat', 'Status'];
  const rows = filteredItems.map(r => [
    r.nomor, r.idPemeriksaan, r.date, r.time, r.pengemudi, r.petugas, r.golongan, r.p, r.t, r.berat, r.status,
  ]);
  downloadCsv(`riwayat_tiket_${new Date().toISOString().slice(0, 10)}.csv`, headers, rows);
  toast(`Ekspor CSV berhasil (${filteredItems.length} baris).`, 'success');
}

function updateClock() {
  const now = new Date();
  const time = now.toLocaleTimeString('en-GB', { timeZone: 'Asia/Jakarta', hour12: false });
  const el = document.getElementById('riwayat-clock');
  if (el) el.textContent = `${time} WIB`;

  const optToday = document.getElementById('opt-today');
  if (optToday) optToday.textContent = `Hari Ini (${formatDateId(now)})`;
}

async function fetchFromApi() {
  try {
    const res = await fetch(`${API_BASE_URL}/api/riwayat`, { cache: 'no-store' });
    if (res.ok) {
      const payload = await res.json();
      const rows = Array.isArray(payload) ? payload : (Array.isArray(payload?.data) ? payload.data : []);
      items = rows.map((t, idx) => {
        const driver = t.nama_pengemudi || t.pengemudi || 'Pengemudi';
        const rawTime = t.waktu_pemeriksaan || t.waktu || '';
        const dt = rawTime ? new Date(typeof rawTime === 'string' ? rawTime.replace(' ', 'T') : rawTime) : null;
        const validDate = dt && !Number.isNaN(dt.getTime());
        const dateStr = validDate
          ? dt.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' })
          : '—';
        const timeStr = validDate
          ? dt.toLocaleTimeString('en-GB', { hour12: false }) + ' WIB'
          : '—';
        const pVal = t.panjang_cm ?? t.P;
        const tVal = t.tinggi_cm ?? t.T;
        const beratVal = Number(t.berat_aktual_gram ?? t.berat_gram ?? t.berat ?? 0);
        const isOver = String(t.status || '').toLowerCase().includes('over');
        const idPem = t.id_pemeriksaan || `CHK-${String(idx + 1).padStart(3, '0')}`;

        return {
          idPemeriksaan: idPem,
          nomor: t.nomor_tiket || t.nomor || idPem,
          date: dateStr,
          time: timeStr,
          timestampMs: validDate ? dt.getTime() : NaN,
          pengemudi: driver,
          initial: driver.split(' ').filter(Boolean).map(w => w[0]).join('').slice(0, 2).toUpperCase() || 'OP',
          petugas: t.nama_petugas || 'Operator',
          jenis: t.jenis_kendaraan || 'Kendaraan',
          golongan: t.golongan ? `Gol ${t.golongan}` : 'Gol A',
          p: pVal !== undefined && pVal !== null && Number(pVal) > 0 ? `${Number(pVal).toFixed(1)} cm` : '—',
          t: tVal !== undefined && tVal !== null && Number(tVal) > 0 ? `${Number(tVal).toFixed(1)} cm` : '—',
          berat: `${beratVal.toFixed(1).replace('.', ',')} g`,
          status: isOver ? 'Overweight' : 'Normal',
          foto_url: t.foto_url || null,
        };
      });
    }
  } catch (err) {
    console.warn('[riwayat] Gagal memuat riwayat dari API:', err);
  }

  updateStatCards(items);
  filterData({ resetPage: false });
}

function init() {
  startClock();
  updateClock();
  setInterval(updateClock, 1000);

  fetchFromApi();
  setInterval(fetchFromApi, 15000);

  const photoDialog = document.getElementById('photo-preview-dialog');
  document.getElementById('btn-close-photo-dialog')?.addEventListener('click', () => {
    photoDialog?.close();
  });
  photoDialog?.addEventListener('click', (e) => {
    if (e.target === photoDialog) photoDialog.close();
  });

  document.getElementById('search-input')?.addEventListener('input', () => filterData({ resetPage: true }));
  document.getElementById('filter-tanggal')?.addEventListener('change', () => filterData({ resetPage: true }));
  document.getElementById('filter-golongan')?.addEventListener('change', () => filterData({ resetPage: true }));
  document.getElementById('filter-status')?.addEventListener('change', () => filterData({ resetPage: true }));

  document.getElementById('btn-reset-filter')?.addEventListener('click', () => {
    const s = document.getElementById('search-input');
    const d = document.getElementById('filter-tanggal');
    const g = document.getElementById('filter-golongan');
    const st = document.getElementById('filter-status');
    if (s) s.value = '';
    if (d) d.value = '';
    if (g) g.value = '';
    if (st) st.value = '';
    filterData({ resetPage: true });
  });

  document.getElementById('btn-print-riwayat')?.addEventListener('click', () => {
    window.print();
  });

  document.getElementById('btn-export')?.addEventListener('click', exportCsv);
}

document.addEventListener('DOMContentLoaded', init);
