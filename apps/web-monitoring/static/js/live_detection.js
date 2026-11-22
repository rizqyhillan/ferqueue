/**
 * live_detection.js — FERQUEUE Web Monitoring
 * Mengirim frame kamera / gambar upload ke /api/detect, menggambar bounding-box,
 * serta menangani kalibrasi & pengukuran dimensi (geometri segitiga kamera & koin 50 yen).
 */

const video = document.querySelector('#camera-video');
const uploadedImage = document.querySelector('#camera-image') || document.querySelector('#camera-feed');
const viewport = document.querySelector('#camera-viewport') || document.querySelector('.mon-cam-viewport');
const coinButton = document.querySelector('#select-coin');
const clearCoinButton = document.querySelector('#clear-coin');
const coinStatus = document.querySelector('#coin-status');

const modeTrigButton = document.querySelector('#cal-mode-trigonometry');
const modeCoinButton = document.querySelector('#cal-mode-coin');
const panelTrig = document.querySelector('#cal-panel-trigonometry');
const panelCoin = document.querySelector('#cal-panel-coin');
const geoSummary = document.querySelector('#geo-summary');
const geoDPerpInput = document.querySelector('#geo-d-perp');
const geoDParallelInput = document.querySelector('#geo-d-parallel');
const geoRefCmInput = document.querySelector('#geo-ref-cm');
const geoFocalNormInput = document.querySelector('#geo-focal-norm');
const calibrateGeoButton = document.querySelector('#calibrate-geometry');
const clearGeoButton = document.querySelector('#clear-geometry');

const GEO_STORAGE_KEY = 'ferqueue.camera_geometry.v1';
const DEFAULT_GEO = {
  dPerpCm: 27.7,
  dParallelCm: 14.3,
  refCm: 10.0,
  focalNorm: null,
  mode: 'trigonometry',
};

if (!video || !uploadedImage || !viewport) {
  console.warn('[live_detection] Elemen DOM kamera tidak ditemukan — module dilewati.');
} else {
  const hasTrigUI = Boolean(modeTrigButton && panelTrig && geoDPerpInput && geoDParallelInput && geoFocalNormInput);
  const frame = document.createElement('canvas');
  const frameContext = frame.getContext('2d');
  const overlay = document.createElement('canvas');
  const context = overlay.getContext('2d');

  Object.assign(video.style, {
    objectFit: 'contain',
    objectPosition: 'center',
  });

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

  // Mode kalibrasi koin 50 yen
  let coinRegion = null;
  let selectingCoin = false;
  let firstCorner = null;

  // Mode kalibrasi geometri segitiga & jarak kamera
  let geo = loadSavedGeometry();
  let calibrationMode = hasTrigUI ? (geo.mode === 'coin' ? 'coin' : 'trigonometry') : 'coin';
  let calibratingGeo = false;
  let geoFirstPoint = null;
  let geoRefLine = null;

  function loadSavedGeometry() {
    try {
      const raw = localStorage.getItem(GEO_STORAGE_KEY);
      if (!raw) return { ...DEFAULT_GEO };
      const parsed = JSON.parse(raw);
      return {
        dPerpCm: Number.isFinite(parsed.dPerpCm) && parsed.dPerpCm > 0 ? parsed.dPerpCm : DEFAULT_GEO.dPerpCm,
        dParallelCm: Number.isFinite(parsed.dParallelCm) && parsed.dParallelCm >= 0 ? parsed.dParallelCm : DEFAULT_GEO.dParallelCm,
        refCm: Number.isFinite(parsed.refCm) && parsed.refCm > 0 ? parsed.refCm : DEFAULT_GEO.refCm,
        focalNorm: Number.isFinite(parsed.focalNorm) && parsed.focalNorm > 0 ? parsed.focalNorm : null,
        mode: parsed.mode === 'coin' ? 'coin' : 'trigonometry',
      };
    } catch {
      return { ...DEFAULT_GEO };
    }
  }

  function saveGeometry() {
    try {
      localStorage.setItem(GEO_STORAGE_KEY, JSON.stringify({ ...geo, mode: calibrationMode }));
    } catch {
      // Abaikan jika penyimpanan browser tidak tersedia.
    }
  }

  function formatId(value, digits = 2) {
    return value.toLocaleString('id-ID', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  function syncGeoInputsFromState() {
    if (!hasTrigUI) return;
    geoDPerpInput.value = String(geo.dPerpCm);
    geoDParallelInput.value = String(geo.dParallelCm);
    if (geoRefCmInput) geoRefCmInput.value = String(geo.refCm);
    geoFocalNormInput.value = geo.focalNorm ? String(geo.focalNorm) : '';
    updateGeoSummary();
  }

  function readGeoFromInputs() {
    if (!hasTrigUI) return;
    const dPerp = Number(geoDPerpInput.value);
    const dParallel = Number(geoDParallelInput.value);
    const refCm = geoRefCmInput ? Number(geoRefCmInput.value) : geo.refCm;
    const focalRaw = geoFocalNormInput.value.trim();
    const focalNorm = focalRaw ? Number(focalRaw) : null;
    geo = {
      ...geo,
      dPerpCm: Number.isFinite(dPerp) && dPerp > 0 ? dPerp : NaN,
      dParallelCm: Number.isFinite(dParallel) && dParallel >= 0 ? dParallel : NaN,
      refCm: Number.isFinite(refCm) && refCm > 0 ? refCm : NaN,
      focalNorm: focalNorm !== null && Number.isFinite(focalNorm) && focalNorm > 0 ? focalNorm : null,
    };
    updateGeoSummary();
    saveGeometry();
  }

  function updateGeoSummary() {
    if (!geoSummary) return;
    if (!(geo.dPerpCm > 0 && geo.dParallelCm >= 0)) {
      geoSummary.textContent = 'Isi jarak segitiga valid';
      return;
    }
    const distance = Math.hypot(geo.dPerpCm, geo.dParallelCm);
    const yawDeg = Math.atan2(geo.dParallelCm, geo.dPerpCm) * (180 / Math.PI);
    geoSummary.textContent = `D = ${formatId(distance, 2)} cm · θ = ${formatId(yawDeg, 2)}°`;
  }

  function currentGeometryHeader() {
    if (calibrationMode !== 'trigonometry') return null;
    if (!(geo.dPerpCm > 0 && geo.dParallelCm >= 0 && geo.focalNorm > 0)) return null;
    return `${geo.dPerpCm},${geo.dParallelCm},${geo.focalNorm}`;
  }

  function setLabel(selector, text) {
    const el = document.querySelector(selector);
    if (el) el.textContent = text;
  }

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
      x: (width - imageWidth) / 2,
      y: (height - imageHeight) / 2,
      width: imageWidth,
      height: imageHeight,
    };
  }

  function drawOverlay() {
    const hasVisual = Boolean(
      displayedResult ||
      (calibrationMode === 'coin' && (coinRegion || firstCorner)) ||
      (calibrationMode === 'trigonometry' && (geoFirstPoint || geoRefLine))
    );
    overlay.hidden = document.hidden || !currentSource || !hasVisual;
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
      const text = `${item.class_name} ${Math.round(item.confidence * 100)}%`;

      context.strokeStyle = '#22c55e';
      context.strokeRect(x, y, (x2 - x1) * bounds.width, (y2 - y1) * bounds.height);
      const labelY = Math.max(20, y);
      context.fillStyle = '#111';
      context.fillRect(x, labelY - 20, context.measureText(text).width + 10, 22);
      context.fillStyle = '#fff';
      context.fillText(text, x + 5, labelY - 4);
    }

    if (calibrationMode === 'coin') {
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
    } else if (calibrationMode === 'trigonometry') {
      context.strokeStyle = '#38bdf8';
      context.fillStyle = '#38bdf8';
      if (geoFirstPoint) {
        const [y, x] = geoFirstPoint;
        context.beginPath();
        context.arc(xAt(x), yAt(y), 5, 0, 2 * Math.PI);
        context.fill();
      }
      if (geoRefLine) {
        const [y1, x1, y2, x2] = geoRefLine;
        context.setLineDash([6, 4]);
        context.beginPath();
        context.moveTo(xAt(x1), yAt(y1));
        context.lineTo(xAt(x2), yAt(y2));
        context.stroke();
        context.setLineDash([]);
        for (const [py, px] of [[y1, x1], [y2, x2]]) {
          context.beginPath();
          context.arc(xAt(px), yAt(py), 4, 0, 2 * Math.PI);
          context.fill();
        }
      }
    }
  }

  function showMeasurement(calibration) {
    const measurement = calibration?.measurement;
    const estimated = measurement?.status === 'estimated' ? measurement : null;
    const active = calibrationMode === 'trigonometry'
      ? Boolean(currentGeometryHeader() || calibratingGeo)
      : Boolean(coinRegion || selectingCoin);
    window.dispatchEvent(new CustomEvent('ferqueue:camera-measurement', {
      detail: { active, estimate: estimated },
    }));

    if (!coinStatus) return;

    const messages = {
      coin_region_small: 'Area koin terlalu kecil. Tandai ulang dengan sedikit ruang di sekeliling koin.',
      coin_not_found: 'Koin belum terbaca. Pastikan seluruh tepinya terlihat, menghadap kamera, dan kontras dengan latar.',
      coin_ambiguous: 'Ada lebih dari satu lingkaran di area koin. Persempit area pilihan.',
      unavailable: 'OpenCV belum tersedia di environment PCV.',
      multiple_vehicles: 'Sisakan satu kendaraan di dalam frame.',
      vehicle_clipped: 'Pastikan seluruh kendaraan masuk ke dalam frame.',
      coin_overlaps_vehicle: 'Geser koin ke luar kotak kendaraan.',
      vehicle_too_small: 'Kotak kendaraan terlalu kecil untuk koreksi sudut. Periksa kalibrasi panjang fokus.',
      no_vehicle: displayedResult?.calibration_only ? 'Skala siap diuji. Jalankan model untuk mengukur kendaraan.' : 'Menunggu kotak kendaraan.',
    };

    let text = '';
    if (calibrationMode === 'trigonometry') {
      if (!currentSource) {
        text = geo.focalNorm
          ? 'Kalibrasi jarak tersimpan. Aktifkan kamera atau unggah foto untuk mulai mengukur.'
          : 'Aktifkan kamera atau unggah foto untuk kalibrasi jarak kamera.';
      } else if (calibratingGeo) {
        text = geoFirstPoint
          ? 'Klik ujung kedua objek acuan di gambar.'
          : 'Klik ujung pertama objek acuan di titik kendaraan (menghadap lurus ke lensa).';
      } else if (!currentGeometryHeader()) {
        text = 'Letakkan penggaris/kartu acuan di titik kendaraan lalu klik "Kalibrasi acuan (2 titik)" (cukup 1×).';
      } else if (calibration?.geometry) {
        const g = calibration.geometry;
        const scale = g.mm_per_px.toLocaleString('id-ID', { maximumFractionDigits: 3 });
        text = `Jarak ${formatId(g.distance_cm, 2)} cm · θ ${formatId(g.yaw_deg, 2)}° · Skala ${scale} mm/px`;
        if (!estimated && measurement?.status) text += ` · ${messages[measurement.status] ?? measurement.status}`;
      } else {
        text = 'Menghitung dimensi dari geometri kamera…';
      }
    } else {
      text = 'Aktifkan kamera atau unggah foto tampak samping untuk menandai koin.';
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
    }

    if (coinStatus.textContent !== text) coinStatus.textContent = text;
  }

  function updateSelection() {
    if (hasTrigUI) {
      const isTrig = calibrationMode === 'trigonometry';
      modeTrigButton.classList.toggle('is-active', isTrig);
      modeTrigButton.setAttribute('aria-selected', String(isTrig));
      if (modeCoinButton) {
        modeCoinButton.classList.toggle('is-active', !isTrig);
        modeCoinButton.setAttribute('aria-selected', String(!isTrig));
      }
      panelTrig.hidden = !isTrig;
      if (panelCoin) panelCoin.hidden = isTrig;
      if (geoSummary) geoSummary.hidden = !isTrig;
      if (calibrateGeoButton) {
        calibrateGeoButton.disabled = !currentSource;
        calibrateGeoButton.setAttribute('aria-pressed', String(calibratingGeo));
        calibrateGeoButton.textContent = calibratingGeo ? 'Batal kalibrasi' : 'Kalibrasi acuan (2 titik)';
      }
      if (clearGeoButton) {
        clearGeoButton.hidden = !geo.focalNorm || calibratingGeo;
      }
    }
    if (coinButton) {
      coinButton.disabled = !currentSource;
      coinButton.setAttribute('aria-pressed', String(selectingCoin));
      coinButton.textContent = selectingCoin ? 'Batal tandai' : 'Tandai koin 50 yen';
    }
    if (clearCoinButton) {
      clearCoinButton.hidden = !coinRegion || selectingCoin;
    }
    viewport.classList.toggle('selecting-coin', selectingCoin || calibratingGeo);
    showMeasurement(null);
    drawOverlay();
  }

  function setCalibrationMode(mode) {
    if (!hasTrigUI || calibrationMode === mode) return;
    calibrationMode = mode;
    selectingCoin = false;
    firstCorner = null;
    calibratingGeo = false;
    geoFirstPoint = null;
    displayedResult = null;
    lastUpload = null;
    saveGeometry();
    updateSelection();
  }

  function resetCalibration(source = null) {
    currentSource = source;
    displayedResult = null;
    lastUpload = null;
    coinRegion = null;
    selectingCoin = false;
    firstCorner = null;
    calibratingGeo = false;
    geoFirstPoint = null;
    geoRefLine = null;
    updateSelection();
  }

  syncGeoInputsFromState();
  window.addEventListener('ferqueue:camera-reset', () => resetCalibration());
  new ResizeObserver(drawOverlay).observe(viewport);

  if (modeTrigButton) modeTrigButton.addEventListener('click', () => setCalibrationMode('trigonometry'));
  if (modeCoinButton) modeCoinButton.addEventListener('click', () => setCalibrationMode('coin'));

  for (const input of [geoDPerpInput, geoDParallelInput, geoRefCmInput, geoFocalNormInput].filter(Boolean)) {
    input.addEventListener('input', () => {
      readGeoFromInputs();
      displayedResult = null;
      lastUpload = null;
      updateSelection();
    });
  }

  if (calibrateGeoButton) {
    calibrateGeoButton.addEventListener('click', () => {
      if (!currentSource) return;
      calibratingGeo = !calibratingGeo;
      geoFirstPoint = null;
      if (calibratingGeo) geoRefLine = null;
      displayedResult = null;
      lastUpload = null;
      updateSelection();
    });
  }

  if (clearGeoButton) {
    clearGeoButton.addEventListener('click', () => {
      geo.focalNorm = null;
      geoRefLine = null;
      if (geoFocalNormInput) geoFocalNormInput.value = '';
      saveGeometry();
      displayedResult = null;
      lastUpload = null;
      updateSelection();
    });
  }

  if (coinButton) {
    coinButton.addEventListener('click', () => {
      selectingCoin = !selectingCoin;
      firstCorner = null;
      displayedResult = null;
      lastUpload = null;
      updateSelection();
    });
  }

  if (clearCoinButton) {
    clearCoinButton.addEventListener('click', () => {
      coinRegion = null;
      displayedResult = null;
      lastUpload = null;
      updateSelection();
    });
  }

  viewport.addEventListener('click', event => {
    if ((!selectingCoin && !calibratingGeo) || !currentSource) return;
    const viewportRect = viewport.getBoundingClientRect();
    const bounds = imageBounds(currentSource, viewportRect.width, viewportRect.height);
    const x = (event.clientX - viewportRect.left - bounds.x) / bounds.width;
    const y = (event.clientY - viewportRect.top - bounds.y) / bounds.height;
    if (!(0 <= x && x <= 1 && 0 <= y && y <= 1)) return;

    if (calibratingGeo) {
      if (!geoFirstPoint) {
        geoFirstPoint = [y, x];
      } else {
        const [startY, startX] = geoFirstPoint;
        const dx = x - startX;
        const dy = (y - startY) * (currentSource.height / currentSource.width);
        const distNormW = Math.hypot(dx, dy);
        if (distNormW < 0.01) return;
        readGeoFromInputs();
        if (!(geo.dPerpCm > 0 && geo.dParallelCm >= 0 && geo.refCm > 0)) {
          if (coinStatus) coinStatus.textContent = 'Isi jarak segitiga dan lebar acuan (> 0) sebelum kalibrasi.';
          return;
        }
        const distanceCm = Math.hypot(geo.dPerpCm, geo.dParallelCm);
        geo.focalNorm = Number(((distNormW * distanceCm) / geo.refCm).toFixed(6));
        if (geoFocalNormInput) geoFocalNormInput.value = String(geo.focalNorm);
        geoRefLine = [startY, startX, y, x];
        calibratingGeo = false;
        geoFirstPoint = null;
        lastUpload = null;
        saveGeometry();
      }
      updateSelection();
      return;
    }

    if (!firstCorner) {
      firstCorner = [y, x];
    } else {
      const [startY, startX] = firstCorner;
      if (Math.abs(x - startX) < 0.01 || Math.abs(y - startY) < 0.01) return;
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
    if (!source || selectingCoin || calibratingGeo || document.hidden || source.key === lastUpload) {
      drawOverlay();
      setTimeout(tick, 250);
      return;
    }

    const mode = calibrationMode;
    const region = mode === 'coin' ? coinRegion : null;
    const geometryHeader = mode === 'trigonometry' ? currentGeometryHeader() : null;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    const stillCurrent = () => (
      !selectingCoin &&
      !calibratingGeo &&
      mode === calibrationMode &&
      (mode === 'coin' ? region === coinRegion : geometryHeader === currentGeometryHeader()) &&
      sameSource(source, frameSource())
    );

    try {
      const ratio = Math.min(1, 640 / Math.max(source.width, source.height));
      frame.width = Math.max(1, Math.round(source.width * ratio));
      frame.height = Math.max(1, Math.round(source.height * ratio));
      frameContext.drawImage(source.media, 0, 0, frame.width, frame.height);
      const blob = await new Promise(resolve => frame.toBlob(resolve, 'image/jpeg', 0.8));
      if (!blob) throw new Error('Frame kamera belum tersedia');

      const headers = { 'Content-Type': 'image/jpeg' };
      if (region) headers['X-Coin-Region'] = region.join(',');
      else if (geometryHeader) headers['X-Camera-Geometry'] = geometryHeader;
      const response = await fetch('/api/detect', {
        method: 'POST',
        headers,
        body: blob,
        signal: controller.signal,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'API gagal');
      if (!stillCurrent()) return;
      if (source.media === uploadedImage) lastUpload = source.key;

      displayedResult = data;
      window.dispatchEvent(new CustomEvent('ferqueue:cv-result', { detail: data }));
      drawOverlay();
      showMeasurement(data.calibration);

      setLabel('#vehicle-summary-label', 'HASIL DETEKSI');
      setLabel('#vehicle-summary',
        data.detections.length
          ? [...new Set(data.detections.map(item => item.class_name))].join(', ')
          : 'Belum ada kendaraan terdeteksi'
      );
      setLabel('#visual-badge', data.calibration_only ? 'KALIBRASI' : 'DETEKSI MODEL');
      setLabel('#camera-message', data.calibration_only
        ? 'Mode kalibrasi aktif.'
        : `Deteksi aktif · ${data.inference_ms} ms per frame`);
    } catch (error) {
      if (stillCurrent()) {
        displayedResult = null;
        drawOverlay();
        showMeasurement(null);
        if ((region || geometryHeader) && coinStatus) coinStatus.textContent = 'Kalibrasi menunggu API PCV.';
        window.dispatchEvent(new CustomEvent('ferqueue:cv-error'));
        setLabel('#vehicle-summary', 'Deteksi belum tersedia');
        setLabel('#visual-badge', 'API TERPUTUS');
        setLabel('#camera-message', `Periksa terminal API: ${error.message}`);
      }
    } finally {
      clearTimeout(timeout);
      setTimeout(tick, 250);
    }
  }

  updateSelection();
  tick();
}
