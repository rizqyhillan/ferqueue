# FERQUEUE

PCV deteksi kendaraan dengan **TensorFlow 2.15.1, preprocessing LAB-CLAHE halus, dan SSD MobileNet V2 FPNLite 320×320**, terhubung ke dashboard Flask untuk kamera live, unggah gambar, pengukuran dimensi kamera samping (pinhole), validasi aturan anomali, dan AI Assistant LLM.

## Alur Utama PCV (LAB-CLAHE → SSD MobileNet V2 FPNLite)

1. Pasang Python 3.11 dan environment `.venv-pcv`, lalu pasang dependensi dari `apps/computer-vision/requirements/`.
2. Siapkan gambar dan label berlabel manual (`Mobil`, `Truk`, `Bus`) di `data/raw/vehicles/`.
3. Jalankan tahap pengolahan data di laptop lokal dari root repo:

```text
.venv-pcv/bin/python pcv.py inspect --config apps/computer-vision/configs/coco-v4-clahe.json
.venv-pcv/bin/python pcv.py preview --config apps/computer-vision/configs/coco-v4-clahe.json --limit 8 --output outputs/preview-v4-clahe
.venv-pcv/bin/python pcv.py build-records --config apps/computer-vision/configs/coco-v4-clahe.json
```

`build-records` otomatis membekukan manifest bila belum ada, menerapkan preprocessing **LAB-CLAHE halus** (`clahe_clip_limit: 1.5`, `clahe_grid_size: 8` pada kanal luminansi `L`), serta menghasilkan `records/train.tfrecord`, `records/test.tfrecord`, `label_map.pbtxt`, `inputs.json`, dan `training-plan.json`.

4. Latih model di **Google Colab GPU** menggunakan `apps/computer-vision/notebooks/train_colab_v4_clahe.ipynb` (atau lokal dengan `pcv.py train`), lalu unduh arsip ZIP hasil ekspor (`pcv-model-colab-v4-clahe-ckpt-XX.zip`) ke `outputs/`.
5. Impor model ke laptop lokal dan jalankan prediksi / API live kamera (default config `pcv.py` adalah `apps/computer-vision/configs/receiver-v4-clahe.json`):

```text
.venv-pcv/bin/python pcv.py import-model --archive outputs/pcv-model-colab-v4-clahe-ckpt-XX.zip
.venv-pcv/bin/python pcv.py predict --input data/inference --output outputs/clahe-predictions
.venv-pcv/bin/python pcv.py serve
```

Preprocessing LAB-CLAHE otomatis dibaca dari metadata model hasil impor (`export.json`), sehingga transformasi saat training, evaluasi, `predict`, dan kamera live (`serve`) selalu identik.

## Struktur

| Lokasi | Fungsi |
| --- | --- |
| `pcv.py` | Entry point CLI seluruh tahap PCV (default: `receiver-v4-clahe.json`) |
| `apps/computer-vision/configs/coco-v4-clahe.json` | Config persiapan data & training LAB-CLAHE (split konsisten `v4`) |
| `apps/computer-vision/configs/receiver-v4-clahe.json` | Config default penerima model LAB-CLAHE untuk `import-model`, `predict`, & `serve` |
| `apps/computer-vision/notebooks/train_colab_v4_clahe.ipynb` | Notebook training Colab GPU, evaluasi perbandingan `v4`, & visualisasi ekstraksi fitur CNN |
| `apps/computer-vision/src/ferqueue_cv/` | Modul tiap tahap PCV (`processing.py`, `training.py`, `live_api.py`, `side_measurement.py`, dll.) |
| `apps/web-monitoring/` | Flask dashboard, monitoring kamera, aturan anomali, & AI Assistant LLM ([panduan web](apps/web-monitoring/README-web.md)) |
| `data/raw/vehicles/` | Gambar dan label asli lokal |
| `data/processed/` | Anotasi COCO dan manifest dataset |
| `models/mobilenet/runs/` | TFRecord, checkpoint, SavedModel ekspor, dan laporan per eksperimen |
| `outputs/` | Preview, prediksi, paket ZIP model, dan diagram alur |
| `firmware/` | Firmware ESP32 load cell HX711 & servo gate |

Perintah utilitas tambahan:

```text
.venv-pcv/bin/python pcv.py test
.venv-pcv/bin/python pcv.py network
.venv-pcv/bin/python pcv.py diagnose
```
