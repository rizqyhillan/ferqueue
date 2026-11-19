# FERQUEUE — konteks kerja agen

## Mulai di sini

- Root project lokal: `/home/foxxyy/project/ferqueue`. Jalankan semua perintah dari root ini kecuali dinyatakan lain. `pcv.py` menolak CWD selain root.
- Gunakan bahasa Indonesia untuk percakapan dan penjelasan, mengikuti bahasa pengguna. Pertahankan gaya kode yang sudah ada; hindari refactor di luar pekerjaan yang diminta.
- Baca `git status --short --branch` sebelum mengubah file. Pertahankan perubahan staged/unstaged/untracked pengguna; jangan reset, checkout branch, commit, atau menghapus artefak tanpa permintaan.
- Dokumen ini adalah peta arsitektur dan status terkini project, bukan pengganti pembacaan kode langsung. Periksa kembali file dan runtime terkait sebelum mengerjakan fitur.
- Panduan utama: `README.md`, `docs/PCV_MANUAL.md`, `apps/computer-vision/README.md`, dan `apps/web-monitoring/README-web.md`. Panduan GPU Windows/WSL2: `docs/PCV_MANUAL_WINDOWS_RTX4060.md`. `docs/PCV_EXPERIMENTS.md` adalah riwayat awal, bukan metrik model saat ini.

## Tujuan dan batas implementasi

FERQUEUE adalah prototipe sistem pemeriksaan kendaraan pelabuhan/gate (skala maket/diecast Hot Wheels) yang terdiri atas tiga subsistem utama:

1. **PCV (Computer Vision)**: Mendeteksi kelas kendaraan (`Mobil`, `Truk`, `Bus`), confidence, dan bounding box dari gambar/kamera menggunakan **TensorFlow 2.15.1 + SSD MobileNet V2 FPNLite 320×320**, ditambah fitur **estimasi dimensi tampak samping (Panjang & Tinggi dalam cm)** menggunakan kalibrasi **koin 50 yen (diameter 21 mm)** melalui OpenCV (`side_measurement.py`).
2. **Dashboard Operator (Web Monitoring)**: Aplikasi **Flask + HTML/CSS/JS** yang menyediakan tampilan kamera live/unggah gambar, penandaan area koin 50 yen, pembacaan berat live dari sensor, tampilan dimensi (`P × T`), pemilihan golongan (`A`/`B`/`C` atau `I`–`IX`), indikator status/skor anomali, serta penerbitan dan pencetakan tiket.
3. **Evaluasi Anomali (Rule + K-Means) & IoT Gate (ESP32)**:
   - Backend Flask (`app.py` + `core_diecast.py` + `model_anomali_k-means.joblib`) menjalankan evaluasi 2 lapis pada fitur `[P, L, T, W]` (skala diecast: cm dan gram): **Lapis 1 (Rule-Based ODOL & batas golongan A/B/C)** dan **Lapis 2 (K-Means Clustering K=3 pada fitur logaritmik)**.
   - Firmware ESP32 (`firmware/loadcellservofix/loadcellservofix.ino`) membaca berat dari load cell HX711 dan mengendalikan servo palang gate melalui polling HTTP ke Flask (`/api/berat`).

### Batas integrasi yang harus dipahami agen
- **Jalur kamera vs jalur `/predict`**: Kamera browser mengirim frame ke Flask `POST /api/detect` → PCV `POST /detect` untuk mendapatkan deteksi kelas, bbox, dan estimasi `[length_cm, height_cm]` dari koin 50 yen. Namun, **frontend belum otomatis memanggil `POST /predict`** setelah ukuran kamera dan berat terkumpul. Endpoint `/predict` saat ini dipanggil terpisah (mis. melalui klien HTTP/Postman) dan memperbarui `state_kendaraan` yang dipolling oleh frontend melalui `GET /api/status-kendaraan` setiap 1 detik.
- **Dimensi 2D tampak samping vs 3D**: Kalibrasi koin 50 yen pada kamera tampak samping hanya mengestimasi **Panjang (`P`) dan Tinggi (`T`)** dalam cm. **Lebar (`L`)** tidak terukur dari kamera samping tunggal. Sementara itu, `/predict` membutuhkan `[P, L, T, W]`.
- **Deteksi offline (`pcv.py predict`)**: Tidak menyertakan header `X-Coin-Region`, sehingga field `dimensions` pada JSON hasil predict offline tetap `null` dengan status `not_calibrated`.
- **Segmentasi GrabCut**: Hanya digunakan untuk review visual (`pcv.py segment`) dan eksperimen perbandingan di notebook, **bukan** ground truth mask training dan **tidak** dipakai saat inference API live.

## Peta repository

- `pcv.py`: Entry point CLI seluruh tahap PCV. Memakai interpreter Python aktif tanpa auto-install atau auto-switch venv.
- `apps/computer-vision/configs/`:
  - `yolo.json`: Config sumber raw YOLO (`data/raw/vehicles`), rasio 70/30 berbasis kelompok, seed 42.
  - `coco.json`: Config default COCO (`prepared_dir`: `data/processed/pcv-coco-manifest-v2`, `run_dir`: `models/mobilenet/runs/pcv-coco-002`, `confidence_threshold`: 0.5).
  - `coco-rtx4060.json`: Config eksperimen GPU RTX 4060 (`run_dir`: `models/mobilenet/runs/pcv-coco-rtx4060-001`, `confidence_threshold`: 0.29).
  - `receiver.json`: Config untuk model hasil impor (`run_dir`: `models/mobilenet/runs/pcv-receiver-001`, `confidence_threshold`: 0.29).
- `apps/computer-vision/src/ferqueue_cv/`:
  - `__main__.py`: Router CLI untuk 20 action (`check`, `check-inference`, `fix-tf-slim`, `diagnose`, `serve`, `stage-yolo`, `adopt-coco`, `inspect`, `prepare`, `plan`, `preview`, `segment`, `build-records`, `clean-dataset`, `train`, `evaluate`, `export`, `predict`, `test`, `package-model`, `import-model`).
  - `dataset.py`, `coco_dataset.py`, `conversion.py`: Validasi dataset YOLO/COCO, pembagian kelompok train/test, staging converter Taeyoung96, adopsi JSON COCO, pembekuan manifest & verifikasi SHA256.
  - `settings.py`, `runtime.py`: Validasi JSON config, perhitungan rencana epoch/steps, konfigurasi `PYTHONPATH` untuk `.cache/tensorflow-models/research`, serta pemilihan CPU default vs `--require-gpu`.
  - `processing.py`: Preprocessing geometris tetap (RGB → Gaussian denoise → CLAHE LAB → gamma) dan mask GrabCut untuk review.
  - `side_measurement.py`: Kalibrasi skala koin 50 yen (`COIN_DIAMETER_MM = 21.0`) menggunakan OpenCV (GaussianBlur, Otsu thresholding dua arah, `findContours`, `fitEllipse`) dan perhitungan `length_cm` & `height_cm` dari bbox kendaraan tampak samping.
  - `training.py`, `coco_metrics.py`, `postprocessing.py`: Pembuatan TFRecord lossless PNG, modifikasi `pipeline.config`, training `model_main_tf2`, export `exporter_main_v2`, evaluasi `pycocotools`, prediksi batch, dan filter confidence + NMS tampilan.
  - `live_api.py`: Server HTTP (`HTTPServer` stdlib, default `127.0.0.1:8000`) untuk `/health` dan `/detect` (mendukung mode normal maupun `--calibration-only`, serta header `X-Coin-Region`).
  - `sharing.py`: Pemaketan (`package-model`) dan impor (`import-model`) arsip ZIP SavedModel portabel beserta metadata preprocessing.
  - `compat.py`: Patch kompatibilitas `tf_slim/data/tfexample_decoder.py` untuk TF 2.15.
  - `diagnostics.py`: Pemeriksaan kesamaan bobot checkpoint training vs SavedModel export dan uji forward pass sampel per kelas.
  - `cleanup.py`: Audit dataset YOLO dan karantina ter-jurnal (`outputs/dataset-cleanup/`).
- `apps/computer-vision/notebooks/`:
  - `perbandingan_segmentasi.ipynb`: Eksperimen evaluasi bbox SSD murni vs bbox yang dirapikan dengan mask GrabCut pada split test (`pcv-cpu-full-001`). Menunjukkan bahwa post-processing GrabCut menurunkan mAP (0.701 → 0.619 pada sampel 24 gambar) dan menambah beban komputasi ~2,17 detik/gambar.
  - `pcv_langkah_bertahap.ipynb`: Walkthrough interaktif seluruh tahapan PCV menggunakan 15 sampel gambar test di `data/processed/pcv-notebook-samples/` (5 Mobil, 5 Truk, 5 Bus).
- `apps/computer-vision/tests/`: 84 unit test mencakup seluruh modul PCV, termasuk kalibrasi koin, API live, metrik COCO, cleanup, sharing, dan pipeline.
- `apps/web-monitoring/`:
  - `app.py`: Server Flask (default port 5000), manajemen state in-memory (`state_iot`, `state_kendaraan`, `antrean_perintah`, `daftar_tiket`), endpoint ML `/predict` & `/predict/<model_type>`, endpoint IoT `/api/berat`, `/api/buka`, `/api/servo`, `/api/tare`, serta endpoint `/api/tiket` dan `/api/status-kendaraan`.
  - `cv_bridge.py`: Blueprint Flask (`/api/cv/health` dan `/api/detect`) yang meneruskan byte gambar (maks 2 MiB) dan header `X-Coin-Region` ke server PCV (`CV_API_URL`, default `http://127.0.0.1:8000`).
  - `core_diecast.py`: Modul aturan aktif (skala diecast cm & gram, golongan `A`/`B`/`C`) dan ekstraksi fitur/skor K-Means (`feat`, `fit_models`, `skor`).
  - `core.py`: Modul aturan skala kendaraan nyata (meter & ton, golongan `A`–`E`, K-Means + Isolation Forest). Tidak diimpor oleh `app.py`; jangan dipertukarkan dengan `core_diecast.py`.
  - `model_anomali_k-means.joblib`: Artefak bundle (`scaler`, `models.kmeans`, `thr`) untuk deteksi anomali skala diecast yang dimuat oleh `app.py`.
  - `db.py`: Modul MySQL opsional (`pymysql`, database `gate_pelabuhan`, tabel `pemeriksaan` dan `tiket`). Kegagalan koneksi ditangani secara graceful tanpa menghentikan aplikasi.
  - `templates/index.html`, `static/styles.css`, `static/app.js`, `static/live_detection.js`, `static/tickets.js`: Frontend operator, loop kamera & overlay kanvas + interaksi klik 2 sudut koin 50 yen, manajemen tiket `localStorage`, dan sinkronisasi status backend.
  - `server.mjs`, `package.json`: Launcher opsional berbasis Node.js untuk menjalankan Flask (`app.py`) dan menjalankan tes tiket JS (`npm test`) / syntax check (`npm run check`).
  - `tests/`: `test_cv_bridge.py` (6 unittest Python untuk integrasi Flask–PCV) dan `tickets.test.mjs` (5 tes Node untuk validasi & penomoran tiket).
- `firmware/loadcellservofix/loadcellservofix.ino`: Sketch Arduino/ESP32 untuk pembacaan load cell HX711, kontrol servo palang, tombol fisik, dan komunikasi HTTP periodik (500 ms) ke `/api/berat`.

## Kontrak data dan eksperimen PCV

- **Urutan kelas baku**: `["Mobil", "Truk", "Bus"]`. Label YOLO memakai indeks `0, 1, 2`; TFRecord dan Object Detection API memakai `1, 2, 3`. Jangan mengubah urutan `classes.txt` tanpa memetakan ulang seluruh label.
- **Format label YOLO**: 5 kolom `class_id center_x center_y width height` ternormalisasi `0..1`. Gambar background wajib memiliki file `.txt` kosong eksplisit.
- **Alur baku PCV**: `inspect` → `stage-yolo` → konversi manual dengan `.cache/yolo-to-coco/main.py` (repo `Taeyoung96/Yolo-to-COCO-format-converter`) untuk `train` dan `test` → `adopt-coco` → `prepare` → `segment`/`preview` (opsional, untuk review) → `plan` → `build-records` → `train` → `export` → `evaluate --split test` → `predict` / `serve`.
- **Split dataset**: Hanya `train` dan `test` (70/30 berdasarkan kelompok/sesi, tanpa validation split). Pada config COCO, split mengikuti file JSON anotasi yang sudah dibuat.
- **Immutabilitas manifest dan run**:
  - `prepared_dir` membekukan `manifest.json` beserta hash SHA256 seluruh gambar dan file JSON anotasi COCO.
  - `run_dir` membekukan `inputs.json` (config identitas training + manifest). Perubahan hyperparameter training, dataset, atau preprocessing wajib memakai `run_dir` baru.
  - Perubahan parameter tampilan (`confidence_threshold`, `nms_iou_threshold`, `max_detections`, `class_agnostic_nms`) dan `segmentation` tidak mengubah identitas training; cukup restart `pcv.py serve` atau jalankan ulang `predict`.
- **Kalibrasi koin 50 yen (`side_measurement.py`)**:
  - Header `X-Coin-Region`: `"ymin,xmin,ymax,xmax"` ternormalisasi `0..1`.
  - Status kalibrasi yang mungkin dikembalikan pada `payload["calibration"]`:
    - Jika koin gagal dideteksi: `status` bernilai `coin_region_small`, `coin_not_found`, `coin_ambiguous`, atau `unavailable`.
    - Jika koin berhasil dideteksi (`status: "ready"`): menyertakan `coin: {center: [cy, cx], diameter_px, mm_per_px}` dan `measurement`.
    - Status `measurement`: `estimated` (menyertakan `length_cm` dan `height_cm`), `no_vehicle`, `multiple_vehicles`, `vehicle_clipped`, atau `coin_overlaps_vehicle`.

## Kontrak API, evaluasi anomali, tiket, dan firmware

- **Format koordinat bbox**:
  - Endpoint live `POST /api/detect` (dan `POST /detect` di PCV): `box` ternormalisasi `[ymin, xmin, ymax, xmax]` dalam rentang `0..1`.
  - File JSON hasil `pcv.py predict` offline: `bbox_xyxy_px` dalam piksel `[xmin, ymin, xmax, ymax]`.
- **Evaluasi aturan & K-Means (`POST /predict` atau `POST /predict/kmeans`)**:
  - Menerima JSON `{"jenis": "mobil"|"bus"|"truk"|"A"|"B"|"C", "P": float_cm, "L": float_cm, "T": float_cm, "W": float_gram}`.
  - Jika sensor load cell (`state_iot["berat"]`) > 0, berat load cell (gram) diprioritaskan di atas `W` dari body request.
  - Aturan `core_diecast.py` (`TOL = 0.10`):
    - Batas legal absolut (`LEGAL`): `P_max = 25.0` cm, `L_max = 8.0` cm, `T_max = 10.0` cm (lewat batas → `TOLAK`).
    - Golongan `A` (`mobil`): `P` 4.0–7.0 cm, `L` 1.8–2.7 cm, `T` 1.8–2.5 cm, `W_max` 40.0 g.
    - Golongan `B` (`bus`): `P` 7.0–15.0 cm, `L` 2.0–4.0 cm, `T` 2.5–4.0 cm, `W_max` 150.0 g.
    - Golongan `C` (`truk`): `P` 10.0–12.0 cm, `L` 2.0–4.0 cm, `T` 2.5–4.0 cm, `W_max` 200.0 g.
    - Berat `> W_max * 1.10` → `TOLAK`; dimensi `P/L/T` di luar rentang `±10%` golongan → `INSPEKSI`; selain itu `OK`.
  - Fitur ML: `np.log([[P, L, T, W]])` → `scaler.transform` → jarak Euclidean terdekat ke centroid K-Means (`skor`). Jika `score > thr` (default `1.606` dari `model_anomali_k-means.joblib`) atau aturan menghasilkan `TOLAK`/`INSPEKSI`, maka `status_anomali = "Terindikasi Anomali"`, selain itu `"Normal"`.
- **Tiket & IoT**:
  - Tiket diterbitkan di browser (`localStorage` key `ferqueue.tickets.v1`, maks 500 tiket, format nomor `FQ-YYMMDD-NNN` zona waktu `Asia/Jakarta`) dan dikirim ke `POST /api/tiket`.
  - `POST /api/tiket` menyimpan tiket ke memori (`daftar_tiket`) dan MySQL (jika aktif), lalu otomatis menambahkan perintah `"buka"` ke `antrean_perintah`.
  - ESP32 mengirim `POST /api/berat` setiap 500 ms dan menerima balasan plaintext satu perintah FIFO (`none`, `buka`, `servo0`, `servo90`, `tare`).

## Menjalankan dan menguji

Gunakan virtual environment yang sudah tersedia (`.venv-pcv` dan `.venv-web`), jangan membuat ulang atau meng-upgrade paket tanpa instruksi.

1. **Pemeriksaan dan unit test PCV (dari root repo)**:
   ```bash
   .venv-pcv/bin/python pcv.py --help
   .venv-pcv/bin/python pcv.py inspect --config apps/computer-vision/configs/coco.json
   .venv-pcv/bin/python pcv.py plan --config apps/computer-vision/configs/coco.json
   .venv-pcv/bin/python pcv.py test
   ```

2. **Menjalankan server PCV dan Web Monitoring (2 terminal dari root repo)**:
   - Gunakan `--config apps/computer-vision/configs/receiver.json` (model impor `ckpt-53`) atau config dengan `run_dir` yang sudah diekspor (mis. `pcv-cpu-full-001`), atau gunakan `--calibration-only` jika hanya menguji koin 50 yen:
   ```bash
   # Terminal 1 (PCV API di 127.0.0.1:8000)
   .venv-pcv/bin/python pcv.py serve --config apps/computer-vision/configs/receiver.json

   # Terminal 2 (Flask Web di 127.0.0.1:5000)
   WEB_HOST=127.0.0.1 CV_API_URL=http://127.0.0.1:8000 .venv-web/bin/python apps/web-monitoring/app.py
   ```

3. **Unit test Web Monitoring (dari root repo)**:
   ```bash
   PYTHONPATH=apps/web-monitoring .venv-web/bin/python -m unittest discover -s apps/web-monitoring/tests -p 'test_*.py' -v
   ```
   Jika Node.js (>=20) tersedia di PATH, jalankan `npm --prefix apps/web-monitoring run check` dan `npm --prefix apps/web-monitoring test`.

## Keselamatan dan batas perubahan

- Jangan membaca massal `.git`, `.venv-*`, `.cache/`, atau bobot biner. Jangan memuat file pickle/joblib dari sumber luar yang tidak dipercaya.
- Jangan memulai training, export, dataset cleanup, atau menimpa artefak laporan/model yang sudah ada hanya untuk orientasi.
- `clean-dataset --dry-run` tetap menulis folder laporan baru di `outputs/dataset-cleanup/`. `fix-tf-slim` memodifikasi file paket di dalam `.venv-pcv`.
- Firmware (`loadcellservofix.ino`) berisi kredensial WiFi hardcoded; **jangan** menyalin SSID/password tersebut ke respons, dokumentasi, atau log.

## Snapshot status terkini repository

Kondisi nyata workspace saat dokumen ini diperbarui (selalu verifikasi ulang dengan `git status`):

- **Branch aktif**: `combine/comvis-kmeans` (commit `4e7b5a7`), hasil merge antara cabang fitur komputer visi + pengukuran koin (`kmean-dummy-data`, `f941b13`) dan cabang model K-Means diecast (`origin/feat/web-monitoring-k-means`, `01f1e41`).
- **File untracked**: Folder `apps/computer-vision/notebooks/` berisi dua notebook analisis (`perbandingan_segmentasi.ipynb` dan `pcv_langkah_bertahap.ipynb`) yang menguji tahapan PCV dan membandingkan akurasi bbox SSD murni vs bbox yang dirapikan GrabCut.
- **Dataset & Manifest aktif (`data/processed/pcv-coco-manifest-v2`)**:
  - Total **976 gambar** berlabel di `data/raw/vehicles/` (tidak ada lagi error duplikat byte pada manifest aktif).
  - Split **train**: **683 gambar** (326 `Mobil`, 178 `Truk`, 179 `Bus`).
  - Split **test**: **293 gambar** (157 `Mobil`, 69 `Truk`, 67 `Bus`).
  - Sampel uji notebook: 15 gambar test (5 per kelas) disalin ke `data/processed/pcv-notebook-samples/` beserta indeks `samples.json`.
- **Artefak Model SSD (`models/mobilenet/runs/`)**:
  - `pcv-cpu-pilot-001`: Run uji coba singkat CPU (`ckpt-4`, 9 gambar test).
  - `pcv-cpu-full-001`: Run training CPU penuh (batch 2, 10 epoch = 3.420 steps, LR 0.002, `freeze_batchnorm: false`), diekspor pada **`ckpt-36`**. Hasil evaluasi pada 293 gambar test (`reports/ckpt-36-test.json`): **mAP (0.50:0.95) = 0.723**, **AP@0.50 = 0.971**, **AP@0.75 = 0.956** (mAP per kelas: `Mobil` 0.753, `Bus` 0.729, `Truk` 0.687).
  - `pcv-receiver-001`: Model hasil impor dari training GPU (`exports/imported-ckpt-53`, arsip `outputs/pcv-model-final.zip`), siap dijalankan dengan `apps/computer-vision/configs/receiver.json`.
  - Catatan: Config default `apps/computer-vision/configs/coco.json` menunjuk ke `run_dir: models/mobilenet/runs/pcv-coco-002` yang belum dibuat; untuk menjalankan model yang sudah ada, arahkan `--config` ke `receiver.json`, `outputs/pcv-cpu-full-001.json`, atau sesuaikan `run_dir`.
- **Environment & Verifikasi Tes**:
  - `.venv-pcv` (Python 3.11.18 + TF 2.15.1 + OpenCV + pycocotools + ipykernel) siap; **84 unit test PCV lulus** (`pcv.py test`).
  - `.venv-web` (Python 3.11 + Flask 3.1.3) siap; **6 unit test bridge Flask lulus** (`test_cv_bridge.py`). Paket opsional ML/DB (`joblib`, `numpy`, `scikit-learn`, `pymysql`) belum terpasang di `.venv-web` (namun tersedia di `.venv-pcv` kecuali `pymysql`/`scikit-learn` bila diperlukan).
- **Daftar ketidaksesuaian/celah integrasi yang tercatat pada kode saat ini** (jangan diasumsikan sudah otomatis beres kecuali diminta memperbaikinya):
  1. **Alur otomatis Kamera → `/predict`**: Pengukuran kamera (`length_cm`, `height_cm` dari koin 50 yen) baru mengisi state/UI dimensi di browser (`P` dan `T`), belum otomatis memicu request `POST /predict` ke Flask. Selain itu, `/predict` masih membutuhkan input lebar `L` (default `0.1` cm jika kosong, yang akan memicu status `INSPEKSI` karena di bawah batas minimum golongan).
  2. **Status anomali pada objek tiket (`tickets.js`)**: Fungsi `createTicket` di `static/tickets.js` masih mengecek `inspection.vehicleStatus === 'Anomali' ? 'Anomali' : 'Normal'`, sedangkan backend dan form UI memakai string `'Terindikasi Anomali'`. Akibatnya, tiket yang disimpan ke `localStorage` oleh `createTicket` akan tercatat sebagai `'Normal'` kecuali bagian tersebut disesuaikan.
  3. **Konsistensi label satuan berat di dialog edit (`index.html` & `tickets.js`)**: Tampilan utama dashboard dan tiket menggunakan satuan **gram (`g`)**, tetapi dialog edit manual (`#weight-input`) masih berlabel `(kg)` dan pesan error `validateInspection` menyebut `0,01–200.000 kg`.
  4. **Konversi field `W` di `app.py`**: Pada `POST /api/berat`, `state_kendaraan["W"]` diisi `berat_mentah / 1_000_000.0` (sisa konversi ton), sedangkan pada `POST /predict`, `state_kendaraan["W"]` diisi `berat_gram` (gram).
