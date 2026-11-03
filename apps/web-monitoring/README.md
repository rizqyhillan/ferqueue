# FERQUEUE — Web Monitoring

Antarmuka pos masuk pelabuhan dengan empat panel sesuai sketsa: **kamera** besar di kiri, **berat** dan **golongan** di kanan atas, serta **tiket masuk** di kanan bawah. Panel menggunakan sudut siku, susunan simetris, warna netral, dan satu aksen biru tua. Pada layar kecil panel disusun vertikal.

## Menjalankan

Butuh Node.js 20 atau lebih baru. Tidak perlu memasang dependensi.

```powershell
cd apps/web-monitoring
npm.cmd run dev
```

Buka **http://localhost:4173**. Server hanya menerima koneksi dari perangkat lokal. Jika port terpakai, atur `PORT` di environment sebelum menjalankan server.

```powershell
npm.cmd run check
npm.cmd test
```

## Fitur

- Header, navigasi pemeriksaan dan riwayat tiket, tanggal serta jam WIB.
- Pratinjau ilustrasi kendaraan berlabel data contoh. Aktifkan kamera perangkat dengan izin browser, atau unggah JPG/PNG/WebP maksimal 12 MB. Tombol ambil gambar mengunduh PNG. Tombol perbesar membuka layar penuh jika didukung browser.
- Berat dan golongan dapat dikonfirmasi melalui dialog Ubah. Kamera yang sebenarnya atau gambar yang diunggah tidak diberi hasil deteksi atau ukuran contoh.
- Validasi nomor polisi, berat, dan pilihan golongan sebelum tiket diterbitkan. Nilai contoh awal perlu dikonfirmasi. Pemeriksaan kendaraan berikutnya mengosongkan berat, golongan, dan nomor polisi agar hasil kendaraan sebelumnya tidak terpakai.
- Nomor tiket berurutan per tanggal WIB, riwayat dan pencarian lokal (500 tiket terbaru), cetak ulang, serta tampilan cetak khusus. Pilih printer atau Simpan sebagai PDF pada dialog cetak browser.
- Riwayat disimpan menggunakan `localStorage`, hanya tersedia di browser/perangkat yang sama. Jika penyimpanan tidak tersedia, tiket tetap dapat dicetak dan pemberitahuan penyimpanan sementara ditampilkan.

## Batas integrasi

Ini antarmuka demo yang dapat dijalankan, belum terhubung ke API, PostgreSQL, load cell, model PCV, maupun palang gate. Berat dan golongan merupakan **input operator**, dimensi awal adalah **contoh simulasi**, dan tiket cetak diberi label demo. Pilihan golongan bukan keputusan klasifikasi otomatis atau penetapan tarif. Tidak ada tarif atau pembayaran yang dihitung.

Kamera memerlukan localhost atau HTTPS dan izin pengguna. Tidak ada gambar yang dikirim ke server; kamera dan unggah gambar diproses di browser. Kamera dihentikan ketika dinonaktifkan atau halaman ditinggalkan.

## Struktur

| File | Fungsi |
| --- | --- |
| `index.html` | Empat panel pemeriksaan, dialog, dan header |
| `src/styles.css` | Desain responsif dan tata letak cetak |
| `src/app.js` | Kamera, unggah, input operator, riwayat, dan cetak |
| `src/tickets.js` | Validasi, nomor tiket, dan pemulihan riwayat |
| `assets/camera-demo.svg` | Ilustrasi kamera lokal, tanpa aset eksternal |
| `server.mjs` | Server pratinjau lokal tanpa dependensi |

File frontend dapat dilayani oleh server statis; tidak ada langkah build yang diperlukan.
