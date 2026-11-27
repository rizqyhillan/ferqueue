/**
 * dashboard.js — FERQUEUE Web Monitoring
 * Dashboard logic: Real-time stats and Chart.js hourly density.
 */

import {
  startClock,
  formatNumber,
  formatDateId,
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

function updateOperationDate() {
  const dateEl = document.getElementById('dash-op-date');
  if (dateEl) dateEl.textContent = formatDateId(new Date());
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
}

async function refreshDashboard() {
  updateOperationDate();
  try {
    const statsRes = await fetch(`${API_BASE_URL}/api/stats`, { cache: 'no-store' });
    if (statsRes.ok) {
      const statsData = await statsRes.json();
      updateStatsUI(statsData);
    }
  } catch (err) {
    console.warn('[dashboard] Gagal memuat data dashboard:', err);
  }
}

function init() {
  startClock();
  updateOperationDate();
  initDensityChart();
  refreshDashboard();
  setInterval(refreshDashboard, 10000);
}

document.addEventListener('DOMContentLoaded', init);
