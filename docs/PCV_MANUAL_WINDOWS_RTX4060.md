# Panduan PCV untuk laptop Windows dengan RTX 4060

Panduan ini mengikuti alur [PCV_MANUAL.md](PCV_MANUAL.md), dari dataset YOLO berlabel sampai deteksi kamera di browser. Windows menjalankan driver NVIDIA dan browser. **Ubuntu di WSL2** menjalankan Python 3.11, TensorFlow 2.15.1, dan training SSD MobileNet V2 FPNLite 320×320. TensorFlow 2.15.1 memakai WSL2 untuk mengakses GPU NVIDIA dari laptop Windows. [Dukungan platform TensorFlow](https://www.tensorflow.org/install/pip).

Jalankan perintah satu per satu. Perintah berlabel **PowerShell** dijalankan di Windows. Semua blok **Bash** dijalankan di terminal Ubuntu, dari root folder `ferqueue` setelah repo tersedia, kecuali saat berpindah ke folder converter.

## 1. Siapkan driver NVIDIA dan WSL2

1. Pasang driver Windows untuk **GeForce RTX 4060 Laptop GPU** dan restart bila diminta. WSL2 memakai driver dari Windows, jadi pemasangan driver NVIDIA dilakukan di Windows saja. [Unduhan driver NVIDIA](https://www.nvidia.com/drivers/), [panduan CUDA di WSL](https://docs.nvidia.com/cuda/wsl-user-guide/).
2. Buka **PowerShell sebagai administrator**. Jika belum punya Ubuntu di WSL, jalankan perintah berikut, lalu restart Windows bila diminta. Jika sudah punya Ubuntu, gunakan distro tersebut dan lewati instalasi. [Instalasi WSL dari Microsoft](https://learn.microsoft.com/windows/wsl/install).

```powershell
wsl --install -d Ubuntu-22.04
```

Di **PowerShell**, perbarui WSL dan periksa driver serta versi distro.

```powershell
nvidia-smi
wsl --update
wsl --list --verbose
```

Pastikan RTX 4060 muncul pada `nvidia-smi` dan kolom `VERSION` untuk Ubuntu bernilai `2`. Jika masih `1`, jalankan `wsl --set-version Ubuntu-22.04 2` dengan nama distro dari hasil daftar. Setelah driver atau WSL diperbarui, restart Windows bila diminta.

Buka **Ubuntu** dari Start Menu. Pada peluncuran pertama, buat username dan password Linux saat diminta. Lalu periksa GPU dari **terminal Ubuntu**.

```bash
nvidia-smi
uname -m
```

Hasil yang diharapkan adalah RTX 4060 dan `x86_64`. Jika Ubuntu tidak menemukan perintah `nvidia-smi`, coba `/usr/lib/wsl/lib/nvidia-smi`. Lanjutkan setelah GPU terlihat dari Ubuntu. [Pemeriksaan GPU di WSL](https://docs.nvidia.com/cuda/wsl-user-guide/).

## 2. Siapkan repo dan Python di Ubuntu

```bash
sudo apt update
sudo apt install git curl unzip build-essential libgl1 libglib2.0-0 python3-venv nano
mkdir -p ~/projects
cd ~/projects
git clone --branch remake-the-calculation-for-pcv https://github.com/rizqyhillan/ferqueue.git
cd ferqueue
```

Contoh clone memakai branch yang memuat `pcv.py` dan alur dari panduan asal. Jika sudah punya salinan yang sesuai, gunakan folder itu. Simpan repo dan dataset kerja di filesystem Ubuntu, misalnya `~/projects/ferqueue`, supaya akses banyak file gambar lebih cepat. Dari root repo di Ubuntu, `explorer.exe .` membuka folder tersebut di File Explorer Windows untuk menyalin dataset atau membuka hasil. [Lokasi file untuk proyek WSL](https://learn.microsoft.com/windows/dev-environment/wsl-interop#performance-considerations).

Periksa `python3.11 --version`. Jika Python 3.11 sudah terpasang di Ubuntu, buat environment dengan `python3.11 -m venv .venv-pcv`. Jika belum, gunakan `uv` untuk mendapatkan Python 3.11 di Ubuntu. Pilih satu cara dan gunakan kembali environment yang sudah sesuai.

```bash
python3 -m venv .venv-tools
.venv-tools/bin/python -m pip install uv
.venv-tools/bin/uv python install 3.11
.venv-tools/bin/uv venv --python 3.11 --seed .venv-pcv
```

Aktifkan environment lalu pasang dependensi GPU dari repo. `training-cuda.txt` mencakup dependensi pengolahan data, TensorFlow 2.15.1, dan library CUDA/cuDNN yang dibutuhkan TensorFlow. Paket tersebut menyediakan library di dalam environment Python. [Versi Python yang dikelola uv](https://docs.astral.sh/uv/concepts/python-versions/), [dependensi CUDA TensorFlow 2.15.1](https://raw.githubusercontent.com/tensorflow/tensorflow/v2.15.1/tensorflow/tools/pip_package/setup.py).

```bash
source .venv-pcv/bin/activate
python --version
python -c 'import sys; print(sys.executable)'
python -m pip install --upgrade pip
python -m pip install -r apps/computer-vision/requirements/training-cuda.txt
python -m pip check
```

Pastikan Python `3.11.x`, executable berada di `.venv-pcv`, dan `pip check` selesai tanpa konflik. Setiap membuka terminal Ubuntu baru untuk PCV, masuk ke root repo dan aktifkan `.venv-pcv` lagi.

## 3. Siapkan Object Detection API dan uji GPU

Gunakan sumber TensorFlow Models pada commit yang dipakai repo, serta `protoc` 3.20.3 Linux x86_64. Jalankan bagian unduh dan ekstrak untuk instalasi baru. Jika `.cache/tensorflow-models` sudah ada, periksa commit yang dipakai dan struktur foldernya sebelum memakai ulang. [Sumber Object Detection API](https://github.com/tensorflow/models/tree/40695ad8964145a90ae1abbcc740c086e7364eac/research/object_detection), [rilis protoc 3.20.3](https://github.com/protocolbuffers/protobuf/releases/tag/v3.20.3).

```bash
mkdir -p .cache
curl -fL https://github.com/tensorflow/models/archive/40695ad8964145a90ae1abbcc740c086e7364eac.zip -o .cache/tensorflow-models.zip
unzip .cache/tensorflow-models.zip -d .cache
mv .cache/models-40695ad8964145a90ae1abbcc740c086e7364eac .cache/tensorflow-models
curl -fL https://github.com/protocolbuffers/protobuf/releases/download/v3.20.3/protoc-3.20.3-linux-x86_64.zip -o .cache/protoc-3.20.3-linux-x86_64.zip
unzip .cache/protoc-3.20.3-linux-x86_64.zip -d .cache/protoc-3.20.3-linux-x86_64
```

`pcv.py` membaca Object Detection API langsung dari `.cache/tensorflow-models/research`. Kompilasi definisi Protobuf lalu perbaiki decoder `tf-slim` pada environment aktif.

```bash
chmod +x .cache/protoc-3.20.3-linux-x86_64/bin/protoc
.cache/protoc-3.20.3-linux-x86_64/bin/protoc --version
.cache/protoc-3.20.3-linux-x86_64/bin/protoc \
  --proto_path=.cache/tensorflow-models/research \
  --python_out=.cache/tensorflow-models/research \
  .cache/tensorflow-models/research/object_detection/protos/*.proto
ls .cache/tensorflow-models/research/object_detection/protos/pipeline_pb2.py
python pcv.py fix-tf-slim
```

Hasil versi compiler harus `libprotoc 3.20.3`. Selanjutnya, arahkan terminal ke library CUDA dan `ptxas` dari `.venv-pcv`. Jalankan blok ini lagi di setiap terminal baru yang dipakai untuk perintah PCV dengan GPU. `TF_FORCE_GPU_ALLOW_GROWTH` juga diteruskan ke proses training agar TensorFlow menambah alokasi VRAM sesuai kebutuhan.

```bash
pcv_site=$(python -c 'import site; print(site.getsitepackages()[0])')
pcv_cuda_libs=$(python -c 'from pathlib import Path; import site; print(":".join(str(p) for p in Path(site.getsitepackages()[0]).glob("nvidia/*/lib")))')
export LD_LIBRARY_PATH="$pcv_cuda_libs:/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PATH="$pcv_site/nvidia/cuda_nvcc/bin:$PATH"
export TF_FORCE_GPU_ALLOW_GROWTH=true
ptxas --version
```

```bash
python -c 'import tensorflow as tf; print(tf.__version__); print(tf.config.list_physical_devices("GPU"))'
python pcv.py check --config apps/computer-vision/configs/coco.json --require-gpu
```

Lanjutkan setelah muncul **`GPU aktif`** dan **`forward pass SSD MobileNet V2 FPNLite siap`**. `check --require-gpu` menguji operasi TensorFlow pada GPU sekaligus memeriksa apakah model SSD bisa menjalankan satu forward pass. Tahap ini dapat dijalankan sebelum menyalin dataset atau bobot pretrained.

## 4. Siapkan dataset YOLO dan konversi ke COCO

Salin gambar asli, label YOLO bbox, dan `classes.txt` ke `data/raw/vehicles/` di Ubuntu. Contoh susunan:

```text
data/raw/vehicles/
  classes.txt
  images/sesi-01/frame-001.jpg
  labels/sesi-01/frame-001.txt
  images/sesi-02/frame-002.jpg
  labels/sesi-02/frame-002.txt
```

Pertahankan urutan kelas pada `classes.txt`. Setiap baris label memakai `class_id center_x center_y width height` dengan ID mulai dari 0 dan koordinat 0–1. Gambar background yang sengaja tanpa objek tetap punya `.txt` kosong. Gunakan subfolder per sesi atau `groups.csv` untuk gambar flat agar frame dari sesi yang sama tetap dalam satu split. Config bawaan membagi data menjadi **70% train dan 30% test berdasarkan kelompok sesi**. Persentase gambar bisa berbeda dari angka tersebut. [Format dataset dan contoh `groups.csv`](PCV_MANUAL.md#4-ambil-dan-susun-data-raw-yang-sudah-berlabel).

```bash
python pcv.py inspect --config apps/computer-vision/configs/yolo.json
python pcv.py stage-yolo --config apps/computer-vision/configs/yolo.json --output data/processed/pcv-converter-v2
```

Perbaiki masalah label dari `inspect` sebelum membuat staging. Buat staging di Ubuntu ini karena `train.txt` dan `test.txt` berisi path absolut. Gunakan folder staging dari hasil yang sudah valid jika masih memakai dataset yang sama.

```bash
git clone https://github.com/Taeyoung96/Yolo-to-COCO-format-converter.git .cache/yolo-to-coco
git -C .cache/yolo-to-coco checkout 35cd81f1e829132f2997f50efcc447c98e9d3d5e
```

Buka `data/processed/pcv-converter-v2/classes_for_converter.txt`. Salin blok `classes = [...]` ke `.cache/yolo-to-coco/main.py` untuk mengganti daftar kelas contoh, lalu simpan. Jalankan converter train dan test satu per satu. Jika ada hasil lama yang ingin disimpan, arsipkan sebelum menjalankan converter lagi. [Petunjuk converter](https://github.com/Taeyoung96/Yolo-to-COCO-format-converter#how-to-use).

```bash
pcv_repo="$PWD"
cd .cache/yolo-to-coco
mkdir -p output
python main.py --path "$pcv_repo/data/processed/pcv-converter-v2/train.txt" --output instances_train.json
python main.py --path "$pcv_repo/data/processed/pcv-converter-v2/test.txt" --output instances_test.json
cd "$pcv_repo"
```

Pastikan kedua JSON ada di `.cache/yolo-to-coco/output/`. Lalu hubungkan hasilnya ke gambar raw.

```bash
python pcv.py adopt-coco --config apps/computer-vision/configs/yolo.json \
  --staging data/processed/pcv-converter-v2 \
  --input .cache/yolo-to-coco/output --output data/processed/pcv-coco-v2
```

## 5. Buat config run RTX 4060 dan TFRecord

Salin config COCO untuk eksperimen ini. Simpan nama config yang sama untuk semua tahap berikutnya.

```bash
cp -i apps/computer-vision/configs/coco.json apps/computer-vision/configs/coco-rtx4060.json
nano apps/computer-vision/configs/coco-rtx4060.json
```

Di salinan tersebut, ubah `run_dir` menjadi `models/mobilenet/runs/pcv-coco-rtx4060-001`. Untuk baseline, pakai `batch_size` 4 dan `epochs` 30 dari config bawaan. Pertahankan `dataset_dir`, `coco_annotations`, dan `prepared_dir` jika mengikuti struktur sebelumnya. Jika data, label, atau split berubah, gunakan versi baru untuk hasil konversi, manifest, dan run, lalu sesuaikan path di config.

```bash
python pcv.py inspect --config apps/computer-vision/configs/coco-rtx4060.json
python pcv.py prepare --config apps/computer-vision/configs/coco-rtx4060.json
```

Periksa `data/processed/pcv-coco-manifest-v2/summary.json` dan distribusi kelas sebelum melatih. Jika manifest yang sesuai sudah tersedia, langsung gunakan kembali. Sebelum membuat TFRecord, kamu bisa memeriksa gambar, kotak label, dan hasil preprocessing pada sampel train. Mask GrabCut dipakai untuk review. Training memakai gambar utuh dan kotak label.

```bash
python pcv.py segment --config apps/computer-vision/configs/coco-rtx4060.json --split train --limit 12 --output outputs/rtx4060-segment
python pcv.py preview --config apps/computer-vision/configs/coco-rtx4060.json --split train --limit 12 --output outputs/rtx4060-preview
```

```bash
python pcv.py plan --config apps/computer-vision/configs/coco-rtx4060.json
python pcv.py build-records --config apps/computer-vision/configs/coco-rtx4060.json
```

Periksa `training-plan.json`, `label_map.pbtxt`, serta `records/train.tfrecord` dan `records/test.tfrecord` di `models/mobilenet/runs/pcv-coco-rtx4060-001/`. `plan` menampilkan jumlah langkah yang dihitung dari epoch, ukuran batch, dan jumlah gambar train.

## 6. Training dengan RTX 4060

Siapkan bobot awal COCO. Untuk unduhan manual, ekstrak arsip resmi ke `models/mobilenet/pretrained/` agar folder `ssd_mobilenet_v2_fpnlite_320x320_coco17_tpu-8/` berisi `pipeline.config` dan `checkpoint/ckpt-0.*`. Jika belum tersedia, `train` mencoba mengunduh model resmi saat mulai. [Arsip SSD MobileNet V2 FPNLite](https://storage.googleapis.com/download.tensorflow.org/models/object_detection/tf2/20200711/ssd_mobilenet_v2_fpnlite_320x320_coco17_tpu-8.tar.gz).

Di terminal Ubuntu dengan `.venv-pcv` aktif dan pengaturan CUDA dari bagian 3, jalankan:

```bash
python pcv.py train --config apps/computer-vision/configs/coco-rtx4060.json --require-gpu
```

Pertahankan `--require-gpu`. Flag ini menghentikan perintah jika GPU gagal dipakai. `train` tanpa flag tersebut memilih CPU. Saat training mulai, cari `GPU:0` di log `MirroredStrategy`. Dari terminal Ubuntu lain, jalankan `watch -n 2 nvidia-smi` untuk melihat penggunaan GPU dan VRAM jika tersedia. Untuk melihat loss, jalankan TensorBoard dari root repo di terminal Ubuntu lain.

```bash
source .venv-pcv/bin/activate
python -m tensorboard.main --logdir models/mobilenet/runs/pcv-coco-rtx4060-001/training --port 6006
```

Buka [TensorBoard](http://localhost:6006) di browser Windows. Jika perlu berhenti, tekan `Ctrl+C` pada terminal training. Ulangi perintah training dengan config dan dataset yang sama untuk melanjutkan dari checkpoint terakhir yang tersimpan. Jika VRAM habis, coba `batch_size` 2 pada config eksperimen dengan `run_dir` baru, lalu ulangi `plan`, `build-records`, dan `train` memakai config baru itu.

## 7. Export, evaluasi, dan prediksi

```bash
python pcv.py export --config apps/computer-vision/configs/coco-rtx4060.json --require-gpu
python pcv.py evaluate --config apps/computer-vision/configs/coco-rtx4060.json --split test --require-gpu
```

`export` memakai checkpoint terakhir. Periksa `export.json` untuk lokasi SavedModel dan `reports/ckpt-*-test.json` untuk mAP, AP50, serta metrik per kelas. Setelah training dilanjutkan, export lagi sebelum menilai model baru.

Masukkan JPG/PNG baru ke `data/inference/`, lalu jalankan:

```bash
python pcv.py predict --config apps/computer-vision/configs/coco-rtx4060.json \
  --input data/inference --output outputs/rtx4060-predictions --require-gpu
```

Buka gambar hasil dan JSON di `outputs/rtx4060-predictions/`. Untuk memindahkan model ke perangkat lain, gunakan `package-model` dan `import-model` sesuai [panduan pemindahan model](PCV_MANUAL.md#15-perangkat-lain-windows-dan-nvidia-opsional), dengan `coco-rtx4060.json` sebagai config saat membuat paket.

## 8. Uji unggah dan kamera dari browser Windows

Jalankan API PCV dan Flask di Ubuntu yang sama. Browser Windows mengakses Flask melalui `localhost` dan meminta izin kamera langsung ke Windows. [Akses localhost dari Windows ke WSL](https://learn.microsoft.com/windows/wsl/networking#accessing-linux-networking-apps-from-windows-localhost).

**Terminal Ubuntu 1.** Dari root repo, aktifkan `.venv-pcv` dan jalankan blok pengaturan CUDA dari bagian 3 bila terminalnya baru.

```bash
python pcv.py serve --config apps/computer-vision/configs/coco-rtx4060.json --require-gpu
```

Tunggu API siap, lalu periksa [health PCV](http://localhost:8000/health) dari Windows. Harus muncul `status: ready` beserta kelas dan checkpoint.

**Terminal Ubuntu 2.** Dari root repo, buat `.venv-web` jika belum ada, lalu jalankan Flask. Arahkan Flask ke API PCV pada port 8000 di Ubuntu yang sama.

```bash
.venv-pcv/bin/python -m venv .venv-web
.venv-web/bin/python -m pip install -r apps/web-monitoring/requirements.txt
WEB_HOST=127.0.0.1 CV_API_URL=http://127.0.0.1:8000 .venv-web/bin/python apps/web-monitoring/app.py
```

Buka [health melalui Flask](http://localhost:5000/api/cv/health), lalu [dashboard FERQUEUE](http://localhost:5000) di browser Windows. Uji **Unggah** dengan gambar baru, lalu klik **Aktifkan kamera** dan izinkan akses kamera. Alur kamera PCV ini cukup dengan kedua server tersebut.

## 9. Jika tersendat

| Gejala | Yang perlu diperiksa |
| --- | --- |
| RTX 4060 terlihat di Windows, tetapi tidak di Ubuntu | Pastikan Ubuntu berjalan sebagai WSL2. Perbarui WSL dan driver Windows, lalu buka ulang Ubuntu setelah restart. Coba `/usr/lib/wsl/lib/nvidia-smi`. |
| `nvidia-smi` berhasil, tetapi daftar GPU TensorFlow `[]` | Pastikan Python berasal dari `.venv-pcv`, `training-cuda.txt` berhasil terpasang, dan `CUDA_VISIBLE_DEVICES` tidak menyembunyikan GPU. Aktifkan ulang environment dan jalankan blok CUDA dari bagian 3. |
| `ptxas` atau `libdevice.10.bc` tidak ditemukan | Periksa `ptxas --version` dan `ls "$pcv_site/nvidia/cuda_nvcc/nvvm/libdevice/libdevice.10.bc"`. Jika file `libdevice` ada, jalankan `export XLA_FLAGS="${XLA_FLAGS:+$XLA_FLAGS }--xla_gpu_cuda_data_dir=$pcv_site/nvidia/cuda_nvcc"`, lalu ulangi `check --require-gpu`. |
| `object_detection` atau `pipeline_pb2` tidak ditemukan | Periksa struktur `.cache/tensorflow-models/research` dan hasil kompilasi `protoc`. |
| Converter tidak menemukan gambar atau kelas berbeda | Buat staging di Ubuntu yang menjalankan converter. Periksa `classes` pada `main.py` dan kedua JSON hasil converter. |
| `ResourceExhaustedError` atau CUDA kehabisan memori | Tutup proses lain yang memakai GPU. Coba batch 2 dengan `run_dir` baru jika masih kehabisan VRAM. |
| Dashboard tidak bisa dibuka dari Windows | Coba `curl -f http://127.0.0.1:5000/api/cv/health` dari Ubuntu. Jika berhasil di Ubuntu, periksa akses `localhost` dari Windows dan pastikan port 5000 tidak sedang dipakai layanan lain. |
| Dashboard terbuka, tetapi PCV belum siap | Cek terminal `serve`, health port 8000, `CV_API_URL`, dan `export.json` pada run yang dipilih. |

Jika perlu meminta bantuan, sertakan perintah yang gagal, baris error terakhir, hasil `nvidia-smi` dari Ubuntu, versi Python, dan nama config yang dipakai.
