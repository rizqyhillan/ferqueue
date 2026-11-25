/**
 * live_detection.js — FERQUEUE Web Monitoring
 * Mengirim frame kamera / gambar upload ke /api/detect, menggambar bounding-box,
 * serta menangani kalibrasi & pengukuran dimensi berbasis trigonometri geometri kamera.
 */

const video = document.querySelector('#camera-video');
const uploadedImage = document.querySelector('#camera-image') || document.querySelector('#camera-feed');
const viewport = document.querySelector('#camera-viewport') || document.querySelector('.mon-cam-viewport');

const geoStatus = document.querySelector('#geo-status');
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
};

if (!video || !uploadedImage || !viewport) {
  console.warn('[live_detection] Elemen DOM kamera tidak ditemukan — module dilewati.');
} else {
  const hasTrigUI = Boolean(geoDPerpInput && geoDParallelInput && geoFocalNormInput);
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

  // Mode kalibrasi geometri segitiga & jarak kamera (trigonometri)
  let geo = loadSavedGeometry();
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
      };
    } catch {
      return { ...DEFAULT_GEO };
    }
  }

  function saveGeometry() {
    try {
      localStorage.setItem(GEO_STORAGE_KEY, JSON.stringify(geo));
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
    const hasVisual = Boolean(displayedResult || geoFirstPoint || geoRefLine);
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
      const text = String(item.class_name || '');

      context.strokeStyle = '#22c55e';
      context.strokeRect(x, y, (x2 - x1) * bounds.width, (y2 - y1) * bounds.height);
      if (text) {
        const labelY = Math.max(20, y);
        context.fillStyle = '#111';
        context.fillRect(x, labelY - 20, context.measureText(text).width + 10, 22);
        context.fillStyle = '#fff';
        context.fillText(text, x + 5, labelY - 4);
      }
    }

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

  function showMeasurement(calibration) {
    const measurement = calibration?.measurement;
    const estimated = measurement?.status === 'estimated' ? measurement : null;
    const active = Boolean(currentGeometryHeader() || calibratingGeo);
    window.dispatchEvent(new CustomEvent('ferqueue:camera-measurement', {
      detail: { active, estimate: estimated },
    }));

    if (!geoStatus) return;

    const messages = {
      multiple_vehicles: 'Sisakan satu kendaraan di dalam frame.',
      vehicle_clipped: 'Pastikan seluruh kendaraan masuk ke dalam frame.',
      vehicle_too_small: 'Kotak kendaraan terlalu kecil untuk koreksi sudut. Periksa kalibrasi panjang fokus.',
      no_vehicle: displayedResult?.calibration_only ? 'Skala siap diuji. Jalankan model untuk mengukur kendaraan.' : 'Menunggu kotak kendaraan.',
    };

    let text = '';
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

    if (geoStatus.textContent !== text) geoStatus.textContent = text;
  }

  function updateSelection() {
    if (calibrateGeoButton) {
      calibrateGeoButton.disabled = !currentSource;
      calibrateGeoButton.setAttribute('aria-pressed', String(calibratingGeo));
      calibrateGeoButton.textContent = calibratingGeo ? 'Batal kalibrasi' : 'Kalibrasi acuan (2 titik)';
    }
    if (clearGeoButton) {
      clearGeoButton.hidden = !geo.focalNorm || calibratingGeo;
    }
    viewport.classList.toggle('calibrating-geo', calibratingGeo);
    showMeasurement(null);
    drawOverlay();
  }

  function resetCalibration(source = null) {
    currentSource = source;
    displayedResult = null;
    lastUpload = null;
    calibratingGeo = false;
    geoFirstPoint = null;
    geoRefLine = null;
    updateSelection();
  }

  syncGeoInputsFromState();
  window.addEventListener('ferqueue:camera-reset', () => resetCalibration());
  new ResizeObserver(drawOverlay).observe(viewport);

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

  viewport.addEventListener('click', event => {
    if (!calibratingGeo || !currentSource) return;
    const viewportRect = viewport.getBoundingClientRect();
    const bounds = imageBounds(currentSource, viewportRect.width, viewportRect.height);
    const x = (event.clientX - viewportRect.left - bounds.x) / bounds.width;
    const y = (event.clientY - viewportRect.top - bounds.y) / bounds.height;
    if (!(0 <= x && x <= 1 && 0 <= y && y <= 1)) return;

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
        if (geoStatus) geoStatus.textContent = 'Isi jarak segitiga dan lebar acuan (> 0) sebelum kalibrasi.';
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
  });

  async function tick() {
    const source = frameSource();
    if (!sameSource(source, currentSource)) resetCalibration(source);
    if (!source || calibratingGeo || document.hidden || source.key === lastUpload) {
      drawOverlay();
      setTimeout(tick, 250);
      return;
    }

    const geometryHeader = currentGeometryHeader();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    const stillCurrent = () => (
      !calibratingGeo &&
      geometryHeader === currentGeometryHeader() &&
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
      if (geometryHeader) headers['X-Camera-Geometry'] = geometryHeader;
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
        if (geometryHeader && geoStatus) geoStatus.textContent = 'Kalibrasi menunggu API PCV.';
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
