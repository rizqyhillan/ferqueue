# FERQUEUE — konteks kerja agen

## Mulai di sini

- Root project lokal: `/home/foxxyy/project/ferqueue`. Jalankan semua perintah dari root ini kecuali dinyatakan lain. `pcv.py` menolak CWD selain root.
- Gunakan bahasa Indonesia untuk percakapan dan penjelasan, mengikuti bahasa pengguna. Pertahankan gaya kode yang sudah ada; hindari refactor di luar pekerjaan yang diminta.
- Baca `git status --short --branch` sebelum mengubah file. Pertahankan perubahan staged/unstaged/untracked pengguna; jangan reset, checkout branch, commit, atau menghapus artefak tanpa permintaan.
- Dokumen ini adalah peta arsitektur dan status terkini project, bukan pengganti pembacaan kode langsung. Periksa kembali file dan runtime terkait sebelum mengerjakan fitur.
- Panduan utama: `README.md`, `apps/computer-vision/README.md`, dan `apps/web-monitoring/README-web.md`. Arsip panduan v2: `docs/PCV_MANUAL.md`, `docs/PCV_MANUAL_WINDOWS_RTX4060.md`, dan `docs/PCV_EXPERIMENTS.md`.

## Tujuan dan batas implementasi

FERQUEUE adalah prototipe sistem pemeriksaan kendaraan pelabuhan/gate (skala maket/diecast) yang terdiri atas empat subsistem utama:

1. **PCV (Computer Vision)**: Mendeteksi kelas kendaraan (`Mobil`, `Truk`, `Bus`), confidence, dan bounding box dari gambar/kamera menggunakan **TensorFlow 2.15.1 + preprocessing LAB-CLAHE halus (`clahe_clip_limit: 1.5`, `clahe_grid_size: 8`) + SSD MobileNet V2 FPNLite 320×320**, ditambah **estimasi dimensi tampak samping (Panjang & Tinggi dalam cm)** berbasis **geometri pinhole kamera samping tegak lurus** (`side_measurement.py`, header `X-Camera-Geometry`).
2. **Dashboard Operator (Web Monitoring)**: Aplikasi **Flask + Jinja2 + HTML/CSS/JS** multi-halaman (`/login`, `/dashboard`, `/monitoring`, `/riwayat`, `/ai-assistant`) dengan autentikasi petugas (MySQL + fallback offline), kamera live/unggah foto, kalibrasi geometri 2 titik, pembacaan berat live, penerbitan & cetak tiket, tangkapan foto kendaraan ke `static/captures/`, serta arsip riwayat + ekspor CSV.
3. **Validasi Berat Rule-Based & Asisten Petugas (Hybrid RAG + Multimodal Vision)**:
   - Validasi berat golongan skala diecast di `app.py` (`Gol. A` Mobil maks `55 g` / Rp 60.000, `Gol. B` Bus maks `85 g` / Rp 120.000, `Gol. C` Truk maks `100 g` / Rp 250.000) dengan rujukan regulasi PM 103/2017.
   - Modul `rag_service.py` + `ingest.py` + dokumen SOP di `apps/web-monitoring/knowledge/` menyediakan chat multi-turn, ringkasan audit harian dari data aktual, dan audit visual multimodal (Gemini + fallback pencarian lokal).
4. **Database & IoT Gate (MySQL + ESP32)**:
   - `db.py` + `database/ferqueue_db.sql` mengelola 4 tabel MySQL (`golongan_kendaraan`, `riwayat_pemeriksaan`, `detail_overweight`, `petugas`) dengan fallback in-memory/offline yang graceful saat MySQL tidak aktif.
   - Firmware ESP32 (`firmware/loadcellservofix/loadcellservofix.ino`) membaca berat load cell HX711 dan mengendalikan servo palang gate melalui polling HTTP periodik ke `/api/berat`.

### Batas integrasi yang harus dipahami agen
- **Dimensi 2D tampak samping**: Estimasi kamera tampak samping (`side_measurement.py`) menghitung **Panjang (`P`) dan Tinggi (`T`)** dalam cm secara langsung menggunakan geometri pinhole tegak lurus (`distance_cm,focal_norm`).
- **Deteksi offline (`pcv.py predict`)**: Tidak menyertakan header `X-Camera-Geometry`, sehingga field `dimensions` pada JSON hasil predict offline tetap `null` dengan status `not_calibrated`.
- **Preprocessing mengikuti metadata model**: `live_api.py` dan `training.py` membaca konfigurasi preprocessing dari `export.json` agar transformasi LAB-CLAHE saat training, evaluasi, `predict`, dan `serve` selalu identik.

## Peta repository

- `pcv.py`: Entry point CLI seluruh tahap PCV. Memakai interpreter Python aktif tanpa auto-install atau auto-switch venv.
- `apps/computer-vision/configs/`:
  - `receiver-v4-clahe.json`: **Config default** (`DEFAULT_CONFIG`) untuk impor model, `predict`, dan `serve` (`run_dir`: `models/mobilenet/runs/pcv-receiver-v4-clahe`, LAB-CLAHE `clip=1.5`, `grid=8`).
  - `coco-v4-clahe.json`: Config persiapan TFRecord & training LAB-CLAHE (`prepared_dir`: `data/processed/pcv-coco-manifest-v4`, `run_dir`: `models/mobilenet/runs/pcv-coco-colab-v4-clahe`).
  - `receiver-v4.json`, `receiver-isnet.json`: Config model pembanding (baseline RGB `v4` dan eksperimen IS-Net).
  - `archive/`: Config lama v2/v3/RTX4060 (`coco.json`, `yolo.json`, `receiver.json`, dll.).
- `apps/computer-vision/src/ferqueue_cv/`:
  - `__main__.py`: Router CLI untuk 18 action (`check`, `check-inference`, `fix-tf-slim`, `diagnose`, `network`, `serve`, `inspect`, `prepare`, `preview`, `build-records`, `clean-dataset`, `train`, `evaluate`, `export`, `predict`, `test`, `package-model`, `import-model`).
  - `dataset.py`, `coco_dataset.py`, `conversion.py`: Validasi dataset YOLO/COCO, pembagian kelompok train/test, inspeksi split, pembekuan manifest & verifikasi SHA256.
  - `settings.py`, `runtime.py`: Validasi JSON config, perhitungan rencana epoch/steps, konfigurasi `PYTHONPATH` untuk `.cache/tensorflow-models/research`, serta pemilihan CPU default vs `--require-gpu`.
  - `processing.py`: Preprocessing geometris tetap (`describe_preprocessing`, `preprocess_image`, `preview_dataset` — Gaussian denoise opsional, LAB-CLAHE, gamma).
  - `side_measurement.py`: Parsing header `X-Camera-Geometry` (`distance_cm,focal_norm`) dan estimasi `length_cm` & `height_cm` berbasis geometri pinhole kamera tampak samping tegak lurus.
  - `training.py`, `coco_metrics.py`, `postprocessing.py`: Pembuatan TFRecord lossless PNG (auto-`prepare` bila manifest belum ada), modifikasi `pipeline.config`, training `model_main_tf2`, export `exporter_main_v2`, evaluasi `pycocotools`, prediksi batch, dan filter confidence + NMS tampilan.
  - `live_api.py`: Server HTTP (`HTTPServer` stdlib, default `127.0.0.1:8000`) untuk `/health` dan `/detect` (mendukung mode normal maupun `--calibration-only`, serta header `X-Camera-Geometry`).
  - `sharing.py`, `compat.py`, `diagnostics.py`, `network_summary.py`, `cleanup.py`: Pemaketan/impor model, patch `tf_slim`, diagnostik bobot, ringkasan/diagram CNN, dan audit/karantina dataset YOLO.
- `apps/computer-vision/notebooks/`: Notebook eksperimen PCV klasik, IS-Net, training Colab (`train_colab_v4.ipynb`, `train_colab_v4_clahe.ipynb`), serta perbandingan metode (`6_perbandingan_2_metode_setara.ipynb`, `8_perbandingan_ssd_isnet_vs_sebelumnya.ipynb`).
- `apps/computer-vision/tests/`: 84 unit test mencakup seluruh modul PCV.
- `apps/web-monitoring/`:
  - `app.py`: Server Flask (default port 5000), autentikasi sesi petugas, validasi berat golongan A/B/C, tangkapan foto kendaraan (`static/captures/`), endpoint IoT (`/api/berat`, `/api/buka`, `/api/servo`, `/api/tare`), pemeriksaan & tiket (`/api/proses-kendaraan`, `/api/tiket`, `/api/riwayat`, `/api/stats`, `/api/aktivitas`, `/api/system-status`), serta endpoint AI (`/api/ai/query`, `/api/ai/knowledge`).
  - `cv_bridge.py`: Blueprint Flask (`/api/cv/health` dan `/api/detect`) yang meneruskan gambar (maks 2 MiB) dan header `X-Camera-Geometry` ke server PCV (`CV_API_URL`, default `http://127.0.0.1:8000`).
  - `db.py` & `database/ferqueue_db.sql`: Koneksi MySQL opsional (`pymysql`, database `gate_pelabuhan`, 4 tabel: `golongan_kendaraan`, `riwayat_pemeriksaan`, `detail_overweight`, `petugas`) dengan fallback offline/in-memory.
  - `rag_service.py`, `ingest.py`, `knowledge/*.md`: Layanan Hybrid RAG (ChromaDB + pencarian keyword lokal) dan audit visual multimodal Gemini.
  - `templates/` & `static/`: Halaman `login.html`, `dashboard.html`, `monitoring.html`, `riwayat.html`, `ai_assistant.html` beserta CSS dan ES modules (`utils.js`, `dashboard.js`, `monitoring.js`, `live_detection.js`, `riwayat.js`, `ai_assistant.js`).
  - `tests/`: `test_cv_bridge.py` (6 test) dan `test_pages.py` (21 test) — total 27 unit test Python.
- `firmware/loadcellservofix/loadcellservofix.ino`: Sketch Arduino/ESP32 untuk pembacaan load cell HX711, kontrol servo palang, dan polling HTTP periodik ke `/api/berat`.

## Kontrak data dan eksperimen PCV

- **Urutan kelas baku**: `["Mobil", "Truk", "Bus"]`. Label YOLO memakai indeks `0, 1, 2`; TFRecord dan Object Detection API memakai `1, 2, 3`. Jangan mengubah urutan `classes.txt` tanpa memetakan ulang seluruh label.
- **Alur baku PCV**: `inspect` → `preview` (opsional) → `build-records` (otomatis menjalankan `prepare` jika manifest belum ada) → `train` (lokal atau Colab `train_colab_v4_clahe.ipynb`) → `export` / `import-model` → `evaluate --split test` → `predict` / `serve`.
- **Split dataset**: Hanya `train` dan `test` (70/30 berdasarkan kelompok/sesi, tanpa validation split). Pada config COCO, split mengikuti file JSON anotasi yang sudah dibuat.
- **Immutabilitas manifest dan run**:
  - `prepared_dir` membekukan `manifest.json` beserta hash SHA256 seluruh gambar dan file anotasi.
  - `run_dir` membekukan `inputs.json` (config identitas training + manifest). Perubahan hyperparameter training, dataset, atau preprocessing wajib memakai `run_dir` baru.
  - Perubahan parameter tampilan (`confidence_threshold`, `nms_iou_threshold`, `max_detections`, `class_agnostic_nms`) tidak mengubah identitas training; cukup restart `pcv.py serve` atau jalankan ulang `predict`.
- **Format koordinat bbox**:
  - Endpoint live `POST /api/detect` (dan `POST /detect` di PCV): `box` ternormalisasi `[ymin, xmin, ymax, xmax]` dalam rentang `0..1`.
  - File JSON hasil `pcv.py predict` offline: `bbox_xyxy_px` dalam piksel `[xmin, ymin, xmax, ymax]`.

## Menjalankan dan menguji

Gunakan virtual environment yang sudah tersedia (`.venv-pcv` dan `.venv-web`), jangan membuat ulang atau meng-upgrade paket tanpa instruksi.

1. **Pemeriksaan dan unit test PCV (dari root repo)**:
   ```bash
   .venv-pcv/bin/python pcv.py --help
   .venv-pcv/bin/python pcv.py inspect --config apps/computer-vision/configs/coco-v4-clahe.json
   .venv-pcv/bin/python pcv.py test
   ```

2. **Menjalankan server PCV dan Web Monitoring (2 terminal dari root repo)**:
   ```bash
   # Terminal 1 (PCV API di 127.0.0.1:8000, default: receiver-v4-clahe.json)
   .venv-pcv/bin/python pcv.py serve

   # Terminal 2 (Flask Web di 127.0.0.1:5000)
   .venv-web/bin/python apps/web-monitoring/app.py
   ```

3. **Unit test Web Monitoring (dari root repo)**:
   ```bash
   PYTHONPATH=apps/web-monitoring .venv-web/bin/python -m unittest discover -s apps/web-monitoring/tests -p 'test_*.py' -v
   ```

## Keselamatan dan batas perubahan

- Jangan membaca massal `.git`, `.venv-*`, `.cache/`, atau bobot biner. Jangan memuat file pickle/joblib dari sumber luar yang tidak dipercaya.
- Jangan memulai training, export, dataset cleanup, atau menimpa artefak laporan/model yang sudah ada hanya untuk orientasi.
- `clean-dataset --dry-run` tetap menulis folder laporan baru di `outputs/dataset-cleanup/`. `fix-tf-slim` memodifikasi file paket di dalam `.venv-pcv`.
- Firmware (`loadcellservofix.ino`) dan `.env` lokal berisi kredensial; **jangan** menyalin SSID/password/API key ke respons, dokumentasi, atau log.
