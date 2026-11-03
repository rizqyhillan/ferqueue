# FERQUEUE

Computer vision kendaraan menggunakan **SSD MobileNet V2 FPNLite 320×320**, dengan rencana integrasi hasil PCV dan berat load cell melalui backend, PostgreSQL, dan web. Metode sistem cerdas masih akan dibandingkan, belum ditetapkan.

## Cara kerja tim sekarang

Seluruh training dilakukan pada **satu laptop Windows 10/11 dengan NVIDIA RTX 4060**, melalui Ubuntu WSL2 dan environment Python. Laptop anggota lain tidak perlu memasang environment training. Tidak ada kebutuhan Docker atau layanan cloud untuk alur ini.

| Pekerjaan | Perangkat | Mulai dari |
| --- | --- | --- |
| Labeling, pemeriksaan dan pembagian dataset | Laptop anggota tim, Windows | `scripts/cv.ps1 setup-data` |
| Training, ekspor, dan evaluasi | Laptop RTX 4060, terminal Ubuntu WSL2 | [Panduan training GPU](docs/TRAINING_GPU_WINDOWS.md) |
| Uji hasil model pada gambar | Windows, CPU cukup | `scripts/cv.ps1 setup-inference` |

Tidak perlu kamera untuk tahap training maupun pengujian file gambar ini.

## Dataset

Salin hasil LabelImg format YOLO ke `data/raw/vehicles/`:

```text
data/raw/vehicles/
  classes.txt
  mobil-001.jpg
  mobil-001.txt
  truk-001.jpg
  truk-001.txt
```

Gunakan `classes.txt` asli; urutan kelas harus sama dengan saat labeling. Panduan format folder, kelompok video, dan pemeriksaan label: [panduan PCV](apps/computer-vision/README.md).

Di Windows, pasang Python 3.11 64-bit, lalu dari root repo:

```powershell
.\scripts\cv.ps1 setup-data
.\scripts\cv.ps1 test
.\scripts\cv.ps1 prepare
```

Environment ini hanya memasang Pillow untuk pengolahan dataset. Bawa dataset asli serta folder `data/processed/vehicles-v1/` ke laptop training dengan susunan folder yang sama; manifest menggunakan path relatif sehingga bisa dipindahkan. Bila belum melakukan prepare, laptop training dapat menjalankannya sendiri.

## Training pada laptop RTX 4060

Ikuti [setup Windows + WSL2](docs/TRAINING_GPU_WINDOWS.md) sekali. Lalu, **jalankan di terminal Ubuntu WSL2 dari root repo**:

```bash
bash scripts/cv.sh setup
bash scripts/cv.sh check --require-gpu
bash scripts/cv.sh test
# Hanya jika manifest belum disiapkan:
bash scripts/cv.sh prepare
bash scripts/cv.sh train
bash scripts/cv.sh export
```

**`bash scripts/cv.sh train` adalah perintah yang melatih dataset.** Proses berhenti jika TensorFlow tidak dapat memakai GPU. Pengaturan ada di `configs/training.json`.

Sesudah training selesai, evaluasi pada data test dan kemas model:

```bash
bash scripts/cv.sh evaluate --split test
bash scripts/cv.sh package-model --archive outputs/ssd-model.zip
```

Pembagian data hanya **80% train dan 20% test**, diatur oleh `train_ratio` dan `test_ratio` pada `configs/training.json`. Pembagian mengikuti kelompok/sesi gambar. Jika pernah menyiapkan manifest dengan tiga bagian, gunakan `prepared_dir` dan `run_dir` baru, lalu jalankan `prepare` lagi; manifest lama tidak ditimpa.

Jika `prepare` menemukan banyak gambar tanpa label atau duplikat, jalankan `bash scripts/cv.sh clean-dataset` (Windows: `.\scripts\cv.ps1 clean-dataset`). Buka laporan lengkap yang ditampilkan, lalu ketik `y` di terminal untuk memindahkan seluruh kandidat yang disetujui ke karantina. Lihat [alur review dan pemulihan dataset](scripts/README.md#review-dan-bersihkan-dataset-sebelum-prepare).

Paket ZIP berisi model untuk prediksi, kelas, dan identitas checkpoint; tidak membawa gambar training, TFRecord, atau environment CUDA.

## Menguji gambar di Windows

Salin `ssd-model.zip` dari teman ke `outputs/ssd-model.zip`. Di PowerShell:

```powershell
.\scripts\cv.ps1 setup-data
.\scripts\cv.ps1 import-model -Archive outputs/ssd-model.zip
.\scripts\cv.ps1 setup-inference
.\scripts\cv.ps1 check
# Masukkan gambar JPG/PNG baru ke data/inference/, lalu:
.\scripts\cv.ps1 predict
```

Hasil bounding box, kelas, confidence, dan JSON disimpan di `outputs/predictions/`. Prediksi Windows memakai CPU; environment TensorFlow dipasang hanya jika anggota tersebut memang perlu menjalankan model. Untuk laptop yang sangat terbatas, prediksi juga dapat dilakukan di laptop RTX 4060 lalu file hasilnya dibagikan.

## Struktur utama

| Lokasi | Isi |
| --- | --- |
| `apps/computer-vision/` | Validasi YOLO, training, evaluasi, prediksi, dan tes |
| `apps/web-monitoring/` | Dashboard pemeriksaan kamera, berat, golongan, dan tiket masuk |
| `scripts/cv.ps1` | Persiapan dataset dan prediksi di Windows |
| `scripts/cv.sh` | Training/evaluasi GPU di WSL2 |
| `scripts/setup_cv.py` | Menyiapkan sumber TensorFlow yang dipatok versinya |
| `configs/training.json` | Lokasi dataset, folder eksperimen, dan parameter |
| `data/raw/vehicles/` | Dataset asli, tidak masuk Git |
| `data/processed/vehicles-v1/` | Manifest split yang dibekukan |
| `models/mobilenet/runs/ssd-v2-001/` | Checkpoint, model ekspor, dan laporan |
| `outputs/` | Prediksi dan paket model |

Folder `.venv-data`, `.venv-training`, `.venv-tools`, `.venv-inference`, dan `.cache` merupakan file lokal; tidak ikut Git dan tidak perlu dibagikan ke anggota lain.

## PostgreSQL dan integrasi selanjutnya

PostgreSQL dipasang langsung di Windows menggunakan installer resmi dan dikelola melalui pgAdmin. Buat user/database `ferqueue`, lalu isi `DATABASE_URL` pada `.env` sesuai konfigurasi lokal. Contoh disediakan di `.env.example`. Training dan prediksi file tidak memerlukan database.

Backend (`apps/backend/`) dan firmware masih berupa kerangka. Web (`apps/web-monitoring/`) sudah menyediakan antarmuka pemeriksaan kamera, input berat/golongan, serta tiket dan riwayat lokal. Jalankan `npm.cmd run dev` dari folder tersebut, lalu buka http://localhost:4173. Lihat [panduan web monitoring](apps/web-monitoring/README.md). Belum ada tabel aplikasi, API integrasi, atau pengiriman hasil prediksi ke database/web.

Pengukuran panjang, lebar, dan tinggi fisik masih membutuhkan modul kalibrasi tersendiri. Prediksi saat ini mengisi dimensi dengan `null` dan status `not_calibrated`; kotak deteksi bukan ukuran 3D. Metode sistem cerdas baru akan mengolah hasil dimensi dan berat sesudah datanya tersedia.
