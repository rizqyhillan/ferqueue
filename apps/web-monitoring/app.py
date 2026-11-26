import base64
import os
import re
import socket
from datetime import datetime
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse
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
    autentikasi_petugas,
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


def normalize_record(record: dict) -> dict:
    """Samakan struktur record dari MySQL maupun fallback in-memory."""
    item = resolve_capture_url(record)
    waktu = item.get("waktu_pemeriksaan") or item.get("waktu") or ""
    item["waktu"] = waktu
    item["waktu_pemeriksaan"] = waktu
    if "nama_petugas" not in item or not item.get("nama_petugas"):
        item["nama_petugas"] = "Operator"
    return item


def get_all_records(limit: int = 500) -> list[dict]:
    """Ambil data pemeriksaan terbaru dari MySQL atau fallback in-memory."""
    data_db = ambil_semua_riwayat(limit=limit)
    records = data_db if data_db else riwayat_pemeriksaan[:limit]
    return [normalize_record(r) for r in records]


def parse_record_time(record: dict) -> datetime | None:
    raw = record.get("waktu_pemeriksaan") or record.get("waktu")
    if isinstance(raw, datetime):
        return raw
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def generate_unique_ticket_no(existing_records: list[dict]) -> str:
    prefix = f"FQ-{datetime.now().strftime('%y%m%d')}-"
    existing = {
        str(r.get("nomor_tiket") or "")
        for r in existing_records
        if str(r.get("nomor_tiket") or "").startswith(prefix)
    }
    seq = len(existing) + 1
    while f"{prefix}{seq:03d}" in existing:
        seq += 1
    return f"{prefix}{seq:03d}"


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
            petugas = autentikasi_petugas(username, password)
            if petugas:
                session["user"] = petugas["nama_petugas"]
                session["username"] = petugas["username"]
                session.permanent = "remember" in request.form
                return redirect(url_for("page_dashboard"))
            error = "Username atau password salah."
        else:
            error = "Harap masukkan username dan password."
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
    records = get_all_records(limit=1000)
    total = len(records)
    total_truk = 0
    total_bus = 0
    total_mobil = 0
    total_normal = 0
    total_overweight = 0

    density_truk = [0] * 24
    density_bus = [0] * 24
    density_lainnya = [0] * 24

    sums = {
        "truk": {"p": 0.0, "t": 0.0, "w": 0.0, "n": 0, "n_dim": 0},
        "bus": {"p": 0.0, "t": 0.0, "w": 0.0, "n": 0, "n_dim": 0},
        "mobil": {"p": 0.0, "t": 0.0, "w": 0.0, "n": 0, "n_dim": 0},
    }

    for r in records:
        gol = str(r.get("golongan") or "").upper().strip()
        jenis = str(r.get("jenis_kendaraan") or r.get("jenis") or "").lower().strip()
        if gol == "C" or "truk" in jenis or "truck" in jenis:
            cat = "truk"
            total_truk += 1
        elif gol == "B" or "bus" in jenis:
            cat = "bus"
            total_bus += 1
        else:
            cat = "mobil"
            total_mobil += 1

        if "over" in str(r.get("status") or "").lower():
            total_overweight += 1
        else:
            total_normal += 1

        try:
            p_val = float(r.get("panjang_cm") or r.get("P") or 0.0)
        except (ValueError, TypeError):
            p_val = 0.0
        try:
            t_val = float(r.get("tinggi_cm") or r.get("T") or 0.0)
        except (ValueError, TypeError):
            t_val = 0.0
        raw_w = r.get("berat_aktual_gram")
        if raw_w is None:
            raw_w = r.get("berat_gram", r.get("berat", 0.0))
        try:
            w_val = float(raw_w or 0.0)
        except (ValueError, TypeError):
            w_val = 0.0

        sums[cat]["n"] += 1
        sums[cat]["w"] += w_val
        if p_val > 0 and t_val > 0:
            sums[cat]["p"] += p_val
            sums[cat]["t"] += t_val
            sums[cat]["n_dim"] += 1

        dt = parse_record_time(r)
        if dt is not None:
            hr = dt.hour
            if cat == "truk":
                density_truk[hr] += 1
            elif cat == "bus":
                density_bus[hr] += 1
            else:
                density_lainnya[hr] += 1

    density_hourly = [
        density_truk[h] + density_bus[h] + density_lainnya[h]
        for h in range(24)
    ]
    density_2h = [
        density_hourly[h] + density_hourly[h + 1]
        for h in range(0, 24, 2)
    ]

    now_hour = datetime.now().hour
    active_hours = max(1, now_hour + 1)
    avg_throughput = round(total / active_hours, 1) if total > 0 else 0.0
    current_hour_throughput = density_hourly[now_hour]

    def calc_avg(bucket: dict) -> dict:
        if bucket["n"] == 0:
            return {"count": 0, "panjang_cm": None, "tinggi_cm": None, "berat_gram": None}
        return {
            "count": bucket["n"],
            "panjang_cm": round(bucket["p"] / bucket["n_dim"], 2) if bucket["n_dim"] > 0 else None,
            "tinggi_cm": round(bucket["t"] / bucket["n_dim"], 2) if bucket["n_dim"] > 0 else None,
            "berat_gram": round(bucket["w"] / bucket["n"], 1),
        }

    return jsonify({
        "total_kendaraan": total,
        "total_truk": total_truk,
        "total_bus": total_bus,
        "total_mobil": total_mobil,
        "total_normal": total_normal,
        "total_overweight": total_overweight,
        "density_truk": density_truk,
        "density_bus": density_bus,
        "density_lainnya": density_lainnya,
        "density_hourly": density_hourly,
        "density_2h": density_2h,
        "avg_throughput": avg_throughput,
        "current_hour_throughput": current_hour_throughput,
        "rata_rata": {
            "truk": calc_avg(sums["truk"]),
            "bus": calc_avg(sums["bus"]),
            "mobil": calc_avg(sums["mobil"]),
        },
        "gerbang": state_iot["gerbang"],
        "sensor_live": state_iot["waktu"] is not None,
    })


@app.route("/api/aktivitas", methods=["GET"])
def api_aktivitas():
    return jsonify(get_all_records(limit=10))


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
        "nama_petugas": str(session.get("user") or "Operator"),
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
        existing_records = get_all_records(limit=1000)
        nomor_tiket = (
            None
            if hasil["status"] == "Overweight"
            else generate_unique_ticket_no(existing_records)
        )
        foto_url = save_capture_photo(id_pemeriksaan, data.get("foto") or data.get("foto_base64"))
        waktu_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        petugas = str(session.get("user") or "Operator")
        jenis_label = "Mobil" if gol == "A" else ("Bus" if gol == "B" else "Truk")

        state_kendaraan.update({
            "jenis": jenis_label.lower(),
            "golongan": gol,
            "P": panjang_cm,
            "T": tinggi_cm,
            "W": berat,
            "berat_gram": berat,
            "berat_kg": round(berat / 1000.0, 4),
            "status": hasil["status"],
        })

        rekam_data = {
            "id_pemeriksaan": id_pemeriksaan,
            "waktu": waktu_now,
            "waktu_pemeriksaan": waktu_now,
            "nomor_tiket": nomor_tiket,
            "nama_pengemudi": driver,
            "nama_petugas": petugas,
            "jenis_kendaraan": jenis_label,
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
            "petugas": petugas,
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

    return jsonify({"status": "success", "data": get_all_records(limit=500)})


@app.route("/api/riwayat", methods=["GET"])
def api_riwayat():
    return jsonify({"status": "success", "data": get_all_records(limit=500)})


def is_cv_api_reachable(timeout: float = 0.15) -> bool:
    base = app.config.get("CV_API_URL", os.environ.get("CV_API_URL", "http://127.0.0.1:8000"))
    parsed = urlparse(base)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@app.route("/api/system-status", methods=["GET"])
def api_system_status():
    """Ringkasan status sensor, gerbang, API PCV, dan notifikasi overweight untuk topbar."""
    bermasalah = ambil_kendaraan_bermasalah(limit=5)
    if not bermasalah:
        bermasalah = [
            normalize_record(item)
            for item in riwayat_pemeriksaan
            if str(item.get("status", "")).lower().startswith("over")
        ][:5]
    return jsonify({
        "sensor_live": state_iot["waktu"] is not None,
        "berat_gram": state_iot["berat"],
        "gerbang": state_iot["gerbang"],
        "cv_online": is_cv_api_reachable(),
        "overweight_count": len(bermasalah),
        "overweight_recent": bermasalah,
    })


@app.route("/api/kendaraan-bermasalah", methods=["GET"])
def api_kendaraan_bermasalah():
    """Daftar log pemeriksaan berstatus Overweight untuk dipilih petugas di halaman AI Assistant."""
    bermasalah = ambil_kendaraan_bermasalah()
    if not bermasalah:
        bermasalah = [item for item in riwayat_pemeriksaan if item["status"] == "Overweight"]
    normalized = [normalize_record(item) for item in bermasalah]
    return jsonify({
        "status": "success",
        "total": len(normalized),
        "data": normalized,
    })


# ==========================================================
# 5. API AI ASSISTANT (MULTI-TURN, AUDIT HARIAN, VISION & SOP)
# ==========================================================
def decode_image_data_url(photo_data_url: str | None) -> tuple[bytes | None, str | None]:
    if not photo_data_url or not isinstance(photo_data_url, str):
        return None, None
    match = _DATA_URL_RE.match(photo_data_url.strip())
    if not match:
        return None, None
    mime_ext, b64_payload = match.group(1).lower(), match.group(2)
    mime_type = "image/jpeg" if mime_ext in ("jpeg", "jpg") else f"image/{mime_ext}"
    try:
        raw_bytes = base64.b64decode(b64_payload, validate=True)
    except Exception:
        return None, None
    if not 0 < len(raw_bytes) <= MAX_CAPTURE_BYTES:
        return None, None
    return raw_bytes, mime_type


def load_capture_image_bytes(foto_url: str | None) -> tuple[bytes | None, str | None]:
    """Muat byte foto tangkapan kendaraan dari static/captures secara aman."""
    if not foto_url or not isinstance(foto_url, str):
        return None, None
    prefix = "/static/captures/"
    if not foto_url.startswith(prefix):
        return None, None
    filename = Path(foto_url[len(prefix):]).name
    if not filename:
        return None, None
    try:
        target = (CAPTURES_DIR / filename).resolve()
        if target.parent != CAPTURES_DIR.resolve() or not target.is_file():
            return None, None
        raw = target.read_bytes()
        if not 0 < len(raw) <= MAX_CAPTURE_BYTES:
            return None, None
        ext = target.suffix.lower()
        mime = "image/png" if ext == ".png" else ("image/webp" if ext == ".webp" else "image/jpeg")
        return raw, mime
    except OSError:
        return None, None


def sanitize_chat_history(raw_history) -> list[dict]:
    if not isinstance(raw_history, list):
        return []
    cleaned = []
    for item in raw_history[-rag_service.MAX_HISTORY_MESSAGES:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").lower().strip()
        if role not in ("user", "assistant"):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        cleaned.append({"role": role, "content": content[:1500]})
    return cleaned


def build_operational_audit_summary() -> dict:
    """Bangun ringkasan data operasional real-time (harian & total) untuk konteks audit LLM."""
    records = get_all_records(limit=1000)
    today_date = datetime.now().date()

    def summarize_bucket(bucket_records: list[dict]) -> dict:
        total = len(bucket_records)
        normal = overweight = mobil = bus = truk = 0
        total_berat = 0.0
        heaviest_over = None
        recent_over = []

        for r in bucket_records:
            gol = str(r.get("golongan") or "").upper().strip()
            jenis = str(r.get("jenis_kendaraan") or r.get("jenis") or "").lower().strip()
            if gol == "C" or "truk" in jenis or "truck" in jenis:
                truk += 1
            elif gol == "B" or "bus" in jenis:
                bus += 1
            else:
                mobil += 1

            berat = float(r.get("berat_aktual_gram") or r.get("berat_gram") or 0.0)
            batas = float(r.get("batas_maksimum_gram") or BATAS_BERAT_GRAM.get(gol, 55.0))
            total_berat += berat
            is_over = "over" in str(r.get("status") or "").lower()
            if is_over:
                overweight += 1
                kelebihan = float(r.get("kelebihan_berat_gram") or max(0.0, round(berat - batas, 2)))
                pct = r.get("persentase_kelebihan") or f"{round((kelebihan / max(1.0, batas)) * 100, 1)}%"
                over_brief = {
                    "id_pemeriksaan": r.get("id_pemeriksaan"),
                    "waktu": r.get("waktu"),
                    "nama_pengemudi": r.get("nama_pengemudi", "Pengemudi"),
                    "jenis_kendaraan": r.get("jenis_kendaraan", "Kendaraan"),
                    "golongan": gol or "A",
                    "berat_aktual_gram": berat,
                    "batas_maksimum_gram": batas,
                    "kelebihan_berat_gram": kelebihan,
                    "persentase_kelebihan": pct,
                }
                if len(recent_over) < 5:
                    recent_over.append(over_brief)
                if heaviest_over is None or kelebihan > heaviest_over["kelebihan_berat_gram"]:
                    heaviest_over = over_brief
            else:
                normal += 1

        return {
            "total": total,
            "normal": normal,
            "overweight": overweight,
            "tingkat_kepatuhan_persen": round((normal / total) * 100, 1) if total > 0 else 100.0,
            "mobil": mobil,
            "bus": bus,
            "truk": truk,
            "rata_rata_berat_gram": round(total_berat / total, 1) if total > 0 else 0.0,
            "pelanggaran_terberat": heaviest_over,
            "daftar_overweight_terbaru": recent_over,
        }

    today_records = []
    for r in records:
        dt = parse_record_time(r)
        if dt is not None and dt.date() == today_date:
            today_records.append(r)

    gol_live = state_kendaraan.get("golongan", "A")
    berat_live = float(state_kendaraan.get("W", 0.0))
    val_live = validasi_berat(gol_live, berat_live)

    return {
        "tanggal_hari_ini": today_date.strftime("%Y-%m-%d"),
        "waktu_server": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ringkasan_hari_ini": summarize_bucket(today_records),
        "ringkasan_keseluruhan": summarize_bucket(records),
        "sensor_timbangan_aktif": {
            "jenis_kendaraan": str(state_kendaraan.get("jenis", "mobil")).capitalize(),
            "golongan": gol_live,
            "berat_gram": berat_live,
            "batas_gram": val_live["batas_berat_gram"],
            "status": val_live["status"],
            "gerbang": state_iot.get("gerbang", "tutup"),
            "sensor_live": state_iot.get("waktu") is not None,
        },
    }


@app.route("/api/ai/query", methods=["POST"])
def api_ai_query():
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    id_pemeriksaan = (data.get("id_pemeriksaan") or data.get("ticket_id") or "").strip()
    custom_vehicle = data.get("vehicle_data")
    chat_history = sanitize_chat_history(data.get("history"))
    uploaded_image = data.get("image") or data.get("foto")
    include_photo = data.get("include_photo", True)

    vehicle_data = None
    image_bytes = None
    image_mime = None
    attached_image_url = None

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
        vehicle_data = normalize_record(found)
        if not query:
            query = (
                "Analisis klasifikasi overweight kendaraan ini, verifikasi kesesuaian visual fotonya "
                "(jika tersedia), saran pengurangan muatannya, dan langkah penanganannya."
            )

    # 2. Jika dikirim payload vehicle_data langsung
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
            "foto_url": custom_vehicle.get("foto_url"),
        }
        if not query:
            query = "Bagaimana klasifikasi pelanggaran, saran pengurangan muatan, dan penanganan kendaraan ini?"

    # 3. Muat lampiran foto (prioritas: foto diunggah di chat -> foto capture kendaraan)
    if uploaded_image:
        image_bytes, image_mime = decode_image_data_url(uploaded_image)
        if image_bytes is None:
            return jsonify({
                "status": "error",
                "message": "Format foto lampiran tidak valid. Gunakan gambar JPG, PNG, atau WebP (maks. 5 MB)."
            }), 400
        if not query:
            query = "Lakukan audit visual pada foto kendaraan ini: identifikasi jenis/golongan kendaraan dan catatan pemeriksaan gerbang."
    elif include_photo and vehicle_data and vehicle_data.get("foto_url"):
        image_bytes, image_mime = load_capture_image_bytes(vehicle_data.get("foto_url"))
        if image_bytes is not None:
            attached_image_url = vehicle_data.get("foto_url")

    # 4. Pastikan ada pertanyaan
    if not query:
        return jsonify({
            "status": "error",
            "message": "Silakan tulis pertanyaan, lampirkan foto, atau pilih data kendaraan bermasalah terlebih dahulu."
        }), 400

    try:
        operational_summary = build_operational_audit_summary()
        rag_result = rag_service.generate_answer(
            question=query,
            vehicle_data=vehicle_data,
            chat_history=chat_history,
            operational_summary=operational_summary,
            image_bytes=image_bytes,
            image_mime=image_mime,
        )
        used_vision = bool(rag_result.get("used_vision", False))
        used_fallback = bool(rag_result.get("used_fallback", False))
        retrieval_mode = rag_result.get("retrieval_mode", "hybrid")

        if vehicle_data:
            mode_konsultasi = "audit_visual_kendaraan" if used_vision else "analisis_kendaraan"
            title = f"Analisis Kendaraan {vehicle_data.get('id_pemeriksaan', '')}".strip()
        elif used_vision:
            mode_konsultasi = "audit_visual_bebas"
            title = "Audit Visual Kendaraan Multimodal"
        elif rag_service._is_daily_audit_query(query):
            mode_konsultasi = "audit_harian"
            title = f"Ringkasan Audit Harian ({operational_summary['tanggal_hari_ini']})"
        else:
            mode_konsultasi = "chat_umum"
            title = "Konsultasi Regulasi & SOP FERQUEUE"

        return jsonify({
            "status": "success",
            "mode": mode_konsultasi,
            "title": title,
            "vehicle": vehicle_data,
            "summary": rag_result["answer"],
            "sources": rag_result.get("sources", []),
            "used_vision": used_vision,
            "used_fallback": used_fallback,
            "retrieval_mode": retrieval_mode,
            "image_url": attached_image_url,
        })
    except Exception as e:
        app.logger.exception("Error pada /api/ai/query")
        return jsonify({
            "status": "error",
            "message": f"Gagal memproses RAG/LLM: {str(e)}",
        }), 503


# ==========================================================
# 6. API MANAJEMEN SOP & RE-INDEX RAG
# ==========================================================
@app.route("/api/ai/knowledge", methods=["GET", "POST"])
def api_ai_knowledge():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        filename = data.get("filename", "")
        content = data.get("content", "")
        try:
            saved = rag_service.save_knowledge_file(filename, content)
        except ValueError as err:
            return jsonify({"status": "error", "message": str(err)}), 400
        reindex_info = rag_service.reindex_knowledge()
        return jsonify({
            "status": "success",
            "file": saved,
            "reindex": reindex_info,
            "rag_status": rag_service.get_knowledge_status(),
        })

    return jsonify({
        "status": "success",
        "files": rag_service.list_knowledge_files(),
        "rag_status": rag_service.get_knowledge_status(),
    })


@app.route("/api/ai/knowledge/<path:filename>", methods=["GET", "DELETE"])
def api_ai_knowledge_item(filename):
    if request.method == "DELETE":
        try:
            deleted = rag_service.delete_knowledge_file(filename)
        except ValueError as err:
            return jsonify({"status": "error", "message": str(err)}), 400
        except FileNotFoundError as err:
            return jsonify({"status": "error", "message": str(err)}), 404
        reindex_info = rag_service.reindex_knowledge()
        return jsonify({
            "status": "success",
            "deleted": deleted,
            "reindex": reindex_info,
            "rag_status": rag_service.get_knowledge_status(),
        })

    try:
        doc = rag_service.read_knowledge_file(filename)
        return jsonify({"status": "success", "file": doc})
    except ValueError as err:
        return jsonify({"status": "error", "message": str(err)}), 400
    except FileNotFoundError as err:
        return jsonify({"status": "error", "message": str(err)}), 404


@app.route("/api/ai/knowledge/reindex", methods=["POST"])
def api_ai_knowledge_reindex():
    reindex_info = rag_service.reindex_knowledge()
    return jsonify({
        "status": "success",
        "reindex": reindex_info,
        "rag_status": rag_service.get_knowledge_status(),
    })


if __name__ == "__main__":
    app.run(
        host=os.getenv("WEB_HOST", "0.0.0.0"),
        port=int(os.getenv("WEB_PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )
