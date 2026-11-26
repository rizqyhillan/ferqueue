# PCV FERQUEUE

Seluruh perintah dijalankan dari root FERQUEUE menggunakan `python pcv.py <tahap>` dengan environment Python `.venv-pcv` yang aktif.

## Struktur

```text
apps/computer-vision/
  configs/
    coco-v4-clahe.json        # Eksperimen LAB-CLAHE halus + SSD MobileNet V2 (split sama dgn v4)
    receiver-v4.json          # Model baseline v4 (RGB standar)
    receiver-v4-clahe.json    # Model eksperimen v4 + LAB-CLAHE hasil training Colab
  notebooks/
    train_colab_v4.ipynb      # Training Colab baseline v4
    train_colab_v4_clahe.ipynb# Training Colab eksperimen v4 + LAB-CLAHE + tabel banding v4
  requirements/
    data.txt                  # Gambar dan preprocessing
    training.txt              # TensorFlow CPU dan Object Detection API
    training-cuda.txt         # Tambahan NVIDIA
    inference.txt             # Prediksi dan API tanpa sumber training
  src/ferqueue_cv/            # Modul tahapan PCV
  tests/                      # Pengujian unit
```

## Perintah

| Tahap | Kegunaan |
| --- | --- |
| `inspect` | Memeriksa sumber YOLO/COCO dan ringkasan split train/test |
| `prepare` | Membekukan manifest kelas, split, dan hash sumber (otomatis dijalankan oleh `build-records` bila manifest belum ada) |
| `preview` | Cek cepat sampel hasil preprocessing side-by-side beserta GT box |
| `build-records` | Membuat `label_map.pbtxt`, `training-plan.json`, dan `records/{train,test}.tfrecord` |
| `train`, `export`, `evaluate` | Training TensorFlow, ekspor SavedModel, dan evaluasi metrik COCO test |
| `predict` | Prediksi file gambar dan penyimpanan bbox/JSON (otomatis mengikuti preprocessing model) |
| `serve` | API kamera untuk Flask pada port 8000 |
| `package-model`, `import-model` | Membagikan dan mengimpor SavedModel beserta metadata preprocessing |
| `fix-tf-slim`, `check`, `check-inference` | Kompatibilitas dan pemeriksaan environment |
| `diagnose`, `network`, `clean-dataset`, `test` | Diagnostik model, ringkasan CNN, audit dataset, dan unit test |

## Alur Eksperimen Perbandingan: `v4` (RGB Standar) vs `v4 + LAB-CLAHE`

1. **Cek cepat sampel hasil LAB-CLAHE halus** (`clahe_clip_limit: 1.5`, `clahe_grid_size: 8`):
   ```bash
   .venv-pcv/bin/python pcv.py preview --config apps/computer-vision/configs/coco-v4-clahe.json --limit 8 --output outputs/preview-v4-clahe
   ```
2. **Bangun TFRecord LAB-CLAHE** (memakai split `pcv-coco-manifest-v4` yang 100% identik dengan baseline `v4`):
   ```bash
   .venv-pcv/bin/python pcv.py build-records --config apps/computer-vision/configs/coco-v4-clahe.json
   ```
3. **Upload ke Google Drive** isi folder `models/mobilenet/runs/pcv-coco-colab-v4-clahe/` (`label_map.pbtxt`, `inputs.json`, `training-plan.json`, `records/train.tfrecord`, `records/test.tfrecord`) ke `MyDrive/ferqueue/pcv-coco-colab-v4-clahe/`.
4. **Jalankan `apps/computer-vision/notebooks/train_colab_v4_clahe.ipynb`** di Google Colab (T4 GPU). Cell 6 otomatis menghitung metrik COCO dan mencetak tabel perbandingan langsung terhadap baseline `v4`.
5. **Impor model hasil Colab ke laptop** (default config `pcv.py` sudah menunjuk ke `receiver-v4-clahe.json`; metadata LAB-CLAHE otomatis terbawa ke `predict` dan `serve`):
   ```bash
   .venv-pcv/bin/python pcv.py import-model --archive outputs/pcv-model-colab-v4-clahe-ckpt-XX.zip
   .venv-pcv/bin/python pcv.py serve
   ```

Untuk menjalankan seluruh unit test:
```bash
.venv-pcv/bin/python pcv.py test
```
