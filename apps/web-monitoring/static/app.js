import { STORAGE_KEY, MAX_HISTORY, CATEGORIES, categoryInfo, createTicket, formatWeight, normalizeDriver, parseHistory, validateInspection } from './tickets.js';

import './live_detection.js';

const $ = selector => document.querySelector(selector);
const DIMENSION_FIELDS = { length: 'P', height: 'T' };
const state = {
  weight: 0,
  category: '',
  vehicleStatus: 'Normal',
  confirmed: false,
  issued: null,
  history: [],
  stream: null,
  imageUrl: null,
  cameraMode: 'demo',
  pendingIssue: false,
  sensorLive: false,
  manualWeightOverride: false,
  manualDimensionOverride: false,
  cameraDimensions: null,
  lastDimensionReading: null,
  cvActive: false,
  dimensions: {},
  vehicleType: 'Belum ada hasil deteksi',
  anomalyScore: 0,
  anomalyThreshold: null,
  anomalyReason: ''
};

const BASE_URL = window.location.origin.startsWith('http') ? window.location.origin : 'http://127.0.0.1:5000';

const dateFormat = new Intl.DateTimeFormat('id-ID', { timeZone: 'Asia/Jakarta', day: '2-digit', month: 'short', year: 'numeric' });
const fullDateFormat = new Intl.DateTimeFormat('id-ID', { timeZone: 'Asia/Jakarta', weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' });
const timeFormat = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Jakarta', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
const dateTime = value => `${dateFormat.format(new Date(value))} · ${timeFormat.format(new Date(value))} WIB`;

let toastTimer;
let captureTimer;
let storageAvailable = true;

try {
  state.history = parseHistory(localStorage.getItem(STORAGE_KEY));
} catch {
  storageAvailable = false;
}

function element(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = value;
  return node;
}

function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'icon');
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', `#i-${name}`);
  svg.append(use);
  return svg;
}

function toast(message) {
  clearTimeout(toastTimer);
  $('#toast span').textContent = message;
  $('#toast').hidden = false;
  toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 4500);
}

function showDialog(dialog) { if (!dialog.open) dialog.showModal(); }

function formatDimensions({ length, height }) {
  const values = [length, height].map(value => value ?? '—');
  return values.some(value => value !== '—') ? `${values.join(' × ')} cm` : 'Belum diisi';
}

function inspectionDimensions() {
  if (state.issued) return state.issued;
  return state.manualDimensionOverride ? state.dimensions : (state.cameraDimensions ?? state.dimensions);
}

function renderDimensions() {
  const dimensions = inspectionDimensions();
  for (const field of Object.keys(DIMENSION_FIELDS)) {
    const reading = $(`#dim-${field}`);
    const value = dimensions[field];
    if (reading) {
      reading.textContent = value ?? '—';
      if (value && value !== '—') reading.append(document.createTextNode(' '), element('small', '', 'cm'));
    }
  }
  if ($('#dim-status')) {
    const hasDimensions = Object.keys(DIMENSION_FIELDS).some(field => dimensions[field] && dimensions[field] !== '—');
    $('#dim-status').textContent = state.issued ? 'Tiket terbit'
      : state.manualDimensionOverride ? 'Input operator'
      : state.cameraDimensions !== null ? (hasDimensions ? 'Kamera · 50 yen' : 'Menunggu hasil kamera')
      : hasDimensions ? 'API' : 'Belum diisi';
  }
  if ($('#ticket-dimensions')) $('#ticket-dimensions').textContent = formatDimensions(dimensions);
}

function updateClock() {
  const now = new Date();
  if ($('#current-date')) $('#current-date').textContent = dateFormat.format(now);
  if ($('#current-date')) $('#current-date').title = fullDateFormat.format(now);
  if ($('#current-time')) $('#current-time').textContent = timeFormat.format(now);
  if ($('#camera-time')) $('#camera-time').textContent = timeFormat.format(now) + ' WIB';
  if (!state.issued && $('#ticket-time')) $('#ticket-time').textContent = dateTime(now);
}

function renderInspection() {
  const category = categoryInfo(state.category);

  if ($('#weight-value')) $('#weight-value').textContent = state.weight === null ? '—' : formatWeight(state.weight);
  if ($('.weight-reading')) $('.weight-reading').classList.toggle('long-reading', state.weight >= 100000);

  if ($('#weight-source')) {
    $('#weight-source').textContent = state.manualWeightOverride
      ? 'Input operator'
      : state.sensorLive
      ? 'Sensor timbangan live'
      : state.weight === null
      ? 'Menunggu input'
      : 'Menghubungkan sensor…';
  }

  if ($('.small-badge')) {
    $('.small-badge').textContent = state.manualWeightOverride
      ? 'MANUAL'
      : state.sensorLive
      ? 'LIVE API'
      : state.weight === null
      ? 'BELUM DIISI'
      : 'STANDBY';
  }

  if ($('#class-source')) $('#class-source').textContent = state.confirmed ? 'Dipilih operator' : 'Pilih golongan sesuai jenis kendaraan';

  if ($('#class-value')) {
    $('#class-value').replaceChildren();
    if (category) {
      const parts = category.code.split(' ');
      const numeral = parts[0] || '';
      const suffix = parts.slice(1).join(' ');
      $('#class-value').append(document.createTextNode(numeral));
      if (suffix) $('#class-value').append(element('span', '', ` ${suffix}`));
    } else {
      $('#class-value').textContent = state.category || '—';
    }
  }

  if ($('#class-description')) $('#class-description').textContent = category?.label || 'Kendaraan Teridentifikasi';

  renderDimensions();

  if ($('#vehicle-summary')) $('#vehicle-summary').textContent = state.vehicleType;

  if ($('#ticket-weight')) $('#ticket-weight').textContent = state.weight === null ? 'Belum diisi' : `${formatWeight(state.weight)} g`;
  if ($('#ticket-class')) {
    $('#ticket-class').textContent = category ? category.code : (state.category || 'Belum dipilih');
    if (category) $('#ticket-class').append(element('span', '', ` · ${category.code.endsWith('B') ? 'Kendaraan barang' : category.label}`));
  }

  const isAnomaly = state.vehicleStatus.toLowerCase().includes('anomali');
  const statusDesc = $('#ticket-status-desc');
  if (statusDesc) {
    statusDesc.replaceChildren();
    const statusPill = element('span', `status-pill ${isAnomaly ? 'status-anomaly' : 'status-normal'}`, state.vehicleStatus);
    statusDesc.append(statusPill);
    if (state.anomalyScore > 0) {
      const scoreBadge = element('small', 'dimension-note', ` (Skor ML: ${Number(state.anomalyScore).toFixed(2)})`);
      scoreBadge.style.color = isAnomaly ? '#dc2626' : '#16a34a';
      scoreBadge.style.fontWeight = '600';
      scoreBadge.style.marginLeft = '6px';
      statusDesc.append(scoreBadge);
    }
    if (isAnomaly && state.anomalyReason) {
      const reasonEl = element('div', 'dimension-note', `⚠️ ${state.anomalyReason}`);
      reasonEl.style.color = '#b91c1c';
      reasonEl.style.fontSize = '11px';
      reasonEl.style.marginTop = '4px';
      statusDesc.append(reasonEl);
    }
  }

  const dimStatus = $('#dim-status');
  if (dimStatus) {
    if (isAnomaly) {
      dimStatus.textContent = 'Terindikasi Anomali';
      dimStatus.className = 'status-anomaly';
    } else {
      dimStatus.textContent = 'Normal';
      dimStatus.className = 'status-normal';
    }
  }

  if ($('#edit-weight')) $('#edit-weight').disabled = Boolean(state.issued);
  if ($('#edit-class')) $('#edit-class').disabled = Boolean(state.issued);
  if ($('#driver-input')) $('#driver-input').readOnly = Boolean(state.issued);
  if ($('#issue-ticket')) $('#issue-ticket').hidden = Boolean(state.issued);
  if ($('#print-ticket')) $('#print-ticket').hidden = !state.issued;
  if ($('#next-vehicle')) $('#next-vehicle').hidden = !state.issued;
  if ($('#ticket-note')) $('#ticket-note').hidden = Boolean(state.issued);
  if ($('#issued-receipt')) $('#issued-receipt').hidden = !state.issued;
  if ($('#ticket-status')) $('#ticket-status').textContent = state.issued ? 'TELAH DITERBITKAN' : 'DRAF TIKET';
  if ($('#ticket-time-label')) $('#ticket-time-label').textContent = state.issued ? 'Waktu terbit' : 'Waktu pemeriksaan';

  if (state.issued) {
    if ($('#issued-ticket-number')) $('#issued-ticket-number').textContent = state.issued.number;
    if ($('#issued-receipt small')) $('#issued-receipt small').textContent = storageAvailable ? 'Tersimpan di perangkat ini' : 'Tersimpan sementara di halaman ini. Cetak tiket sebelum menutup halaman.';
    if ($('#ticket-time')) $('#ticket-time').textContent = dateTime(state.issued.createdAt);
  }

  if ($('#history-count')) $('#history-count').textContent = String(state.history.length);
}

// ------------------------------------------------------------------
// FUNGSI UTAMA FETCH KE BACKEND (SUDAH DIPERBAIKI)
// ------------------------------------------------------------------
async function fetchStatusKendaraanFromBackend() {
  if (state.issued) return;
  try {
    const res = await fetch(`${BASE_URL}/api/status-kendaraan?t=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error('Flask Backend Offline');
    const data = await res.json();
    if (state.issued) return;

    // 1. Format label Jenis Kendaraan
    if (data.jenis && data.waktu && !state.cvActive) {
      const jenisRaw = data.jenis.toLowerCase().trim();
      let labelJenis = '';

      if (jenisRaw === 'mobil') {
        labelJenis = 'Mobil pribadi / penumpang';
      } else if (jenisRaw === 'bus') {
        labelJenis = 'Bus angkutan penumpang';
      } else {
        const jenisCapitalized = jenisRaw.charAt(0).toUpperCase() + jenisRaw.slice(1);
        labelJenis = `${jenisCapitalized} angkutan barang`;
      }

      state.vehicleType = labelJenis;
    }

    // 2. Pembacaan BERAT (Dari Load Cell live) jika operator tidak sedang mengunci manual
    if (!state.manualWeightOverride) {
      let weightVal = null;
      if (typeof data.berat === 'number') {
        weightVal = data.berat;
      } else if (typeof data.berat_gram === 'number') {
        weightVal = data.berat_gram;
      } else if (typeof data.berat_kg === 'number') {
        weightVal = data.berat_kg;
      } else if (typeof data.W === 'number' && data.W > 0) {
        weightVal = data.W < 1000 ? data.W * 1000 : data.W;
      }

      if (weightVal !== null) {
        state.weight = weightVal;
      }
    }

    // Ingat pembacaan API terakhir agar tidak muncul lagi pada kendaraan berikutnya.
    const dimensionReading = JSON.stringify([data.waktu, data.P, data.T]);
    if (dimensionReading !== state.lastDimensionReading) {
      state.lastDimensionReading = dimensionReading;
      if (!state.manualDimensionOverride) {
        const dimensions = {};
        for (const [field, key] of Object.entries(DIMENSION_FIELDS)) {
          const value = Number(data[key]);
          if (Number.isFinite(value) && value > 0) dimensions[field] = value.toFixed(2).replace('.', ',');
        }
        state.dimensions = dimensions;
      }
    }

    // 4. Pembacaan GOLONGAN & STATUS ANOMALI
    if (!state.confirmed && data.golongan && data.golongan !== '-') {
      state.category = data.golongan;
    }

    if (data.status_anomali) {
      state.vehicleStatus = data.status_anomali;
    }
    if (typeof data.skor_anomali === 'number') {
      state.anomalyScore = data.skor_anomali;
    }
    if (typeof data.ambang_anomali === 'number') {
      state.anomalyThreshold = data.ambang_anomali;
    }
    if (Array.isArray(data.alasan) && data.alasan.length > 0) {
      state.anomalyReason = data.alasan.join(', ');
    } else {
      state.anomalyReason = '';
    }

    state.sensorLive = true;
    renderInspection();
  } catch (error) {
    if (state.sensorLive) {
      state.sensorLive = false;
      renderInspection();
    }
  }
}

function openEditor(focus = 'weight') {
  if (state.issued) return;
  if ($('#weight-input')) $('#weight-input').value = state.weight ?? '';
  if ($('#class-input')) $('#class-input').value = state.category;
  if ($('#vehicle-status-input')) $('#vehicle-status-input').value = state.vehicleStatus || 'Normal';
  if ($('#edit-error')) $('#edit-error').hidden = true;
  showDialog($('#edit-dialog'));
  $(focus === 'category' ? '#class-input' : focus === 'status' ? '#vehicle-status-input' : '#weight-input').focus();
}

if ($('#class-input')) {
  $('#class-input').append(element('option', '', 'Pilih golongan kendaraan'));
  if ($('#class-input option')) $('#class-input option').value = '';
  for (const category of CATEGORIES) {
    const option = element('option', '', `Golongan ${category.code} — ${category.label}`);
    option.value = category.code;
    $('#class-input').append(option);
  }
}

if ($('#edit-weight')) $('#edit-weight').addEventListener('click', () => openEditor());
if ($('#edit-class')) $('#edit-class').addEventListener('click', () => openEditor('category'));

const dimensionsForm = $('#dimensions-form');
if (dimensionsForm) {
  const inputs = Object.keys(DIMENSION_FIELDS).map(field => dimensionsForm.elements.namedItem(field));
  const dialog = $('#dimensions-dialog');
  const error = $('#dimensions-error');
  $('#edit-dimensions').addEventListener('click', () => {
    if (state.issued) return;
    const dimensions = inspectionDimensions();
    for (const input of inputs) input.value = dimensions[input.name] ?? '';
    error.hidden = true;
    showDialog(dialog);
    inputs[0].focus();
  });
  dimensionsForm.addEventListener('submit', event => {
    event.preventDefault();
    if (state.issued) return;
    const invalidInput = inputs.find(input => {
      const raw = input.value.trim();
      const value = Number(raw.replace(',', '.'));
      return !/^\d*[.,]?\d+$/.test(raw) || !Number.isFinite(value) || value <= 0;
    });
    if (invalidInput) {
      error.textContent = 'Masukkan angka lebih dari 0 untuk setiap dimensi.';
      error.hidden = false;
      invalidInput.focus();
      return;
    }
    state.dimensions = Object.fromEntries(inputs.map(input => [input.name, input.value.trim().replace('.', ',')]));
    state.manualDimensionOverride = true;
    dialog.close();
    renderInspection();
    toast('Dimensi kendaraan telah disimpan.');
  });
}

if ($('#edit-form')) {
  $('#edit-form').addEventListener('submit', event => {
    event.preventDefault();
    const rawVal = String($('#weight-input').value).trim().replace(',', '.');
    const weight = Number(rawVal);
    const category = $('#class-input').value;
    const vehicleStatus = $('#vehicle-status-input').value || 'Normal';
    const errors = validateInspection({ driver: 'Operator', weight, category });
    if (errors.weight || errors.category) {
      $('#edit-error').textContent = errors.weight || errors.category;
      $('#edit-error').hidden = false;
      return;
    }
    state.weight = weight;
    state.category = category;
    state.vehicleStatus = vehicleStatus;
    state.confirmed = true;
    state.manualWeightOverride = true;
    const pending = state.pendingIssue;
    state.pendingIssue = false;
    $('#edit-dialog').close();
    renderInspection();
    if (pending) requestIssueTicket();
    else toast('Data pemeriksaan kendaraan telah diperbarui.');
  });
}

if ($('#driver-input')) {
  $('#driver-input').addEventListener('input', () => {
    if ($('#driver-error')) $('#driver-error').hidden = true;
    $('#driver-input').removeAttribute('aria-invalid');
  });
  $('#driver-input').addEventListener('blur', () => { $('#driver-input').value = normalizeDriver($('#driver-input').value); });
  $('#driver-input').addEventListener('keydown', event => { if (event.key === 'Enter') requestIssueTicket(); });
}

function issueTicket() {
  if (state.issued) return;
  const dimensions = inspectionDimensions();
  const inspection = {
    driver: $('#driver-input').value,
    weight: state.weight,
    category: state.category,
    length: dimensions.length ?? '—',
    height: dimensions.height ?? '—',
    vehicleStatus: state.vehicleStatus,
  };
  const errors = validateInspection(inspection);
  if (errors.driver || errors.plate) {
    if ($('#driver-error')) {
      $('#driver-error').textContent = errors.driver || errors.plate;
      $('#driver-error').hidden = false;
    }
    $('#driver-input').setAttribute('aria-invalid', 'true');
    $('#driver-input').focus();
    return;
  }
  if (state.sensorLive && !errors.weight && !errors.category && !state.confirmed) {
    state.confirmed = true;
  }
  if (!state.confirmed || errors.weight || errors.category) {
    state.pendingIssue = true;
    openEditor();
    return;
  }
  try {
    const fresh = parseHistory(localStorage.getItem(STORAGE_KEY));
    state.history = parseHistory(JSON.stringify([...fresh, ...state.history]));
  } catch { storageAvailable = false; }

  const ticket = createTicket(inspection, state.history);
  state.history = [ticket, ...state.history].slice(0, MAX_HISTORY);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.history));
    storageAvailable = true;
  } catch { storageAvailable = false; }

  state.issued = ticket;
  $('#driver-input').value = ticket.driver || ticket.plate;
  renderInspection();

  fetch(`${BASE_URL}/api/tiket`, {
    method: 'POST',
    body: JSON.stringify({ nomor: ticket.number, berat: ticket.weight, pengemudi: ticket.driver || 'Pengemudi', golongan: ticket.category || state.category, status: ticket.vehicleStatus || state.vehicleStatus }),
    headers: { 'Content-Type': 'application/json' }
  }).catch(() => {});

  toast(storageAvailable ? `Tiket ${ticket.number} berhasil diterbitkan.` : 'Tiket dibuat sementara. Penyimpanan browser tidak tersedia; segera cetak tiket.');
  if ($('#print-ticket')) $('#print-ticket').focus();
}

function requestIssueTicket() {
  if (navigator.locks?.request) navigator.locks.request('ferqueue-issue-ticket', issueTicket).catch(() => toast('Tiket belum diterbitkan. Silakan coba kembali.'));
  else issueTicket();
}

if ($('#issue-ticket')) $('#issue-ticket').addEventListener('click', requestIssueTicket);

if ($('#next-vehicle')) {
  $('#next-vehicle').addEventListener('click', () => {
    state.issued = null;
    state.manualWeightOverride = false;
    state.manualDimensionOverride = false;
    if (state.cameraDimensions !== null) state.cameraDimensions = {};
    state.dimensions = {};
    state.category = '';
    state.vehicleStatus = 'Normal';
    state.anomalyScore = 0;
    state.anomalyThreshold = null;
    state.anomalyReason = '';
    state.vehicleType = 'Belum ada hasil deteksi';
    state.confirmed = false;
    if ($('#driver-input')) $('#driver-input').value = '';
    if ($('#driver-error')) $('#driver-error').hidden = true;
    if ($('#snapshot-label')) $('#snapshot-label').hidden = true;
    if (state.cameraMode === 'upload') resetCameraPreview();
    fetchStatusKendaraanFromBackend();
    renderInspection();
    updateClock();
    if ($('#driver-input')) $('#driver-input').focus();
    toast('Siap untuk kendaraan berikutnya. Isi ulang data.');
  });
}

function renderPrint(ticket) {
  const area = $('#print-area');
  if (!area) return;
  area.replaceChildren();
  const header = element('div', 'receipt-header');
  header.append(element('strong', '', 'FERQUEUE.'), element('span', '', 'TIKET PEMERIKSAAN'));
  const title = element('div', 'receipt-title');
  title.append(element('h1', '', 'TIKET MASUK'), element('p', '', ticket.number));
  const driverName = ticket.driver || ticket.plate;
  const statusLabel = ticket.vehicleStatus === 'Terindikasi Anomali' ? 'Anomali (Pemeriksaan Lanjutan)' : 'Normal (Sesuai Ketentuan)';
  const dimText = formatDimensions(ticket);
  const details = element('dl', 'receipt-details');
  for (const [label, value] of [
    ['Nama pengemudi', driverName], ['Berat kendaraan', `${formatWeight(ticket.weight)} g`],
    ['Golongan', `${ticket.category} · ${categoryInfo(ticket.category)?.label || 'Kendaraan Barang'}`],
    ['Panjang × tinggi', dimText],
    ['Kondisi kendaraan', statusLabel],
    ['Waktu terbit', dateTime(ticket.createdAt)],
  ]) {
    const row = element('div');
    row.append(element('dt', '', label), element('dd', '', value));
    details.append(row);
  }
  const footer = element('div', 'receipt-footer');
  footer.append(element('strong', '', 'TIKET DEMO · DATA INTEGRASI'), element('div', '', 'Simpan tiket ini sebagai bukti pemeriksaan kendaraan.'), element('div', '', 'Berat dan golongan dikonfirmasi oleh sistem.'), element('div', '', 'FERQUEUE — Sistem Pemeriksaan Kendaraan Pelabuhan'));
  area.append(header, title, element('div', 'receipt-plate', driverName), details, footer);
}

function printTicket(ticket) {
  renderPrint(ticket);
  document.querySelectorAll('dialog[open]').forEach(dialog => dialog.close());
  window.print();
}

if ($('#print-ticket')) $('#print-ticket').addEventListener('click', () => { if (state.issued) printTicket(state.issued); });
window.addEventListener('beforeprint', () => {
  if (state.issued) renderPrint(state.issued);
});

function renderHistory() {
  const query = $('#history-search').value.trim().toUpperCase();
  const tickets = state.history.filter(ticket => (ticket.driver || ticket.plate || '').toUpperCase().includes(query) || ticket.number.includes(query));
  const list = $('#history-list');
  if (!list) return;
  list.replaceChildren();
  if ($('#history-summary')) $('#history-summary').textContent = `${tickets.length} tiket${query ? ' ditemukan' : ' tersimpan'} · maksimal ${MAX_HISTORY} tiket terbaru`;
  if (!tickets.length) {
    const empty = element('div', 'history-empty');
    empty.append(icon('ticket'), element('strong', '', query ? 'Tiket tidak ditemukan' : 'Belum ada tiket yang diterbitkan'), element('p', '', query ? 'Coba kata kunci nama pengemudi atau nomor tiket lainnya.' : 'Tiket yang Anda terbitkan akan tampil di sini.'));
    list.append(empty);
    return;
  }
  for (const ticket of tickets) {
    const driverName = ticket.driver || ticket.plate;
    const row = element('article', 'history-item');
    const info = element('div');
    info.append(element('strong', '', driverName), element('span', 'history-number', ticket.number), element('small', '', `${dateTime(ticket.createdAt)} · ${formatWeight(ticket.weight)} g · Gol. ${ticket.category}`));
    const button = element('button', 'button button-secondary');
    button.append(icon('print'), document.createTextNode('Cetak'));
    button.setAttribute('aria-label', `Cetak tiket ${ticket.number} untuk ${driverName}`);
    button.addEventListener('click', () => printTicket(ticket));
    row.append(info, button);
    list.append(row);
  }
}

if ($('#history-button')) {
  $('#history-button').addEventListener('click', () => {
    try {
      const saved = parseHistory(localStorage.getItem(STORAGE_KEY));
      state.history = parseHistory(JSON.stringify([...saved, ...state.history]));
    } catch { /* Keep session tickets. */ }
    if ($('#history-count')) $('#history-count').textContent = String(state.history.length);
    if ($('#history-search')) $('#history-search').value = '';
    renderHistory();
    showDialog($('#history-dialog'));
  });
}

if ($('#history-search')) $('#history-search').addEventListener('input', renderHistory);
if ($('#help-button')) $('#help-button').addEventListener('click', () => showDialog($('#help-dialog')));

document.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
document.querySelectorAll('dialog').forEach(dialog => {
  dialog.addEventListener('click', event => {
    const rect = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close();
  });
});

if ($('#edit-dialog')) $('#edit-dialog').addEventListener('close', () => { state.pendingIssue = false; });

window.addEventListener('storage', event => {
  if (event.key !== STORAGE_KEY) return;
  state.history = parseHistory(event.newValue);
  if ($('#history-count')) $('#history-count').textContent = String(state.history.length);
  if ($('#history-dialog')?.open) renderHistory();
});

function stopCamera() {
  state.stream?.getTracks().forEach(track => track.stop());
  state.stream = null;
  if ($('#camera-video')) $('#camera-video').srcObject = null;
}

function clearUploadedImage() {
  if (state.imageUrl) URL.revokeObjectURL(state.imageUrl);
  state.imageUrl = null;
}

function resetCameraPreview() {
  stopCamera();
  clearUploadedImage();
  state.cameraMode = 'demo';
  state.cvActive = false;
  state.vehicleType = 'Belum ada hasil deteksi';
  window.dispatchEvent(new Event('ferqueue:camera-reset'));
  if ($('#camera-image')) {
    $('#camera-image').dataset.pcv = 'false';
    $('#camera-image').src = './assets/camera-demo.svg';
    $('#camera-image').alt = 'Ilustrasi contoh truk di jalur pemeriksaan, bukan siaran langsung';
    $('#camera-image').hidden = false;
  }
  if ($('#camera-video')) $('#camera-video').hidden = true;
  updateCameraLabels();
}

function updateCameraLabels() {
  const live = state.cameraMode === 'live';
  const demo = state.cameraMode === 'demo';
  if ($('#camera-source-label')) $('#camera-source-label').textContent = live ? 'KAMERA PERANGKAT' : demo ? 'PRATINJAU DEMO' : 'GAMBAR DIUNGGAH';
  if ($('#camera-view-label')) $('#camera-view-label').textContent = demo ? 'TAMPAK SAMPING' : live ? 'SIARAN LANGSUNG' : 'PRATINJAU GAMBAR';
  if ($('#activate-camera span')) $('#activate-camera span').textContent = live ? 'Matikan kamera' : 'Aktifkan kamera';
  if ($('#vehicle-summary-label')) $('#vehicle-summary-label').textContent = 'JENIS KENDARAAN';

  if ($('#vehicle-summary')) $('#vehicle-summary').textContent = state.vehicleType || 'Kendaraan Terdeteksi';

  if ($('#visual-badge')) $('#visual-badge').textContent = demo ? 'DATA CONTOH' : 'LIVE API';
  if ($('#camera-message')) $('#camera-message').textContent = demo ? 'Kamera perangkat dapat diaktifkan secara manual.' : 'Menghubungkan PCV untuk mengenali jenis kendaraan…';
  if ($('#snapshot-label')) $('#snapshot-label').hidden = true;
}

if ($('#activate-camera')) {
  $('#activate-camera').addEventListener('click', async () => {
    if (state.stream) { resetCameraPreview(); return; }
    if (!navigator.mediaDevices?.getUserMedia) {
      if ($('#camera-message')) $('#camera-message').textContent = 'Kamera tidak tersedia. Buka lewat localhost atau HTTPS, atau gunakan unggah gambar.';
      toast('Kamera tidak tersedia di browser ini. Anda dapat mengunggah gambar.');
      return;
    }
    const button = $('#activate-camera');
    button.disabled = true;
    if ($('#camera-message')) $('#camera-message').textContent = 'Menunggu izin akses kamera perangkat…';
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 960 } }, audio: false });
      stopCamera();
      clearUploadedImage();
      state.stream = stream;
      if ($('#camera-video')) {
        $('#camera-video').srcObject = stream;
        await $('#camera-video').play();
        $('#camera-video').hidden = false;
      }
      state.cameraMode = 'live';
      if ($('#camera-image')) $('#camera-image').hidden = true;
      updateCameraLabels();
      stream.getVideoTracks()[0].addEventListener('ended', resetCameraPreview, { once: true });
    } catch (error) {
      stopCamera();
      const messages = {
        NotAllowedError: 'Akses kamera belum diizinkan. Izinkan kamera melalui pengaturan browser atau unggah gambar.',
        NotFoundError: 'Tidak ada kamera yang terdeteksi. Hubungkan kamera atau unggah gambar kendaraan.',
        NotReadableError: 'Kamera sedang digunakan aplikasi lain. Tutup aplikasi tersebut atau unggah gambar.',
      };
      if ($('#camera-message')) $('#camera-message').textContent = messages[error.name] || 'Kamera belum dapat diaktifkan. Coba kembali atau unggah gambar.';
      toast('Kamera belum aktif. Lihat petunjuk di bawah tampilan kamera.');
    } finally { button.disabled = false; }
  });
}

if ($('#upload-button')) $('#upload-button').addEventListener('click', () => $('#image-upload').click());

if ($('#image-upload')) {
  $('#image-upload').addEventListener('change', async event => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 12 * 1024 * 1024) {
      toast('Pilih gambar JPG, PNG, atau WebP dengan ukuran maksimal 12 MB.');
      return;
    }
    const url = URL.createObjectURL(file);
    try {
      const image = new Image();
      image.src = url;
      await image.decode();
      stopCamera();
      clearUploadedImage();
      state.imageUrl = url;
      state.cameraMode = 'upload';
      if ($('#camera-image')) {
        $('#camera-image').dataset.pcv = 'true';
        $('#camera-image').src = url;
        $('#camera-image').alt = `Gambar kendaraan yang diunggah: ${file.name}`;
        $('#camera-image').hidden = false;
      }
      if ($('#camera-video')) $('#camera-video').hidden = true;
      updateCameraLabels();
      toast('Gambar kendaraan siap ditinjau.');
    } catch {
      URL.revokeObjectURL(url);
      toast('Gambar tidak dapat dibuka. Pilih file gambar lain.');
    }
  });
}

if ($('#capture-button')) {
  $('#capture-button').addEventListener('click', async () => {
    const live = state.cameraMode === 'live';
    const media = $(live ? '#camera-video' : '#camera-image');
    if (!media) return;
    const width = live ? media.videoWidth : media.naturalWidth;
    const height = live ? media.videoHeight : media.naturalHeight;
    if (!width || !height) { toast('Tunggu hingga gambar atau kamera selesai dimuat.'); return; }
    const canvas = document.createElement('canvas');
    const ratio = Math.min(1, 1920 / Math.max(width, height));
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    try {
      const context = canvas.getContext('2d');
      context.drawImage(media, 0, 0, canvas.width, canvas.height);
      context.fillStyle = '#292929';
      context.fillRect(0, canvas.height - 34, canvas.width, 34);
      context.fillStyle = '#ffffff';
      context.font = `${Math.min(13, canvas.width / 50)}px monospace`;
      context.fillText(`FERQUEUE | ${state.cameraMode === 'demo' ? 'DATA CONTOH | ' : ''}${dateTime(new Date())}`, 12, canvas.height - 13);
      const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
      if (!blob) throw new Error('Gambar tidak tersedia.');
      const url = URL.createObjectURL(blob);
      const link = element('a');
      link.href = url;
      link.download = `ferqueue-${Date.now()}.png`;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      if ($('#snapshot-label')) $('#snapshot-label').hidden = false;
      clearTimeout(captureTimer);
      captureTimer = setTimeout(() => { if ($('#snapshot-label')) $('#snapshot-label').hidden = true; }, 3000);
      toast('Gambar pemeriksaan disimpan ke perangkat.');
    } catch { toast('Gambar belum dapat disimpan. Silakan coba lagi.'); }
  });
}

if ($('#expand-camera')) {
  $('#expand-camera').addEventListener('click', async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else if ($('#camera-viewport')?.requestFullscreen) await $('#camera-viewport').requestFullscreen();
      else toast('Layar penuh tidak tersedia di browser ini.');
    } catch { toast('Browser belum mengizinkan tampilan layar penuh.'); }
  });
}

window.addEventListener('pagehide', () => { stopCamera(); clearUploadedImage(); });
window.addEventListener('pageshow', event => { if (event.persisted) resetCameraPreview(); });

renderInspection();
updateClock();
setInterval(updateClock, 1000);

fetchStatusKendaraanFromBackend();
setInterval(fetchStatusKendaraanFromBackend, 1000);
window.addEventListener('ferqueue:camera-measurement', event => {
  const { active, estimate } = event.detail;
  state.cameraDimensions = active ? {} : null;
  if (estimate) {
    state.cameraDimensions = {
      length: estimate.length_cm.toFixed(2).replace('.', ','),
      height: estimate.height_cm.toFixed(2).replace('.', ','),
    };
  }
  if (!state.issued && !state.manualDimensionOverride) renderDimensions();
});
window.addEventListener('ferqueue:cv-result', event => {
  state.cvActive = true;
  state.vehicleType = event.detail.calibration_only ? 'Kalibrasi koin aktif' : event.detail.detections.length
    ? [...new Set(event.detail.detections.map(item => item.class_name))].join(', ')
    : 'Belum ada kendaraan terdeteksi';
  renderInspection();
});
window.addEventListener('ferqueue:cv-error', () => {
  state.cvActive = true;
  state.vehicleType = 'Deteksi belum tersedia';
});
