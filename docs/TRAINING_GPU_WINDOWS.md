# Training di laptop Windows dengan NVIDIA RTX 4060

Jalur ini menggunakan Ubuntu WSL2 + Python 3.11 + TensorFlow 2.15.1. Semua training tetap berlangsung lokal di laptop temanmu. Tidak menggunakan Docker, Colab, atau server luar.

TensorFlow setelah 2.10 tidak mendukung CUDA GPU di Windows native. Karena model proyek memakai TensorFlow 2.15/Keras 2, training GPU dijalankan melalui WSL2. Lihat [panduan TensorFlow](https://www.tensorflow.org/install/pip#windows-native) dan [NVIDIA CUDA on WSL](https://docs.nvidia.com/cuda/wsl-user-guide/index.html).

## 1. Siapkan Windows sekali, hanya pada laptop RTX 4060

1. Perbarui driver NVIDIA Windows dari [NVIDIA](https://www.nvidia.com/Download/index.aspx).
2. Buka PowerShell **sebagai Administrator**:

```powershell
wsl --install -d Ubuntu-22.04
wsl --update
```

Restart jika Windows memintanya. Buka Ubuntu dan buat akun Linux saat pertama kali dijalankan. Jika WSL sudah ada, cukup periksa bahwa Ubuntu menggunakan versi 2:

```powershell
wsl --list --verbose
# Jalankan ini hanya jika Ubuntu-22.04 masih versi 1:
wsl --set-version Ubuntu-22.04 2
```

Nama distro bisa berbeda; gunakan nama yang tercantum pada daftar. Instalasi WSL ini tidak dijalankan otomatis oleh repo karena merupakan perubahan fitur Windows dan bisa memerlukan restart.

## 2. Siapkan Ubuntu

Perintah berikut dijalankan di **terminal Ubuntu**, bukan PowerShell:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git
nvidia-smi
```

Jika perintah terakhir tidak ditemukan, coba `/usr/lib/wsl/lib/nvidia-smi`. GPU RTX 4060 harus terlihat. Jangan memasang driver GPU Linux terpisah di WSL; WSL memakai driver NVIDIA Windows. Pustaka CUDA yang dibutuhkan TensorFlow dipasang ke environment Python oleh setup repo.

## 3. Tempatkan repo dan dataset

Untuk akses gambar yang lebih cepat, gunakan salinan repo di filesystem Ubuntu, misalnya `~/ferqueue`. Clone repo tim di sana atau salin folder proyek tanpa `.venv-*`, `.cache`, `.git`, dan artefak model lama. Jika memakai clone, dataset lokal tidak ikut Git sehingga perlu disalin terpisah.

Alternatif awal: akses repo Windows melalui `/mnt/c/...` atau `/mnt/d/...`; sesuaikan path dengan laptop temanmu. Contoh jika foldernya sama seperti laptop pemilik proyek:

```bash
cd /mnt/d/Semester5/project/ferqueue
```

Pastikan tersedia:

- `data/raw/vehicles/`: gambar asli, label YOLO `.txt`, `classes.txt`.
- `configs/training.json`: parameter dan folder dataset/run.
- `data/processed/vehicles-v1/`: jika tim sudah melakukan prepare, bawa folder ini juga agar split tetap sama. Manifest tidak boleh diubah saat dipindahkan.

## 4. Setup environment GPU

Dari root repo di Ubuntu:

```bash
bash scripts/cv.sh setup
```

Setup akan:

1. Memeriksa apakah NVIDIA terlihat di WSL.
2. Membuat `.venv-tools` untuk mendapatkan Python 3.11 lewat uv, tanpa mengganti Python sistem Ubuntu.
3. Membuat `.venv-training` dan memasang dependensi TensorFlow/CUDA.
4. Mengunduh sumber Object Detection API pada commit tetap ke `.cache/tensorflow-models` serta compiler protobuf lokal.
5. Menguji operasi GPU dan forward pass SSD MobileNet V2 FPNLite.

Setup pertama memerlukan internet dan beberapa GB ruang untuk dependensi CUDA/TensorFlow. Environment ini hanya diperlukan pada laptop training. Jangan menyalin environment Windows ke WSL atau sebaliknya.

Periksa kembali:

```bash
bash scripts/cv.sh check --require-gpu
bash scripts/cv.sh test
```

Jika TensorFlow tidak menemukan GPU atau operasi tes gagal, jangan mulai training. Periksa driver Windows, WSL2, dan pesan error. Setup tidak mengubah instalasi driver Windows secara otomatis.

## 5. Latih dataset

Jika manifest belum ada:

```bash
bash scripts/cv.sh prepare
```

Baca `data/processed/vehicles-v1/summary.json`. Kemudian:

```bash
bash scripts/cv.sh train
```

Training mengharuskan GPU; tidak beralih diam-diam ke CPU. Parameter awal di `configs/training.json`: batch size 4, 3000 langkah, learning rate 0.004. Angka tersebut titik awal eksperimen, bukan jaminan akurasi atau hasil tuning untuk RTX 4060.

Checkpoint dan log berada di `models/mobilenet/runs/ssd-v2-001/training/`. Jika terputus, ulangi `train` dengan konfigurasi dan manifest yang sama untuk melanjutkan checkpoint terakhir. Untuk parameter baru, gunakan `run_dir` baru; `prepared_dir` boleh sama jika dataset dan split tetap sama.

## 6. Evaluasi dan bagikan hasil

```bash
bash scripts/cv.sh export
```

Ekspor memakai checkpoint terbaru. Dataset hanya dibagi menjadi train (80%) dan test (20%), dengan rasio yang dapat diubah di `configs/training.json`. Sesudah training selesai, evaluasi pada test dan kemas model:

```bash
bash scripts/cv.sh evaluate --split test
bash scripts/cv.sh package-model --archive outputs/ssd-model.zip
```

Bagikan ZIP itu ke anggota tim. Mereka cukup melakukan `import-model` dan, jika ingin prediksi lokal, `setup-inference` di Windows. Untuk model berikutnya, gunakan nama ZIP serta `run_dir` baru agar hasil sebelumnya tidak tertimpa.

Prediksi juga bisa dijalankan di laptop ini:

```bash
# Isi data/inference/ dengan gambar JPG/PNG baru.
bash scripts/cv.sh predict
```

Hasil gambar dengan bounding box dan JSON berada di `outputs/predictions/`. Belum ada pengukuran dimensi fisik atau koneksi database/web.

## Jika unduhan model gagal karena sertifikat

Pesan `CERTIFICATE_VERIFY_FAILED` dengan `Hostname mismatch` pada `download.tensorflow.org` berarti unduhan checkpoint terhenti sebelum training. Downloader sekarang menggunakan endpoint HTTPS resmi bucket: `storage.googleapis.com/download.tensorflow.org`.

Perbarui `apps/computer-vision/src/ferqueue_cv/training.py` dari repo terbaru, kemudian ulangi:

```bash
bash scripts/cv.sh train
```

Tidak perlu mengulang prepare atau setup. Pemeriksaan sertifikat SSL tetap aktif.

## Jika decoder tf-slim mengeluhkan fungsi case/cond

`AttributeError: module 'tensorflow.python.ops.control_flow_ops' has no attribute 'case'` berasal dari decoder `tf-slim==1.1.0` yang mengakses API internal TensorFlow lama. Setup FERQUEUE sekarang mengarahkan import decoder tersebut ke API publik `tensorflow.compat.v1`, yang menyediakan `case` dan `cond`.

Sesudah memperbarui file script dari repo, jalankan di Ubuntu dari root proyek:

```bash
.venv-training/bin/python scripts/fix_tf_slim.py
bash scripts/cv.sh train
```

Script perbaikan juga menguji pembacaan JPEG dan PNG di dalam graph TensorFlow. Tidak perlu mengulang prepare atau menghapus dataset, checkpoint, dan environment. Setup akan menerapkan perbaikan lagi jika paket dipasang ulang; perintah `check` ikut menguji decoder gambar.

## Jika evaluasi berhenti dengan Category stats do not exist

Pesan ini berasal dari wrapper TensorFlow yang mengharapkan ekstensi `category_stats` di pycocotools. Perhitungan COCO keseluruhan dapat selesai, tetapi laporan gagal disimpan saat wrapper mencoba membaca metrik per kelas.

Perbarui kedua file `apps/computer-vision/src/ferqueue_cv/training.py` dan `apps/computer-vision/src/ferqueue_cv/coco_metrics.py`, kemudian jalankan ulang `bash scripts/cv.sh evaluate`. Evaluasi sekarang menggunakan API pycocotools standar dan mengambil AP per kelas dari tensor precision hasil evaluasi. Model, dataset, serta checkpoint yang sudah ada tetap dipakai; training dan export tidak perlu diulang.

## Jika TensorBoard tidak menemukan pkg_resources

TensorBoard 2.15 masih mengimpor `pkg_resources`. Environment perlu memakai setuptools yang menyediakan modul tersebut. Kebutuhan training sekarang mematok `setuptools==80.9.0` dan `tensorboard==2.15.2`; setup ikut memeriksa startup TensorBoard.

Untuk memperbaiki environment yang sudah ada, jalankan dari root repo di Ubuntu:

```bash
.venv-training/bin/python -m pip install "setuptools==80.9.0"
.venv-training/bin/python -m tensorboard.main --logdir models/mobilenet/runs/ssd-v2-001/training --host 127.0.0.1 --port 6006
```

Buka `http://localhost:6006` di browser Windows. Model dan log training yang sudah ada tetap digunakan.

## Memeriksa model ketika loss turun tetapi prediksi masih lemah

Jalankan pemeriksaan dari root repo di Ubuntu:

```bash
.venv-training/bin/python scripts/diagnose_model.py
```

Pemeriksaan ini menggunakan CPU untuk membaca nomor langkah pada checkpoint, membandingkan bobot training dan checkpoint pendamping ekspor, lalu menjalankan SavedModel pada satu gambar train per kelas serta gambar abu-abu. Hasilnya di `outputs/model-diagnosis.json`. Dataset, konfigurasi, checkpoint, dan bobot tidak diubah; tidak ada training atau export ulang.

Hasil pembandingan bobot belum membuktikan kualitas generalisasi. Prediksi contoh train juga hanya pemeriksaan diagnostik; laporan evaluasi test tetap menjadi hasil pengujian yang terpisah.

## Percobaan 6000 langkah

`configs/training-6000.json` memakai dataset dan manifest pembagian yang sama, dengan `num_steps: 6000` dan folder hasil terpisah `models/mobilenet/runs/ssd-v2-6000`. Nilai awal lain mengikuti konfigurasi 3000 langkah. Percobaan dimulai dari checkpoint pretrained COCO; hasil 3000 langkah tetap tersimpan. Seed yang ada mengatur pembagian kelompok, sehingga bobot awal head dan perhitungan GPU belum dijamin identik antarpercobaan.

```bash
bash scripts/cv.sh train --config configs/training-6000.json
bash scripts/cv.sh export --config configs/training-6000.json
bash scripts/cv.sh evaluate --config configs/training-6000.json
```

Manifest yang sudah ada dipakai kembali; tidak perlu prepare ulang. Kode mengaitkan durasi cosine decay dengan num_steps, sehingga jadwal learning rate ikut berubah menjadi 6000 langkah. Ini merupakan eksperimen durasi training beserta jadwalnya, bukan penambahan 3000 langkah pada checkpoint lama.

Bandingkan mAP keseluruhan/per kelas dan ketepatan kotak, bukan hanya loss training atau jumlah kotak. Gunakan threshold yang sama untuk perbandingan gambar. Jika hasil test digunakan berulang untuk memilih pengaturan, laporkan sebagai perbandingan eksploratif; penilaian final memerlukan data independen yang belum dipakai memilih pengaturan.
