import { STORAGE_KEY, MAX_HISTORY, CATEGORIES, categoryInfo, createTicket, formatWeight, normalizePlate, parseHistory, validateInspection } from './tickets.js';

const $ = selector => document.querySelector(selector);
const state = { weight: 8420, category: 'VI B', confirmed: false, issued: null, history: [], stream: null, imageUrl: null, cameraMode: 'demo', pendingIssue: false };
const dateFormat = new Intl.DateTimeFormat('id-ID', { timeZone: 'Asia/Jakarta', day: '2-digit', month: 'short', year: 'numeric' });
const fullDateFormat = new Intl.DateTimeFormat('id-ID', { timeZone: 'Asia/Jakarta', weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' });
const timeFormat = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Jakarta', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
const dateTime = value => `${dateFormat.format(new Date(value))} · ${timeFormat.format(new Date(value))} WIB`;
let toastTimer;
let captureTimer;
let storageAvailable = true;
try { state.history = parseHistory(localStorage.getItem(STORAGE_KEY)); }
catch { storageAvailable = false; }

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
function updateClock() {
  const now = new Date();
  $('#current-date').textContent = dateFormat.format(now);
  $('#current-date').title = fullDateFormat.format(now);
  $('#current-time').textContent = timeFormat.format(now);
  $('#camera-time').textContent = timeFormat.format(now) + ' WIB';
  if (!state.issued) $('#ticket-time').textContent = dateTime(now);
}
function renderInspection() {
  const category = categoryInfo(state.category);
  $('#weight-value').textContent = state.weight === null ? '—' : formatWeight(state.weight);
  $('.weight-reading').classList.toggle('long-reading', state.weight >= 100000);
  $('#weight-source').textContent = state.confirmed ? 'Input operator' : state.weight === null ? 'Menunggu input' : 'Input demo';
  $('.small-badge').textContent = state.confirmed ? 'MANUAL' : state.weight === null ? 'BELUM DIISI' : 'CONTOH';
  $('#class-source').textContent = state.confirmed ? 'Dipilih operator' : state.category ? 'Pilihan contoh' : 'Menunggu input';
  $('#class-value').replaceChildren();
  if (category) {
    const [numeral, suffix] = category.code.split(' ');
    $('#class-value').append(document.createTextNode(numeral));
    if (suffix) $('#class-value').append(element('span', '', suffix));
  } else $('#class-value').textContent = '—';
  $('#class-description').textContent = category?.label || 'Menunggu pilihan operator';
  $('#ticket-weight').textContent = state.weight === null ? 'Belum diisi' : `${formatWeight(state.weight)} kg`;
  $('#ticket-class').textContent = category ? category.code : 'Belum dipilih';
  if (category) $('#ticket-class').append(element('span', '', ` · ${category.code.endsWith('B') ? 'Kendaraan barang' : category.label}`));
  $('#edit-weight').disabled = Boolean(state.issued);
  $('#edit-class').disabled = Boolean(state.issued);
  $('#plate-input').readOnly = Boolean(state.issued);
  $('#issue-ticket').hidden = Boolean(state.issued);
  $('#print-ticket').hidden = !state.issued;
  $('#next-vehicle').hidden = !state.issued;
  $('#ticket-note').hidden = Boolean(state.issued);
  $('#issued-receipt').hidden = !state.issued;
  $('#ticket-status').textContent = state.issued ? 'TELAH DITERBITKAN' : 'DRAF TIKET';
  $('#ticket-time-label').textContent = state.issued ? 'Waktu terbit' : 'Waktu pemeriksaan';
  if (state.issued) {
    $('#issued-ticket-number').textContent = state.issued.number;
    $('#issued-receipt small').textContent = storageAvailable ? 'Tersimpan di perangkat ini' : 'Tersimpan sementara di halaman ini. Cetak tiket sebelum menutup halaman.';
    $('#ticket-time').textContent = dateTime(state.issued.createdAt);
  }
  $('#history-count').textContent = String(state.history.length);
}
function openEditor(focus = 'weight') {
  if (state.issued) return;
  $('#weight-input').value = state.weight ?? '';
  $('#class-input').value = state.category;
  $('#edit-error').hidden = true;
  showDialog($('#edit-dialog'));
  $(focus === 'category' ? '#class-input' : '#weight-input').focus();
}
$('#class-input').append(element('option', '', 'Pilih golongan kendaraan'));
$('#class-input option').value = '';
for (const category of CATEGORIES) {
  const option = element('option', '', `Golongan ${category.code} — ${category.label}`);
  option.value = category.code;
  $('#class-input').append(option);
}
$('#edit-weight').addEventListener('click', () => openEditor());
$('#edit-class').addEventListener('click', () => openEditor('category'));
$('#edit-form').addEventListener('submit', event => {
  event.preventDefault();
  const weight = Number($('#weight-input').value);
  const category = $('#class-input').value;
  const errors = validateInspection({ plate: 'B 1 A', weight, category });
  if (errors.weight || errors.category) {
    $('#edit-error').textContent = errors.weight || errors.category;
    $('#edit-error').hidden = false;
    return;
  }
  state.weight = weight;
  state.category = category;
  state.confirmed = true;
  const pending = state.pendingIssue;
  state.pendingIssue = false;
  $('#edit-dialog').close();
  renderInspection();
  if (pending) requestIssueTicket();
  else toast('Berat dan golongan kendaraan telah diperbarui.');
});
$('#plate-input').addEventListener('input', () => {
  $('#plate-error').hidden = true;
  $('#plate-input').removeAttribute('aria-invalid');
});
$('#plate-input').addEventListener('blur', () => { $('#plate-input').value = normalizePlate($('#plate-input').value); });
$('#plate-input').addEventListener('keydown', event => { if (event.key === 'Enter') requestIssueTicket(); });
function issueTicket() {
  if (state.issued) return;
  const inspection = { plate: $('#plate-input').value, weight: state.weight, category: state.category };
  const errors = validateInspection(inspection);
  if (errors.plate) {
    $('#plate-error').textContent = errors.plate;
    $('#plate-error').hidden = false;
    $('#plate-input').setAttribute('aria-invalid', 'true');
    $('#plate-input').focus();
    return;
  }
  if (!state.confirmed || errors.weight || errors.category) {
    state.pendingIssue = true;
    openEditor();
    return;
  }
  // Re-read before allocating a number to include tickets issued in another tab.
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
  $('#plate-input').value = ticket.plate;
  renderInspection();
  toast(storageAvailable ? `Tiket ${ticket.number} berhasil diterbitkan.` : 'Tiket dibuat sementara. Penyimpanan browser tidak tersedia; segera cetak tiket.');
  $('#print-ticket').focus();
}
function requestIssueTicket() {
  if (navigator.locks?.request) navigator.locks.request('ferqueue-issue-ticket', issueTicket).catch(() => toast('Tiket belum diterbitkan. Silakan coba kembali.'));
  else issueTicket();
}
$('#issue-ticket').addEventListener('click', requestIssueTicket);
$('#next-vehicle').addEventListener('click', () => {
  state.issued = null;
  state.weight = null;
  state.category = '';
  state.confirmed = false;
  $('#plate-input').value = '';
  $('#plate-error').hidden = true;
  $('#snapshot-label').hidden = true;
  if (state.cameraMode === 'upload') resetCameraPreview();
  renderInspection();
  updateClock();
  $('#plate-input').focus();
  toast('Siap untuk kendaraan berikutnya. Isi ulang berat dan golongan.');
});

function renderPrint(ticket) {
  const area = $('#print-area');
  area.replaceChildren();
  const header = element('div', 'receipt-header');
  header.append(element('strong', '', 'FERQUEUE.'), element('span', '', 'GATE 01 · MASUK'));
  const title = element('div', 'receipt-title');
  title.append(element('h1', '', 'TIKET MASUK'), element('p', '', ticket.number));
  const details = element('dl', 'receipt-details');
  for (const [label, value] of [
    ['Nomor polisi', ticket.plate], ['Berat kendaraan', `${formatWeight(ticket.weight)} kg`],
    ['Golongan', `${ticket.category} · ${categoryInfo(ticket.category).label}`],
    ['Gate masuk', 'Gate 01 · Jalur masuk'], ['Waktu terbit', dateTime(ticket.createdAt)],
  ]) {
    const row = element('div');
    row.append(element('dt', '', label), element('dd', '', value));
    details.append(row);
  }
  const footer = element('div', 'receipt-footer');
  footer.append(element('strong', '', 'TIKET DEMO · DATA MANUAL'), element('div', '', 'Simpan tiket ini sebagai bukti pemeriksaan kendaraan.'), element('div', '', 'Berat dan golongan dikonfirmasi oleh operator.'), element('div', '', 'FERQUEUE — Sistem Pemeriksaan Kendaraan Pelabuhan'));
  area.append(header, title, element('div', 'receipt-plate', ticket.plate), details, footer);
}
function printTicket(ticket) {
  renderPrint(ticket);
  // Native modal dialogs participate in the browser's print top layer.
  // Close before printing so only the receipt is included.
  document.querySelectorAll('dialog[open]').forEach(dialog => dialog.close());
  window.print();
}
$('#print-ticket').addEventListener('click', () => { if (state.issued) printTicket(state.issued); });

function renderHistory() {
  const query = $('#history-search').value.trim().toUpperCase();
  const tickets = state.history.filter(ticket => ticket.plate.includes(query) || ticket.number.includes(query));
  const list = $('#history-list');
  list.replaceChildren();
  $('#history-summary').textContent = `${tickets.length} tiket${query ? ' ditemukan' : ' tersimpan'} · maksimal ${MAX_HISTORY} tiket terbaru`;
  if (!tickets.length) {
    const empty = element('div', 'history-empty');
    empty.append(icon('ticket'), element('strong', '', query ? 'Tiket tidak ditemukan' : 'Belum ada tiket yang diterbitkan'), element('p', '', query ? 'Coba kata kunci nomor polisi atau nomor tiket lainnya.' : 'Tiket yang Anda terbitkan akan tampil di sini.'));
    list.append(empty);
    return;
  }
  for (const ticket of tickets) {
    const row = element('article', 'history-item');
    const info = element('div');
    info.append(element('strong', '', ticket.plate), element('span', 'history-number', ticket.number), element('small', '', `${dateTime(ticket.createdAt)} · ${formatWeight(ticket.weight)} kg · Gol. ${ticket.category}`));
    const button = element('button', 'button button-secondary');
    button.append(icon('print'), document.createTextNode('Cetak'));
    button.setAttribute('aria-label', `Cetak tiket ${ticket.number} untuk ${ticket.plate}`);
    button.addEventListener('click', () => printTicket(ticket));
    row.append(info, button);
    list.append(row);
  }
}
$('#history-button').addEventListener('click', () => {
  try {
    const saved = parseHistory(localStorage.getItem(STORAGE_KEY));
    state.history = parseHistory(JSON.stringify([...saved, ...state.history]));
  } catch { /* Keep this session's tickets available. */ }
  $('#history-count').textContent = String(state.history.length);
  $('#history-search').value = '';
  renderHistory();
  showDialog($('#history-dialog'));
});
$('#history-search').addEventListener('input', renderHistory);
$('#help-button').addEventListener('click', () => showDialog($('#help-dialog')));
document.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
document.querySelectorAll('dialog').forEach(dialog => {
  dialog.addEventListener('click', event => {
    const rect = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close();
  });
});
$('#edit-dialog').addEventListener('close', () => { state.pendingIssue = false; });
window.addEventListener('storage', event => {
  if (event.key !== STORAGE_KEY) return;
  state.history = parseHistory(event.newValue);
  $('#history-count').textContent = String(state.history.length);
  if ($('#history-dialog').open) renderHistory();
});

function stopCamera() {
  state.stream?.getTracks().forEach(track => track.stop());
  state.stream = null;
  $('#camera-video').srcObject = null;
}
function clearUploadedImage() {
  if (state.imageUrl) URL.revokeObjectURL(state.imageUrl);
  state.imageUrl = null;
}
function resetCameraPreview() {
  stopCamera();
  clearUploadedImage();
  state.cameraMode = 'demo';
  $('#camera-image').src = './assets/camera-demo.svg';
  $('#camera-image').alt = 'Ilustrasi contoh truk di jalur pemeriksaan, bukan siaran langsung';
  $('#camera-image').hidden = false;
  $('#camera-video').hidden = true;
  updateCameraLabels();
}
function updateCameraLabels() {
  const live = state.cameraMode === 'live';
  const demo = state.cameraMode === 'demo';
  $('#camera-source-label').textContent = live ? 'KAMERA PERANGKAT' : demo ? 'PRATINJAU DEMO' : 'GAMBAR DIUNGGAH';
  $('#camera-view-label').textContent = demo ? 'TAMPAK SAMPING' : live ? 'SIARAN LANGSUNG' : 'PRATINJAU GAMBAR';
  $('#activate-camera span').textContent = live ? 'Matikan kamera' : 'Aktifkan kamera';
  $('#vehicle-summary-label').textContent = demo ? 'KENDARAAN CONTOH' : 'PEMERIKSAAN VISUAL MANUAL';
  $('#vehicle-summary').textContent = demo ? 'Truk angkutan barang' : live ? 'Kamera perangkat aktif' : 'Gambar kendaraan diunggah';
  $('#visual-badge').textContent = demo ? 'DATA CONTOH' : 'TINJAU MANUAL';
  const dimensions = $('.dimension-row');
  dimensions.children[0].querySelector('strong').replaceChildren(document.createTextNode(demo ? '7,20 ' : '— '), element('small', '', 'm'));
  dimensions.children[1].querySelector('strong').replaceChildren(document.createTextNode(demo ? '3,10 ' : '— '), element('small', '', 'm'));
  dimensions.children[2].querySelector('strong').textContent = demo ? 'Contoh simulasi' : 'Belum diukur';
  $('#camera-message').textContent = demo ? 'Kamera perangkat dapat diaktifkan secara manual.' : 'Gambar ditinjau manual. Deteksi dan pengukuran otomatis belum terhubung.';
  $('#snapshot-label').hidden = true;
}
$('#activate-camera').addEventListener('click', async () => {
  if (state.stream) { resetCameraPreview(); return; }
  if (!navigator.mediaDevices?.getUserMedia) {
    $('#camera-message').textContent = 'Kamera tidak tersedia. Buka lewat localhost atau HTTPS, atau gunakan unggah gambar.';
    toast('Kamera tidak tersedia di browser ini. Anda dapat mengunggah gambar.');
    return;
  }
  const button = $('#activate-camera');
  button.disabled = true;
  $('#camera-message').textContent = 'Menunggu izin akses kamera perangkat…';
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 960 } }, audio: false });
    stopCamera();
    clearUploadedImage();
    state.stream = stream;
    $('#camera-video').srcObject = stream;
    await $('#camera-video').play();
    state.cameraMode = 'live';
    $('#camera-video').hidden = false;
    $('#camera-image').hidden = true;
    updateCameraLabels();
    stream.getVideoTracks()[0].addEventListener('ended', resetCameraPreview, { once: true });
  } catch (error) {
    stopCamera();
    const messages = {
      NotAllowedError: 'Akses kamera belum diizinkan. Izinkan kamera melalui pengaturan browser atau unggah gambar.',
      NotFoundError: 'Tidak ada kamera yang terdeteksi. Hubungkan kamera atau unggah gambar kendaraan.',
      NotReadableError: 'Kamera sedang digunakan aplikasi lain. Tutup aplikasi tersebut atau unggah gambar.',
    };
    $('#camera-message').textContent = messages[error.name] || 'Kamera belum dapat diaktifkan. Coba kembali atau unggah gambar.';
    toast('Kamera belum aktif. Lihat petunjuk di bawah tampilan kamera.');
  } finally { button.disabled = false; }
});
$('#upload-button').addEventListener('click', () => $('#image-upload').click());
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
    $('#camera-image').src = url;
    $('#camera-image').alt = `Gambar kendaraan yang diunggah: ${file.name}`;
    $('#camera-image').hidden = false;
    $('#camera-video').hidden = true;
    updateCameraLabels();
    toast('Gambar kendaraan siap ditinjau.');
  } catch {
    URL.revokeObjectURL(url);
    toast('Gambar tidak dapat dibuka. Pilih file gambar lain.');
  }
});
$('#capture-button').addEventListener('click', async () => {
  const live = state.cameraMode === 'live';
  const media = $(live ? '#camera-video' : '#camera-image');
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
    link.download = `ferqueue-gate01-${Date.now()}.png`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    $('#snapshot-label').hidden = false;
    clearTimeout(captureTimer);
    captureTimer = setTimeout(() => { $('#snapshot-label').hidden = true; }, 3000);
    toast('Gambar pemeriksaan disimpan ke perangkat.');
  } catch { toast('Gambar belum dapat disimpan. Silakan coba lagi.'); }
});
$('#expand-camera').addEventListener('click', async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else if ($('#camera-viewport').requestFullscreen) await $('#camera-viewport').requestFullscreen();
    else toast('Layar penuh tidak tersedia di browser ini.');
  } catch { toast('Browser belum mengizinkan tampilan layar penuh.'); }
});
window.addEventListener('pagehide', () => { stopCamera(); clearUploadedImage(); });
window.addEventListener('pageshow', event => { if (event.persisted) resetCameraPreview(); });

renderInspection();
updateClock();
setInterval(updateClock, 1000);
