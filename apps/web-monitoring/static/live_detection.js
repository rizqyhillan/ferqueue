const video = document.querySelector('#camera-video');
const viewport = document.querySelector('#camera-viewport');

Object.assign(video.style, {
  objectFit: 'contain',
  objectPosition: 'center',
});

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

function drawDetections(detections) {
  overlay.width = viewport.clientWidth;
  overlay.height = viewport.clientHeight;

  const scale = Math.min(
    overlay.width / frame.width,
    overlay.height / frame.height
  );
  const offsetX = (overlay.width - frame.width * scale) / 2;
  const offsetY = (overlay.height - frame.height * scale) / 2;

  context.font = 'bold 15px sans-serif';
  context.lineWidth = 3;

  for (const item of detections) {
    const [y1, x1, y2, x2] = item.box;
    const x = offsetX + x1 * frame.width * scale;
    const y = offsetY + y1 * frame.height * scale;
    const width = (x2 - x1) * frame.width * scale;
    const height = (y2 - y1) * frame.height * scale;
    const text = item.class_name + ' ' +
      Math.round(item.confidence * 100) + '%';

    context.strokeStyle = '#22c55e';
    context.strokeRect(x, y, width, height);

    const labelY = Math.max(20, y);
    context.fillStyle = '#111';
    context.fillRect(
      x, labelY - 20, context.measureText(text).width + 10, 22
    );
    context.fillStyle = '#fff';
    context.fillText(text, x + 5, labelY - 4);
  }
}

async function tick() {
  const stream = video.srcObject;
  const live = stream && !video.hidden &&
    video.readyState >= 2 &&
    stream.getVideoTracks().some(
      track => track.readyState === 'live'
    );

  if (!live || document.hidden) {
    overlay.hidden = true;
    setTimeout(tick, 250);
    return;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);

  try {
    const ratio = Math.min(
      1, 640 / Math.max(video.videoWidth, video.videoHeight)
    );
    frame.width = Math.max(
      1, Math.round(video.videoWidth * ratio)
    );
    frame.height = Math.max(
      1, Math.round(video.videoHeight * ratio)
    );
    frameContext.drawImage(
      video, 0, 0, frame.width, frame.height
    );

    const blob = await new Promise(resolve =>
      frame.toBlob(resolve, 'image/jpeg', 0.8)
    );
    if (!blob) throw new Error('Frame kamera belum tersedia');

    const response = await fetch(
      'http://127.0.0.1:8000/detect',
      {
        method: 'POST',
        headers: { 'Content-Type': 'image/jpeg' },
        body: blob,
        signal: controller.signal,
      }
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || 'API gagal');
    }

    // Abaikan hasil lama jika kamera sudah dihentikan/diganti.
    if (video.srcObject !== stream || video.hidden) return;

    overlay.hidden = false;
    drawDetections(data.detections);

    document.querySelector(
      '#vehicle-summary-label'
    ).textContent = 'HASIL DETEKSI';

    document.querySelector('#vehicle-summary').textContent =
      data.detections.length
        ? [...new Set(
            data.detections.map(item => item.class_name)
          )].join(', ')
        : 'Belum ada kendaraan terdeteksi';

    document.querySelector('#visual-badge').textContent =
      'DETEKSI MODEL';

    document.querySelector('#camera-message').textContent =
      'Deteksi aktif · ' + data.inference_ms + ' ms per frame';
  } catch (error) {
    overlay.hidden = true;
    if (video.srcObject === stream && !video.hidden) {
      document.querySelector('#vehicle-summary').textContent =
        'Deteksi belum tersedia';
      document.querySelector('#visual-badge').textContent =
        'API TERPUTUS';
      document.querySelector('#camera-message').textContent =
        'Periksa terminal API: ' + error.message;
    }
  } finally {
    clearTimeout(timeout);
    setTimeout(tick, 250);
  }
}

tick();