# Perintah FERQUEUE

## PowerShell Windows: anggota tim

Pasang Python 3.11 64-bit. Tidak perlu aktivasi environment secara manual.

```powershell
.\scripts\cv.ps1 setup-data
.\scripts\cv.ps1 prepare
.\scripts\cv.ps1 test
```

Untuk menguji model yang dibagikan laptop training:

```powershell
.\scripts\cv.ps1 import-model -Archive outputs/ssd-model.zip
.\scripts\cv.ps1 setup-inference
.\scripts\cv.ps1 check
.\scripts\cv.ps1 predict -Images data/inference -Output outputs/predictions
```

- `setup-data`: membuat `.venv-data` dan memasang Pillow.
- `prepare`: memvalidasi LabelImg YOLO lalu membekukan split train/test (default 80/20).
- `test`: tes dataset/paket model; tes TensorFlow dilewati bila dependensinya tidak tersedia.
- `import-model`: memasang paket model dari laptop teman; tidak menimpa model/run yang sudah ada.
- `setup-inference`: membuat `.venv-inference`, memasang TensorFlow CPU, NumPy, Pillow.
- `check`: memeriksa environment prediksi Windows.
- `predict`: menyimpan gambar dengan bounding box dan JSON.

Gunakan `-Config configs/eksperimen.json` untuk konfigurasi lain. Bila Python tidak ditemukan, gunakan `-Python C:\lokasi\Python311\python.exe` pada perintah setup. Bila execution policy memblokir `.ps1`, panggil `powershell -ExecutionPolicy Bypass -File .\scripts\cv.ps1 setup-data`; tidak perlu mengubah kebijakan sistem.

## Ubuntu WSL2: laptop NVIDIA RTX 4060

```bash
bash scripts/cv.sh setup
bash scripts/cv.sh check --require-gpu
bash scripts/cv.sh test
bash scripts/cv.sh prepare
bash scripts/cv.sh train
bash scripts/cv.sh export
bash scripts/cv.sh evaluate --split test
bash scripts/cv.sh predict
bash scripts/cv.sh package-model --archive outputs/ssd-model.zip
```

Semua opsi CLI diteruskan melalui `cv.sh`, misalnya `--config configs/eksperimen.json`. Evaluasi memakai test secara default, sehingga cukup menjalankan `bash scripts/cv.sh evaluate`. Jangan jalankan `prepare` lagi jika manifest sudah ada. Untuk mengganti manifest tiga bagian yang lama, pilih `prepared_dir` dan `run_dir` baru sebelum prepare.

Setup lengkap: [training GPU Windows](../docs/TRAINING_GPU_WINDOWS.md). Kebutuhan training hanya dipasang di laptop NVIDIA; PowerShell menolak perintah training agar tidak salah menjalankannya di CPU Windows.
