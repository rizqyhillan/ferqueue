# PCV FERQUEUE

Mulai dari **[panduan PCV manual](../../docs/PCV_MANUAL.md)** untuk instalasi, dataset, konversi, segmentasi, training, dan web. Seluruh perintah dijalankan dari root FERQUEUE menggunakan `python pcv.py <tahap>` dengan environment Python yang kamu aktifkan sendiri.

## Struktur

```text
apps/computer-vision/
  configs/
    yolo.json                 # Data raw dan pembagian train/test
    coco.json                 # Training, evaluasi, prediksi, dan API
  requirements/
    data.txt                  # Gambar, preprocessing, converter eksternal
    training.txt              # TensorFlow CPU dan Object Detection API
    training-cuda.txt         # Tambahan NVIDIA
    inference.txt             # Prediksi dan API tanpa sumber training
  src/ferqueue_cv/             # Modul tahapan PCV
  tests/                      # Pengujian dengan data buatan
```

`docs/PCV_MANUAL.md` menjadi panduan utama. Catatan eksperimen terdahulu tersimpan di `docs/PCV_EXPERIMENTS.md`.

## Perintah

| Tahap | Kegunaan |
| --- | --- |
| `inspect` | Memeriksa sumber YOLO/COCO dan ringkasan data |
| `stage-yolo` | Menyiapkan gambar/label dan daftar train/test converter |
| `adopt-coco` | Menghubungkan JSON converter ke gambar raw |
| `prepare` | Membekukan manifest kelas, split, dan hash sumber |
| `segment`, `preview` | Review mask GrabCut dan pengolahan citra |
| `plan`, `build-records` | Anggaran epoch/langkah dan TFRecord |
| `train`, `export`, `evaluate` | Training TensorFlow, SavedModel, dan metrik test |
| `predict` | Prediksi file gambar dan penyimpanan bbox/JSON |
| `serve` | API kamera untuk Flask pada port 8000 |
| `package-model`, `import-model` | Membagikan model dan preprocessing |
| `fix-tf-slim`, `check`, `check-inference` | Kompatibilitas dan pemeriksaan environment |
| `diagnose` | Memeriksa checkpoint dan model ekspor |
| `clean-dataset` | Audit/karantina dataset setelah review operator |
| `test` | Menjalankan pengujian kode tanpa training dataset pengguna |

Untuk data YOLO gunakan `--config apps/computer-vision/configs/yolo.json`. Setelah konversi gunakan `--config apps/computer-vision/configs/coco.json`; config COCO ini juga menjadi default. Semua path di dalam config tetap relatif terhadap root repo.

Konversi memakai [Taeyoung96/Yolo-to-COCO-format-converter](https://github.com/Taeyoung96/Yolo-to-COCO-format-converter), yang dijalankan manual lewat `main.py`. Helper FERQUEUE menyiapkan input dan menyesuaikan path hasilnya; bbox tetap berasal dari converter.

Model: SSD MobileNet V2 FPNLite 320×320, TensorFlow 2.15.1, Python 3.11. Hanya ada **train 70% dan test 30% berdasarkan kelompok/sesi**. Tidak ada split validasi. Model memprediksi kelas dan bounding box; mask GrabCut untuk review, dan dimensi fisik memerlukan kalibrasi terpisah.

Preprocessing mengikuti metadata model pada evaluasi, prediksi, serta web. Confidence/NMS tampilan mengikuti config yang dipilih. [Tabel parameter](../../docs/PCV_MANUAL.md#13-bagian-yang-bisa-diubah-dan-pengaruhnya) menjelaskan pengaruh dan tahap yang perlu diulang.

Untuk tes, setelah dependensi terpasang:

```text
python pcv.py test
```

Dataset buatan diproses dalam folder sementara. Tes TensorFlow/OpenCV dilewati jika dependensinya belum tersedia.
