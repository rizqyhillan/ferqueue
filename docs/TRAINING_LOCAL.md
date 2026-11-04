# Training di laptop sendiri

Branch `igpu` menggunakan Linux native pada laptop Ryzen 5 PRO 5675U, Python 3.11, TensorFlow 2.15.1, dan SSD MobileNet V2 FPNLite 320×320. Training memakai **CPU**; Radeon iGPU belum digunakan oleh backend ini. Model, batch 4, learning rate 0.004, dan alur training sama seperti sebelumnya.

## Setup sekali

Dari root repo:

```bash
bash scripts/cv.sh setup
```

Setup mengunduh Python 3.11 ke cache repo dan memasang dependensi ke `.venv-training` menggunakan uv. Python sistem Fedora tidak diubah. Setup CPU tidak memerlukan NVIDIA, CUDA, WSL, atau Docker. Perlu internet untuk dependensi dan sumber Object Detection API.

Tunggu sampai muncul **`Environment training cpu siap`** sebelum menjalankan perintah lain. Jika setup terhenti, ulangi perintah yang sama untuk melanjutkan dengan cache yang tersedia. Pesan `Environment training belum lengkap` berarti setup belum selesai atau gagal.

## Siapkan dan latih dataset

Pastikan seluruh gambar, anotasi YOLO, dan `classes.txt` sudah berada di `data/raw/vehicles/`. Kemudian:

```bash
bash scripts/cv.sh check
bash scripts/cv.sh test
# Hanya jika data/processed/vehicles-v1/manifest.json belum ada:
bash scripts/cv.sh prepare
bash scripts/cv.sh train
```

Jika manifest dari laptop lama ikut disalin, gunakan path relatif gambar yang sama; pembagian yang sudah dibekukan dipakai kembali. Konfigurasi saat ini memakai rasio train/test 70/30 untuk manifest baru.

Training menjalankan 3.000 langkah, menyimpan checkpoint setiap 100 langkah, dan dapat dilanjutkan dengan mengulang `train` pada config/manifest yang sama. Hasil berada di `models/mobilenet/runs/ssd-v2-igpu-001/`. Jangan menjalankan dua training pada run yang sama. Pengaturan ada di `configs/training.json`; default thread CPU adalah 6 intra-op dan 2 inter-op, yang dapat diubah melalui environment.

Untuk eksperimen 6.000 langkah di folder terpisah:

```bash
bash scripts/cv.sh train --config configs/training-6000.json
```

## Sumber training COCO JSON

Untuk dataset hasil konversi COCO JSON, gunakan konfigurasi terpisah:

```bash
# Sekali saja; tidak perlu diulang jika manifest COCO sudah ada:
bash scripts/cv.sh prepare --config configs/training-coco.json
bash scripts/cv.sh train --config configs/training-coco.json
```

JSON sumber berada di `data/processed/vehicles-coco/annotations/`, gambar tetap di `data/raw/vehicles/`, dan hasil training menggunakan `models/mobilenet/runs/ssd-v2-coco-001/`. Anotasi dibaca dari COCO, tanpa memerlukan label YOLO. Split JSON tidak diacak ulang. Tambahkan `--config configs/training-coco.json` juga pada export, evaluate, predict, dan package-model. Lihat [format dan validasi COCO](../apps/computer-vision/README.md#sumber-training-coco-json).

## Ekspor dan evaluasi

```bash
bash scripts/cv.sh export
bash scripts/cv.sh evaluate --split test
bash scripts/cv.sh package-model --archive outputs/ssd-model.zip
```

Tambahkan `--config configs/training-6000.json` pada perintah di atas bila menggunakan run 6.000 langkah.

NVIDIA tetap tersedia sebagai opsi: setup memakai `--device cuda`, lalu check/train memakai `--require-gpu`. Lihat [panduan NVIDIA](TRAINING_GPU_WINDOWS.md).
