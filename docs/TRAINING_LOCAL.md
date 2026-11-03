# Training dan benchmark laptop sendiri

Branch `igpu` menggunakan Linux native, Python 3.11, TensorFlow 2.15.1, dan SSD MobileNet V2 FPNLite 320×320 yang sama dengan alur NVIDIA. Laptop yang diperiksa: Ryzen 5 PRO 5675U, 6 core/12 thread, Radeon terintegrasi, RAM sekitar 16 GB, Fedora Linux. Python sistem 3.14 tidak diubah; setup mengunduh Python 3.11 ke cache repo dan membuat `.venv-training`.

## Perangkat yang dipakai

Training default berjalan di **CPU**. TensorFlow pip standar mendukung GPU melalui NVIDIA/CUDA; Radeon terintegrasi pada Ryzen 5675U bukan target yang didukung alur tersebut. Matriks ROCm Ryzen juga tidak mencantumkan 5675U. Branch ini tidak memasang ROCm atau mengaktifkan iGPU dengan override driver.

- [Instalasi TensorFlow](https://www.tensorflow.org/install/pip)
- [Matriks dukungan AMD Ryzen](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityryz/native_linux/native_linux_compatibility.html)

## Setup dan dataset

Dari root repo:

```bash
bash scripts/cv.sh setup
bash scripts/cv.sh check
bash scripts/cv.sh test
```

Setup perlu internet untuk Python, dependensi, dan sumber Object Detection API. Check menguji forward pass model di CPU. Tidak perlu Docker, WSL, NVIDIA, maupun perubahan Python sistem pada Linux native.

Tunggu sampai penyalinan seluruh gambar, anotasi, dan `classes.txt` ke `data/raw/vehicles/` selesai. Bila manifest `data/processed/vehicles-v1/manifest.json` dari laptop lama ikut disalin, bawa semua gambar pada path relatif yang sama. Manifest lama dipakai kembali; pembagiannya tidak diubah otomatis oleh konfigurasi. Bila belum ada manifest, jalankan:

```bash
bash scripts/cv.sh prepare
```

Konfigurasi repo sekarang memakai rasio 70/30. Manifest yang sudah dibekukan adalah acuan split sebenarnya. Jangan menjalankan prepare atau training ketika flashdisk masih menyalin gambar/label.

## Mengukur kemampuan laptop

Hubungkan charger, gunakan mode daya yang sama untuk setiap percobaan, dan tutup aplikasi berat. Jalankan:

```bash
bash scripts/cv.sh benchmark
```

Ini training sungguhan selama 200 langkah pada dataset asli, batch 4, dalam run baru di `outputs/benchmarks/<waktu-id>/`. Seratus langkah awal untuk warmup tidak ikut menghitung kecepatan. Benchmark tetap mencatat waktu total, termasuk pembuatan TFRecord dan unduhan checkpoint COCO pertama. Perkiraan 3.000/6.000 langkah menggunakan rata-rata detik/langkah setelah warmup, di luar persiapan, ekspor, dan evaluasi. Suhu, mode daya, aktivitas lain, dan ukuran gambar dapat mengubah kecepatan run panjang.

Untuk sampel lebih panjang atau membandingkan jumlah thread:

```bash
bash scripts/cv.sh benchmark --steps 500
TF_NUM_INTRAOP_THREADS=12 bash scripts/cv.sh benchmark
```

Jumlah benchmark minimal 200 dan harus kelipatan 100, mengikuti blok training API resmi. Default thread adalah 6 intra-op dan 2 inter-op; keduanya bisa diubah melalui environment. Setiap benchmark memakai folder baru, tidak melanjutkan checkpoint benchmark sebelumnya, dan tidak mengisi run training utama. Benchmark menggunakan jadwal learning rate yang dipendekkan; hasilnya untuk waktu, bukan perbandingan akurasi.

## Training penuh

```bash
# 3.000 langkah:
bash scripts/cv.sh train
# Atau eksperimen terpisah 6.000 langkah:
bash scripts/cv.sh train --config configs/training-6000.json
```

Run utama branch ini adalah `models/mobilenet/runs/ssd-v2-igpu-001/` dan `ssd-v2-igpu-6000/`, terpisah dari run RTX lama. Model, batch 4, learning rate 0.004, dan dataset dipertahankan. Untuk membandingkan waktu dengan laptop teman, gunakan manifest, jumlah langkah, dan batch yang sama, serta mulai dari checkpoint COCO yang sama. Resume hanya mengukur pekerjaan sesi yang dilanjutkan, bukan waktu training dari nol.

Laporan setiap sesi berada di `<run_dir>/reports/training-<waktu-id>.json`, bersama log `.log`. Isinya meliputi status selesai/gagal/terputus, durasi persiapan, durasi proses training, versi runtime, pengaturan thread, sampel kecepatan, dan estimasi waktu. Penghentian dengan Ctrl+C mempertahankan laporan dan checkpoint yang sudah tersimpan; ulangi `train` untuk resume. Checkpoint disimpan setiap 100 langkah.

Setelah selesai:

```bash
bash scripts/cv.sh export
bash scripts/cv.sh evaluate --split test
bash scripts/cv.sh package-model --archive outputs/ssd-model.zip
```

Gunakan `--config configs/training-6000.json` juga pada export/evaluate/package-model bila memilih run 6.000 langkah. Evaluasi dan ekspor tidak termasuk estimasi benchmark.

## NVIDIA masih tersedia

Pada laptop NVIDIA Linux/WSL2, gunakan `bash scripts/cv.sh setup --device cuda`, lalu `bash scripts/cv.sh check --require-gpu` dan `bash scripts/cv.sh train --require-gpu`. Benchmark GPU juga menerima `--require-gpu`. Lihat [panduan NVIDIA](TRAINING_GPU_WINDOWS.md).
