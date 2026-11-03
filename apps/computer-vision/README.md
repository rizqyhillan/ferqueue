# PCV: dataset, training, dan prediksi gambar

Model: **SSD MobileNet V2 FPNLite 320×320**. Dataset: gambar + anotasi YOLO dari LabelImg. Kamera tidak diperlukan. Branch `igpu` menjalankan training di CPU laptop Ryzen pada Linux native. Radeon iGPU tidak dipakai oleh backend TensorFlow ini. [Training lokal](../../docs/TRAINING_LOCAL.md); [NVIDIA WSL2 opsional](../../docs/TRAINING_GPU_WINDOWS.md).

## Dataset yang diterima

Susunan flat hasil LabelImg:

```text
data/raw/vehicles/
  classes.txt
  mobil-001.jpg
  mobil-001.txt
  truk-001.jpg
  truk-001.txt
```

Atau gambar/label terpisah dengan subfolder yang sama:

```text
data/raw/vehicles/
  classes.txt
  images/rekaman-01/frame-001.jpg
  labels/rekaman-01/frame-001.txt
  images/rekaman-02/frame-001.jpg
  labels/rekaman-02/frame-001.txt
```

`classes.txt` berisi daftar kelas asli saat labeling, satu nama per baris. Jangan mengubah urutannya. Semua salinan `classes.txt` dalam subfolder harus memiliki urutan identik.

Baris label YOLO: `class_id center_x center_y width height`, dengan koordinat dinormalisasi 0–1 dan ID mulai dari 0. Konverter mengubah ID menjadi mulai dari 1 untuk TensorFlow; tidak perlu labeling ulang. Format YOLO merupakan format anotasi, bukan kewajiban memakai model YOLO.

Setiap gambar JPG/JPEG/PNG harus punya label `.txt`. Gambar background menggunakan label kosong yang dibuat sengaja. Label hilang, kotak tidak valid, ID kelas salah, file rusak, gambar duplikat, serta label tanpa pasangan gambar ditolak. Normalisasi rotasi EXIF sebelum labeling, bukan setelah kotak dibuat.

Jika `prepare` menemukan banyak file tanpa pasangan atau duplikat, jalankan `bash scripts/cv.sh clean-dataset` (Windows: `.\scripts\cv.ps1 clean-dataset`). Perintah ini membuat laporan lengkap dan menunggu input `y` setelah kamu review sebelum memindahkan kandidat ke karantina. Opsi `--dry-run` (PowerShell: `-DryRun`) hanya membuat laporan. Gambar identik dengan anotasi bertentangan tetap disimpan untuk diperiksa; label yang isinya sama pada gambar berbeda tidak dihapus. [Alur review, backup, dan pemulihan](../../scripts/README.md#review-dan-bersihkan-dataset-sebelum-prepare).

## Pembagian kelompok dan data uji

Untuk frame video atau foto satu kendaraan dalam sesi yang sama, simpan dalam subfolder tingkat pertama yang sama. Kelompok itu tidak akan tersebar antara train dan test.

Jika hasil LabelImg masih flat, tambahkan `groups.csv`:

```csv
image,group
frame-001.jpg,rekaman-01
frame-002.jpg,rekaman-01
frame-100.jpg,rekaman-02
```

Nama gambar relatif terhadap folder `images/` bila ada; jika tidak, relatif terhadap `data/raw/vehicles/`. Tanpa folder/CSV, setiap gambar flat dianggap independen. Script tidak dapat mengetahui sendiri apakah dua foto menampilkan kendaraan yang sama.

Perlu minimal dua kelompok independen untuk membuat split train/test, tetapi jumlah itu saja belum cukup untuk menilai kualitas model. Konfigurasi saat ini sekitar 70% train dan 30% test berdasarkan kelompok; jumlah gambar bisa berbeda karena ukuran kelompok tidak sama.

## Validasi ringan di Windows

```powershell
.\scripts\cv.ps1 setup-data
.\scripts\cv.ps1 prepare
.\scripts\cv.ps1 test
```

Hanya Pillow yang dipasang di `.venv-data`. `prepare` menulis manifest JSON serta `summary.json` ke `data/processed/vehicles-v1/`; TFRecord train dan test baru dibuat saat training. Jika suatu kelas tidak ada di training, prepare berhenti. Kelas yang hilang dari test ditulis sebagai peringatan.

Manifest tidak ditimpa. Gunakan `prepared_dir` baru untuk versi dataset baru, termasuk jika label diperbaiki. Jika sebelumnya memakai manifest tiga bagian, gunakan `prepared_dir` dan `run_dir` baru lalu jalankan prepare; format lama akan ditolak agar tidak tercampur. Bawa dataset asli dan folder manifest ke laptop training dengan path relatif yang sama. Jangan membagikan `.venv-*` atau `.cache`.

## Konfigurasi

Edit `configs/training.json`:

| Kunci | Nilai awal | Kegunaan |
| --- | --- | --- |
| `dataset_dir` | `data/raw/vehicles` | Dataset asli |
| `prepared_dir` | `data/processed/vehicles-v1` | Manifest pembagian |
| `run_dir` | `models/mobilenet/runs/ssd-v2-igpu-001` | Satu eksperimen/model |
| `train_ratio` | 0.7 | Proporsi kelompok training |
| `test_ratio` | 0.3 | Proporsi kelompok test; jumlah kedua rasio harus 1 |
| `batch_size` | 4 | Gambar per langkah |
| `num_steps` | 3000 | Jumlah langkah, bukan epoch |
| `learning_rate` | 0.004 | Nilai awal fine-tuning |
| `seed` | 42 | Pembagian kelompok, bukan jaminan determinisme training GPU |
| `confidence_threshold` | 0.5 | Ambang tampilan prediksi |

## Training di laptop sendiri

Dari root repo dalam Linux native:

```bash
bash scripts/cv.sh setup
bash scripts/cv.sh check
# Bila belum ada manifest:
bash scripts/cv.sh prepare
bash scripts/cv.sh train
bash scripts/cv.sh export
bash scripts/cv.sh evaluate --split test
```

Transfer learning memakai checkpoint COCO resmi. Script membuat TFRecord, label map, serta pipeline sesuai jumlah kelas. Batch normalization dibekukan untuk batch kecil; optimizer momentum menggunakan cosine decay dan warmup. Versi TensorFlow/Keras, sumber Object Detection API, dan compiler protobuf dipatok pada setup.

Artefak dalam `run_dir`: `inputs.json` (config + manifest), `label_map.pbtxt`, `pipeline.config`, `records/`, `training/`, `exports/`, `export.json`, dan `reports/`.

Checkpoint disimpan setiap 100 langkah. Ulangi `train` dengan config/manifest sama untuk resume. Jangan menjalankan dua training pada run yang sama. Parameter/dataset berbeda memerlukan `run_dir` baru. Bila split tetap, jangan membuat ulang pembagian untuk setiap eksperimen.

Untuk NVIDIA, setup memakai `--device cuda` dan perintah check/train memakai `--require-gpu`.

## Evaluasi

Evaluasi COCO berjalan satu kali pada split test berlabel. Laporan `reports/ckpt-N-test.json` mencakup mAP IoU 0.50:0.95, AP@0.50, average recall, dan metrik per kelas. Ambang tampilan `confidence_threshold` tidak menyaring evaluasi COCO. Nilai `-1` berarti kategori/rentang itu tidak dapat dievaluasi.

Tetapkan parameter training sebelum mengevaluasi data test sebagai pengujian akhir. Jalankan `bash scripts/cv.sh evaluate` atau `bash scripts/cv.sh evaluate --split test`. `export` memakai checkpoint terbaru, bukan otomatis checkpoint terbaik. Setelah melanjutkan training, jalankan export lagi sebelum evaluasi/prediksi.

## Membagikan model dan prediksi Windows

Laptop training:

```bash
bash scripts/cv.sh package-model --archive outputs/ssd-model.zip
```

Anggota tim menerima ZIP itu di `outputs/ssd-model.zip`:

```powershell
.\scripts\cv.ps1 setup-data
.\scripts\cv.ps1 import-model -Archive outputs/ssd-model.zip
.\scripts\cv.ps1 setup-inference
.\scripts\cv.ps1 check
.\scripts\cv.ps1 predict -Images data/inference -Output outputs/predictions
```

Prediksi CPU memakai `.venv-inference` berisi TensorFlow, NumPy, dan Pillow; tidak memasang CUDA atau sumber training. Pilih `run_dir` baru sebelum impor jika sudah ada model/training di sana. ZIP hanya berisi SavedModel dan metadata kelas; belum mencakup API/web.

Gambar baru tidak perlu label untuk melihat hasil deteksi. Hasil `foto.jpg.predicted.jpg` menampilkan kotak, kelas, dan confidence. File `foto.jpg.predicted.json` berisi koordinat `[xmin, ymin, xmax, ymax]` dalam piksel gambar asli, ukuran gambar, serta checkpoint. Folder output berbeda dapat dipilih untuk menyimpan hasil percobaan terpisah.

Dimensi panjang/lebar/tinggi tetap `null`, status `not_calibrated`. Label kotak 2D tidak menyediakan ukuran fisik/3D. Pengukuran memerlukan kalibrasi, geometri pandang, dan ukuran acuan. Load cell, PostgreSQL, dan metode sistem cerdas tidak diperlukan untuk menjalankan alur gambar ini.

## Referensi

- [TensorFlow: instalasi dan GPU Windows/WSL2](https://www.tensorflow.org/install/pip)
- [TensorFlow Object Detection API: training](https://github.com/tensorflow/models/blob/master/research/object_detection/g3doc/tf2_training_and_evaluation.md)
- [Model Zoo SSD MobileNet V2 FPNLite](https://github.com/tensorflow/models/blob/master/research/object_detection/g3doc/tf2_detection_zoo.md)
- [NVIDIA CUDA on WSL](https://docs.nvidia.com/cuda/wsl-user-guide/index.html)
- [LabelImg YOLO](https://github.com/HumanSignal/labelImg#yolo)
