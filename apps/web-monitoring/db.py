import os
import socket
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import pymysql
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
env_path = BASE_DIR / ".env" if (BASE_DIR / ".env").exists() else BASE_DIR.parents[1] / ".env"
load_dotenv(dotenv_path=env_path)

# Konfigurasi Database MySQL (Laragon / phpMyAdmin)
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "gate_pelabuhan"),
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": True,
    "connect_timeout": 0.5,
}

_last_db_error_time = 0
DB_RETRY_INTERVAL = 15


def is_mysql_port_open(host="127.0.0.1", port=3306, timeout=0.04):
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except (OSError, socket.timeout):
        return False


def get_db_connection():
    global _last_db_error_time
    now = time.time()
    if now - _last_db_error_time < DB_RETRY_INTERVAL:
        return None
    h = "127.0.0.1" if DB_CONFIG.get("host") in ("localhost", "127.0.0.1") else DB_CONFIG.get("host", "127.0.0.1")
    if not is_mysql_port_open(h, DB_CONFIG.get("port", 3306)):
        _last_db_error_time = now
        return None
    try:
        connection = pymysql.connect(**DB_CONFIG)
        _last_db_error_time = 0
        return connection
    except Exception as e:
        _last_db_error_time = now
        print(f"[DB ERROR] Gagal terhubung ke MySQL ({DB_CONFIG['database']}): {e}")
        return None


def _format_row(row):
    if not row:
        return row
    formatted = dict(row)
    for k, v in formatted.items():
        if isinstance(v, Decimal):
            formatted[k] = float(v)
        elif isinstance(v, (datetime, date)):
            formatted[k] = v.strftime("%Y-%m-%d %H:%M:%S")
    return formatted


def simpan_pemeriksaan(data: dict) -> bool:
    """Menyimpan data pemeriksaan ke MySQL."""
    riwayat = {
        "id_pemeriksaan": data.get("id_pemeriksaan"),
        "nomor_tiket": data.get("nomor_tiket") or None,
        "nama_pengemudi": data.get("nama_pengemudi") or data.get("pengemudi") or "Pengemudi",
        "jenis_kendaraan": str(data.get("jenis_kendaraan") or data.get("jenis") or "Mobil").capitalize(),
        "golongan": str(data.get("golongan") or "A").upper(),
        "panjang_cm": float(data.get("panjang_cm") if data.get("panjang_cm") is not None else data.get("P", 0.0)),
        "tinggi_cm": float(data.get("tinggi_cm") if data.get("tinggi_cm") is not None else data.get("T", 0.0)),
        "berat_aktual_gram": float(data.get("berat_aktual_gram") if data.get("berat_aktual_gram") is not None else (data.get("berat_gram") or data.get("W", 0.0))),
        "batas_maksimum_gram": float(data.get("batas_maksimum_gram") if data.get("batas_maksimum_gram") is not None else data.get("batas_berat_gram", 55.0)),
        "status": "Overweight" if str(data.get("status", "")).lower().startswith("over") else "Normal",
    }

    is_overweight = riwayat["status"] == "Overweight"

    detail = None
    if is_overweight:
        detail = {
            "id_pemeriksaan": riwayat["id_pemeriksaan"],
            "kelebihan_berat_gram": float(data.get("kelebihan_berat_gram", 0.0)),
            "persentase_kelebihan": str(data.get("persentase_kelebihan") or "0%"),
            "kategori_overweight": str(data.get("kategori_overweight") or "-"),
            "minimal_pengurangan_gram": float(data.get("minimal_pengurangan_gram", 0.0)),
            "status_tiket": data.get("status_tiket") or "Tidak Diterbitkan (Ditolak - Pasal 5 PM 103/2017)",
            "status_gerbang": data.get("status_gerbang") or "Dibuka - Jalur Khusus Keluar (Pasal 6 PM 103/2017)",
            "tindakan": data.get("tindakan") or "Pemeriksaan fisik oleh petugas & putar balik",
        }

    conn = get_db_connection()
    if not conn:
        print("[DB WARNING] MySQL tidak tersedia, data tidak tersimpan.")
        return False

    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO riwayat_pemeriksaan (
                    id_pemeriksaan, nomor_tiket, nama_pengemudi, jenis_kendaraan, golongan,
                    panjang_cm, tinggi_cm, berat_aktual_gram, batas_maksimum_gram, status
                ) VALUES (
                    %(id_pemeriksaan)s, %(nomor_tiket)s, %(nama_pengemudi)s, %(jenis_kendaraan)s, %(golongan)s,
                    %(panjang_cm)s, %(tinggi_cm)s, %(berat_aktual_gram)s, %(batas_maksimum_gram)s, %(status)s
                )
            """, riwayat)
            if detail:
                cur.execute("""
                    INSERT INTO detail_overweight (
                        id_pemeriksaan, kelebihan_berat_gram, persentase_kelebihan,
                        kategori_overweight, minimal_pengurangan_gram,
                        status_tiket, status_gerbang, tindakan
                    ) VALUES (
                        %(id_pemeriksaan)s, %(kelebihan_berat_gram)s, %(persentase_kelebihan)s,
                        %(kategori_overweight)s, %(minimal_pengurangan_gram)s,
                        %(status_tiket)s, %(status_gerbang)s, %(tindakan)s
                    )
                """, detail)
        return True
    except Exception as e:
        print(f"[DB ERROR] Gagal menyimpan ke MySQL: {e}")
        return False
    finally:
        conn.close()


def ambil_semua_riwayat(limit: int = 100) -> list[dict]:
    """Mengambil riwayat pemeriksaan (untuk halaman Riwayat)."""
    conn = get_db_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM riwayat_pemeriksaan ORDER BY waktu_pemeriksaan DESC LIMIT %s",
                (limit,),
            )
            return [_format_row(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"[DB ERROR] Gagal mengambil riwayat: {e}")
        return []
    finally:
        conn.close()


def ambil_kendaraan_bermasalah(limit: int = 50) -> list[dict]:
    """Mengambil pemeriksaan Overweight + detail lengkap (untuk Asisten LLM)."""
    conn = get_db_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.*, d.kelebihan_berat_gram, d.persentase_kelebihan,
                       d.kategori_overweight, d.minimal_pengurangan_gram,
                       d.status_tiket, d.status_gerbang, d.tindakan
                FROM riwayat_pemeriksaan r
                JOIN detail_overweight d ON r.id_pemeriksaan = d.id_pemeriksaan
                WHERE r.status = 'Overweight'
                ORDER BY r.waktu_pemeriksaan DESC
                LIMIT %s
            """, (limit,))
            return [_format_row(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"[DB ERROR] Gagal mengambil data bermasalah: {e}")
        return []
    finally:
        conn.close()


def ambil_detail_pemeriksaan(id_pemeriksaan: str) -> dict | None:
    """Mengambil detail lengkap satu pemeriksaan + detail overweight (untuk Asisten LLM)."""
    conn = get_db_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.*, d.kelebihan_berat_gram, d.persentase_kelebihan,
                       d.kategori_overweight, d.minimal_pengurangan_gram,
                       d.status_tiket, d.status_gerbang, d.tindakan
                FROM riwayat_pemeriksaan r
                LEFT JOIN detail_overweight d ON r.id_pemeriksaan = d.id_pemeriksaan
                WHERE r.id_pemeriksaan = %s
            """, (id_pemeriksaan,))
            row = cur.fetchone()
            return _format_row(row) if row else None
    except Exception as e:
        print(f"[DB ERROR] Gagal mengambil detail: {e}")
        return None
    finally:
        conn.close()
