import pymysql

# Konfigurasi Database MySQL (Laragon / phpMyAdmin)
DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "",               # Kosong untuk Laragon default
    "database": "gate_pelabuhan", # Nama database di MySQL Anda
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": True
}

def get_db_connection():
    """Membuka koneksi ke database MySQL."""
    try:
        connection = pymysql.connect(**DB_CONFIG)
        return connection
    except Exception as e:
        print(f"[DB ERROR] Gagal terhubung ke MySQL ({DB_CONFIG['database']}): {e}")
        return None

def simpan_pemeriksaan(data):
    """Menyimpan data hasil pemeriksaan & ML ke tabel pemeriksaan."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            sql = """
                INSERT INTO pemeriksaan 
                (nomor_tiket, jenis_kendaraan, panjang, lebar, tinggi, berat, golongan, model_ml, skor_anomali, status_anomali, alasan_aturan)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cur.execute(sql, (
                data.get("nomor_tiket"),
                data.get("jenis", "mobil"),
                data.get("P", 0.0),
                data.get("L", 0.0),
                data.get("T", 0.0),
                data.get("W_gram", data.get("berat_gram", 0.0)),
                data.get("golongan", "-"),
                data.get("model", "kmeans"),
                data.get("skor_anomali", 0.0),
                data.get("status_anomali", "Normal"),
                data.get("alasan_aturan", "")
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

