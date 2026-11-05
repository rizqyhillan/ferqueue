from datetime import datetime
import os
from flask import Flask, jsonify, request, render_template, send_from_directory
from cv_bridge import cv_api

# Kamera dan dashboard dapat berjalan tanpa paket model anomali.
try:
    import joblib
    import numpy as np
except ImportError:
    joblib = None
    np = None

# Import modul aturan & ekstraksi fitur (menggunakan core_diecast.py untuk skala Hot Wheels)
try:
    from core_diecast import cek_aturan, feat, skor
    print("[OK] Memuat aturan diecast dari core_diecast.py")
except ImportError:
    cek_aturan = feat = skor = None
    print("[INFO] Evaluasi anomali tidak aktif; kamera PCV tetap tersedia.")

# Import modul database MySQL (db.py)
try:
    from db import simpan_pemeriksaan, simpan_tiket, ambil_semua_tiket
    print("[OK] Modul database db.py berhasil diimpor!")
except ImportError:
    simpan_pemeriksaan = lambda x: None
    simpan_tiket = lambda *args: None
    ambil_semua_tiket = lambda: []
    print("[WARN] db.py tidak ditemukan, integrasi DB dilewati.")

# Inisialisasi Flask (menggunakan folder templates dan static yang sudah dibuat)
app = Flask(__name__, template_folder="templates", static_folder="static")
app.register_blueprint(cv_api)

# ------------------------------------------------------------------
# 1. Load Model & Scaler Machine Learning (Model Diecast)
# ------------------------------------------------------------------
scaler = None
models = None
thresholds = {"kmeans": 1.56, "iforest": 0.56}
MODEL_FILE_NAME = "model_anomali_diecast.joblib"

try:
    model_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), MODEL_FILE_NAME)
    if joblib is None:
        raise ImportError("Paket model anomali belum dipasang")
    saved_data = joblib.load(model_file)
    scaler = saved_data["scaler"]
    models = saved_data["models"]
    if "thr" in saved_data:
        thresholds = {k: float(v) for k, v in saved_data["thr"].items()}
    print(f"[OK] Model ML & Scaler ({MODEL_FILE_NAME}) berhasil dimuat! Ambang batas: {thresholds}")
except Exception as e:
    print(
        f"[WARN] Gagal memuat {MODEL_FILE_NAME} (Fitur ML mungkin tidak bisa digunakan): {e}"
    )

# ------------------------------------------------------------------
# 2. State Memory Backend (IoT & Monitoring Web)
# ------------------------------------------------------------------
# state_iot["berat"] menyimpan nilai mentah dalam SATUAN GRAM dari ESP32/Loadcell
state_iot = {"berat": 0.0, "servo": 0, "waktu": None}
antrean_perintah = []
daftar_tiket = []

state_kendaraan = {
    "jenis": "truk",
    "P": 0.0,
    "L": 0.0,
    "T": 0.0,
    "W": 0.0,           # Satuan Ton (ML / Rule)
    "berat_kg": 0.0,    # Satuan KG (Dashboard Web)
    "berat_gram": 0.0,  # Satuan Gram mentah
    "golongan": "-",
    "status_anomali": "Normal",
    "skor_anomali": 0.0,
    "waktu": None,
}


# ==================================================================
# ROUTE UTAMA & STATIC FILE HANDLING (FRONTEND)
# ==================================================================
@app.route("/", methods=["GET"])
def index():
    # Menampilkan langsung index.html dari folder templates
    return render_template("index.html")


@app.route("/src/<path:filename>")
@app.route("/<path:filename>")
def serve_static_files(filename):
    # Route pendukung jika index.html memanggil file dari path relatif
    static_dir = os.path.join(app.root_path, "static")
    if os.path.exists(os.path.join(static_dir, filename)):
        return send_from_directory(static_dir, filename)
    return jsonify({"error": f"File {filename} tidak ditemukan"}), 404


# ==================================================================
# ENDPOINT MACHINE LEARNING & INTEGRASI DASHBOARD
# ==================================================================
@app.route("/predict/<model_type>", methods=["POST"])
def predict(model_type):
    if not models or not scaler or cek_aturan is None:
        return (
            jsonify({"error": "Model Machine Learning belum dimuat di server"}),
            500,
        )

    try:
        data = request.get_json(force=True) if request.is_json and request.get_data() else {}

        # 1. Ambil input dimensi & jenis dari Postman
        # SATUAN: dimensi dalam CM, berat dalam GRAM (skala diecast)
        jenis = str(data.get("jenis", "truk")).strip().lower()
        
        # Batasi minimum dimensi 0.1 cm agar tidak 0
        P = max(float(data.get("P", 0.0)), 0.1)
        L = max(float(data.get("L", 0.0)), 0.1)
        T = max(float(data.get("T", 0.0)), 0.1)

        # 2. Penentuan Berat dalam GRAM
        # Prioritas: Load Cell > W dari Postman > fallback 0
        berat_loadcell_gram = float(state_iot.get("berat", 0.0))

        if berat_loadcell_gram > 0:
            berat_gram = berat_loadcell_gram
        elif "W" in data and float(data.get("W", 0)) > 0:
            berat_gram = float(data["W"])
        elif "berat_gram" in data and float(data.get("berat_gram", 0)) > 0:
            berat_gram = float(data["berat_gram"])
        elif "berat" in data and float(data.get("berat", 0)) > 0:
            berat_gram = float(data["berat"])
        else:
            berat_gram = 0.1  # minimum fallback

        berat_kg = round(berat_gram / 1000.0, 4)
        W = berat_gram  # W sekarang dalam GRAM (sama dengan core.py)

        # 3. Eksekusi Pengecekan Aturan Hukum (core.py)
        rule_result = cek_aturan(jenis, P, L, T, W)

        # 4. Fitur Ekstraksi & Penanganan Error Infinity/NaN
        raw_feats = np.array([[P, L, T, W]])
        log_feats = feat(raw_feats)
        
        # Konversi NaN / -Inf jika ada nilai tak terhingga dari logaritma
        log_feats = np.nan_to_num(log_feats, nan=0.0, posinf=1e6, neginf=-1e6)
        scaled_feats = scaler.transform(log_feats)

        # 5. Prediksi Model ML & Thresholding
        if model_type == "kmeans":
            score = float(skor("kmeans", models["kmeans"], scaled_feats)[0])
            nama_model = "K-Means Clustering (Distance Score)"
            thr = thresholds.get("kmeans", 1.56)
            is_anomali = score > thr
        elif model_type == "isolation_forest":
            score = float(skor("iforest", models["iforest"], scaled_feats)[0])
            nama_model = "Isolation Forest (Anomaly Score)"
            thr = thresholds.get("iforest", 0.56)
            is_anomali = score > thr
        else:
            return (
                jsonify(
                    {
                        "error": "Nama model tidak valid",
                        "model_tersedia": ["kmeans", "isolation_forest"],
                    }
                ),
                400,
            )

        status_rule = rule_result.get("status", "OK") if isinstance(rule_result, dict) else rule_result
        # Status anomali gabungan (ML + Rules):
        # Terindikasi anomali jika melanggar batas aturan (TOLAK/INSPEKSI) ATAU model ML mendeteksi anomali
        if status_rule in ["TOLAK", "INSPEKSI"] or is_anomali:
            status_anomali = "Terindikasi Anomali"
        else:
            status_anomali = "Normal"

        waktu_sekarang = datetime.now().isoformat(timespec="seconds")

        golongan_val = "-"
        if isinstance(rule_result, dict):
            golongan_val = rule_result.get("golongan", "-")
        elif isinstance(rule_result, str):
            golongan_val = rule_result

        # 6. Update State Global Kendaraan untuk Web Monitoring
        state_kendaraan.update(
            {
                "jenis": jenis,
                "P": P,
                "L": L,
                "T": T,
                "W": W,
                "berat_kg": berat_kg,
                "berat_gram": berat_gram,
                "golongan": golongan_val,
                "status_anomali": status_anomali,
                "skor_anomali": score,
                "waktu": waktu_sekarang,
            }
        )

        response = {
            "input": {
                "jenis": jenis,
                "P": P,
                "L": L,
                "T": T,
                "W_gram": W,
                "berat_kg": berat_kg,
                "berat_gram": berat_gram,
            },
            "model": model_type,
            "nama_model": nama_model,
            "hasil": {
                "evaluasi_aturan": rule_result,
                "skor_anomali": score,
                "ambang_anomali": thr,
                "anomali_ml": is_anomali,
                "status_anomali": status_anomali,
            },
        }

        # 7. Simpan Riwayat Pemeriksaan ke Database MySQL
        alasan_str = ", ".join(rule_result.get("alasan", [])) if isinstance(rule_result, dict) else ""
        simpan_pemeriksaan({
            "jenis": jenis,
            "P": P,
            "L": L,
            "T": T,
            "W_gram": W,
            "golongan": golongan_val,
            "model": model_type,
            "skor_anomali": score,
            "status_anomali": status_anomali,
            "alasan_aturan": alasan_str
        })

        return jsonify(response), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/status-kendaraan", methods=["GET"])
def get_status_kendaraan():
    return jsonify(state_kendaraan)


# ==================================================================
# ENDPOINT IOT (ESP32) & MANAJEMEN TIKET
# ==================================================================
@app.route("/api/berat", methods=["POST"])
def terima_berat():
    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}

    if not data and request.form:
        data = request.form.to_dict()

    val = data.get("berat", data.get("berat_gram", data.get("weight", data.get("nilai", 0.0))))
    try:
        berat_mentah = float(str(val).replace(',', '.'))
    except (ValueError, TypeError):
        berat_mentah = 0.0

    servo_val = data.get("servo", 0)
    try:
        servo_val = int(servo_val)
    except (ValueError, TypeError):
        servo_val = 0

    print(f"[IOT] Data ESP32: {data} -> Berat: {berat_mentah} g, Servo: {servo_val}", flush=True)

    # Simpan ke state_iot
    state_iot["berat"] = berat_mentah
    state_iot["servo"] = servo_val
    state_iot["waktu"] = datetime.now().isoformat(timespec="seconds")

    # Selalu update state_kendaraan dengan data dari ESP32/load cell (termasuk 0)
    state_kendaraan["berat"] = berat_mentah
    state_kendaraan["berat_gram"] = berat_mentah
    state_kendaraan["berat_kg"] = round(berat_mentah / 1000.0, 4)
    state_kendaraan["W"] = max(berat_mentah / 1000000.0, 0.0001)

    perintah = antrean_perintah.pop(0) if antrean_perintah else "none"
    return perintah, 200, {"Content-Type": "text/plain"}


@app.route("/api/berat", methods=["GET"])
def ambil_berat():
    berat_gram = state_iot["berat"]
    return jsonify({
        "berat": berat_gram,
        "berat_gram": berat_gram,
        "berat_kg": round(berat_gram / 1000.0, 4),
        "servo": state_iot["servo"],
        "waktu": state_iot["waktu"]
    })


@app.route("/api/tiket", methods=["POST"])
def cetak_tiket():
    data = request.get_json(silent=True) or {}
    nomor_tiket = str(data.get("nomor", f"TKT-{len(daftar_tiket) + 1}"))
    berat = float(data.get("berat", state_kendaraan.get("W", state_iot.get("berat", 0.0))))
    pengemudi = str(data.get("pengemudi", data.get("driver", "Pengemudi")))
    golongan = str(data.get("golongan", data.get("category", state_kendaraan.get("golongan", "A"))))
    status_kendaraan = str(data.get("status", state_kendaraan.get("status_anomali", "Normal")))

    # Simpan tiket ke Database MySQL
    simpan_tiket(nomor_tiket, pengemudi, golongan, berat, status_kendaraan)

    tiket = {
        "nomor": nomor_tiket,
        "pengemudi": pengemudi,
        "golongan": golongan,
        "berat": berat,
        "status": status_kendaraan,
        "waktu": datetime.now().isoformat(timespec="seconds"),
        "berat_gram": berat,
        "berat_kg": round(berat / 1000.0, 4),
    }
    daftar_tiket.append(tiket)
    if "buka" not in antrean_perintah:
        antrean_perintah.append("buka")
    return jsonify(status="ok", tiket=tiket)


@app.route("/api/tiket", methods=["GET"])
def lihat_tiket():
    tiket_db = ambil_semua_tiket()
    if tiket_db:
        return jsonify(tiket_db)
    return jsonify(daftar_tiket)


@app.route("/api/buka", methods=["POST"])
def buka():
    if "buka" not in antrean_perintah:
        antrean_perintah.append("buka")
    return jsonify(status="antri")


@app.route("/api/servo", methods=["POST"])
def set_servo():
    posisi = request.get_json(force=True).get("posisi")
    if posisi not in (0, 90):
        return jsonify(error="posisi harus 0 atau 90"), 400
    antrean_perintah.append(f"servo{posisi}")
    return jsonify(status="antri")


@app.route("/api/tare", methods=["POST"])
def tare():
    antrean_perintah.append("tare")
    return jsonify(status="antri")


if __name__ == "__main__":
    app.run(host=os.environ.get("WEB_HOST", "0.0.0.0"),
            port=int(os.environ.get("WEB_PORT", "5000")), debug=False)
