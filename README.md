# FERQUEUE

PCV deteksi kendaraan dengan **TensorFlow 2.15.1 dan SSD MobileNet V2 FPNLite 320×320**, terhubung ke dashboard Flask untuk kamera dan unggah gambar.

Mulai dari **[panduan PCV manual](docs/PCV_MANUAL.md)** untuk persiapan dataset, pemeriksaan bounding box, training, evaluasi, dan integrasi web. Untuk training GPU di laptop Windows dan pengaturan deteksi webcam, ikuti **[panduan RTX 4060](docs/PCV_MANUAL_WINDOWS_RTX4060.md)**.

## Alur utama

1. Pasang Python 3.11 dan environment `.venv-pcv`; ikuti pemasangan manual TensorFlow, sumber Object Detection API, serta protoc pada panduan.
2. Salin gambar, label YOLO bbox, dan `classes.txt` asli ke `data/raw/vehicles/`. Gunakan subfolder sesi atau `groups.csv` agar frame satu rekaman tidak bocor antar-split.
3. Jalankan tahap berikut satu per satu dari root repo dengan Python environment tersebut:

```text
python pcv.py inspect --config apps/computer-vision/configs/yolo.json
python pcv.py stage-yolo --config apps/computer-vision/configs/yolo.json --output data/processed/pcv-converter-v2
# Jalankan main.py repo Taeyoung96 untuk train dan test sesuai panduan bagian 5.
python pcv.py adopt-coco --config apps/computer-vision/configs/yolo.json --staging data/processed/pcv-converter-v2 --input .cache/yolo-to-coco/output --output data/processed/pcv-coco-v2
python pcv.py prepare --config apps/computer-vision/configs/coco.json
python pcv.py preview --config apps/computer-vision/configs/coco.json --output outputs/pcv-preview-v1
python pcv.py plan --config apps/computer-vision/configs/coco.json
python pcv.py build-records --config apps/computer-vision/configs/coco.json
python pcv.py train --config apps/computer-vision/configs/coco.json
python pcv.py export --config apps/computer-vision/configs/coco.json
python pcv.py evaluate --config apps/computer-vision/configs/coco.json --split test
```

4. Periksa laporan test, prediksi gambar baru, lalu jalankan API PCV dan Flask sesuai bagian 11–12 pada panduan.

Contoh config baru memakai **70/30 berdasarkan kelompok**, batch 4, dan anggaran 30 epoch. Tidak ada split validasi. Training default memakai CPU; Radeon iGPU tidak dipakai oleh backend ini. NVIDIA Linux/WSL2 tetap opsional.

## Pengaturan dan batas hasil

Edit `apps/computer-vision/configs/coco.json` untuk epoch, batch, learning rate, augmentasi, preprocessing, serta threshold/NMS. [Tabel parameter dan pengaruhnya](docs/PCV_MANUAL.md#13-bagian-yang-bisa-diubah-dan-pengaruhnya) menjelaskan perubahan yang memerlukan training baru dan perubahan tampilan yang cukup dengan restart API. Eksperimen berbeda memakai `run_dir` berbeda.

Model dilatih dengan gambar utuh dan anotasi bounding box. Ukuran panjang, lebar, dan tinggi fisik memerlukan kalibrasi kamera.

Web menerima kelas, confidence, dan bounding box melalui `/api/detect`. Integrasi kamera tidak memerlukan database atau ESP32. Model anomali, load cell, gate, dan penyimpanan pemeriksaan merupakan bagian lain yang perlu diverifikasi terpisah. [Panduan web](apps/web-monitoring/README-web.md).

## Struktur

| Lokasi | Fungsi |
| --- | --- |
| `docs/PCV_MANUAL.md` | Panduan utama dari instalasi sampai web dan penanganan error |
| `pcv.py` | Entry point manual memakai Python aktif |
| `apps/computer-vision/configs/yolo.json` | Sumber YOLO dan pembagian kelompok |
| `apps/computer-vision/configs/coco.json` | Sumber COCO dan parameter eksperimen baru |
| `apps/computer-vision/requirements/` | Dependensi data, training CPU/CUDA, dan inference |
| `apps/computer-vision/src/ferqueue_cv/` | Modul tiap tahap PCV |
| `apps/web-monitoring/` | Flask, kamera/unggah, dan penghubung PCV |
| `data/raw/vehicles/` | Gambar/label asli lokal |
| `data/processed/` | COCO dan manifest versi dataset |
| `models/mobilenet/runs/` | Records, checkpoint, ekspor, dan laporan per eksperimen |
| `outputs/` | Pratinjau bounding box dan prediksi |
| `firmware/` | Firmware load cell/servo |

Default `pcv.py` adalah `apps/computer-vision/configs/coco.json`. Untuk tahap sumber YOLO, pilih `--config apps/computer-vision/configs/yolo.json`. Konfigurasi, dependensi, kode, dan tes PCV berada di satu aplikasi; panduan lengkap ada di `docs/PCV_MANUAL.md`.

Menjalankan API dan memeriksa model juga melalui entry point yang sama:

```text
python pcv.py serve
python pcv.py diagnose
```

Catatan percobaan terdahulu disimpan di [catatan eksperimen PCV](docs/PCV_EXPERIMENTS.md). Pipeline tetap memakai train/test dan converter eksternal yang dipilih. Dataset, checkpoint, serta hasil model tersimpan pada folder data/model/output masing-masing.
