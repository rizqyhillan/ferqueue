/**
 * monitoring.js — FERQUEUE Web Monitoring
 * Monitoring logic: Polling berat, kamera visual, dimensi, penerbitan tiket & pembukaan portal.
 */

import { startClock, formatNumber, formatDateId, toast, API_BASE_URL } from './utils.js';
import './live_detection.js';

const $ = s => document.querySelector(s);

const DEFAULT_DEMO_PANJANG = 720; // cm
const DEFAULT_DEMO_TINGGI = 320;  // cm

const GOLONGAN_META = {
  A: { code: 'GOL. A', desc: 'Kendaraan Penumpang (Mobil)', limit: 55, tarif: 60000, jenis: 'mobil' },
  B: { code: 'GOL. B', desc: 'Kendaraan Angkutan Penumpang (Bus)', limit: 85, tarif: 120000, jenis: 'bus' },
  C: { code: 'GOL. C', desc: 'Kendaraan Angkutan Barang (Truk)', limit: 100, tarif: 250000, jenis: 'truk' },
};

// State monitoring (satuan berat: gram sesuai load cell prototipe & aturan PM 103/2017)
const state = {
  weight: 0.0,           // Satuan gram
  weightLimit: 55.0,     // Batas maksimum golongan (gram)
  vehicleKind: 'mobil',  // 'mobil' | 'bus' | 'truk'
  vehicleType: 'Mobil (Golongan A)',
  panjang: DEFAULT_DEMO_PANJANG, // cm
  tinggi: DEFAULT_DEMO_TINGGI,   // cm
  cameraDimensionsActive: false,
  golonganCode: 'A',
  golongan: 'GOL. A',
  golonganDesc: 'Kendaraan Penumpang (Mobil)',
  status: 'Normal',
  gerbang: 'tutup',
  tarif: 60000,
  sensorLive: false,
  stream: null,
  imageUrl: null,
  cameraMode: 'demo',    // 'demo' | 'live' | 'upload'
  cvActive: false,
  lastGolSyncAt: 0,
};

function formatGram(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return '0,0';
  return num.toFixed(1).replace('.', ',');
}

function applyGolonganMeta(code, { updateVehicleType = false } = {}) {
  const key = String(code || 'A').toUpperCase().replace(/^GOL\.?\s*/, '').trim();
  const meta = GOLONGAN_META[key] || GOLONGAN_META.A;
  state.golonganCode = key in GOLONGAN_META ? key : 'A';
  state.golongan = meta.code;
  state.golonganDesc = meta.desc;
  state.weightLimit = meta.limit;
  state.tarif = meta.tarif;
  state.vehicleKind = meta.jenis;
  if (updateVehicleType) {
    const label = meta.jenis.charAt(0).toUpperCase() + meta.jenis.slice(1);
    state.vehicleType = `${label} (Golongan ${state.golonganCode})`;
  }
  state.status = state.weight > state.weightLimit ? 'Overweight' : 'Normal';
}

function mapClassNameToGolongan(className) {
  const lower = String(className || '').toLowerCase();
  if (lower.includes('truk') || lower.includes('truck')) return 'C';
  if (lower.includes('bus')) return 'B';
  if (lower.includes('mobil') || lower.includes('car')) return 'A';
  return null;
}

function syncSensorStateToBackend() {
  const payload = {
    jenis: state.vehicleKind,
    golongan: state.golonganCode,
  };
  if (Number.isFinite(state.panjang)) payload.P = state.panjang;
  if (Number.isFinite(state.tinggi)) payload.T = state.tinggi;
  fetch(`${API_BASE_URL}/api/sensor/update`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).catch(() => {});
}

function formatDimCm(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return Number.isInteger(value) ? String(value) : value.toFixed(2).replace('.', ',');
}

function useCmDisplay(panjang, tinggi) {
  return state.cameraDimensionsActive || (Number.isFinite(panjang) && Number.isFinite(tinggi) && panjang < 100 && tinggi < 100);
}

function formatDimShort(value, preferCm) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return preferCm ? `${formatDimCm(value)} cm` : `${(value / 100).toFixed(2)}m`;
}

function formatDimSummary(panjang, tinggi) {
  if (!Number.isFinite(panjang) || !Number.isFinite(tinggi)) return 'P: — · T: —';
  if (useCmDisplay(panjang, tinggi)) {
    return `P: ${formatDimCm(panjang)} cm · T: ${formatDimCm(tinggi)} cm`;
  }
  return `P: ${(panjang / 100).toFixed(2)} m · T: ${(tinggi / 100).toFixed(2)} m`;
}

function formatDimPair(panjang, tinggi) {
  if (!Number.isFinite(panjang) || !Number.isFinite(tinggi)) return '— × —';
  if (useCmDisplay(panjang, tinggi)) {
    return `${formatDimCm(panjang)} cm × ${formatDimCm(tinggi)} cm`;
  }
  return `${(panjang / 100).toFixed(2)} m × ${(tinggi / 100).toFixed(2)} m`;
}

function updateClocks() {
  const now = new Date();
  const monDate = document.getElementById('mon-date');
  if (monDate) monDate.textContent = formatDateId(now);

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
  // Update berat (satuan gram)
  const weightEl = document.getElementById('weight-display');
  if (weightEl) weightEl.textContent = formatGram(state.weight);

  const weightLimitLabel = document.getElementById('weight-limit-label');
  if (weightLimitLabel) {
    weightLimitLabel.textContent = `Batas ${state.golongan}: ${state.weightLimit} g`;
  }

  const sensorLabel = document.getElementById('sensor-status-label');
  if (sensorLabel) {
    sensorLabel.textContent = state.sensorLive
      ? `Sensor Aktif · Gerbang: ${state.gerbang}`
      : 'Menunggu Sensor ESP32';
  }

  const isOver = state.status.toLowerCase().includes('over') || state.weight > state.weightLimit;

  const weightBar = document.getElementById('weight-bar');
  if (weightBar) {
    const pct = Math.min(100, Math.max(0, (state.weight / 150) * 100));
    weightBar.style.width = `${pct}%`;
    weightBar.classList.toggle('is-danger', isOver);
    weightBar.classList.toggle('is-warning', !isOver && state.weightLimit > 0 && state.weight >= state.weightLimit * 0.85);
  }

  // Update dimensi di kamera & panel
  const preferCm = useCmDisplay(state.panjang, state.tinggi);

  const demoLabel = document.getElementById('cam-demo-label');
  if (demoLabel) {
    demoLabel.textContent = `${state.vehicleKind.toUpperCase()} · PRATINJAU`;
  }

  const overlayDims = document.getElementById('cam-overlay-dims');
  if (overlayDims) overlayDims.textContent = `◄ P: ${formatDimShort(state.panjang, preferCm)} | T: ${formatDimShort(state.tinggi, preferCm)} ►`;

  const detVehicle = document.getElementById('det-vehicle-type');
  if (detVehicle) detVehicle.textContent = state.vehicleType;

  const detP = document.getElementById('det-p');
  if (detP) detP.textContent = formatDimCm(state.panjang);

  const detT = document.getElementById('det-t');
  if (detT) detT.textContent = formatDimCm(state.tinggi);

  const dimsSummary = document.getElementById('class-dims-summary');
  if (dimsSummary) dimsSummary.textContent = formatDimSummary(state.panjang, state.tinggi);

  const classDisplay = document.getElementById('class-display');
  if (classDisplay) classDisplay.textContent = state.golongan;

  const classDesc = document.getElementById('class-desc');
  if (classDesc) classDesc.textContent = state.golonganDesc;

  document.querySelectorAll('.mon-gol-btn').forEach(btn => {
    const isActive = btn.dataset.gol === state.golonganCode;
    btn.classList.toggle('is-active', isActive);
    btn.setAttribute('aria-pressed', String(isActive));
  });

  // Status Lolos / Overweight
  const statusPill = document.getElementById('det-status-pill');
  if (statusPill) {
    statusPill.className = isOver ? 'mon-status-pill is-danger' : 'mon-status-pill';
    statusPill.innerHTML = isOver
      ? `<span>⚠ Overweight</span>`
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
      const kelebihan = Math.max(0, state.weight - state.weightLimit).toFixed(1).replace('.', ',');
      llmCard.style.borderColor = '#FCA5A5';
      llmCard.style.background = '#FEF2F2';
      llmText.innerHTML = `<strong>PERINGATAN OVERWEIGHT (PM 103/2017):</strong> Berat melebihi batas ${state.golongan} (+${kelebihan} g). <em>Tindakan:</em> Tiket masuk tidak diterbitkan (Pasal 5), arahkan ke jalur keluar pelabuhan (Pasal 6) &amp; konsultasikan di Workspace AI.`;
    } else {
      llmCard.style.borderColor = '#E9D5FF';
      llmCard.style.background = '#FAF5FF';
      llmText.innerHTML = `<strong>Analisis Regulasi (PM 103/2017):</strong> Berat muatan (${formatGram(state.weight)} g / batas ${state.weightLimit} g) berada dalam batas toleransi legal. Palang portal aman dibuka untuk penerbitan tiket.`;
    }
  }
}

// Polling data timbangan dari backend IoT (satuan gram)
async function pollSensor() {
  try {
    const res = await fetch(`${API_BASE_URL}/api/berat`);
    if (res.ok) {
      const data = await res.json();
      const gram = Number(data.berat_gram ?? data.berat);
      if (Number.isFinite(gram)) {
        state.weight = gram;
      }
      if (data.gerbang) state.gerbang = data.gerbang;
      state.sensorLive = Boolean(data.waktu);
    }

    const stRes = await fetch(`${API_BASE_URL}/api/status-kendaraan`, { cache: 'no-store' });
    if (stRes.ok) {
      const stData = await stRes.json();
      if (!state.cameraDimensionsActive) {
        const pVal = Number(stData.P);
        const tVal = Number(stData.T);
        if (Number.isFinite(pVal) && pVal > 0) state.panjang = Number(pVal.toFixed(2));
        if (Number.isFinite(tVal) && tVal > 0) state.tinggi = Number(tVal.toFixed(2));
      }
      const recentlyChangedLocally = Date.now() - state.lastGolSyncAt < 4000;
      if (!recentlyChangedLocally && stData.golongan && stData.golongan !== '-') {
        applyGolonganMeta(stData.golongan, { updateVehicleType: !state.cvActive });
      }
      if (!recentlyChangedLocally && stData.status) {
        state.status = stData.status;
      } else {
        state.status = state.weight > state.weightLimit ? 'Overweight' : 'Normal';
      }
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
  const driverName = ticket.pengemudi || 'Pengemudi';
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

  const pModal = ticket.panjang_cm !== undefined && ticket.panjang_cm !== null && Number(ticket.panjang_cm) > 0
    ? Number(ticket.panjang_cm)
    : state.panjang;
  const tModal = ticket.tinggi_cm !== undefined && ticket.tinggi_cm !== null && Number(ticket.tinggi_cm) > 0
    ? Number(ticket.tinggi_cm)
    : state.tinggi;
  const preferCm = useCmDisplay(pModal, tModal);
  const elDims = document.getElementById('modal-dims');
  if (elDims) elDims.textContent = formatDimPair(pModal, tModal);

  const elWeight = document.getElementById('modal-weight');
  const weightGram = formatGram(ticket.berat_gram ?? ticket.berat ?? state.weight);
  if (elWeight) elWeight.textContent = `${weightGram} g`;

  const elStatus = document.getElementById('modal-status');
  if (elStatus) {
    elStatus.textContent = isOver ? 'OVERWEIGHT (PELANGGARAN)' : 'Normal / Lolos Limit';
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
      const limitGram = ticket.batas_berat_gram ?? state.weightLimit;
      violationDesc.innerHTML = `Kendaraan terdeteksi <strong>Overweight</strong>: P: ${formatDimShort(pModal, preferCm)} | T: ${formatDimShort(tModal, preferCm)} | Berat: ${weightGram} g melebihi batas ${vehicleClass} (${limitGram} g) sesuai PM 103/2017.<br><br><strong>Instruksi Petugas Lapangan:</strong> Tiket masuk tidak diterbitkan (Pasal 5). Gerbang dibuka khusus untuk <strong>Jalur Keluar / Putar Balik (Pasal 6)</strong> agar pengemudi menurunkan kelebihan muatan di luar pelabuhan.`;
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
  if (elTariff) elTariff.textContent = `Rp ${formatNumber(ticket.tarif ?? state.tarif)}`;

  const elBarcodeNo = document.getElementById('modal-barcode-no');
  if (elBarcodeNo) elBarcodeNo.textContent = `*${ticketNo}*`;

  // Render garis barcode
  const barcodeBox = document.getElementById('modal-barcode-svg');
  generateBarcodeLines(barcodeBox);

  // Tampilkan foto tangkapan kamera jika tersedia
  const photoWrap = document.getElementById('modal-photo-wrap');
  const photoImg = document.getElementById('modal-vehicle-photo');
  if (photoWrap && photoImg) {
    if (ticket.foto_url) {
      photoImg.src = ticket.foto_url;
      photoWrap.hidden = false;
    } else {
      photoImg.removeAttribute('src');
      photoWrap.hidden = true;
    }
  }

  // Tampilkan Pop-up & fokuskan tombol cetak agar Enter berikutnya langsung cetak & keluar
  modal.classList.add('is-open');
  modal.setAttribute('aria-hidden', 'false');
  const printBtnFocus = document.getElementById('btn-print-ticket-modal');
  if (printBtnFocus) {
    printBtnFocus.focus();
  } else if (document.activeElement instanceof HTMLElement) {
    document.activeElement.blur();
  }
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
    driverInput.placeholder = 'Masukkan nama pengemudi (opsional)...';
    setTimeout(() => {
      const modal = document.getElementById('ticket-modal');
      if (!modal?.classList.contains('is-open')) {
        driverInput.focus();
      }
    }, 80);
  }

  // Nol-kan tampilan & kirim perintah tare timbangan di latar belakang
  state.weight = 0.0;
  state.status = 'Normal';
  renderUI();
  fetch(`${API_BASE_URL}/api/tare`, { method: 'POST' }).catch(() => {});

  toast('Sistem kembali ke posisi awal. Siap untuk kendaraan berikutnya.', 'info');
}

let isIssuingTicket = false;
let isPrintingTicket = false;
let lastPrintFinishedAt = 0;

// Cetak tiket otomatis lalu keluar dari tampilan modal tiket
function printAndCloseTicketModal() {
  const modal = document.getElementById('ticket-modal');
  if (!modal || !modal.classList.contains('is-open') || isPrintingTicket) return;
  isPrintingTicket = true;

  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    isPrintingTicket = false;
    lastPrintFinishedAt = Date.now();
    window.removeEventListener('afterprint', onAfterPrint);
    setTimeout(() => {
      resetToInitialState();
    }, 60);
  };

  const onAfterPrint = () => finish();
  window.addEventListener('afterprint', onAfterPrint, { once: true });

  try {
    window.print();
  } catch {
    finish();
    return;
  }

  // Fallback jika browser tidak memicu event afterprint setelah dialog print selesai
  setTimeout(finish, 250);
}

// Ambil snapshot JPEG dari kamera live atau foto yang diunggah
function captureVehiclePhoto() {
  try {
    let sourceEl = null;
    let srcWidth = 0;
    let srcHeight = 0;

    if (state.cameraMode === 'live') {
      const video = document.getElementById('camera-video');
      if (video && video.videoWidth > 0 && video.videoHeight > 0) {
        sourceEl = video;
        srcWidth = video.videoWidth;
        srcHeight = video.videoHeight;
      }
    } else if (state.cameraMode === 'upload') {
      const img = document.getElementById('camera-feed');
      if (img && img.naturalWidth > 0 && img.naturalHeight > 0) {
        sourceEl = img;
        srcWidth = img.naturalWidth;
        srcHeight = img.naturalHeight;
      }
    }

    if (!sourceEl || !srcWidth || !srcHeight) return null;

    const scale = Math.min(1, 960 / Math.max(srcWidth, srcHeight));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(srcWidth * scale));
    canvas.height = Math.max(1, Math.round(srcHeight * scale));
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    ctx.drawImage(sourceEl, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.85);
  } catch {
    return null;
  }
}

// Penerbitan Tiket, Foto Kendaraan & Buka Barrier (Instan & Responsif)
async function issueTicket(e) {
  if (e) e.preventDefault();
  const modalEl = document.getElementById('ticket-modal');
  if (
    isIssuingTicket ||
    isPrintingTicket ||
    modalEl?.classList.contains('is-open') ||
    Date.now() - lastPrintFinishedAt < 800
  ) {
    return;
  }
  isIssuingTicket = true;

  const driverInput = document.getElementById('driver-name');
  const driver = driverInput ? driverInput.value.trim() || 'Pengemudi' : 'Pengemudi';

  const isOver = state.status.toLowerCase().includes('over') || state.weight > state.weightLimit;
  const capturedPhoto = captureVehiclePhoto();

  const btn = document.getElementById('btn-issue-ticket');
  if (btn) btn.disabled = true;

  let ticketData = null;

  try {
    const payload = {
      pengemudi: driver,
      jenis_kendaraan: state.vehicleKind,
      golongan: state.golonganCode,
      berat: state.weight,
      berat_gram: state.weight,
      panjang_cm: Number.isFinite(state.panjang) ? state.panjang : 0,
      tinggi_cm: Number.isFinite(state.tinggi) ? state.tinggi : 0,
      status: state.status,
      foto: capturedPhoto,
    };

    const res = await fetch(`${API_BASE_URL}/api/tiket`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (res.ok) {
      const json = await res.json();
      ticketData = json.tiket;
      const ticketOver = String(ticketData?.status || state.status).toLowerCase().includes('over');
      const photoNote = ticketData?.foto_url ? ' Foto tersimpan ke riwayat.' : '';

      if (ticketOver) {
        toast(`Kendaraan OVERWEIGHT! Tiket ditolak (Pasal 5), gerbang dibuka untuk jalur keluar (Pasal 6).${photoNote}`, 'warning');
      } else {
        toast(`Tiket resmi diterbitkan & gerbang dibuka.${photoNote}`, 'success');
      }
    } else {
      toast('Tiket diterbitkan (mode lokal).', 'info');
    }
  } catch (err) {
    toast('Tiket diterbitkan (mode offline).', 'info');
  } finally {
    isIssuingTicket = false;
    if (btn) btn.disabled = false;

    // Tampilkan modal tiket pop-up seketika tanpa jeda
    showTicketModal(ticketData || {
      nomor: `FQ-${new Date().toISOString().slice(2, 10).replace(/-/g, '')}-${String(Math.floor(Math.random() * 900) + 100)}`,
      pengemudi: driver,
      golongan: state.golongan,
      berat: state.weight,
      berat_gram: state.weight,
      status: isOver ? 'Overweight' : 'Normal',
      waktu: new Date().toISOString(),
      foto_url: capturedPhoto,
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

  // Tombol kontrol gerbang & tare load cell ESP32
  document.getElementById('btn-buka-gerbang')?.addEventListener('click', async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/buka`, { method: 'POST' });
      if (res.ok) toast('Perintah BUKA gerbang dikirim ke ESP32.', 'success');
      else toast('Gagal mengirim perintah buka gerbang.', 'warning');
    } catch {
      toast('Server tidak terjangkau untuk membuka gerbang.', 'warning');
    }
  });

  document.getElementById('btn-tare-sensor')?.addEventListener('click', async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/tare`, { method: 'POST' });
      if (res.ok) {
        state.weight = 0.0;
        renderUI();
        toast('Perintah TARE dikirim. Timbangan di-nolkan.', 'info');
      } else {
        toast('Gagal mengirim perintah tare.', 'warning');
      }
    } catch {
      toast('Server tidak terjangkau untuk tare sensor.', 'warning');
    }
  });

  // Pilih golongan manual (A / B / C)
  document.querySelectorAll('.mon-gol-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const gol = btn.dataset.gol;
      if (!gol) return;
      state.lastGolSyncAt = Date.now();
      applyGolonganMeta(gol, { updateVehicleType: true });
      renderUI();
      syncSensorStateToBackend();
      toast(`Golongan diubah ke ${state.golongan} (batas ${state.weightLimit} g).`, 'info');
    });
  });

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
    const isModalOpen = Boolean(modal?.classList.contains('is-open'));

    if (e.key === 'Escape' && isModalOpen) {
      e.preventDefault();
      resetToInitialState();
      return;
    }

    if (e.key !== 'Enter' || e.repeat || e.ctrlKey || e.altKey || e.metaKey || e.shiftKey) {
      return;
    }

    const active = document.activeElement;

    // Saat modal struk terbuka (Normal maupun Overweight):
    // Tekan Enter lagi -> otomatis cetak tiket & keluar dari tampilan tiket
    if (isModalOpen) {
      if (active && active.id === 'btn-copy-ticket-no') {
        return; // biarkan tombol salin tetap bekerja jika dipilih via Tab
      }
      e.preventDefault();
      e.stopPropagation();
      printAndCloseTicketModal();
      return;
    }

    if (isIssuingTicket || isPrintingTicket || Date.now() - lastPrintFinishedAt < 800) {
      e.preventDefault();
      e.stopPropagation();
      return;
    }

    // Shortcut Enter: foto kendaraan + terbitkan struk (Normal/Overweight) + buka gate
    if (active && active.id === 'driver-name') {
      e.preventDefault();
      issueTicket(e);
      return;
    }
    const tag = active?.tagName?.toLowerCase();
    if (tag === 'button' || tag === 'a' || tag === 'textarea' || tag === 'select' || tag === 'input') {
      return;
    }
    e.preventDefault();
    issueTicket(e);
  });

  document.getElementById('btn-print-ticket-modal')?.addEventListener('click', () => {
    printAndCloseTicketModal();
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

  // ------------------------------------------------------------------
  // KAMERA PERANGKAT (getUserMedia) & UNGGAH FOTO UNTUK PCV
  // ------------------------------------------------------------------
  function setCameraMessage(text, isError = false) {
    const msgEl = document.getElementById('camera-message');
    if (!msgEl) return;
    msgEl.textContent = text;
    msgEl.classList.toggle('is-error', Boolean(isError));
  }

  function stopCamera() {
    if (state.stream) {
      state.stream.getTracks().forEach((track) => track.stop());
      state.stream = null;
    }
    const video = document.getElementById('camera-video');
    if (video) {
      video.srcObject = null;
    }
  }

  function clearUploadedImage() {
    if (state.imageUrl) {
      URL.revokeObjectURL(state.imageUrl);
      state.imageUrl = null;
    }
  }

  function updateCameraUI() {
    const live = state.cameraMode === 'live';
    const demo = state.cameraMode === 'demo';
    const video = document.getElementById('camera-video');
    const img = document.getElementById('camera-feed');
    const demoBbox = document.getElementById('cam-demo-bbox');
    const sourceBadge = document.getElementById('cam-source-badge');
    const camBtnSpan = document.querySelector('#btn-reload-cam span');

    if (video) video.hidden = !live;
    if (img) img.hidden = live;
    if (demoBbox) demoBbox.hidden = !demo;
    if (sourceBadge) {
      sourceBadge.textContent = live
        ? 'LIVE KAMERA'
        : demo
        ? 'REC PRATINJAU SISI'
        : 'FOTO DIUNGGAH';
    }
    if (camBtnSpan) {
      camBtnSpan.textContent = live ? 'Matikan Kamera' : 'Aktifkan Kamera';
    }
  }

  function resetCameraPreview(message = 'Kamera perangkat dapat diaktifkan secara manual atau unggah foto kendaraan.') {
    stopCamera();
    clearUploadedImage();
    state.cameraMode = 'demo';
    state.cvActive = false;
    const img = document.getElementById('camera-feed');
    if (img) {
      img.dataset.pcv = 'false';
      img.src = '/static/assets/camera-demo.svg';
      img.alt = 'Truck Camera Feed';
    }
    updateCameraUI();
    window.dispatchEvent(new CustomEvent('ferqueue:camera-reset'));
    setCameraMessage(message, false);
  }

  async function requestCameraStream() {
    try {
      return await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 960 } },
        audio: false,
      });
    } catch (err) {
      if (err?.name === 'OverconstrainedError' || err?.name === 'NotFoundError') {
        return await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      }
      throw err;
    }
  }

  async function toggleCamera() {
    const camBtn = document.getElementById('btn-reload-cam');
    if (state.stream) {
      resetCameraPreview('Kamera dimatikan. Klik Aktifkan Kamera untuk menyalakan kembali.');
      toast('Kamera dimatikan.', 'info');
      return;
    }

    if (!navigator.mediaDevices?.getUserMedia) {
      const msg = 'Kamera tidak tersedia di browser ini. Buka halaman lewat http://localhost:5000 atau HTTPS, atau gunakan Unggah Foto.';
      setCameraMessage(msg, true);
      toast('Kamera tidak tersedia. Pastikan akses lewat localhost/HTTPS.', 'warning');
      return;
    }

    if (camBtn) camBtn.disabled = true;
    setCameraMessage('Menunggu izin akses kamera perangkat…', false);

    try {
      const stream = await requestCameraStream();
      const video = document.getElementById('camera-video');
      const img = document.getElementById('camera-feed');
      if (!video) {
        stream.getTracks().forEach((t) => t.stop());
        throw new Error('Elemen video kamera tidak ditemukan.');
      }

      stopCamera();
      clearUploadedImage();
      state.stream = stream;
      state.cameraMode = 'live';
      if (img) img.dataset.pcv = 'false';

      video.srcObject = stream;
      updateCameraUI();
      await video.play();

      const videoTrack = stream.getVideoTracks()[0];
      if (videoTrack) {
        videoTrack.addEventListener('ended', () => {
          resetCameraPreview('Koneksi kamera terputus. Klik Aktifkan Kamera untuk mencoba lagi.');
        }, { once: true });
      }

      window.dispatchEvent(new CustomEvent('ferqueue:camera-reset'));
      setCameraMessage('Kamera aktif. Menghubungkan API PCV untuk deteksi kendaraan…', false);
      toast('Kamera berhasil diaktifkan.', 'success');
    } catch (error) {
      stopCamera();
      state.cameraMode = 'demo';
      updateCameraUI();
      const messages = {
        NotAllowedError: 'Akses kamera ditolak. Izinkan akses kamera di pengaturan browser (ikon gembok/kamera di address bar), lalu coba lagi.',
        PermissionDeniedError: 'Akses kamera ditolak. Izinkan akses kamera di pengaturan browser, lalu coba lagi.',
        NotFoundError: 'Tidak ada kamera yang terdeteksi di perangkat ini. Hubungkan webcam atau gunakan Unggah Foto.',
        DevicesNotFoundError: 'Tidak ada kamera yang terdeteksi di perangkat ini. Hubungkan webcam atau gunakan Unggah Foto.',
        NotReadableError: 'Kamera sedang digunakan aplikasi lain. Tutup aplikasi tersebut lalu coba lagi.',
        TrackStartError: 'Kamera sedang digunakan aplikasi lain. Tutup aplikasi tersebut lalu coba lagi.',
        SecurityError: 'Akses kamera diblokir keamanan browser. Buka halaman lewat http://localhost:5000 atau HTTPS.',
      };
      const errMsg = messages[error?.name] || `Kamera gagal diaktifkan (${error?.name || error?.message || 'Error tidak dikenal'}). Coba lagi atau gunakan Unggah Foto.`;
      setCameraMessage(errMsg, true);
      toast('Kamera belum bisa diaktifkan. Periksa pesan di bawah tampilan kamera.', 'warning');
    } finally {
      if (camBtn) camBtn.disabled = false;
    }
  }

  document.getElementById('btn-reload-cam')?.addEventListener('click', toggleCamera);

  // Fullscreen viewport button
  document.getElementById('btn-expand-cam')?.addEventListener('click', async () => {
    const viewport = document.getElementById('camera-viewport');
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else if (viewport?.requestFullscreen) await viewport.requestFullscreen();
      else toast('Layar penuh tidak tersedia di browser ini.', 'info');
    } catch {
      toast('Browser belum mengizinkan tampilan layar penuh.', 'warning');
    }
  });

  // Upload foto button
  const uploadBtn = document.getElementById('btn-upload-foto');
  const fileInput = document.getElementById('file-upload');
  if (uploadBtn && fileInput) {
    uploadBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', async (e) => {
      const file = e.target.files?.[0];
      e.target.value = '';
      if (!file) return;
      if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 12 * 1024 * 1024) {
        setCameraMessage('Pilih gambar JPG, PNG, atau WebP dengan ukuran maksimal 12 MB.', true);
        toast('Format gambar harus JPG, PNG, atau WebP (maks. 12 MB).', 'warning');
        return;
      }
      const url = URL.createObjectURL(file);
      try {
        const probe = new Image();
        probe.src = url;
        await probe.decode();

        stopCamera();
        clearUploadedImage();
        state.imageUrl = url;
        state.cameraMode = 'upload';

        const img = document.getElementById('camera-feed');
        if (img) {
          img.dataset.pcv = 'true';
          img.src = url;
          img.alt = `Foto kendaraan: ${file.name}`;
        }
        updateCameraUI();
        window.dispatchEvent(new CustomEvent('ferqueue:camera-reset'));
        setCameraMessage('Foto diunggah. Mengirim ke API PCV untuk deteksi…', false);
        toast('Foto kendaraan berhasil diunggah.', 'success');
      } catch {
        URL.revokeObjectURL(url);
        setCameraMessage('Gambar tidak dapat dibuka. Pilih file gambar lain.', true);
        toast('Gambar tidak dapat dibuka.', 'warning');
      }
    });
  }

  // Update dimensi panjang & tinggi dari kalibrasi kamera samping (pinhole)
  window.addEventListener('ferqueue:camera-measurement', (e) => {
    const active = Boolean(e.detail?.active);
    const estimate = e.detail?.estimate;
    state.cameraDimensionsActive = active;
    if (estimate && Number.isFinite(estimate.length_cm) && Number.isFinite(estimate.height_cm)) {
      state.panjang = Number(estimate.length_cm.toFixed(2));
      state.tinggi = Number(estimate.height_cm.toFixed(2));
      syncSensorStateToBackend();
    } else if (active || state.cameraMode !== 'demo') {
      state.panjang = null;
      state.tinggi = null;
    } else {
      state.panjang = DEFAULT_DEMO_PANJANG;
      state.tinggi = DEFAULT_DEMO_TINGGI;
    }
    renderUI();
  });

  // Update jenis kendaraan & status pesan dari hasil deteksi PCV
  window.addEventListener('ferqueue:cv-result', (e) => {
    const data = e.detail;
    state.cvActive = true;
    const msgEl = document.getElementById('camera-message');
    if (msgEl) msgEl.classList.remove('is-error');
    if (data?.calibration_only) {
      state.vehicleType = 'Mode Kalibrasi Geometri Aktif';
    } else if (data?.detections?.length) {
      const classes = [...new Set(data.detections.map((item) => item.class_name))];
      state.vehicleType = classes.join(', ');
      const mappedGol = mapClassNameToGolongan(data.detections[0].class_name);
      if (mappedGol) {
        state.lastGolSyncAt = Date.now();
        applyGolonganMeta(mappedGol);
        syncSensorStateToBackend();
      }
    } else {
      state.vehicleType = 'Belum ada kendaraan terdeteksi';
    }
    renderUI();
  });

  window.addEventListener('ferqueue:cv-error', () => {
    state.cvActive = true;
    const msgEl = document.getElementById('camera-message');
    if (msgEl) msgEl.classList.add('is-error');
  });

  window.addEventListener('pagehide', () => {
    stopCamera();
    clearUploadedImage();
  });

  updateCameraUI();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
