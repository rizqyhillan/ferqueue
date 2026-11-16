const video = document.querySelector('#camera-video');
const uploadedImage = document.querySelector('#camera-image');
const viewport = document.querySelector('#camera-viewport');
const coinButton = document.querySelector('#select-coin');
const clearCoinButton = document.querySelector('#clear-coin');
const coinStatus = document.querySelector('#coin-status');
const frame = document.createElement('canvas');
const frameContext = frame.getContext('2d');
const overlay = document.createElement('canvas');
const context = overlay.getContext('2d');

Object.assign(overlay.style, {
  position: 'absolute',
  inset: '0',
  width: '100%',
  height: '100%',
  pointerEvents: 'none',
  zIndex: '1',
});
overlay.hidden = true;
viewport.append(overlay);

let currentSource = null;
let displayedResult = null;
let lastUpload = null;
let coinRegion = null;
let selectingCoin = false;
let firstCorner = null;

function frameSource() {
  const stream = video.srcObject;
  if (stream && !video.hidden && video.readyState >= 2 && video.videoWidth &&
      stream.getVideoTracks().some(track => track.readyState === 'live')) {
    return { media: video, key: stream, width: video.videoWidth, height: video.videoHeight };
  }
  if (!uploadedImage.hidden && uploadedImage.dataset.pcv === 'true' && uploadedImage.naturalWidth) {
    return { media: uploadedImage, key: uploadedImage.src, width: uploadedImage.naturalWidth, height: uploadedImage.naturalHeight };
  }
  return null;
}

function sameSource(a, b) {
  return a?.key === b?.key && a?.width === b?.width && a?.height === b?.height;
}

function imageBounds(source, width, height) {
  const scale = Math.min(width / source.width, height / source.height);
  const imageWidth = source.width * scale;
  const imageHeight = source.height * scale;
  return {
    x: (width - imageWidth) / 2, y: (height - imageHeight) / 2,
    width: imageWidth, height: imageHeight,
  };
}

function drawOverlay() {
  overlay.hidden = document.hidden || !currentSource || !(displayedResult || coinRegion || firstCorner);
  if (overlay.hidden) return;

  overlay.width = viewport.clientWidth;
  overlay.height = viewport.clientHeight;
  const bounds = imageBounds(currentSource, overlay.width, overlay.height);
  const xAt = x => bounds.x + x * bounds.width;
  const yAt = y => bounds.y + y * bounds.height;
  context.font = 'bold 15px sans-serif';
  context.lineWidth = 3;

  for (const item of displayedResult?.detections ?? []) {
    const [y1, x1, y2, x2] = item.box;
    const x = xAt(x1);
    const y = yAt(y1);
    const text = item.class_name + ' ' + Math.round(item.confidence * 100) + '%';

    context.strokeStyle = '#22c55e';
    context.strokeRect(x, y, (x2 - x1) * bounds.width, (y2 - y1) * bounds.height);
    const labelY = Math.max(20, y);
    context.fillStyle = '#111';
    context.fillRect(x, labelY - 20, context.measureText(text).width + 10, 22);
    context.fillStyle = '#fff';
    context.fillText(text, x + 5, labelY - 4);
  }

  context.strokeStyle = '#fbbf24';
  context.fillStyle = '#fbbf24';
  if (coinRegion) {
    const [y1, x1, y2, x2] = coinRegion;
    context.setLineDash([5, 4]);
    context.strokeRect(xAt(x1), yAt(y1), (x2 - x1) * bounds.width, (y2 - y1) * bounds.height);
    context.setLineDash([]);
  }
  if (firstCorner) {
    const [y, x] = firstCorner;
    context.fillRect(xAt(x) - 3, yAt(y) - 3, 6, 6);
  }
  const coin = displayedResult?.calibration?.coin;
  if (coin) {
    const [y, x] = coin.center;
    const radius = coin.diameter_px * bounds.width / (2 * frame.width);
    context.beginPath();
    context.arc(xAt(x), yAt(y), radius, 0, 2 * Math.PI);
    context.stroke();
  }
}

function showMeasurement(calibration) {
  const measurement = calibration?.measurement;
  const estimated = measurement?.status === 'estimated' ? measurement : null;
  window.dispatchEvent(new CustomEvent('ferqueue:camera-measurement', {
    detail: { active: Boolean(coinRegion || selectingCoin), estimate: estimated },
  }));

  const messages = {
    coin_region_small: 'Area koin terlalu kecil. Tandai ulang dengan sedikit ruang di sekeliling koin.',
    coin_not_found: 'Koin belum terbaca. Pastikan seluruh tepinya terlihat, menghadap kamera, dan kontras dengan latar.',
    coin_ambiguous: 'Ada lebih dari satu lingkaran di area koin. Persempit area pilihan.',
    unavailable: 'OpenCV belum tersedia di environment PCV.',
    multiple_vehicles: 'Sisakan satu kendaraan di dalam frame.',
    vehicle_clipped: 'Pastikan seluruh kendaraan masuk ke dalam frame.',
    coin_overlaps_vehicle: 'Geser koin ke luar kotak kendaraan.',
    no_vehicle: displayedResult?.calibration_only ? 'Skala siap diuji. Jalankan model untuk mengukur kendaraan.' : 'Menunggu kotak kendaraan.',
  };
  let text = 'Aktifkan kamera atau unggah foto tampak samping untuk menandai koin.';
  if (currentSource) text = 'Tandai area koin yang menghadap kamera dan sebidang dengan sisi kendaraan.';
  if (coinRegion) text = messages[calibration?.status] ?? 'Membaca diameter koin 50 yen…';
  if (calibration?.coin) {
    const scale = calibration.coin.mm_per_px.toLocaleString('id-ID', { maximumFractionDigits: 3 });
    text = `Skala ${scale} mm/px`;
    if (!estimated) text += ` · ${messages[measurement.status]}`;
  }
  if (selectingCoin) {
    text = firstCorner ? 'Klik sudut berlawanan pada kotak di sekeliling koin.' : 'Klik sudut pertama pada kotak di sekeliling koin.';
  }
  if (coinStatus.textContent !== text) coinStatus.textContent = text;
}

function updateSelection() {
  coinButton.disabled = !currentSource;
  coinButton.setAttribute('aria-pressed', String(selectingCoin));
  coinButton.textContent = selectingCoin ? 'Batal tandai' : 'Tandai koin 50 yen';
  clearCoinButton.hidden = !coinRegion || selectingCoin;
  viewport.classList.toggle('selecting-coin', selectingCoin);
  showMeasurement(null);
  drawOverlay();
}

function resetCalibration(source = null) {
  currentSource = source;
  displayedResult = null;
  lastUpload = null;
  coinRegion = null;
  selectingCoin = false;
  firstCorner = null;
  updateSelection();
}

window.addEventListener('ferqueue:camera-reset', () => resetCalibration());
new ResizeObserver(drawOverlay).observe(viewport);

coinButton.addEventListener('click', () => {
  selectingCoin = !selectingCoin;
  firstCorner = null;
  displayedResult = null;
  lastUpload = null;
  updateSelection();
});

clearCoinButton.addEventListener('click', () => {
  coinRegion = null;
  displayedResult = null;
  lastUpload = null;
  updateSelection();
});

viewport.addEventListener('click', event => {
  if (!selectingCoin || !currentSource) return;
  const viewportRect = viewport.getBoundingClientRect();
  const bounds = imageBounds(currentSource, viewportRect.width, viewportRect.height);
  const x = (event.clientX - viewportRect.left - bounds.x) / bounds.width;
  const y = (event.clientY - viewportRect.top - bounds.y) / bounds.height;
  if (!(0 <= x && x <= 1 && 0 <= y && y <= 1)) return;

  if (!firstCorner) {
    firstCorner = [y, x];
  } else {
    const [startY, startX] = firstCorner;
    if (Math.abs(x - startX) < .01 || Math.abs(y - startY) < .01) return;
    coinRegion = [Math.min(startY, y), Math.min(startX, x), Math.max(startY, y), Math.max(startX, x)];
    selectingCoin = false;
    firstCorner = null;
    lastUpload = null;
  }
  updateSelection();
});

async function tick() {
  const source = frameSource();
  if (!sameSource(source, currentSource)) resetCalibration(source);
  if (!source || selectingCoin || document.hidden || source.key === lastUpload) {
    drawOverlay();
    setTimeout(tick, 250);
    return;
  }

  const region = coinRegion;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  const stillCurrent = () => !selectingCoin && region === coinRegion && sameSource(source, frameSource());

  try {
    const ratio = Math.min(1, 640 / Math.max(source.width, source.height));
    frame.width = Math.max(1, Math.round(source.width * ratio));
    frame.height = Math.max(1, Math.round(source.height * ratio));
    frameContext.drawImage(source.media, 0, 0, frame.width, frame.height);
    const blob = await new Promise(resolve => frame.toBlob(resolve, 'image/jpeg', 0.8));
    if (!blob) throw new Error('Frame kamera belum tersedia');

    const headers = { 'Content-Type': 'image/jpeg' };
    if (region) headers['X-Coin-Region'] = region.join(',');
    const response = await fetch('/api/detect', {
      method: 'POST', headers, body: blob, signal: controller.signal,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'API gagal');
    if (!stillCurrent()) return;
    if (source.media === uploadedImage) lastUpload = source.key;

    displayedResult = data;
    window.dispatchEvent(new CustomEvent('ferqueue:cv-result', { detail: data }));
    drawOverlay();
    showMeasurement(data.calibration);

    document.querySelector('#vehicle-summary-label').textContent = 'HASIL DETEKSI';
    document.querySelector('#visual-badge').textContent = data.calibration_only ? 'KALIBRASI KOIN' : 'DETEKSI MODEL';
    document.querySelector('#camera-message').textContent = data.calibration_only
      ? 'Mode kalibrasi koin aktif.'
      : 'Deteksi aktif · ' + data.inference_ms + ' ms per frame';
  } catch (error) {
    if (stillCurrent()) {
      displayedResult = null;
      drawOverlay();
      showMeasurement(null);
      if (region) coinStatus.textContent = 'Kalibrasi menunggu API PCV.';
      window.dispatchEvent(new CustomEvent('ferqueue:cv-error'));
      document.querySelector('#vehicle-summary').textContent = 'Deteksi belum tersedia';
      document.querySelector('#visual-badge').textContent = 'API TERPUTUS';
      document.querySelector('#camera-message').textContent = 'Periksa terminal API: ' + error.message;
    }
  } finally {
    clearTimeout(timeout);
    setTimeout(tick, 250);
  }
}

tick();
