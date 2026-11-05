# FERQUEUE — kamera web dan PCV

Alur aktif: kamera/unggah gambar → Flask `/api/detect` → model PCV lokal → bounding box, kelas Mobil/Truk/Bus dan confidence pada web. Golongan dipilih operator lewat **Ubah**. Dimensi belum diukur. Kamera ini tidak memerlukan ESP32, MySQL atau model anomali.

## Menjalankan di Linux (dari root repo)

Setup web sekali:

```bash
python3 -m venv .venv-web
.venv-web/bin/python -m pip install -r apps/web-monitoring/requirements.txt
```

Terminal pertama — web:

```bash
.venv-web/bin/python apps/web-monitoring/app.py
```

Terminal kedua — PCV:

```bash
python3 scripts/start_pcv.py
```

Launcher PCV memakai `.venv-training` atau `.venv-inference` yang sudah ada dan memilih model melalui `configs/training-coco-bn.json`. Tunggu pesan **API siap**. Untuk model dari eksperimen lain:

```bash
python3 scripts/start_pcv.py --config configs/training.json
```

Model harus sudah diekspor pada `run_dir` config terpilih. Bila belum ada environment/model, ikuti panduan computer vision untuk setup dan export/import terlebih dahulu. Launcher tidak melakukan training atau unduhan otomatis.

Buka **http://localhost:5000**, klik **Aktifkan kamera**, dan izinkan akses kamera. Bisa juga klik **Unggah** untuk menguji JPG/PNG/WebP. Hasil pada gambar unggahan dipertahankan sampai gambar diganti; kamera live memperbarui hasil setiap frame selesai diproses. Gambar diperkecil hingga sisi terpanjang 640 piksel sebelum dikirim. Tidak ada pengukuran dimensi 3D atau penetapan golongan otomatis.

`npm run dev` / `npm start` di folder ini sekarang juga menjalankan Flask, menggunakan `.venv-web` atau executable dari `WEB_PYTHON`. Node bukan server statis terpisah. Node tidak wajib jika menjalankan Python langsung.

## Windows

Dari root repo, setup dan jalankan web:

```powershell
py -3.11 -m venv .venv-web
.\.venv-web\Scripts\python.exe -m pip install -r apps/web-monitoring/requirements.txt
.\.venv-web\Scripts\python.exe apps/web-monitoring/app.py
```

Di terminal kedua: `py -3.11 scripts/start_pcv.py`. PCV membutuhkan environment inference/training dan model ekspor yang sesuai; lihat panduan computer vision untuk setup Windows.

## Pemeriksaan koneksi

- http://localhost:5000/api/cv/health harus berisi `status: ready` dan daftar kelas jika PCV sudah siap.
- Bila muncul **PCV belum terhubung**, periksa terminal PCV dan pastikan port 8000 belum dipakai aplikasi lain.
- Bila model belum diekspor, gunakan config dengan `run_dir` yang benar atau export/import model terlebih dahulu.
- Browser mengirim gambar ke web; web meneruskannya ke `CV_API_URL` (default `http://127.0.0.1:8000`). Ini menghindari perbedaan origin port 5000/4173 dan alamat loopback komputer browser.
- `WEB_HOST` dan `WEB_PORT` mengatur listener web (default `0.0.0.0:5000`). Variabel tersebut dibaca dari environment proses, bukan otomatis dari `.env`.
- Untuk kamera, buka localhost pada komputer kamera atau gunakan HTTPS. Alamat IP LAN lewat HTTP biasanya tidak mendapat izin kamera dari browser.
- PCV mengenali jenis kendaraan; ketepatan hasil bergantung pada model/data, bukan koneksi saja. Layar kosong abu-abu wajar menghasilkan nol deteksi.

Integrasi ESP32/load cell/gate belum diverifikasi pada tahap ini. Endpoint IoT lama dipertahankan. Tidak ada perintah perangkat yang dikirim oleh modul kamera atau pemeriksaan health PCV. Model anomali dan MySQL bersifat terpisah; dependensi/koneksinya tidak wajib untuk kamera PCV.

## Tes

```bash
PYTHONPATH=apps/web-monitoring .venv-web/bin/python -m unittest discover -s apps/web-monitoring/tests -p 'test_*.py' -v
```

Dari folder web, `npm run check` memeriksa sintaks JavaScript dan `npm test` menjalankan tes tiket. Tes penghubung PCV memeriksa render halaman/modul, forwarding gambar, batas ukuran, respons model tidak valid dan pesan saat PCV mati.
