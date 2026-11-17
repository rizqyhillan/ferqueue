/**
 * monitoring.js — FERQUEUE Web Monitoring
 * Monitoring logic: Polling berat, kamera visual, dimensi, penerbitan tiket & pembukaan portal.
 */

import { startClock, formatNumber, toast, API_BASE_URL } from './utils.js';
import { CATEGORIES, categoryInfo } from './tickets.js';
import './live_detection.js';

const $ = s => document.querySelector(s);

// State monitoring (default initial state persis sesuai Screenshot 2)
const state = {
  weight: 8450,          // Satuan kg
  vehicleType: 'Truk Sedang Boks (Golongan V-A)',
  panjang: 720,          // cm
  tinggi: 320,           // cm
  golongan: 'GOL. V-A',
  golonganDesc: 'Kendaraan Barang Sedang',
  status: 'Normal / Lolos',
  tarif: 642000,
  sensorLive: true,
};

function updateClocks() {
  const now = new Date();
  const timeStr = now.toLocaleTimeString('en-GB', { timeZone: 'Asia/Jakarta', hour12: false });
  const monClock = document.getElementById('mon-clock');
  if (monClock) monClock.textContent = `${timeStr} WIB`;

  const utcMs = String(now.getMilliseconds()).padStart(3, '0');
  const utcHours = String(now.getUTCHours()).padStart(2, '0');
  const utcMins = String(now.getUTCMinutes()).padStart(2, '0');
  const utcSecs = String(now.getUTCSeconds()).padStart(2, '0');
  const camTime = document.getElementById('cam-timestamp');
  if (camTime) camTime.textContent = `${utcHours}:${utcMins}:${utcSecs}.${utcMs} UTC`;
}

function renderUI() {
  // Update berat
  const weightEl = document.getElementById('weight-display');
  if (weightEl) weightEl.textContent = formatNumber(Math.round(state.weight));

  const weightBar = document.getElementById('weight-bar');
  if (weightBar) {
    const pct = Math.min(100, Math.max(5, (state.weight / 25000) * 100));
    weightBar.style.width = `${pct}%`;
  }

  // Update dimensi di kamera & panel
  const pM = (state.panjang / 100).toFixed(2);
  const tM = (state.tinggi / 100).toFixed(2);

  const overlayDims = document.getElementById('cam-overlay-dims');
  if (overlayDims) overlayDims.textContent = `◄ P: ${pM}m | T: ${tM}m ►`;

  const detVehicle = document.getElementById('det-vehicle-type');
  if (detVehicle) detVehicle.textContent = state.vehicleType;

  const detP = document.getElementById('det-p');
  if (detP) detP.textContent = state.panjang;

  const detT = document.getElementById('det-t');
  if (detT) detT.textContent = state.tinggi;

  const dimsSummary = document.getElementById('class-dims-summary');
  if (dimsSummary) dimsSummary.textContent = `P: ${pM} m · T: ${tM} m`;

  const classDisplay = document.getElementById('class-display');
  if (classDisplay) classDisplay.textContent = state.golongan;

  const classDesc = document.getElementById('class-desc');
  if (classDesc) classDesc.textContent = state.golonganDesc;

  // Status Lolos / Overdimension
  const isOver = state.status.toLowerCase().includes('over');
  const statusPill = document.getElementById('det-status-pill');
  if (statusPill) {
    statusPill.className = isOver ? 'mon-status-pill is-danger' : 'mon-status-pill';
    statusPill.innerHTML = isOver
      ? `<span>⚠ Overdimension</span>`
      : `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="13" height="13"><polyline points="20 6 9 17 4 12"/></svg><span>Normal / Lolos</span>`;
  }

  const limitStatus = document.getElementById('class-limit-status');
  if (limitStatus) {
    limitStatus.style.color = isOver ? 'var(--clr-danger)' : 'var(--clr-success-text)';
    limitStatus.innerHTML = isOver
      ? `<span>Melebihi Limit</span>`
      : `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="13" height="13"><circle cx="12" cy="12" r="10"/><polyline points="16 10 11 15 8 12"/></svg><span>Lolos Limit</span>`;
  }

  // Tarif
  const tariffEl = document.getElementById('tariff-display');
  if (tariffEl) tariffEl.textContent = `Rp ${formatNumber(state.tarif)}`;

  // Update LLM Advisory box
  const llmText = document.getElementById('llm-advisory-text');
  const llmCard = document.getElementById('mon-llm-card');
  if (llmText && llmCard) {
    if (isOver) {
      llmCard.style.borderColor = '#FCA5A5';
      llmCard.style.background = '#FEF2F2';
      llmText.innerHTML = `<strong>PERINGATAN ODOL (PM 59/2022):</strong> Terdeteksi pelanggaran dimensi/muatan melebihi batas toleransi. <em>Rekomendasi Tindakan:</em> Tahan palang (SERVO_LOCK), arahkan pengemudi ke U-Turn bay, dan terbitkan Berita Acara penolakan.`;
    } else {
      llmCard.style.borderColor = '#E9D5FF';
      llmCard.style.background = '#FAF5FF';
      llmText.innerHTML = `<strong>Analisis Regulasi (PM 59/2022):</strong> Dimensi optik dan tonase berada dalam batas toleransi legal. Palang portal aman dibuka untuk penerbitan tiket.`;
    }
  }
}

// Polling data timbangan dari backend IoT
async function pollSensor() {
  try {
    const res = await fetch(`${API_BASE_URL}/api/berat`);
    if (res.ok) {
      const data = await res.json();
      if (data.berat_kg !== undefined && data.berat_kg > 0) {
        state.weight = data.berat_kg;
      } else if (data.berat !== undefined && data.berat > 0) {
        state.weight = Math.round(data.berat / 1000);
      }
    }

    const stRes = await fetch(`${API_BASE_URL}/api/status-kendaraan`);
    if (stRes.ok) {
      const stData = await stRes.json();
      if (stData.P > 0) state.panjang = Math.round(stData.P * 100);
      if (stData.T > 0) state.tinggi = Math.round(stData.T * 100);
      if (stData.golongan && stData.golongan !== '-') state.golongan = `GOL. ${stData.golongan}`;
      if (stData.status) state.status = stData.status;
    }
  } catch (err) {
    // Abaikan error polling agar tidak mengganggu UI demo
  }
  renderUI();
}

// Generator Barcode Visual Struk
function generateBarcodeLines(containerEl) {
  if (!containerEl) return;
  containerEl.innerHTML = '';
  const pattern = [2, 1, 3, 1, 4, 1, 2, 2, 1, 3, 2, 1, 4, 2, 1, 3, 1, 2, 4, 1, 2, 3, 1, 4, 1, 2, 3, 2, 1, 4, 2, 1, 3];
  pattern.forEach((w) => {
    const bar = document.createElement('span');
    bar.style.width = `${w}px`;
    containerEl.appendChild(bar);
  });
}

// Buka Modal Pop-up Tiket (Mendukung Tiket Normal & Tiket Pelanggaran ODOL)
function showTicketModal(ticket) {
  const modal = document.getElementById('ticket-modal');
  if (!modal) return;

  const ticketNo = ticket.nomor || `FQ-${new Date().toISOString().slice(2, 10).replace(/-/g, '')}-${String(Math.floor(Math.random() * 900) + 100)}`;
  const driverName = ticket.pengemudi || 'Budi Santoso';
  const vehicleClass = ticket.golongan || state.golongan;
  const statusVal = ticket.status || state.status;
  const isOver = statusVal.toLowerCase().includes('over') || statusVal.toLowerCase().includes('langgar');

  // Format tanggal & waktu WIB
  const now = new Date();
  const options = { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' };
  const timeStr = `${now.toLocaleDateString('id-ID', options)} WIB`;

  // Isi data modal
  const elNo = document.getElementById('modal-ticket-no');
  if (elNo) elNo.textContent = ticketNo;

  const elTime = document.getElementById('modal-ticket-time');
  if (elTime) elTime.textContent = timeStr;

  const elDriver = document.getElementById('modal-driver-name');
  if (elDriver) elDriver.textContent = driverName;

  const elClass = document.getElementById('modal-vehicle-class');
  if (elClass) elClass.textContent = vehicleClass;

  const pM = (state.panjang / 100).toFixed(2);
  const tM = (state.tinggi / 100).toFixed(2);
  const elDims = document.getElementById('modal-dims');
  if (elDims) elDims.textContent = `${pM} m × ${tM} m`;

  const elWeight = document.getElementById('modal-weight');
  const weightKg = formatNumber(Math.round(ticket.berat || state.weight));
  if (elWeight) elWeight.textContent = `${weightKg} kg`;

  const elStatus = document.getElementById('modal-status');
  if (elStatus) {
    elStatus.textContent = isOver ? 'OVERDIMENSION (PELANGGARAN)' : 'Normal / Lolos Limit';
    elStatus.className = isOver ? 'ticket-receipt__val ticket-receipt__val--status is-danger' : 'ticket-receipt__val ticket-receipt__val--status';
  }

  // Elemen Dinamis Tiket Normal vs Pelanggaran
  const modalTitle = document.getElementById('modal-ticket-title');
  const receiptLogo = document.getElementById('modal-receipt-logo');
  const badgeEl = document.getElementById('modal-ticket-badge');
  const badgeText = document.getElementById('modal-badge-text');
  const totalBox = document.getElementById('modal-total-box');
  const violationBox = document.getElementById('modal-violation-box');
  const violationDesc = document.getElementById('modal-violation-desc');
  const printBtn = document.getElementById('btn-print-ticket-modal');
  const printText = document.getElementById('btn-print-text');
  const footerNote = document.getElementById('modal-footer-note');

  if (isOver) {
    // Mode Pelanggaran: Tiket Merah Inspeksi Khusus
    if (modalTitle) modalTitle.textContent = 'TIKET PELANGGARAN & DISPOSISI INSPEKSI';
    if (receiptLogo) receiptLogo.style.background = 'var(--clr-danger)';
    if (badgeEl) badgeEl.className = 'ticket-receipt__badge is-danger';
    if (badgeText) badgeText.textContent = '⚠ WAJIB INSPEKSI FISIK (DITAHAN)';
    if (totalBox) totalBox.style.display = 'none';
    if (violationBox) violationBox.style.display = 'block';
    if (violationDesc) {
      violationDesc.innerHTML = `Kendaraan terdeteksi <strong>Over Dimension / Over Load (ODOL)</strong>: P: ${pM}m | T: ${tM}m | Berat: ${weightKg}kg melebihi batas legal PM 59/2022.<br><br><strong>Instruksi Petugas Lapangan:</strong> Palang gerbang utama DITUTUP. Pengemudi wajib membawa lembar disposisi ini ke <strong>Pos Jalur Inspeksi Fisik (U-Turn Bay) Gate #03</strong> untuk verifikasi manual pita ukur oleh petugas pengawas.`;
    }
    if (printBtn) printBtn.className = 'btn btn--danger';
    if (printText) printText.textContent = 'Cetak Tiket Pelanggaran';
    if (footerNote) footerNote.textContent = 'Lembar bukti pelanggaran resmi — Wajib diserahkan ke Petugas Pos Inspeksi Fisik.';
  } else {
    // Mode Normal: Tiket Hijau Manifest Resmi
    if (modalTitle) modalTitle.textContent = 'TIKET MANIFEST GERBANG MASUK';
    if (receiptLogo) receiptLogo.style.background = 'var(--clr-navy)';
    if (badgeEl) badgeEl.className = 'ticket-receipt__badge';
    if (badgeText) badgeText.textContent = 'TIKET RESMI BERLAKU';
    if (totalBox) totalBox.style.display = 'flex';
    if (violationBox) violationBox.style.display = 'none';
    if (printBtn) printBtn.className = 'btn btn--primary';
    if (printText) printText.textContent = 'Cetak Tiket';
    if (footerNote) footerNote.textContent = 'Simpan tiket ini untuk verifikasi kartu lambung kapal penyeberangan.';
  }

  const elTariff = document.getElementById('modal-total-tariff');
  if (elTariff) elTariff.textContent = `Rp ${formatNumber(state.tarif)}`;

  const elBarcodeNo = document.getElementById('modal-barcode-no');
  if (elBarcodeNo) elBarcodeNo.textContent = `*${ticketNo}*`;

  // Render garis barcode
  const barcodeBox = document.getElementById('modal-barcode-svg');
  generateBarcodeLines(barcodeBox);

  // Tampilkan Pop-up
  modal.classList.add('is-open');
  modal.setAttribute('aria-hidden', 'false');
}

// Tutup Modal Pop-up Tiket
function closeTicketModal() {
  const modal = document.getElementById('ticket-modal');
  if (modal) {
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
  }
}

// Kembali ke Awal (Standby untuk Kendaraan Berikutnya)
function resetToInitialState() {
  closeTicketModal();

  // Reset input form
  const driverInput = document.getElementById('driver-name');
  if (driverInput) {
    driverInput.value = '';
    driverInput.placeholder = 'Nama Pengemudi Berikutnya...';
    driverInput.focus();
  }

  // Nol-kan timbangan tare di latar belakang
  fetch(`${API_BASE_URL}/api/tare`, { method: 'POST' }).catch(() => {});

  toast('Sistem kembali ke posisi awal. Siap untuk kendaraan berikutnya.', 'info');
}

// Penerbitan Tiket & Buka Barrier (Instan & Responsif)
async function issueTicket(e) {
  if (e) e.preventDefault();

  const driverInput = document.getElementById('driver-name');
  const driver = driverInput ? driverInput.value.trim() || 'Budi Santoso' : 'Budi Santoso';

  const isOver = state.status.toLowerCase().includes('over') || state.status.toLowerCase().includes('langgar');

  const btn = document.getElementById('btn-issue-ticket');
  if (btn) btn.disabled = true;

  let ticketData = null;

  try {
    const payload = {
      pengemudi: driver,
      golongan: state.golongan,
      berat: state.weight,
      status: state.status,
    };

    const res = await fetch(`${API_BASE_URL}/api/tiket`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (res.ok) {
      const json = await res.json();
      ticketData = json.tiket;

      if (isOver) {
        // JIKA PELANGGARAN: Jangan buka palang! Beri peringatan
        toast('Kendaraan terindikasi ODOL! Tiket pelanggaran diterbitkan untuk inspeksi fisik.', 'warning');
      } else {
        // JIKA NORMAL: Buka palang gerbang
        toast('Tiket resmi diterbitkan! Barrier gerbang dibuka.', 'success');
        fetch(`${API_BASE_URL}/api/buka`, { method: 'POST' }).catch(() => {});
      }
    } else {
      toast('Tiket diterbitkan (mode lokal).', 'info');
    }
  } catch (err) {
    toast('Tiket diterbitkan (mode offline).', 'info');
  } finally {
    if (btn) btn.disabled = false;

    // Tampilkan modal tiket pop-up seketika tanpa jeda
    showTicketModal(ticketData || {
      nomor: `FQ-${new Date().toISOString().slice(2, 10).replace(/-/g, '')}-${String(Math.floor(Math.random() * 900) + 100)}`,
      pengemudi: driver,
      golongan: state.golongan,
      berat: state.weight,
      status: state.status,
      waktu: new Date().toISOString(),
    });
  }
}

function init() {
  startClock();
  updateClocks();
  setInterval(updateClocks, 1000);

  renderUI();
  pollSensor();
  setInterval(pollSensor, 3000);

  const form = document.getElementById('ticket-form');
  if (form) form.addEventListener('submit', issueTicket);

  // Trigger Enter pada input driver untuk langsung memunculkan pop-up tiket
  const driverInput = document.getElementById('driver-name');
  if (driverInput) {
    driverInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        issueTicket(e);
      }
    });
  }

  // Modal event listeners
  document.getElementById('btn-close-ticket-modal')?.addEventListener('click', () => {
    resetToInitialState();
  });

  document.getElementById('btn-next-vehicle-modal')?.addEventListener('click', () => {
    resetToInitialState();
  });

  const modal = document.getElementById('ticket-modal');
  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) resetToInitialState();
    });
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modal?.classList.contains('is-open')) {
      resetToInitialState();
    }
  });

  document.getElementById('btn-print-ticket-modal')?.addEventListener('click', () => {
    window.print();
  });

  document.getElementById('btn-copy-ticket-no')?.addEventListener('click', () => {
    const ticketNo = document.getElementById('modal-ticket-no')?.textContent || '';
    if (ticketNo && navigator.clipboard) {
      navigator.clipboard.writeText(ticketNo).then(() => {
        toast(`Nomor tiket ${ticketNo} berhasil disalin!`, 'info');
      }).catch(() => {
        toast(`Nomor tiket: ${ticketNo}`, 'info');
      });
    }
  });

  // Reload cam button
  document.getElementById('btn-reload-cam')?.addEventListener('click', () => {
    const img = document.getElementById('camera-feed');
    if (img) {
      img.src = `/static/assets/camera-demo.svg?t=${Date.now()}`;
      toast('Kamera kendaraan berhasil di-refresh', 'info');
    }
  });

  // Upload foto button
  const uploadBtn = document.getElementById('btn-upload-foto');
  const fileInput = document.getElementById('file-upload');
  if (uploadBtn && fileInput) {
    uploadBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => {
      const file = e.target.files?.[0];
      if (file) {
        const reader = new FileReader();
        reader.onload = (event) => {
          const img = document.getElementById('camera-feed');
          if (img) img.src = event.target.result;
          toast('Foto kendaraan berhasil diunggah', 'success');
        };
        reader.readAsDataURL(file);
      }
    });
  }
}

document.addEventListener('DOMContentLoaded', init);
