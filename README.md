# FERQUEUE

Sistem Manajemen Antrean Kapal Berbasis Computer Vision dan Sensor Load Cell pada Gate Pelabuhan.

FERQUEUE menggabungkan webcam, model Computer Vision berbasis MobileNet, sensor load cell, servo, dan ESP32 untuk mengatur antrean kendaraan yang masuk ke kapal feri. Sistem mencatat tipe kendaraan, berat kendaraan, status gate, serta menampilkan kondisi antrean melalui web monitoring.

## Pembagian jobdesk

| Anggota | Area kerja | Folder utama |
| --- | --- | --- |
| Hillan | Computer Vision: webcam, MobileNet, klasifikasi kendaraan, dan penghitungan kendaraan | `apps/computer-vision/` |
| Zafar | Rancang sistem tertanam: ESP32, load cell, servo, dan komunikasi perangkat | `firmware/esp32-gate/` |
| Zaki | Rancang sistem cerdas: aturan antrean, validasi event, API, dan integrasi data | `apps/backend/`, `shared/contracts/` |
| Akbar | Desain dan pembuatan web monitoring | `apps/web-monitoring/` |

## Struktur proyek

```text
ferqueue/
├── apps/
│   ├── backend/            # API dan logika sistem cerdas
│   ├── computer-vision/    # Engine MobileNet + webcam
│   └── web-monitoring/     # Dashboard monitoring
├── firmware/
│   └── esp32-gate/         # Firmware ESP32, load cell, dan servo
├── shared/
│   └── contracts/           # Kontrak event/API lintas komponen
├── docs/                    # Arsitektur, alur, wiring, dan pembagian kerja
├── data/                    # Dataset lokal, tidak di-commit
├── models/                  # File model, tidak di-commit
├── scripts/                 # Script bantuan development
├── .env.example
└── docker-compose.yml
```

## Mulai cepat

### 1. Backend

```powershell
cd apps/backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8000
```

API tersedia di `http://localhost:8000`, dokumentasi Swagger di `http://localhost:8000/docs`.

### 2. Computer Vision

```powershell
cd apps/computer-vision
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.main --source 0 --api-url http://localhost:8000
```

File model MobileNet diletakkan di `models/mobilenet/`. Detail model dan format label ada di `apps/computer-vision/README.md`.

### 3. ESP32

Buka folder `firmware/esp32-gate/` dengan PlatformIO, salin `include/config.example.h` menjadi `include/config.h`, lalu sesuaikan pin dan alamat API/MQTT. Detail wiring ada di `docs/wiring-esp32.md`.

### 4. Web monitoring

```powershell
cd apps/web-monitoring
npm install
npm run dev
```

Dashboard tersedia di alamat yang ditampilkan Vite, biasanya `http://localhost:5173`.

## Catatan penting

- File di `data/` dan `models/` sengaja tidak masuk Git karena ukuran dataset/model.
- Jangan memasukkan password Wi-Fi, token API, atau kredensial cloud ke source code.
- Kontrak payload event ada di `shared/contracts/vehicle-event.schema.json`. Perubahan kontrak harus dibahas lintas tim.
- Sistem ini adalah scaffold awal. Pin sensor, jenis board ESP32, model final, dan kelas kendaraan perlu divalidasi menggunakan perangkat nyata.

## Dokumentasi

- [Arsitektur sistem](docs/arsitektur.md)
- [Alur kerja dan integrasi](docs/alur-kerja.md)
- [Kontrak API dan event](docs/kontrak-api.md)
- [Wiring ESP32](docs/wiring-esp32.md)
- [Panduan kontribusi](CONTRIBUTING.md)
