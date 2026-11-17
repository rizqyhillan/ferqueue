import socket
import time
import pymysql

# Konfigurasi Database MySQL (Laragon / phpMyAdmin)
DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "",               # Kosong untuk Laragon default
    "database": "gate_pelabuhan", # Nama database di MySQL Anda
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": True,
    "connect_timeout": 0.3
}

_last_db_error_time = 0
DB_RETRY_INTERVAL = 15  # Detik jeda sebelum mencoba koneksi ulang jika MySQL tidak aktif

def is_mysql_port_open(host="127.0.0.1", port=3306, timeout=0.04):
    """Pengecekan cepat apakah port MySQL aktif agar tidak memblokir aplikasi web."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except (OSError, socket.timeout):
        return False

def get_db_connection():
    """Membuka koneksi ke database MySQL dengan perlindungan timeout instan."""
    global _last_db_error_time
    now = time.time()
    # Jika koneksi gagal dalam interval retry, langsung lewati tanpa lag
    if now - _last_db_error_time < DB_RETRY_INTERVAL:
        return None

    # Tes socket kilat (<0.04s) sebelum pymysql connect
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

def simpan_pemeriksaan(data):
    """Menyimpan data hasil pemeriksaan ke tabel pemeriksaan."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            sql = """
                INSERT INTO pemeriksaan 
                (nomor_tiket, jenis_kendaraan, panjang, lebar, tinggi, berat, golongan, status, alasan)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cur.execute(sql, (
                data.get("nomor_tiket"),
                data.get("jenis", "mobil"),
                data.get("P", 0.0),
                data.get("L", 0.0),
                data.get("T", 0.0),
                data.get("W_gram", data.get("berat_gram", 0.0)),
                data.get("golongan", "-"),
                data.get("status", "Normal"),
                data.get("alasan", "")
            ))
        return True
    except Exception as e:
        print(f"[DB ERROR] Gagal menyimpan pemeriksaan: {e}")
        return False
    finally:
        conn.close()

def simpan_tiket(nomor_tiket, pengemudi, golongan, berat, status_kendaraan="Normal"):
    """Menyimpan data tiket ke tabel tiket."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            sql = """
                INSERT INTO tiket (nomor_tiket, pengemudi, golongan, berat, status_kendaraan)
                VALUES (%s, %s, %s, %s, %s)
            """
            cur.execute(sql, (nomor_tiket, pengemudi, golongan, berat, status_kendaraan))
        return True
    except Exception as e:
        print(f"[DB ERROR] Gagal menyimpan tiket: {e}")
        return False
    finally:
        conn.close()

def ambil_semua_tiket():
    """Mengambil riwayat tiket dari tabel tiket."""
    conn = get_db_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM tiket ORDER BY created_at DESC")
            return cur.fetchall()
    except Exception as e:
        print(f"[DB ERROR] Gagal mengambil tiket: {e}")
        return []
    finally:
        conn.close()

