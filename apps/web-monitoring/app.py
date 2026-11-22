import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from rag_service import generate_answer
from db import (
    ambil_detail_pemeriksaan,
    ambil_kendaraan_bermasalah,
    ambil_semua_riwayat,
    simpan_pemeriksaan,
)

BASE_DIR = Path(__file__).resolve().parent
env_path = BASE_DIR / ".env" if (BASE_DIR / ".env").exists() else BASE_DIR.parents[1] / ".env"
load_dotenv(dotenv_path=env_path)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "ferqueue-secret-key")

# Register CV Bridge blueprint (untuk Computer Vision API) jika tersedia
try:
    from cv_bridge import cv_api
    app.register_blueprint(cv_api)
except Exception as e:
    app.logger.warning(f"cv_api blueprint tidak dapat dimuat: {e}")

# ==========================================================
# 1. KONFIGURASI RULE-BASED BERAT (SATUAN INTERNAL: GRAM)
# ==========================================================
BATAS_BERAT_GRAM = {
    "A": 55.0,   # Mobil
    "B": 85.0,   # Bus
    "C": 100.0,  # Truk
}

MAP_GOLONGAN = {
    "mobil": "A",
    "car": "A",
    "bus": "B",
    "truk": "C",
    "truck": "C",
}

state_kendaraan = {
    "jenis": "mobil",
    "golongan": "A",
    "P": 0.0,
    "T": 0.0,
    "W": 0.0,
    "status": "Menunggu",
}

antrean_perintah = []
riwayat_pemeriksaan = []


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
    }


def generate_id_pemeriksaan() -> str:
    now = datetime.now()
    return f"CHK-{now.strftime('%Y%m%d%H%M%S')}-{int(now.microsecond / 1000):03d}"


def generate_nomor_tiket() -> str:
    now = datetime.now()
    return f"TKT-{now.strftime('%Y%m%d%H%M%S')}-{int(now.microsecond / 1000):03d}"


# ==========================================================
# 2. ROUTES HALAMAN WEB
# ==========================================================
@app.route("/")
@app.route("/monitoring")
def page_monitoring():
    return render_template("monitoring.html", active_page="monitoring")


@app.route("/dashboard")
def page_dashboard():
    return render_template("dashboard.html", active_page="dashboard")


@app.route("/ai-assistant")
def page_ai_assistant():
    return render_template("ai_assistant.html", active_page="ai-assistant")


@app.route("/riwayat")
def page_riwayat():
    return render_template("riwayat.html", active_page="riwayat")


@app.route("/tickets")
def page_tickets():
    return render_template("tickets.html", active_page="tickets")


# ==========================================================
# 3. API SENSOR (ESP32 LOAD CELL) & COMPUTER VISION
# ==========================================================
@app.route("/api/state", methods=["GET"])
def api_get_state():
    gol = state_kendaraan["golongan"]
    hasil = validasi_berat(gol, state_kendaraan["W"])
    return jsonify({
        **state_kendaraan,
        **hasil,
    })


@app.route("/api/sensor/update", methods=["POST"])
def api_sensor_update():
    data = request.get_json(silent=True) or request.form.to_dict()

    if "jenis" in data and data["jenis"]:
        jenis = str(data["jenis"]).lower().strip()
        state_kendaraan["jenis"] = jenis
        state_kendaraan["golongan"] = MAP_GOLONGAN.get(jenis, "A")

    if "golongan" in data and data["golongan"]:
        gol = str(data["golongan"]).upper().strip()
        if gol in BATAS_BERAT_GRAM:
            state_kendaraan["golongan"] = gol

    if "P" in data and data["P"] is not None:
        state_kendaraan["P"] = float(data["P"])

    if "T" in data and data["T"] is not None:
        state_kendaraan["T"] = float(data["T"])

    if "W" in data and data["W"] is not None:
        state_kendaraan["W"] = float(data["W"])

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
    antrean_perintah.append("buka")
    return jsonify({"status": "ok", "command": "buka"})


@app.route("/api/tare", methods=["POST"])
def api_tare():
    antrean_perintah.append("tare")
    state_kendaraan["W"] = 0.0
    return jsonify({"status": "ok", "command": "tare"})


@app.route("/api/berat", methods=["GET", "POST"])
def api_berat():
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form.to_dict()
        if "berat" in data:
            try:
                state_kendaraan["W"] = float(data["berat"])
            except (ValueError, TypeError):
                pass
        perintah = antrean_perintah.pop(0) if antrean_perintah else "none"
        return perintah, 200, {"Content-Type": "text/plain"}
    return jsonify({"berat": state_kendaraan["W"]})


@app.route("/api/status-kendaraan", methods=["GET"])
def api_status_kendaraan():
    return api_get_state()


# ==========================================================
# 4. API PROSES PEMERIKSAAN, TIKET & DAFTAR BERMASALAH
# ==========================================================
@app.route("/api/proses-kendaraan", methods=["POST"])
def api_proses_kendaraan():
    data = request.get_json(silent=True) or {}

    jenis = str(data.get("jenis_kendaraan") or state_kendaraan["jenis"]).lower().strip()
    golongan = str(data.get("golongan") or MAP_GOLONGAN.get(jenis, state_kendaraan["golongan"])).upper().strip()
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
        "status": hasil["status"],
    })

    antrean_perintah.append("buka")

    id_pemeriksaan = generate_id_pemeriksaan()
    nomor_tiket = None if hasil["status"] == "Overweight" else generate_nomor_tiket()

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
        driver = data.get("pengemudi") or data.get("nama_pengemudi") or "Pengemudi"
        gol = str(data.get("golongan") or state_kendaraan["golongan"]).upper().replace("GOL. ", "").strip()
        if gol not in BATAS_BERAT_GRAM:
            gol = "A"
        berat = float(data.get("berat") if data.get("berat") is not None else state_kendaraan["W"])
        hasil = validasi_berat(gol, berat)

        id_pemeriksaan = generate_id_pemeriksaan()
        nomor_tiket = None if hasil["status"] == "Overweight" else f"FQ-{datetime.now().strftime('%y%m%d')}-{str(len(riwayat_pemeriksaan) + 1).zfill(3)}"

        rekam_data = {
            "id_pemeriksaan": id_pemeriksaan,
            "waktu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "nomor_tiket": nomor_tiket,
            "nama_pengemudi": driver,
            "jenis_kendaraan": "Mobil" if gol == "A" else ("Bus" if gol == "B" else "Truk"),
            "golongan": gol,
            "panjang_cm": float(state_kendaraan.get("P", 0.0)),
            "tinggi_cm": float(state_kendaraan.get("T", 0.0)),
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
        }
        riwayat_pemeriksaan.insert(0, rekam_data)
        simpan_pemeriksaan(rekam_data)

        ticket_obj = {
            "nomor": nomor_tiket or f"OVW-{id_pemeriksaan[-6:]}",
            "pengemudi": driver,
            "golongan": gol,
            "berat": berat,
            "status": hasil["status"],
            "waktu": rekam_data["waktu"],
            "kelebihan": hasil["kelebihan_berat_gram"],
            "id_pemeriksaan": id_pemeriksaan,
        }
        return jsonify({"status": "ok", "tiket": ticket_obj})

    data_db = ambil_semua_riwayat()
    return jsonify({"status": "success", "data": data_db if data_db else riwayat_pemeriksaan})


@app.route("/api/riwayat", methods=["GET"])
def api_riwayat():
    data_db = ambil_semua_riwayat()
    return jsonify({"status": "success", "data": data_db if data_db else riwayat_pemeriksaan})


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
        golongan = str(custom_vehicle.get("golongan") or MAP_GOLONGAN.get(jenis, "A")).upper().strip()
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
        rag_result = generate_answer(question=query, vehicle_data=vehicle_data)
        mode_konsultasi = "analisis_kendaraan" if vehicle_data else "chat_umum"
        return jsonify({
            "status": "success",
            "mode": mode_konsultasi,
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
    app.run(host="0.0.0.0", port=5000, debug=True)
