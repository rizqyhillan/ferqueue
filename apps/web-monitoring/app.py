from datetime import datetime
import os
from functools import wraps
from flask import Flask, jsonify, request, render_template, send_from_directory, session, redirect, url_for
from cv_bridge import cv_api

# Import modul database MySQL (db.py)
try:
    from db import simpan_pemeriksaan, simpan_tiket, ambil_semua_tiket
    print("[OK] Modul database db.py berhasil diimpor!")
except ImportError:
    simpan_pemeriksaan = lambda x: None
    simpan_tiket = lambda *args: None
    ambil_semua_tiket = lambda: []
    print("[WARN] db.py tidak ditemukan, integrasi DB dilewati.")

# Inisialisasi Flask
app = Flask(__name__, template_folder="templates", static_folder="static")
app.register_blueprint(cv_api)
app.secret_key = os.environ.get("SECRET_KEY", "ferqueue-dev-2026")
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


# ------------------------------------------------------------------
# AUTH HELPER
# ------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


@app.after_request
def add_cache_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# ------------------------------------------------------------------
# State Memory Backend (IoT & Monitoring Web)
# ------------------------------------------------------------------
# state_iot["berat"] menyimpan nilai mentah dalam SATUAN GRAM dari ESP32/Loadcell
state_iot = {"berat": 0.0, "servo": 0, "waktu": None}
antrean_perintah = []
daftar_tiket = []

state_kendaraan = {
    "jenis": "mobil",
    "P": 0.0,
    "L": 0.0,
    "T": 0.0,
    "W": 0.0,           # Satuan Gram (dari Load Cell)
    "berat_kg": 0.0,    # Satuan KG (Dashboard Web)
    "berat_gram": 0.0,  # Satuan Gram mentah
    "golongan": "-",
    "status": "Normal",
    "alasan": [],
    "waktu": None,
}


# ==================================================================
# ROUTE UTAMA & STATIC FILE HANDLING (FRONTEND)
# ==================================================================
@app.route("/", methods=["GET"])
def root():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login_page"))


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if "user" in session:
        return redirect(url_for("dashboard"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        # Demo: accept any non-empty username+password
        if username and password:
            session["user"] = username
            session.permanent = "remember" in request.form
            return redirect(url_for("dashboard"))
        error = "Username atau password tidak valid."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", active_page="dashboard", user=session["user"])


@app.route("/monitoring")
@login_required
def monitoring():
    return render_template("monitoring.html", active_page="monitoring", user=session["user"])


@app.route("/riwayat")
@login_required
def riwayat():
    return render_template("riwayat.html", active_page="riwayat", user=session["user"])


@app.route("/ai-assistant")
@login_required
def ai_assistant():
    return render_template("ai_assistant.html", active_page="ai-assistant", user=session["user"])


@app.route("/src/<path:filename>")
@app.route("/<path:filename>")
def serve_static_files(filename):
    static_dir = os.path.join(app.root_path, "static")
    if os.path.exists(os.path.join(static_dir, filename)):
        return send_from_directory(static_dir, filename)
    return jsonify({"error": f"File {filename} tidak ditemukan"}), 404


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

    state_iot["berat"] = berat_mentah
    state_iot["servo"] = servo_val
    state_iot["waktu"] = datetime.now().isoformat(timespec="seconds")

    state_kendaraan["berat"] = berat_mentah
    state_kendaraan["berat_gram"] = berat_mentah
    state_kendaraan["berat_kg"] = round(berat_mentah / 1000.0, 4)
    state_kendaraan["W"] = berat_mentah

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


@app.route("/api/status-kendaraan", methods=["GET"])
def get_status_kendaraan():
    return jsonify(state_kendaraan)


@app.route("/api/tiket", methods=["POST"])
def cetak_tiket():
    data = request.get_json(silent=True) or {}
    nomor_tiket = str(data.get("nomor", f"TKT-{len(daftar_tiket) + 1}"))
    berat = float(data.get("berat", state_kendaraan.get("W", state_iot.get("berat", 0.0))))
    pengemudi = str(data.get("pengemudi", data.get("driver", "Pengemudi")))
    golongan = str(data.get("golongan", data.get("category", state_kendaraan.get("golongan", "A"))))
    status_kendaraan_val = str(data.get("status", state_kendaraan.get("status", "Normal")))

    simpan_tiket(nomor_tiket, pengemudi, golongan, berat, status_kendaraan_val)

    tiket = {
        "nomor": nomor_tiket,
        "pengemudi": pengemudi,
        "golongan": golongan,
        "berat": berat,
        "status": status_kendaraan_val,
        "waktu": datetime.now().isoformat(timespec="seconds"),
        "berat_gram": berat,
        "berat_kg": round(berat / 1000.0, 4),
    }
    daftar_tiket.append(tiket)
    is_pelanggaran = "over" in status_kendaraan_val.lower() or "langgar" in status_kendaraan_val.lower()
    if not is_pelanggaran and "buka" not in antrean_perintah:
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


# ==================================================================
# API DASHBOARD STATS & AKTIVITAS
# ==================================================================
@app.route("/api/stats")
def api_stats():
    total = max(len(daftar_tiket), 1428)
    return jsonify({
        "total_kendaraan": total,
        "total_truk":  max(int(total * 0.45), 642),
        "total_bus":   max(int(total * 0.22), 318),
        "total_mobil": max(int(total * 0.33), 468),
        "density_truk":    [2,1,0,1,3,8,22,38,45,41,39,36,30,28,32,35,38,42,37,30,21,14,8,4],
        "density_bus":     [1,0,0,0,2,4,10,18,22,19,18,16,14,12,15,16,18,20,17,14,10,6,3,1],
        "density_lainnya": [1,0,1,0,1,3,8,15,19,17,16,15,12,10,13,14,16,18,15,12,8,5,2,1],
    })


@app.route("/api/aktivitas")
def api_aktivitas():
    tiket_db = ambil_semua_tiket()
    if tiket_db:
        return jsonify(list(reversed(tiket_db))[:10])
    if daftar_tiket:
        return jsonify(list(reversed(daftar_tiket))[:10])
    # Mock data
    mock = [
        {"nomor": "GAT-T2862", "jenis": "Truk",  "P": 11.9, "T": 3.8, "berat": 24180, "status": "Tiket Lunas"},
        {"nomor": "GAT-T2881", "jenis": "Bus",   "P": 11.2, "T": 3.4, "berat": 55120, "status": "Lunas"},
        {"nomor": "GAT-T2898", "jenis": "Mobil", "P":  3.8, "T": 1.5, "berat":  1930, "status": "Lunas"},
        {"nomor": "GAT-T2906", "jenis": "Bus",   "P": 10.8, "T": 3.2, "berat": 32080, "status": "Tiket Lunas"},
        {"nomor": "GAT-T2947", "jenis": "Mobil", "P":  4.2, "T": 1.6, "berat":  1300, "status": "Lunas"},
    ]
    return jsonify(mock)


# ==================================================================
# API FERQUEUE AI ASSISTANT & OPERATIONAL REASONING
# ==================================================================
@app.route("/api/ai/query", methods=["POST"])
def api_ai_query():
    data = request.get_json(silent=True) or {}
    query_text = (data.get("query") or "").strip().lower()
    ticket_id = (data.get("ticket_id") or "").strip()

    # Skenario 1: Kasus Overdimension FQ-2N261117-W001 (Truk Fuso Tinggi +40cm)
    if "w001" in query_text or "w001" in ticket_id.lower() or "overdimension" in query_text or "berita acara" in query_text:
        return jsonify({
            "status": "success",
            "type": "dispute_justification",
            "title": "Analisis Pelanggaran Tiket #FQ-2N261117-W001 (Ahmad Fauzi)",
            "summary": "Kendaraan Truk Fuso teridentifikasi melanggar batas tinggi fisik (Overheight) sebesar +40 cm dari ambang batas aman kanopi gate.",
            "metrics": {
                "jenis": "Truk Fuso Boks",
                "panjang_terukur": "12,4 m (Batas Gol. VI: 10,0 m - Kelebihan +2,4 m)",
                "tinggi_terukur": "4,20 m (Batas Clearance: 3,80 m - Kelebihan +40 cm)",
                "berat_terukur": "16.480 kg (MST: 16.000 kg)"
            },
            "legal_basis": "Peraturan Menteri Perhubungan No. PM 59 Tahun 2022 Pasal 14 ayat (3) jo. UU No. 22 Tahun 2009 Pasal 277.",
            "operational_risk": "Tinggi 4,20 m berisiko fatal membentur kanopi portal gerbang pelabuhan dan instalasi sprinkler keselamatan geladak kapal ferry penyeberangan.",
            "recommendation": [
                "1. Kunci portal gerbang tetap tertutup (SERVO_LOCK).",
                "2. Arahkan pengemudi keluar menuju Jalur Putar Balik Khusus (U-Turn Bay) Gate 03.",
                "3. Terbitkan Berita Acara Penolakan Manifest Tiket resmi untuk diserahkan ke pengemudi."
            ],
            "document_draft": """===============================================================
BERITA ACARA PENOLAKAN TIKET MANIFEST PELABUHAN
Nomor Registrasi: BA/ODOL/2026/XI/0042
Tanggal: 17 November 2026 | Pos Pemeriksaan: Gate Kendaraan #03
---------------------------------------------------------------
Nama Pengemudi   : Ahmad Fauzi
Jenis Kendaraan  : Truk Fuso Boks
No. Tiket Sistem : FQ-2N261117-W001

HASIL PENGUKURAN SENSOR GATE:
- Panjang Terukur : 12,40 meter (Batas Maksimum: 10,00 meter)
- Tinggi Terukur  : 4,20 meter  (Batas Clearance: 3,80 meter)
- Berat Aktual    : 16.480 kg   (Ambang Batas: 16.000 kg)

STATUS: DITOLAK MASUK (OVER DIMENSION OVER LOADING)
Dasar Hukum: PM 59/2022 & Standar Keselamatan Gerbang Penyeberangan.

Petugas Pemeriksa: Rian Setiawan | Pengemudi: Ahmad Fauzi
==============================================================="""
        })

    # Skenario 2: Diagnosa Diskrepansi Sensor vs Bounding Box Visual
    if "diskrepansi" in query_text or "sensor" in query_text or "miring" in query_text or "bayangan" in query_text or "w012" in ticket_id.lower():
        return jsonify({
            "status": "success",
            "type": "sensor_diagnostic",
            "title": "Diagnosa Integritas Sensor vs Bounding Box Visual",
            "summary": "Analisis mendeteksi kontradiksi antara dimensi visual 2D Bounding Box kamera dengan beban load cell.",
            "metrics": {
                "visual_class": "Mobil Pribadi (Golongan IV)",
                "bounding_box": "P: 7,0 cm · T: 2,4 cm (Skala 1:64)",
                "loadcell_weight": "210 gram (Normal Mobil Diecast: 35 - 45 gram)"
            },
            "diagnostic_finding": "Terjadi deviasi bobot +360% di atas profil fisik mobil pribadi. Terdapat indikasi kuat kendaraan antrean belakang ikut menginjak plat timbangan (tailgating / double axle overlap) atau terjadi pergeseran titik nol (zero-drift).",
            "recommendation": [
                "1. Periksa kamera pengawas antrean gate, pastikan mobil berikutnya berada di belakang marka kuning.",
                "2. Minta pengemudi belakang mundur 1 meter.",
                "3. Tekan tombol 'Tare (Nol-kan Sensor)' di dashboard monitoring sebelum validasi tiket."
            ],
            "document_draft": None
        })

    # Skenario 3: Resume Shift Operasional Harian
    if "shift" in query_text or "laporan" in query_text or "harian" in query_text or "rekap" in query_text:
        return jsonify({
            "status": "success",
            "type": "shift_summary",
            "title": "Resume Operasional Shift 1 (00:00 - 08:00 WIB)",
            "summary": "Rekapitulasi komprehensif throughput kendaraan, kepatuhan dimensi, dan insiden gerbang masuk.",
            "metrics": {
                "total_throughput": "1.428 kendaraan terverifikasi",
                "kepatuhan_normal": "1.419 unit (99,38%)",
                "pelanggaran_odol": "9 unit (0,62%)",
                "jam_puncak": "06:00 WIB (Throughput 188 unit/jam)"
            },
            "executive_note": "Aktivitas gate berjalan lancar. Seluruh 9 insiden overdimensi terpusat pada truk barang di Gate 03. Sebanyak 6 unit berhasil dialihkan ke dermaga khusus muatan terbuka, dan 3 unit ditolak putar balik resmi dengan berita acara.",
            "recommendation": [
                "Lakukan inspeksi pembersihan plat timbangan Gate 03 sebelum pergantian Shift 2.",
                "Persiapkan pembukaan Gate Cadangan #04 menjelang lonjakan siang pukul 14:00 WIB."
            ],
            "document_draft": None
        })

    # Default general regulation assistant
    return jsonify({
        "status": "success",
        "type": "general_assistant",
        "title": "Konsultasi Regulasi & Operasional Gate FERQUEUE",
        "summary": "FERQUEUE AI Reasoning Engine siap membantu verifikasi kepatuhan kendaraan, analisis dimensi, dan panduan regulasi PM 59/2022 skala 1:64.",
        "metrics": None,
        "recommendation": [
            "Gunakan tombol investigasi cepat di panel kiri untuk menganalisis tiket overdimension.",
            "Ketik 'Analisis Tiket #W001' untuk simulasi Berita Acara Pelanggaran.",
            "Ketik 'Diagnosa Sensor' untuk mengecek integritas bounding box vs load cell.",
            "Ketik 'Resume Shift 1' untuk melihat laporan operasional manajerial."
        ],
        "document_draft": None
    })


if __name__ == "__main__":
    app.run(host=os.environ.get("WEB_HOST", "0.0.0.0"),
            port=int(os.environ.get("WEB_PORT", "5000")), debug=False)
