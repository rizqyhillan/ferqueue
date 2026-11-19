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
  stream: null,
  imageUrl: null,
  cameraMode: 'demo',    // 'demo' | 'live' | 'upload'
  cvActive: false,
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

  // Update dimensi panjang & tinggi dari kalibrasi koin 50 yen
  window.addEventListener('ferqueue:camera-measurement', (e) => {
    const estimate = e.detail?.estimate;
    if (estimate) {
      state.panjang = Math.round(estimate.length_cm);
      state.tinggi = Math.round(estimate.height_cm);
      renderUI();
    }
  });

  // Update jenis kendaraan & status pesan dari hasil deteksi PCV
  window.addEventListener('ferqueue:cv-result', (e) => {
    const data = e.detail;
    state.cvActive = true;
    const msgEl = document.getElementById('camera-message');
    if (msgEl) msgEl.classList.remove('is-error');
    if (data?.calibration_only) {
      state.vehicleType = 'Mode Kalibrasi Koin Aktif';
    } else if (data?.detections?.length) {
      const classes = [...new Set(data.detections.map((item) => item.class_name))];
      state.vehicleType = classes.join(', ');
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
