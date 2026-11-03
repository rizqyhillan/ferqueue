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
- `clean-dataset`: audit seluruh gambar tanpa label, label tanpa gambar, dan duplikat gambar berdasarkan SHA256. Tulis laporan lengkap, lalu tunggu input `y` sebelum karantina. Lihat alur review di bawah.
- `prepare`: memvalidasi LabelImg YOLO lalu membekukan split train/test (konfigurasi saat ini 70/30).
- `test`: tes dataset/paket model; tes TensorFlow dilewati bila dependensinya tidak tersedia.
- `import-model`: memasang paket model dari laptop teman; tidak menimpa model/run yang sudah ada.
- `setup-inference`: membuat `.venv-inference`, memasang TensorFlow CPU, NumPy, Pillow.
- `check`: memeriksa environment prediksi Windows.
- `predict`: menyimpan gambar dengan bounding box dan JSON.

Gunakan `-Config configs/eksperimen.json` untuk konfigurasi lain. Bila Python tidak ditemukan, gunakan `-Python C:\lokasi\Python311\python.exe` pada perintah setup. Bila execution policy memblokir `.ps1`, panggil `powershell -ExecutionPolicy Bypass -File .\scripts\cv.ps1 setup-data`; tidak perlu mengubah kebijakan sistem.

## Linux native: laptop sendiri, CPU Ryzen

```bash
bash scripts/cv.sh setup
bash scripts/cv.sh check
bash scripts/cv.sh test
bash scripts/cv.sh prepare
bash scripts/cv.sh benchmark
bash scripts/cv.sh train
bash scripts/cv.sh export
bash scripts/cv.sh evaluate --split test
bash scripts/cv.sh predict
bash scripts/cv.sh package-model --archive outputs/ssd-model.zip
```

Semua opsi CLI diteruskan melalui `cv.sh`, misalnya `--config configs/eksperimen.json`. Evaluasi memakai test secara default, sehingga cukup menjalankan `bash scripts/cv.sh evaluate`. Jangan jalankan `prepare` lagi jika manifest sudah ada. Untuk mengganti manifest tiga bagian yang lama, pilih `prepared_dir` dan `run_dir` baru sebelum prepare.

`benchmark` mengukur 200 langkah pada run baru di `outputs/benchmarks/`, mengabaikan 100 langkah awal untuk estimasi waktu 3.000/6.000 langkah. Gunakan `--steps 500` untuk pengukuran lebih lama. Training penuh dan benchmark menyimpan log serta laporan durasi JSON di folder `reports/` run masing-masing. Default training memakai CPU, dengan 6 thread intra-op dan 2 inter-op. [Panduan training lokal](../docs/TRAINING_LOCAL.md).

Untuk laptop NVIDIA, gunakan `bash scripts/cv.sh setup --device cuda`, lalu tambahkan `--require-gpu` saat `check`, `benchmark`, dan `train`. [Panduan training GPU Windows](../docs/TRAINING_GPU_WINDOWS.md). PowerShell tetap digunakan untuk persiapan dataset dan prediksi; training dijalankan dari Linux.

## Review dan bersihkan dataset sebelum prepare

```bash
bash scripts/cv.sh clean-dataset
```

Perintah ini memindai seluruh dataset tanpa berhenti di masalah pertama. Buka `outputs/dataset-cleanup/<waktu-id>/report.txt` atau `report.json` yang ditampilkan di terminal. Laporan mencantumkan setiap file kandidat, alasan, pasangan duplikat, file yang dipertahankan, serta konflik yang perlu diperiksa manual. Setelah selesai review, kembali ke terminal yang masih menunggu dan ketik **`y`** untuk menjalankan seluruh rencana. Jawaban selain `y`, Ctrl+C, atau input tertutup membatalkan perubahan dataset.

Untuk hanya membuat laporan tanpa pertanyaan:

```bash
bash scripts/cv.sh clean-dataset --dry-run
```

PowerShell Windows menggunakan environment data yang sudah tersedia:

```powershell
.\scripts\cv.ps1 clean-dataset
# Audit saja:
.\scripts\cv.ps1 clean-dataset -DryRun
```

- Gambar tanpa `.txt` dan label tanpa gambar menjadi kandidat karantina. Label kosong yang memang untuk background tetap sah; script tidak membuat label kosong otomatis.
- Gambar duplikat berarti **byte file identik (SHA256)** walaupun namanya berbeda. Foto yang hanya mirip atau disimpan ulang dengan kompresi berbeda tidak digabung otomatis.
- Untuk gambar identik dengan anotasi setara dan valid, pasangan pertama berdasarkan urutan path dipertahankan; salinan lainnya beserta label pasangannya menjadi kandidat karantina. Gambar tanpa label tidak dipilih sebagai salinan utama.
- Isi `.txt` yang sama pada gambar berbeda tidak menjadi alasan penghapusan. Anotasi berbeda untuk gambar identik, label tidak valid, atau dua gambar berbagi satu label dicatat untuk review manual dan pasangan berlabel tersebut tetap disimpan.
- File yang disetujui dipindahkan dari dataset ke `<folder-laporan>/files/` dengan struktur path asal. Ini mengeluarkannya dari input `prepare` tanpa penghapusan permanen. Untuk memulihkan, salin file dari `files/` kembali ke path relatif yang sama di root repo; daftar path asal/backup tersedia di `applied.json`.
- Jika `groups.csv` mencantumkan gambar yang dikarantina, barisnya ikut dihapus setelah persetujuan. CSV asli disimpan di `<folder-laporan>/original/`; pulihkan juga CSV tersebut jika membatalkan cleanup.
- Dataset diperiksa ulang setelah konfirmasi. Perubahan file selama review membatalkan rencana. Jangan menjalankan labeling, cleanup lain, atau `prepare` bersamaan. `moves.jsonl` mencatat kemajuan setiap pemindahan, sedangkan `applied.json` menyimpan rangkuman saat operasi selesai atau mengalami kesalahan. Jika operasi terputus, periksa catatan dan backup sebelum melanjutkan.
- Cleanup diblokir jika `prepared_dir` sudah berisi hasil prepare. Gunakan `prepared_dir` dan `run_dir` baru agar manifest/eksperimen lama tidak dipakai kembali setelah dataset berubah.

Setelah cleanup selesai dan catatan manual diperbaiki, jalankan `bash scripts/cv.sh prepare`. Perintah `prepare` tetap memvalidasi dataset secara ketat.
