/**
 * live_detection.js — FERQUEUE Web Monitoring
 * Pindahan dari static/live_detection.js.
 * Mengirim frame kamera / gambar upload ke /api/detect dan menggambar
 * bounding-box hasil deteksi di atas overlay canvas.
 *
 * Dependensi DOM: #camera-video, #camera-image, #camera-viewport,
 *                 #vehicle-summary-label, #vehicle-summary,
 *                 #visual-badge, #camera-message
 */

const video        = document.querySelector('#camera-video');
const uploadedImage = document.querySelector('#camera-image');
const viewport     = document.querySelector('#camera-viewport');

// Pastikan elemen wajib tersedia sebelum berjalan
if (!video || !uploadedImage || !viewport) {
  console.warn('[live_detection] Elemen DOM kamera tidak ditemukan — module dilewati.');
} else {
  let lastUpload = null;

  // Reset state saat kamera di-reset dari monitoring.js
  window.addEventListener('ferqueue:camera-reset', () => {
    lastUpload = null;
    overlay.hidden = true;
  });

  // Gaya dasar video
  Object.assign(video.style, {
    objectFit: 'contain',
    objectPosition: 'center',
  });

  // Canvas untuk capture frame (tidak terlihat)
  const frame = document.createElement('canvas');
  const frameContext = frame.getContext('2d');

  // Canvas overlay bounding-box (di atas viewport)
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

  /**
   * Gambar bounding-box hasil deteksi ke overlay canvas.
   * @param {Array<{box: number[], class_name: string, confidence: number}>} detections
   */
  function drawDetections(detections) {
    overlay.width  = viewport.clientWidth;
    overlay.height = viewport.clientHeight;

    const scale   = Math.min(overlay.width / frame.width, overlay.height / frame.height);
    const offsetX = (overlay.width  - frame.width  * scale) / 2;
    const offsetY = (overlay.height - frame.height * scale) / 2;

    context.font      = 'bold 15px sans-serif';
    context.lineWidth = 3;

    for (const item of detections) {
      const [y1, x1, y2, x2] = item.box;
      const x      = offsetX + x1 * frame.width  * scale;
      const y      = offsetY + y1 * frame.height * scale;
      const width  = (x2 - x1) * frame.width  * scale;
      const height = (y2 - y1) * frame.height * scale;
      const text   = `${item.class_name} ${Math.round(item.confidence * 100)}%`;

      context.strokeStyle = '#22c55e';
      context.strokeRect(x, y, width, height);

      const labelY = Math.max(20, y);
      context.fillStyle = '#111';
      context.fillRect(x, labelY - 20, context.measureText(text).width + 10, 22);
      context.fillStyle = '#fff';
      context.fillText(text, x + 5, labelY - 4);
    }
  }

  /** Update label elemen DOM jika tersedia. */
  function setLabel(selector, text) {
    const el = document.querySelector(selector);
    if (el) el.textContent = text;
  }

  /** Satu siklus deteksi: ambil frame → kirim ke /api/detect → gambar hasil. */
  async function tick() {
    const stream = video.srcObject;
    const live   = stream && !video.hidden &&
      video.readyState >= 2 &&
      stream.getVideoTracks().some(t => t.readyState === 'live');

    const uploaded = !uploadedImage.hidden &&
      uploadedImage.dataset.pcv === 'true' &&
      uploadedImage.complete;

    const media  = live ? video : uploadedImage;
    const source = live ? stream : uploadedImage.src;

    // Jika gambar upload sama dan belum ada yang baru, skip
    if (!live && uploaded && source === lastUpload && !document.hidden) {
      setTimeout(tick, 250);
      return;
    }
    // Jika tidak ada media aktif, sembunyikan overlay
    if ((!live && !uploaded) || document.hidden) {
      overlay.hidden = true;
      setTimeout(tick, 250);
      return;
    }

    const controller = new AbortController();
    const timeout    = setTimeout(() => controller.abort(), 15000);

    try {
      // Skala frame ke max 640px
      const ratio = Math.min(
        1,
        640 / Math.max(
          live ? video.videoWidth  : media.naturalWidth,
          live ? video.videoHeight : media.naturalHeight
        )
      );
      frame.width  = Math.max(1, Math.round((live ? video.videoWidth  : media.naturalWidth)  * ratio));
      frame.height = Math.max(1, Math.round((live ? video.videoHeight : media.naturalHeight) * ratio));
      frameContext.drawImage(media, 0, 0, frame.width, frame.height);

      const blob = await new Promise(resolve => frame.toBlob(resolve, 'image/jpeg', 0.8));
      if (!blob) throw new Error('Frame kamera belum tersedia');

      const response = await fetch('/api/detect', {
        method: 'POST',
        headers: { 'Content-Type': 'image/jpeg' },
        body: blob,
        signal: controller.signal,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'API gagal');

      // Batalkan jika kamera sudah diganti
      if (live
        ? video.srcObject !== source || video.hidden
        : uploadedImage.src !== source || uploadedImage.hidden
      ) return;

      if (!live) lastUpload = source;

      // Kirim event global untuk monitoring.js
      window.dispatchEvent(new CustomEvent('ferqueue:cv-result', { detail: data }));

      overlay.hidden = false;
      drawDetections(data.detections);

      setLabel('#vehicle-summary-label', 'HASIL DETEKSI');
      setLabel('#vehicle-summary',
        data.detections.length
          ? [...new Set(data.detections.map(item => item.class_name))].join(', ')
          : 'Belum ada kendaraan terdeteksi'
      );
      setLabel('#visual-badge', 'DETEKSI MODEL');
      setLabel('#camera-message', `Deteksi aktif · ${data.inference_ms} ms per frame`);
    } catch (error) {
      overlay.hidden = true;
      const stillValid = live
        ? video.srcObject === source && !video.hidden
        : uploadedImage.src === source && !uploadedImage.hidden;
      if (stillValid) {
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

  // Mulai loop deteksi
  tick();
}
