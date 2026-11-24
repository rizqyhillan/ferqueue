import base64
import os
import re
from datetime import datetime
from functools import wraps
from pathlib import Path
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*_args, **_kwargs):
        return False

import rag_service
from db import (
    ambil_detail_pemeriksaan,
    ambil_kendaraan_bermasalah,
    ambil_semua_riwayat,
    simpan_pemeriksaan,
)

BASE_DIR = Path(__file__).resolve().parent
CAPTURES_DIR = BASE_DIR / "static" / "captures"
MAX_CAPTURE_BYTES = 5 * 1024 * 1024
_DATA_URL_RE = re.compile(r"^data:image/(jpeg|jpg|png|webp);base64,([A-Za-z0-9+/=\s]+)$", re.IGNORECASE)
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_-]")
env_path = BASE_DIR / ".env" if (BASE_DIR / ".env").exists() else BASE_DIR.parents[1] / ".env"
load_dotenv(dotenv_path=env_path)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("SECRET_KEY", "ferqueue-dev-2026")
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# Register CV Bridge blueprint (untuk Computer Vision API) jika tersedia
try:
    from cv_bridge import cv_api
    app.register_blueprint(cv_api)
except Exception as e:
    app.logger.warning(f"cv_api blueprint tidak dapat dimuat: {e}")


# ------------------------------------------------------------------
# AUTH & CACHE HELPERS
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


# ==========================================================
# 1. KONFIGURASI RULE-BASED BERAT (SATUAN INTERNAL: GRAM)
# ==========================================================
BATAS_BERAT_GRAM = {
    "A": 55.0,   # Mobil
    "B": 85.0,   # Bus
    "C": 100.0,  # Truk
}

TARIF_GOLONGAN = {
    "A": 60000,
    "B": 120000,
    "C": 250000,
}

MAP_GOLONGAN = {
    "mobil": "A",
    "car": "A",
    "bus": "B",
    "truk": "C",
    "truck": "C",
}

state_iot = {
    "berat": 0.0,
    "jarak": -1.0,
    "servo": 0,
    "gerbang": "tutup",
    "waktu": None,
}

state_kendaraan = {
    "jenis": "mobil",
    "golongan": "A",
    "P": 0.0,
    "T": 0.0,
    "W": 0.0,
    "berat_gram": 0.0,
    "berat_kg": 0.0,
    "status": "Menunggu",
}

antrean_perintah = []
riwayat_pemeriksaan = []


def normalize_golongan(raw_gol: str | None, jenis: str | None = None) -> str:
    if raw_gol:
        cleaned = str(raw_gol).upper().replace("GOL.", "").replace("GOL", "").strip()
        if cleaned in BATAS_BERAT_GRAM:
            return cleaned
    if jenis:
        mapped = MAP_GOLONGAN.get(str(jenis).lower().strip())
        if mapped:
            return mapped
    return state_kendaraan.get("golongan", "A")


def validasi_berat(golongan: str, berat_gram: float) -> dict:
    gol = golongan.upper().strip()
    batas = BATAS_BERAT_GRAM.get(gol)
    if batas is None:
        raise ValueError(f"Golongan '{golongan}' tidak valid. Gunakan A, B, atau C.")

    if berat_gram > batas:
        kelebihan = round(berat_gram - batas, 2)
        persentase = round((kelebihan / batas) * 100, 1)
        kategori = (
            "Overweight Ringan (<= 15%)"
            if persentase <= 15.0
            else "Overweight Berat (> 15%)"
        )
        return {
            "status": "Overweight",
            "kategori_overweight": kategori,
            "batas_berat_gram": batas,
            "kelebihan_berat_gram": kelebihan,
            "persentase_kelebihan": f"{persentase}%",
            "minimal_pengurangan_gram": kelebihan,
            "tiket_terbit": False,
            "status_tiket": "Tidak Diterbitkan (Ditolak - Pasal 5 PM 103/2017)",
            "status_gerbang": "Dibuka - Jalur Khusus Keluar (Pasal 6 PM 103/2017)",
            "tindakan": "Pemeriksaan fisik oleh petugas & putar balik meninggalkan pelabuhan",
            "tarif": TARIF_GOLONGAN.get(gol, 60000),
        }

    return {
        "status": "Normal",
        "kategori_overweight": "-",
        "batas_berat_gram": batas,
        "kelebihan_berat_gram": 0.0,
        "persentase_kelebihan": "0%",
        "minimal_pengurangan_gram": 0.0,
        "tiket_terbit": True,
        "status_tiket": "Diterbitkan",
        "status_gerbang": "Dibuka - Jalur Masuk",
        "tindakan": "Melanjutkan proses masuk pelabuhan",
        "tarif": TARIF_GOLONGAN.get(gol, 60000),
    }


def generate_id_pemeriksaan() -> str:
    now = datetime.now()
    return f"CHK-{now.strftime('%Y%m%d%H%M%S')}-{int(now.microsecond / 1000):03d}"


def generate_nomor_tiket() -> str:
    now = datetime.now()
    return f"TKT-{now.strftime('%Y%m%d%H%M%S')}-{int(now.microsecond / 1000):03d}"


def queue_command(cmd: str) -> None:
    if cmd not in antrean_perintah:
        antrean_perintah.append(cmd)


def save_capture_photo(id_pemeriksaan: str, photo_data_url: str | None) -> str | None:
    """Decode base64 data URL dari kamera/upload dan simpan ke static/captures/."""
    if not photo_data_url or not isinstance(photo_data_url, str):
        return None
    match = _DATA_URL_RE.match(photo_data_url.strip())
    if not match:
        return None
    mime_ext, b64_payload = match.group(1).lower(), match.group(2)
    ext = "jpg" if mime_ext in ("jpeg", "jpg") else mime_ext
    try:
        raw_bytes = base64.b64decode(b64_payload, validate=True)
    except Exception:
        return None
    if not 0 < len(raw_bytes) <= MAX_CAPTURE_BYTES:
        return None

    safe_id = _SAFE_ID_RE.sub("", id_pemeriksaan) or generate_id_pemeriksaan()
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{safe_id}.{ext}"
    (CAPTURES_DIR / filename).write_bytes(raw_bytes)
    return f"/static/captures/{filename}"


def resolve_capture_url(record: dict) -> dict:
    """Pastikan field foto_url terisi jika file tangkapan kamera ada di disk."""
    item = dict(record)
    if item.get("foto_url"):
        return item
    rec_id = _SAFE_ID_RE.sub("", str(item.get("id_pemeriksaan") or ""))
    if rec_id and CAPTURES_DIR.exists():
        for ext in ("jpg", "png", "webp"):
            if (CAPTURES_DIR / f"{rec_id}.{ext}").exists():
                item["foto_url"] = f"/static/captures/{rec_id}.{ext}"
                break
    return item


# ==========================================================
# 2. ROUTES HALAMAN WEB & AUTH
# ==========================================================
@app.route("/", methods=["GET"])
def root():
    if "user" in session:
        return redirect(url_for("page_dashboard"))
    return redirect(url_for("login_page"))


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if "user" in session:
        return redirect(url_for("page_dashboard"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if username and password:
            session["user"] = username
            session.permanent = "remember" in request.form
            return redirect(url_for("page_dashboard"))
        error = "Username atau password tidak valid."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/dashboard")
@login_required
def page_dashboard():
    return render_template("dashboard.html", active_page="dashboard", user=session["user"])


@app.route("/monitoring")
@login_required
def page_monitoring():
    return render_template("monitoring.html", active_page="monitoring", user=session["user"])


@app.route("/riwayat")
@login_required
def page_riwayat():
    return render_template("riwayat.html", active_page="riwayat", user=session["user"])


@app.route("/ai-assistant")
@login_required
def page_ai_assistant():
    return render_template("ai_assistant.html", active_page="ai-assistant", user=session["user"])


@app.route("/src/<path:filename>")
@app.route("/<path:filename>")
def serve_static_files(filename):
    static_dir = os.path.join(app.root_path, "static")
    if os.path.exists(os.path.join(static_dir, filename)):
        return send_from_directory(static_dir, filename)
    return jsonify({"error": f"File {filename} tidak ditemukan"}), 404


# ==========================================================
# 3. API SENSOR (ESP32 LOAD CELL) & COMPUTER VISION
# ==========================================================
@app.route("/api/state", methods=["GET"])
@app.route("/api/status-kendaraan", methods=["GET"])
def api_get_state():
    gol = state_kendaraan["golongan"]
    hasil = validasi_berat(gol, state_kendaraan["W"])
    return jsonify({
        **state_kendaraan,
        **hasil,
        "jarak": state_iot["jarak"],
        "servo": state_iot["servo"],
        "gerbang": state_iot["gerbang"],
        "waktu_sensor": state_iot["waktu"],
    })


@app.route("/api/sensor/update", methods=["POST"])
def api_sensor_update():
    data = request.get_json(silent=True) or request.form.to_dict()

    if "jenis" in data and data["jenis"]:
        jenis = str(data["jenis"]).lower().strip()
        state_kendaraan["jenis"] = jenis
        if jenis in MAP_GOLONGAN:
            state_kendaraan["golongan"] = MAP_GOLONGAN[jenis]

    if "golongan" in data and data["golongan"]:
        gol = normalize_golongan(data["golongan"], state_kendaraan.get("jenis"))
        if gol in BATAS_BERAT_GRAM:
            state_kendaraan["golongan"] = gol

    if "P" in data and data["P"] is not None:
        state_kendaraan["P"] = float(data["P"])

    if "T" in data and data["T"] is not None:
        state_kendaraan["T"] = float(data["T"])

    if "W" in data and data["W"] is not None:
        w = float(data["W"])
        state_kendaraan["W"] = w
        state_kendaraan["berat_gram"] = w
        state_kendaraan["berat_kg"] = round(w / 1000.0, 4)

    hasil = validasi_berat(state_kendaraan["golongan"], state_kendaraan["W"])
    state_kendaraan["status"] = hasil["status"]

    return jsonify({
        "status": "ok",
        "state": state_kendaraan,
        "validasi": hasil,
    })


@app.route("/api/gate/command", methods=["GET"])
def api_gate_command():
    perintah = antrean_perintah.pop(0) if antrean_perintah else "tunggu"
    return jsonify({"command": perintah})


@app.route("/api/buka", methods=["POST"])
def api_buka():
    queue_command("buka")
    return jsonify({"status": "ok", "command": "buka"})


@app.route("/api/servo", methods=["POST"])
def api_servo():
    data = request.get_json(silent=True) or {}
    posisi = data.get("posisi")
    if posisi not in (0, 90):
        return jsonify({"error": "posisi harus 0 atau 90"}), 400
    cmd = f"servo{posisi}"
    queue_command(cmd)
    return jsonify({"status": "ok", "command": cmd})


@app.route("/api/tare", methods=["POST"])
def api_tare():
    queue_command("tare")
    state_iot["berat"] = 0.0
    state_kendaraan["W"] = 0.0
    state_kendaraan["berat_gram"] = 0.0
    state_kendaraan["berat_kg"] = 0.0
    return jsonify({"status": "ok", "command": "tare"})


@app.route("/api/berat", methods=["GET", "POST"])
def api_berat():
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form.to_dict()
        raw_val = data.get("berat", data.get("berat_gram", data.get("weight", data.get("nilai"))))
        if raw_val is not None:
            try:
                berat_gram = float(str(raw_val).replace(",", "."))
                state_iot["berat"] = berat_gram
                state_kendaraan["W"] = berat_gram
                state_kendaraan["berat_gram"] = berat_gram
                state_kendaraan["berat_kg"] = round(berat_gram / 1000.0, 4)
                hasil = validasi_berat(state_kendaraan["golongan"], berat_gram)
                state_kendaraan["status"] = hasil["status"]
            except (ValueError, TypeError):
                pass

        if "jarak" in data:
            try:
                state_iot["jarak"] = float(data["jarak"])
            except (ValueError, TypeError):
                pass

        if "servo" in data:
            try:
                state_iot["servo"] = int(data["servo"])
            except (ValueError, TypeError):
                pass

        if "gerbang" in data and data["gerbang"]:
            state_iot["gerbang"] = str(data["gerbang"])

        state_iot["waktu"] = datetime.now().isoformat(timespec="seconds")

        perintah = antrean_perintah.pop(0) if antrean_perintah else "none"
        return perintah, 200, {"Content-Type": "text/plain"}

    berat_gram = state_iot["berat"]
    return jsonify({
        "berat": berat_gram,
        "berat_gram": berat_gram,
        "berat_kg": round(berat_gram / 1000.0, 4),
        "jarak": state_iot["jarak"],
        "servo": state_iot["servo"],
        "gerbang": state_iot["gerbang"],
        "waktu": state_iot["waktu"],
    })


# ==========================================================
# 4. API DASHBOARD STATS, PROSES PEMERIKSAAN, TIKET & RIWAYAT
# ==========================================================
@app.route("/api/stats", methods=["GET"])
def api_stats():
    data_db = ambil_semua_riwayat()
    records = data_db if data_db else riwayat_pemeriksaan
    total = max(len(records), 1428)
    return jsonify({
        "total_kendaraan": total,
        "total_truk": max(int(total * 0.45), 642),
        "total_bus": max(int(total * 0.22), 318),
        "total_mobil": max(int(total * 0.33), 468),
        "density_truk": [2, 1, 0, 1, 3, 8, 22, 38, 45, 41, 39, 36, 30, 28, 32, 35, 38, 42, 37, 30, 21, 14, 8, 4],
        "density_bus": [1, 0, 0, 0, 2, 4, 10, 18, 22, 19, 18, 16, 14, 12, 15, 16, 18, 20, 17, 14, 10, 6, 3, 1],
        "density_lainnya": [1, 0, 1, 0, 1, 3, 8, 15, 19, 17, 16, 15, 12, 10, 13, 14, 16, 18, 15, 12, 8, 5, 2, 1],
    })


@app.route("/api/aktivitas", methods=["GET"])
def api_aktivitas():
    data_db = ambil_semua_riwayat(limit=10)
    if data_db:
        return jsonify(data_db)
    if riwayat_pemeriksaan:
        return jsonify(riwayat_pemeriksaan[:10])
    return jsonify([
        {"nomor": "GAT-T2862", "jenis": "Truk", "P": 11.9, "T": 3.8, "berat": 95.0, "status": "Normal"},
        {"nomor": "GAT-T2881", "jenis": "Bus", "P": 11.2, "T": 3.4, "berat": 80.0, "status": "Normal"},
        {"nomor": "GAT-T2898", "jenis": "Mobil", "P": 3.8, "T": 1.5, "berat": 48.0, "status": "Normal"},
    ])


@app.route("/api/proses-kendaraan", methods=["POST"])
def api_proses_kendaraan():
    data = request.get_json(silent=True) or {}

    jenis = str(data.get("jenis_kendaraan") or state_kendaraan["jenis"]).lower().strip()
    golongan = normalize_golongan(data.get("golongan"), jenis)
    berat_gram = float(data["berat_gram"]) if data.get("berat_gram") is not None else float(state_kendaraan["W"])
    panjang_cm = float(data["panjang_cm"]) if data.get("panjang_cm") is not None else float(state_kendaraan["P"])
    tinggi_cm = float(data["tinggi_cm"]) if data.get("tinggi_cm") is not None else float(state_kendaraan["T"])
    pengemudi = str(data.get("nama_pengemudi") or data.get("pengemudi") or "Pengemudi").strip()

    try:
        hasil = validasi_berat(golongan, berat_gram)
    except ValueError as err:
        return jsonify({"status": "error", "message": str(err)}), 400

    state_kendaraan.update({
        "jenis": jenis,
        "golongan": golongan,
        "P": panjang_cm,
        "T": tinggi_cm,
        "W": berat_gram,
        "berat_gram": berat_gram,
        "berat_kg": round(berat_gram / 1000.0, 4),
        "status": hasil["status"],
    })

    queue_command("buka")

    id_pemeriksaan = generate_id_pemeriksaan()
    nomor_tiket = None if hasil["status"] == "Overweight" else generate_nomor_tiket()
    foto_url = save_capture_photo(id_pemeriksaan, data.get("foto") or data.get("foto_base64"))

    rekam_data = {
        "id_pemeriksaan": id_pemeriksaan,
        "waktu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "nomor_tiket": nomor_tiket,
        "nama_pengemudi": pengemudi,
        "jenis_kendaraan": jenis.capitalize(),
        "golongan": golongan,
        "panjang_cm": panjang_cm,
        "tinggi_cm": tinggi_cm,
        "berat_aktual_gram": berat_gram,
        "batas_maksimum_gram": hasil["batas_berat_gram"],
        "kelebihan_berat_gram": hasil["kelebihan_berat_gram"],
        "persentase_kelebihan": hasil["persentase_kelebihan"],
        "kategori_overweight": hasil["kategori_overweight"],
        "minimal_pengurangan_gram": hasil["minimal_pengurangan_gram"],
        "status": hasil["status"],
        "status_tiket": hasil["status_tiket"],
        "status_gerbang": hasil["status_gerbang"],
        "tindakan": hasil["tindakan"],
        "foto_url": foto_url,
    }
    riwayat_pemeriksaan.insert(0, rekam_data)
    simpan_pemeriksaan(rekam_data)

    if hasil["status"] == "Overweight":
        return jsonify({
            **rekam_data,
            "gate": "buka",
            "pesan": (
                f"OVERWEIGHT (+{hasil['kelebihan_berat_gram']} gram / {hasil['persentase_kelebihan']}). "
                "Tiket tidak diterbitkan (Pasal 5 PM 103/2017). Gerbang dibuka untuk jalur khusus keluar (Pasal 6), "
                "petugas memeriksa kendaraan dan mengarahkan putar balik meninggalkan pelabuhan."
            ),
        })

    return jsonify({
        **rekam_data,
        "gate": "buka",
        "pesan": "Kendaraan normal. Tiket masuk diterbitkan dan gerbang dibuka.",
    })


@app.route("/api/tiket", methods=["GET", "POST"])
def api_tiket():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        driver = str(data.get("pengemudi") or data.get("nama_pengemudi") or "Pengemudi").strip()
        jenis = str(data.get("jenis_kendaraan") or state_kendaraan.get("jenis") or "mobil").lower().strip()
        gol = normalize_golongan(data.get("golongan"), jenis)
        if gol not in BATAS_BERAT_GRAM:
            gol = "A"

        raw_berat = data.get("berat_gram", data.get("berat"))
        berat = float(raw_berat) if raw_berat is not None else float(state_kendaraan["W"])
        panjang_cm = float(data["panjang_cm"]) if data.get("panjang_cm") is not None else float(state_kendaraan.get("P", 0.0))
        tinggi_cm = float(data["tinggi_cm"]) if data.get("tinggi_cm") is not None else float(state_kendaraan.get("T", 0.0))

        hasil = validasi_berat(gol, berat)

        id_pemeriksaan = generate_id_pemeriksaan()
        nomor_tiket = (
            None
            if hasil["status"] == "Overweight"
            else f"FQ-{datetime.now().strftime('%y%m%d')}-{str(len(riwayat_pemeriksaan) + 1).zfill(3)}"
        )
        foto_url = save_capture_photo(id_pemeriksaan, data.get("foto") or data.get("foto_base64"))

        rekam_data = {
            "id_pemeriksaan": id_pemeriksaan,
            "waktu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "nomor_tiket": nomor_tiket,
            "nama_pengemudi": driver,
            "jenis_kendaraan": "Mobil" if gol == "A" else ("Bus" if gol == "B" else "Truk"),
            "golongan": gol,
            "panjang_cm": panjang_cm,
            "tinggi_cm": tinggi_cm,
            "berat_aktual_gram": berat,
            "batas_maksimum_gram": hasil["batas_berat_gram"],
            "kelebihan_berat_gram": hasil["kelebihan_berat_gram"],
            "persentase_kelebihan": hasil["persentase_kelebihan"],
            "kategori_overweight": hasil["kategori_overweight"],
            "minimal_pengurangan_gram": hasil["minimal_pengurangan_gram"],
            "status": hasil["status"],
            "status_tiket": hasil["status_tiket"],
            "status_gerbang": hasil["status_gerbang"],
            "tindakan": hasil["tindakan"],
            "foto_url": foto_url,
        }
        riwayat_pemeriksaan.insert(0, rekam_data)
        simpan_pemeriksaan(rekam_data)

        # Buka gerbang (Normal -> jalur masuk, Overweight -> jalur khusus keluar sesuai PM 103/2017)
        queue_command("buka")

        ticket_obj = {
            "nomor": nomor_tiket or f"OVW-{id_pemeriksaan[-6:]}",
            "pengemudi": driver,
            "golongan": f"GOL. {gol}",
            "berat": berat,
            "berat_gram": berat,
            "batas_berat_gram": hasil["batas_berat_gram"],
            "panjang_cm": panjang_cm,
            "tinggi_cm": tinggi_cm,
            "status": hasil["status"],
            "waktu": rekam_data["waktu"],
            "kelebihan": hasil["kelebihan_berat_gram"],
            "persentase_kelebihan": hasil["persentase_kelebihan"],
            "id_pemeriksaan": id_pemeriksaan,
            "tarif": hasil["tarif"],
            "foto_url": foto_url,
        }
        return jsonify({"status": "ok", "tiket": ticket_obj})

    data_db = ambil_semua_riwayat()
    records = data_db if data_db else riwayat_pemeriksaan
    return jsonify({"status": "success", "data": [resolve_capture_url(r) for r in records]})


@app.route("/api/riwayat", methods=["GET"])
def api_riwayat():
    data_db = ambil_semua_riwayat()
    records = data_db if data_db else riwayat_pemeriksaan
    return jsonify({"status": "success", "data": [resolve_capture_url(r) for r in records]})


@app.route("/api/kendaraan-bermasalah", methods=["GET"])
def api_kendaraan_bermasalah():
    """Daftar log pemeriksaan berstatus Overweight untuk dipilih petugas di halaman AI Assistant."""
    bermasalah = ambil_kendaraan_bermasalah()
    if not bermasalah:
        bermasalah = [item for item in riwayat_pemeriksaan if item["status"] == "Overweight"]
    return jsonify({
        "status": "success",
        "total": len(bermasalah),
        "data": bermasalah,
    })


# ==========================================================
# 5. API AI ASSISTANT (CHAT BEBAS & PILIH DATA BERMASALAH)
# ==========================================================
@app.route("/api/ai/query", methods=["POST"])
def api_ai_query():
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    id_pemeriksaan = (data.get("id_pemeriksaan") or data.get("ticket_id") or "").strip()
    custom_vehicle = data.get("vehicle_data")

    vehicle_data = None

    # 1. Jika petugas memilih salah satu catatan kendaraan/tiket bermasalah dari daftar
    if id_pemeriksaan:
        found = ambil_detail_pemeriksaan(id_pemeriksaan)
        if not found:
            found = next(
                (item for item in riwayat_pemeriksaan if item["id_pemeriksaan"] == id_pemeriksaan),
                None,
            )
        if not found:
            return jsonify({
                "status": "error",
                "message": f"Data pemeriksaan '{id_pemeriksaan}' tidak ditemukan."
            }), 404
        vehicle_data = found
        if not query:
            query = "Analisis klasifikasi overweight kendaraan ini, saran pengurangan muatannya, dan langkah penanganannya."

    # 2. Jika dikirim payload vehicle_data langsung (misalnya dari simulasi Postman atau tombol analisis aktif)
    elif isinstance(custom_vehicle, dict) and custom_vehicle:
        jenis = str(custom_vehicle.get("jenis_kendaraan") or "mobil").lower().strip()
        golongan = normalize_golongan(custom_vehicle.get("golongan"), jenis)
        berat_gram = float(custom_vehicle.get("berat_aktual_gram", 0))
        panjang_cm = float(custom_vehicle.get("panjang_cm", 0))
        tinggi_cm = float(custom_vehicle.get("tinggi_cm", 0))

        try:
            hasil = validasi_berat(golongan, berat_gram)
        except ValueError as err:
            return jsonify({"status": "error", "message": str(err)}), 400

        vehicle_data = {
            "jenis_kendaraan": jenis.capitalize(),
            "golongan": golongan,
            "panjang_cm": panjang_cm,
            "tinggi_cm": tinggi_cm,
            "berat_aktual_gram": berat_gram,
            "batas_maksimum_gram": hasil["batas_berat_gram"],
            "kelebihan_berat_gram": hasil["kelebihan_berat_gram"],
            "persentase_kelebihan": hasil["persentase_kelebihan"],
            "kategori_overweight": hasil["kategori_overweight"],
            "minimal_pengurangan_gram": hasil["minimal_pengurangan_gram"],
            "status": hasil["status"],
            "status_tiket": hasil["status_tiket"],
            "status_gerbang": hasil["status_gerbang"],
        }
        if not query:
            query = "Bagaimana klasifikasi pelanggaran, saran pengurangan muatan, dan penanganan kendaraan ini?"

    # 3. Jika mode chat bebas (tanpa memilih tiket/kendaraan)
    if not query:
        return jsonify({
            "status": "error",
            "message": "Silakan tulis pertanyaan atau pilih data kendaraan bermasalah terlebih dahulu."
        }), 400

    try:
        rag_result = rag_service.generate_answer(question=query, vehicle_data=vehicle_data)
        mode_konsultasi = "analisis_kendaraan" if vehicle_data else "chat_umum"
        title = (
            f"Analisis Kendaraan {vehicle_data.get('id_pemeriksaan', '')}".strip()
            if vehicle_data
            else "Konsultasi Regulasi & SOP FERQUEUE"
        )
        return jsonify({
            "status": "success",
            "mode": mode_konsultasi,
            "title": title,
            "vehicle": vehicle_data,
            "summary": rag_result["answer"],
            "sources": rag_result["sources"],
        })
    except Exception as e:
        app.logger.exception("Error pada /api/ai/query")
        return jsonify({
            "status": "error",
            "message": f"Gagal memproses RAG/LLM: {str(e)}",
        }), 503


if __name__ == "__main__":
    app.run(
        host=os.getenv("WEB_HOST", "0.0.0.0"),
        port=int(os.getenv("WEB_PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )
