/**
 * dashboard.js — FERQUEUE Web Monitoring
 * Dashboard logic: Chart.js visualization, real-time metrics, auto-refresh.
 */

import { startClock, formatNumber, API_BASE_URL } from './utils.js';

let chartInstance = null;

// Mock data per 2 jam sesuai screenshot
const HOURS_LABELS = ['00:00', '02:00', '04:00', '06:00', '08:00', '10:00', '12:00', '14:00', '16:00', '18:00', '20:00', '22:00'];
const DENSITY_DATA = [45, 62, 110, 188, 142, 92, 118, 172, 134, 98, 72, 50];

// Warna bar berdasarkan kepadatan
function getBarColors(data) {
  return data.map(val => {
    if (val >= 140) return '#0C2744'; // Padat (Navy)
    if (val >= 90)  return '#0A789B'; // Sedang (Teal)
    if (val >= 70)  return '#38BDF8'; // Lancar (Cyan)
    return '#CBD5E1';                 // Lengang (Light Slate)
  });
}

// Chart.js Plugin untuk menampilkan badge nilai puncak (188 & 172)
const peakBadgesPlugin = {
  id: 'peakBadges',
  afterDatasetsDraw(chart) {
    const { ctx } = chart;
    const meta = chart.getDatasetMeta(0);

    const peaks = [
      { index: 3, label: '188' }, // 06:00
      { index: 7, label: '172' }, // 14:00
    ];

    ctx.save();
    peaks.forEach(({ index, label }) => {
      const bar = meta.data[index];
      if (!bar) return;

      const x = bar.x;
      const y = bar.y - 12;

      // Capsule background
      ctx.fillStyle = '#0C2744';
      ctx.beginPath();
      ctx.roundRect(x - 22, y - 10, 44, 20, 10);
      ctx.fill();

      // Green dot inside badge
      ctx.fillStyle = '#22C55E';
      ctx.beginPath();
      ctx.arc(x - 12, y, 3, 0, Math.PI * 2);
      ctx.fill();

      // Text
      ctx.fillStyle = '#FFFFFF';
      ctx.font = 'bold 11px Inter, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(label, x + 5, y);

      // Down arrow pointer
      ctx.fillStyle = '#0C2744';
      ctx.beginPath();
      ctx.moveTo(x - 4, y + 10);
      ctx.lineTo(x + 4, y + 10);
      ctx.lineTo(x, y + 14);
      ctx.closePath();
      ctx.fill();
    });
    ctx.restore();
  }
};

function initDensityChart() {
  const canvas = document.getElementById('density-chart');
  if (!canvas || typeof Chart === 'undefined') return;

  const ctx = canvas.getContext('2d');
  const barColors = getBarColors(DENSITY_DATA);

  chartInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: HOURS_LABELS,
      datasets: [{
        label: 'Kendaraan',
        data: DENSITY_DATA,
        backgroundColor: barColors,
        borderRadius: 4,
        borderSkipped: false,
        barPercentage: 0.65,
      }]
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
            label: (ctx) => ` Throughput: ${ctx.parsed.y} kendaraan/jam`
          }
        }
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: {
            font: { family: 'Inter', size: 11, weight: '600' },
            color: '#64748B'
          }
        },
        y: {
          beginAtZero: true,
          max: 220,
          display: false,
          grid: { display: false }
        }
      }
    },
    plugins: [peakBadgesPlugin]
  });
}

async function fetchStats() {
  try {
    const res = await fetch(`${API_BASE_URL}/api/stats`);
    if (res.ok) {
      const data = await res.json();
      if (data.total_kendaraan) {
        const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = formatNumber(val); };
        setVal('stat-total', data.total_kendaraan);
        setVal('stat-truk',  data.total_truk);
        setVal('stat-bus',   data.total_bus);
        setVal('stat-mobil', data.total_mobil);
      }
    }
  } catch (err) {
    console.warn('[dashboard] Gagal memuat stats:', err);
  }
}

function init() {
  startClock();
  initDensityChart();
  fetchStats();
  setInterval(fetchStats, 30000);
}

document.addEventListener('DOMContentLoaded', init);
