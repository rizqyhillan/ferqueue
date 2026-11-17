/**
 * riwayat.js — FERQUEUE Web Monitoring
 * Riwayat Page: Search, filter, pagination, export.
 */

import { startClock, formatNumber, API_BASE_URL } from './utils.js';

// Mock data riwayat persis seperti di Screenshot 3
const DEFAULT_ROWS = [
  {
    nomor: 'FQ-2N261117-W002',
    date: '17 Nov 2026',
    time: '04:41:12 WIB',
    pengemudi: 'Budi Santoso',
    initial: 'BS',
    petugas: 'Rian Setiawan',
    golongan: 'Gol V B',
    p: '7.2m',
    t: '3.1m',
    berat: '8.450 kg',
    status: 'Normal',
  },
  {
    nomor: 'FQ-2N261117-W001',
    date: '17 Nov 2026',
    time: '04:38:44 WIB',
    pengemudi: 'Ahmad Fauzi',
    initial: 'AF',
    petugas: 'Dedi Kurniawan',
    golongan: 'Gol VI B',
    p: '12.4m',
    t: '4.2m',
    berat: '16.480 kg',
    status: 'Overdimension',
  },
  {
    nomor: 'FQ-2N261117-W009',
    date: '17 Nov 2026',
    time: '04:32:04 WIB',
    pengemudi: 'Hendra Wijaya',
    initial: 'HW',
    petugas: 'Agus Pratama',
    golongan: 'Gol IV A',
    p: '4.8m',
    t: '1.6m',
    berat: '1.820 kg',
    status: 'Normal',
  },
  {
    nomor: 'FQ-2N261117-W008',
    date: '17 Nov 2026',
    time: '04:27:18 WIB',
    pengemudi: 'Rudi Hermansyah',
    initial: 'RH',
    petugas: 'Rian Hidayat',
    golongan: 'Gol VI A',
    p: '11.8m',
    t: '3.4m',
    berat: '12.100 kg',
    status: 'Normal',
  },
  {
    nomor: 'FQ-2N261117-W007',
    date: '17 Nov 2026',
    time: '04:19:40 WIB',
    pengemudi: 'Joko Pramono',
    initial: 'JP',
    petugas: 'Bambang SL',
    golongan: 'Gol IV B',
    p: '4.9m',
    t: '1.6m',
    berat: '2.450 kg',
    status: 'Normal',
  },
  {
    nomor: 'FQ-2N261117-W006',
    date: '17 Nov 2026',
    time: '04:11:02 WIB',
    pengemudi: 'Supardi Jaya',
    initial: 'SJ',
    petugas: 'Felly Iswanto',
    golongan: 'Gol VII',
    p: '13.5m',
    t: '3.8m',
    berat: '24.620 kg',
    status: 'Normal',
  },
];

let items = [...DEFAULT_ROWS];
let currentPage = 1;
const PER_PAGE = 6;

function renderTable(data) {
  const tbody = document.getElementById('riwayat-tbody');
  if (!tbody) return;

  if (!data.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:32px;color:#94A3B8;">Tidak ada transaksi ditemukan</td></tr>';
    return;
  }

  tbody.innerHTML = data.map(r => {
    const isOver = r.status.toLowerCase().includes('over');
    const avatarClass = isOver ? 'cell-avatar cell-avatar--red' : 'cell-avatar';
    const dimsClass = isOver ? 'cell-dims is-danger' : 'cell-dims';
    const beratClass = isOver ? 'cell-berat is-danger' : 'cell-berat';
    const statusPill = isOver
      ? '<span class="pill-status-over">⚠ Overdimension</span>'
      : '<span class="pill-status-normal">✓ Normal</span>';

    return `
      <tr>
        <td><span class="cell-ticket-no">${r.nomor}</span></td>
        <td>
          <div class="cell-time-date">${r.date}</div>
          <div class="cell-time-hour">${r.time}</div>
        </td>
        <td>
          <div class="cell-driver">
            <div class="${avatarClass}">${r.initial}</div>
            <span>${r.pengemudi}</span>
          </div>
        </td>
        <td>
          <div class="cell-petugas">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="13" height="13">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
            </svg>
            <span>${r.petugas}</span>
          </div>
        </td>
        <td><span class="cell-golongan-pill">${r.golongan}</span></td>
        <td>
          <div class="${dimsClass}">P: ${r.p}</div>
          <div class="${dimsClass}">T: ${r.t}</div>
        </td>
        <td><span class="${beratClass}">${r.berat}</span></td>
        <td>${statusPill}</td>
      </tr>
    `;
  }).join('');
}

function renderPagination(total, page) {
  const container = document.getElementById('pagination');
  const info = document.getElementById('pagination-info');
  if (info) {
    info.textContent = `Menampilkan 1 - ${Math.min(total, PER_PAGE)} dari 1.428 transaksi terverifikasi`;
  }
  if (!container) return;

  container.innerHTML = `
    <button class="riwayat-page-btn-text" ${page === 1 ? 'disabled' : ''}>‹ Sebelumnya</button>
    <button class="riwayat-page-btn is-active">1</button>
    <button class="riwayat-page-btn">2</button>
    <button class="riwayat-page-btn">3</button>
    <span style="padding: 0 4px; color: #94A3B8;">...</span>
    <button class="riwayat-page-btn">143</button>
    <button class="riwayat-page-btn-text">Selanjutnya ›</button>
  `;
}

function filterData() {
  const query = (document.getElementById('search-input')?.value || '').toLowerCase().trim();
  const gol = document.getElementById('filter-golongan')?.value || '';
  const st = document.getElementById('filter-status')?.value || '';

  const filtered = items.filter(r => {
    const textMatch = !query || r.nomor.toLowerCase().includes(query) || r.pengemudi.toLowerCase().includes(query);
    const golMatch = !gol || r.golongan.includes(gol);
    const stMatch = !st || r.status.toLowerCase() === st.toLowerCase();
    return textMatch && golMatch && stMatch;
  });

  renderTable(filtered);
}

function exportExcel() {
  const headers = ['No. Tiket', 'Tanggal', 'Waktu', 'Pengemudi', 'Petugas', 'Golongan', 'Panjang', 'Tinggi', 'Berat', 'Status'];
  const rows = items.map(r => [
    r.nomor, r.date, r.time, r.pengemudi, r.petugas, r.golongan, r.p, r.t, r.berat, r.status
  ]);
  const csv = [headers.join(','), ...rows.map(e => e.join(','))].join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `riwayat_tiket_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
}

function updateClock() {
  const now = new Date();
  const time = now.toLocaleTimeString('en-GB', { timeZone: 'Asia/Jakarta', hour12: false });
  const el = document.getElementById('riwayat-clock');
  if (el) el.textContent = `${time} WIB`;
}

async function fetchFromApi() {
  try {
    const res = await fetch(`${API_BASE_URL}/api/tiket`);
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data) && data.length > 0) {
        // Gabungkan tiket baru di depan
        const mapped = data.map((t, idx) => ({
          nomor: t.nomor || `FQ-2N261117-W${String(idx + 10).padStart(3, '0')}`,
          date: '17 Nov 2026',
          time: new Date(t.waktu || Date.now()).toLocaleTimeString('en-GB', { hour12: false }) + ' WIB',
          pengemudi: t.pengemudi || 'Pengemudi',
          initial: (t.pengemudi || 'P').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase(),
          petugas: 'Rian Setiawan',
          golongan: t.golongan ? `Gol ${t.golongan}` : 'Gol V A',
          p: t.P ? `${t.P}m` : '7.2m',
          t: t.T ? `${t.T}m` : '3.1m',
          berat: `${formatNumber(Math.round(t.berat || t.berat_gram || 8450))} kg`,
          status: (t.status || '').toLowerCase().includes('over') ? 'Overdimension' : 'Normal'
        }));
        items = [...mapped, ...DEFAULT_ROWS];
      }
    }
  } catch (err) {
    console.warn('[riwayat] Memakai data default:', err);
  }
  filterData();
  renderPagination(items.length, 1);
}

function init() {
  startClock();
  updateClock();
  setInterval(updateClock, 1000);

  fetchFromApi();

  document.getElementById('search-input')?.addEventListener('input', filterData);
  document.getElementById('filter-golongan')?.addEventListener('change', filterData);
  document.getElementById('filter-status')?.addEventListener('change', filterData);
  document.getElementById('btn-reset-filter')?.addEventListener('click', () => {
    const s = document.getElementById('search-input');
    const g = document.getElementById('filter-golongan');
    const st = document.getElementById('filter-status');
    if (s) s.value = '';
    if (g) g.value = '';
    if (st) st.value = '';
    filterData();
  });

  document.getElementById('btn-export')?.addEventListener('click', exportExcel);
}

document.addEventListener('DOMContentLoaded', init);
