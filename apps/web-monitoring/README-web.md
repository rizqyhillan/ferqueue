# FERQUEUE — kamera web dan PCV

Alur kamera/unggah: browser → Flask `/api/detect` → API PCV → kelas, confidence, dan bounding box pada web. Golongan dipilih operator. Kamera PCV dapat berjalan tanpa database, ESP32, atau model anomali.

Ikuti **[panduan PCV manual](../../docs/PCV_MANUAL.md)** untuk memasang dependensi dan menyiapkan model. Model pada config yang dipilih harus sudah diekspor atau diimpor.

## Linux

Dari root repo, buat environment web jika belum ada:

```text
python3 -m venv .venv-web
.venv-web/bin/python -m pip install -r apps/web-monitoring/requirements.txt
```

Terminal pertama — PCV, memakai environment Python PCV yang sudah dipasang:

```text
source .venv-pcv/bin/activate
python pcv.py serve --config apps/computer-vision/configs/coco.json
```

Tunggu **API siap**. Terminal kedua — Flask:

```text
.venv-web/bin/python apps/web-monitoring/app.py
```

Buka [dashboard](http://localhost:5000). Uji **Unggah** dahulu, lalu **Aktifkan kamera** dan izinkan akses kamera. Frame diperkecil hingga sisi terpanjang 640 piksel sebelum dikirim.

### Ukur panjang dan tinggi dengan trigonometri geometri kamera

1. Ukur posisi kamera tetap terhadap titik kendaraan berhenti: **jarak tegak lurus (`d_perp`)** dan **geser samping (`d_parallel`)** dalam cm, lalu masukkan ke panel kalibrasi di halaman Monitoring.
2. Letakkan objek acuan (misalnya penggaris/kartu) dengan lebar diketahui di titik kendaraan menghadap lensa, isi **Lebar acuan (cm)**, lalu klik **Kalibrasi acuan (2 titik)** dan klik kedua ujung objek acuan di gambar untuk menyimpan nilai fokus (`f_norm`).
3. Saat ada satu kendaraan utuh terdeteksi, PCV menghitung perkiraan panjang dan tinggi otomatis dalam cm dengan koreksi sudut (`θ`) menggunakan geometri trigonometri.

Untuk mencoba skala sebelum model kendaraan tersedia, jalankan PCV dengan `python pcv.py serve --calibration-only` dan jalankan Flask seperti biasa. Setelah model tersedia, jalankan ulang PCV memakai config model. Bandingkan hasil di kamera tetap dengan penggaris sebelum memakai perkiraan ukuran untuk pemeriksaan.

## Windows

Dari root repo:

```text
py -3.11 -m venv .venv-web
.\.venv-web\Scripts\python.exe -m pip install -r apps/web-monitoring/requirements.txt
.\.venv-web\Scripts\python.exe apps/web-monitoring/app.py
```

Di terminal lain, gunakan environment PCV/inference yang sudah dipasang:

```text
.\.venv-pcv\Scripts\python.exe pcv.py serve --config apps/computer-vision/configs/coco.json
```

Jika model diterima dari komputer lain, berikan config penerima yang sudah dipakai saat `import-model`.

## Koneksi dan parameter

- [Health PCV](http://127.0.0.1:8000/health) dan [health melalui Flask](http://localhost:5000/api/cv/health) harus berisi `status: ready`, kelas, checkpoint, preprocessing, serta threshold yang sesuai.
- Confidence threshold, NMS, dan jumlah deteksi dibaca dari config JSON. Restart API setelah mengubahnya. Preprocessing mengikuti metadata model hasil training.
- Browser mengirim gambar ke Flask pada origin yang sama. Flask meneruskan gambar ke `CV_API_URL`, default `http://127.0.0.1:8000` pada mesin server.
- Untuk mengganti port PCV, gunakan `python pcv.py serve --port 8001` dan set `CV_API_URL=http://127.0.0.1:8001` pada environment proses Flask.
- `WEB_HOST` dan `WEB_PORT` mengatur Flask. File `.env` tidak dimuat otomatis.
- Kamera memerlukan localhost pada komputer kamera atau HTTPS. Alamat IP LAN melalui HTTP biasanya tidak mendapat izin kamera.
- Deteksi kosong bisa terjadi karena gambar tidak berisi objek target atau model/threshold belum sesuai; periksa hasil test dan gambar yang jelas.

Untuk mengoreksi panjang dan tinggi, pilih **Ubah** pada baris dimensi di panel kamera. Koreksi dalam cm dipakai sampai pemeriksaan kendaraan berikutnya. Integrasi ESP32/load cell/gate belum diverifikasi pada tahap ini. Model anomali dan MySQL bersifat terpisah dari jalur kamera.

Node tidak wajib. `npm run dev`/`npm start` tetap dapat menjalankan Flask menggunakan `.venv-web` atau `WEB_PYTHON`.

## Tes penghubung web

```text
PYTHONPATH=apps/web-monitoring .venv-web/bin/python -m unittest discover -s apps/web-monitoring/tests -p 'test_*.py' -v
```

Tes memeriksa halaman/modul kamera, forwarding gambar, batas ukuran, dan penanganan PCV offline. Dari folder web, `npm run check` memeriksa sintaks JavaScript dan `npm test` menjalankan tes tiket.
