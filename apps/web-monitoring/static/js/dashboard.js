/**
 * dashboard.js — FERQUEUE Web Monitoring
 * Dashboard logic: Real-time stats, Chart.js hourly density, per-category averages,
 * recent activity table, and shift CSV report download.
 */

import {
  startClock,
  formatNumber,
  formatDateId,
  getCurrentShiftWib,
  escapeHtml,
  downloadCsv,
  toast,
  API_BASE_URL,
} from './utils.js';

let chartInstance = null;

const HOURS_LABELS = [
  '00:00', '02:00', '04:00', '06:00', '08:00', '10:00',
  '12:00', '14:00', '16:00', '18:00', '20:00', '22:00',
];

function getBarColors(data) {
  const maxVal = Math.max(...data, 0);
  if (maxVal === 0) return data.map(() => '#CBD5E1');
  return data.map(val => {
    const ratio = val / maxVal;
    if (val === 0) return '#E2E8F0';
    if (ratio >= 0.75) return '#0C2744'; // Padat (Navy)
    if (ratio >= 0.45) return '#0A789B'; // Sedang (Teal)
    return '#38BDF8';                    // Lancar (Cyan)
  });
}

// Chart.js Plugin dinamis untuk menampilkan badge pada 1-2 jam puncak aktual
const peakBadgesPlugin = {
  id: 'peakBadges',
  afterDatasetsDraw(chart) {
    const { ctx } = chart;
    const dataset = chart.data?.datasets?.[0]?.data || [];
    const maxVal = Math.max(...dataset, 0);
    if (maxVal <= 0) return;

    const meta = chart.getDatasetMeta(0);
    const ranked = dataset
      .map((val, index) => ({ index, val }))
      .filter(item => item.val > 0)
      .sort((a, b) => b.val - a.val);

    // Ambil maks 2 puncak yang tidak bersebelahan
    const peaks = [];
    for (const item of ranked) {
      if (peaks.every(p => Math.abs(p.index - item.index) > 1)) {
        peaks.push(item);
      }
      if (peaks.length >= 2) break;
    }

    ctx.save();
    peaks.forEach(({ index, val }) => {
      const bar = meta.data[index];
      if (!bar) return;

      const label = String(val);
      const badgeW = Math.max(38, ctx.measureText(label).width + 26);
      const x = bar.x;
      const y = Math.max(16, bar.y - 14);

      ctx.fillStyle = '#0C2744';
      ctx.beginPath();
      if (typeof ctx.roundRect === 'function') {
        ctx.roundRect(x - badgeW / 2, y - 10, badgeW, 20, 10);
      } else {
        ctx.rect(x - badgeW / 2, y - 10, badgeW, 20);
      }
      ctx.fill();

      ctx.fillStyle = '#22C55E';
      ctx.beginPath();
      ctx.arc(x - badgeW / 2 + 10, y, 3, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = '#FFFFFF';
      ctx.font = 'bold 11px Inter, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(label, x + 4, y);

      ctx.fillStyle = '#0C2744';
      ctx.beginPath();
      ctx.moveTo(x - 4, y + 10);
      ctx.lineTo(x + 4, y + 10);
      ctx.lineTo(x, y + 14);
      ctx.closePath();
      ctx.fill();
    });
    ctx.restore();
  },
};

function initDensityChart(initialData = new Array(12).fill(0)) {
  const canvas = document.getElementById('density-chart');
  if (!canvas || typeof Chart === 'undefined') return;

  const ctx = canvas.getContext('2d');
  const maxVal = Math.max(...initialData, 0);

  chartInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: HOURS_LABELS,
      datasets: [{
        label: 'Kendaraan',
        data: initialData,
        backgroundColor: getBarColors(initialData),
        borderRadius: 4,
        borderSkipped: false,
        barPercentage: 0.65,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#0C2744',
          titleFont: { family: 'Inter', size: 12 },
          bodyFont: { family: 'Inter', size: 12 },
          padding: 10,
          cornerRadius: 6,
          callbacks: {
            label: (context) => ` Jumlah kendaraan: ${context.parsed.y} unit`,
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: {
            font: { family: 'Inter', size: 11, weight: '600' },
            color: '#64748B',
          },
        },
        y: {
          beginAtZero: true,
          suggestedMax: Math.max(5, Math.ceil(maxVal * 1.3)),
          display: false,
          grid: { display: false },
        },
      },
    },
    plugins: [peakBadgesPlugin],
  });
}

function updateDensityChart(series) {
  const values = Array.isArray(series) && series.length === 12
    ? series.map(v => Number(v) || 0)
    : new Array(12).fill(0);

  if (!chartInstance) {
    initDensityChart(values);
    return;
  }

  const maxVal = Math.max(...values, 0);
  chartInstance.data.datasets[0].data = values;
  chartInstance.data.datasets[0].backgroundColor = getBarColors(values);
  chartInstance.options.scales.y.suggestedMax = Math.max(5, Math.ceil(maxVal * 1.3));
  chartInstance.update('none');
}

function formatCm(val) {
  if (val === null || val === undefined || !Number.isFinite(Number(val)) || Number(val) <= 0) return '—';
  return `${Number(val).toFixed(1).replace('.', ',')} cm`;
}

function formatGram(val) {
  if (val === null || val === undefined || !Number.isFinite(Number(val))) return '—';
  return `${Number(val).toFixed(1).replace('.', ',')} g`;
}

function updateDateAndShift() {
  const now = new Date();
  const dateEl = document.getElementById('dash-op-date');
  const shiftEl = document.getElementById('dash-op-shift');
  if (dateEl) dateEl.textContent = formatDateId(now);
  if (shiftEl) shiftEl.textContent = getCurrentShiftWib(now);
}

function updateStatsUI(data) {
  const total = Number(data.total_kendaraan || 0);
  const truk = Number(data.total_truk || 0);
  const bus = Number(data.total_bus || 0);
  const mobil = Number(data.total_mobil || 0);
  const overweight = Number(data.total_overweight || 0);

  const setText = (id, text) => {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  };

  setText('stat-total', formatNumber(total));
  setText('stat-truk', formatNumber(truk));
  setText('stat-bus', formatNumber(bus));
  setText('stat-mobil', formatNumber(mobil));

  const pct = (part) => (total > 0 ? `${Math.round((part / total) * 100)}% dari total` : '0% dari total');
  setText('stat-truk-pct', pct(truk));
  setText('stat-bus-pct', pct(bus));
  setText('stat-mobil-pct', pct(mobil));

  const gateWrap = document.getElementById('stat-gate-wrap');
  const gateStatus = document.getElementById('stat-gate-status');
  if (gateWrap && gateStatus) {
    if (overweight > 0) {
      gateWrap.classList.remove('is-green');
      gateWrap.classList.add('is-danger');
      gateStatus.textContent = `${formatNumber(overweight)} Overweight tercatat`;
    } else {
      gateWrap.classList.add('is-green');
      gateWrap.classList.remove('is-danger');
      gateStatus.textContent = total > 0 ? 'Semua Kendaraan Normal' : 'Gerbang Normal';
    }
  }

  // Update chart per 2 jam
  let series2h = data.density_2h;
  if (!Array.isArray(series2h) || series2h.length !== 12) {
    const dt = data.density_truk || [];
    const db = data.density_bus || [];
    const dl = data.density_lainnya || [];
    series2h = Array.from({ length: 12 }, (_, idx) => {
      const h = idx * 2;
      return (
        (dt[h] || 0) + (db[h] || 0) + (dl[h] || 0) +
        (dt[h + 1] || 0) + (db[h + 1] || 0) + (dl[h + 1] || 0)
      );
    });
  }
  updateDensityChart(series2h);

  const avgThr = Number(data.avg_throughput || 0).toFixed(1).replace('.', ',');
  const curThr = Number(data.current_hour_throughput || 0);
  setText('dash-avg-throughput', `${avgThr} unit/jam`);
  setText('dash-cur-throughput', `${formatNumber(curThr)} unit`);

  const nowStr = new Date().toLocaleTimeString('en-GB', { timeZone: 'Asia/Jakarta', hour12: false });
  setText('dash-last-updated', `Terakhir diperbarui ${nowStr} WIB`);

  // Update statistik rata-rata per kategori
  const rata = data.rata_rata || {};
  for (const key of ['truk', 'bus', 'mobil']) {
    const bucket = rata[key];
    if (bucket && bucket.count > 0) {
      setText(`avg-${key}-p`, formatCm(bucket.panjang_cm));
      setText(`avg-${key}-t`, formatCm(bucket.tinggi_cm));
      setText(`avg-${key}-w`, formatGram(bucket.berat_gram));
    } else {
      setText(`avg-${key}-p`, '—');
      setText(`avg-${key}-t`, '—');
      setText(`avg-${key}-w`, '—');
    }
  }
}

function formatActivityTime(rawTime) {
  if (!rawTime) return '—';
  const dt = new Date(typeof rawTime === 'string' ? rawTime.replace(' ', 'T') : rawTime);
  if (Number.isNaN(dt.getTime())) return String(rawTime);
  const hhmm = dt.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false });
  return `${hhmm} WIB`;
}

function renderActivities(rows) {
  const tbody = document.getElementById('activity-tbody');
  if (!tbody) return;

  if (!Array.isArray(rows) || rows.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" style="text-align: center; padding: 28px; color: #94A3B8;">
          Belum ada aktivitas pemeriksaan tercatat. Mulai pemeriksaan pada menu <a href="/monitoring" style="color: var(--clr-accent); font-weight: 600;">Monitoring</a>.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = rows.slice(0, 8).map(item => {
    const nomor = item.nomor_tiket || item.nomor || item.id_pemeriksaan || '—';
    const jenis = item.jenis_kendaraan || item.jenis || 'Kendaraan';
    const pVal = item.panjang_cm ?? item.P;
    const tVal = item.tinggi_cm ?? item.T;
    const berat = item.berat_aktual_gram ?? item.berat_gram ?? item.berat ?? 0;
    const waktu = formatActivityTime(item.waktu_pemeriksaan || item.waktu);
    const isOver = String(item.status || '').toLowerCase().includes('over');

    const pillClass = isOver
      ? 'activity-status-pill activity-status-pill--overweight'
      : (item.nomor_tiket ? 'activity-status-pill activity-status-pill--terbit' : 'activity-status-pill activity-status-pill--lolos');
    const pillLabel = isOver
      ? 'Overweight'
      : (item.nomor_tiket ? 'Tiket Terbit' : 'Normal');

    return `
      <tr>
        <td><span class="activity-unit">${escapeHtml(nomor)}</span></td>
        <td>${escapeHtml(jenis)}</td>
        <td class="activity-dim">${escapeHtml(formatCm(pVal))}</td>
        <td class="activity-dim">${escapeHtml(formatCm(tVal))}</td>
        <td class="activity-berat">${escapeHtml(formatGram(berat))}</td>
        <td class="activity-waktu">${escapeHtml(waktu)}</td>
        <td><span class="${pillClass}">${pillLabel}</span></td>
      </tr>
    `;
  }).join('');
}

async function refreshDashboard() {
  updateDateAndShift();
  try {
    const [statsRes, actRes] = await Promise.all([
      fetch(`${API_BASE_URL}/api/stats`, { cache: 'no-store' }),
      fetch(`${API_BASE_URL}/api/aktivitas`, { cache: 'no-store' }),
    ]);

    if (statsRes.ok) {
      const statsData = await statsRes.json();
      updateStatsUI(statsData);
    }

    if (actRes.ok) {
      const actData = await actRes.json();
      renderActivities(actData);
    }
  } catch (err) {
    console.warn('[dashboard] Gagal memuat data dashboard:', err);
  }
}

async function downloadShiftReport() {
  try {
    const res = await fetch(`${API_BASE_URL}/api/riwayat`, { cache: 'no-store' });
    if (!res.ok) throw new Error('Gagal mengambil data riwayat');
    const json = await res.json();
    const rows = Array.isArray(json?.data) ? json.data : [];

    if (rows.length === 0) {
      toast('Belum ada data pemeriksaan untuk diunduh.', 'info');
      return;
    }

    const headers = [
      'ID Pemeriksaan', 'No. Tiket', 'Waktu', 'Pengemudi', 'Jenis Kendaraan',
      'Golongan', 'Panjang (cm)', 'Tinggi (cm)', 'Berat Aktual (g)', 'Batas Maks (g)', 'Status',
    ];
    const csvRows = rows.map(r => [
      r.id_pemeriksaan || '',
      r.nomor_tiket || '-',
      r.waktu_pemeriksaan || r.waktu || '',
      r.nama_pengemudi || 'Pengemudi',
      r.jenis_kendaraan || '',
      r.golongan ? `Gol. ${r.golongan}` : '',
      r.panjang_cm ?? 0,
      r.tinggi_cm ?? 0,
      r.berat_aktual_gram ?? 0,
      r.batas_maksimum_gram ?? 0,
      r.status || 'Normal',
    ]);

    const today = new Date().toISOString().slice(0, 10);
    downloadCsv(`rekap_shift_ferqueue_${today}.csv`, headers, csvRows);
    toast(`Rekap laporan shift (${rows.length} data) berhasil diunduh.`, 'success');
  } catch (err) {
    toast('Gagal mengunduh rekap laporan shift.', 'warning');
  }
}

function init() {
  startClock();
  updateDateAndShift();
  initDensityChart();
  refreshDashboard();
  setInterval(refreshDashboard, 10000);

  document.getElementById('btn-download-shift-report')?.addEventListener('click', downloadShiftReport);
}

document.addEventListener('DOMContentLoaded', init);
