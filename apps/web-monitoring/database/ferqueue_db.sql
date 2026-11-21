-- ==============================================================================
-- FERQUEUE — SISTEM PEMERIKSAAN KENDARAAN GERBANG PELABUHAN PENYEBERANGAN
-- Skala Prototipe / Miniatur Diecast (Satuan Berat: Gram, Satuan Dimensi: cm)
-- Rujukan Regulasi: Peraturan Menteri Perhubungan RI No. PM 103 Tahun 2017
-- ==============================================================================

CREATE DATABASE IF NOT EXISTS gate_pelabuhan
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE gate_pelabuhan;

-- ==============================================================================
-- 1. TABEL: golongan_kendaraan (Master Golongan & Batas Berat)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS golongan_kendaraan (
    golongan CHAR(1) PRIMARY KEY COMMENT 'A=Mobil, B=Bus, C=Truk',
    jenis_kendaraan VARCHAR(30) NOT NULL,
    batas_maksimum_gram DECIMAL(8, 2) NOT NULL,
    tarif DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    keterangan VARCHAR(255) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO golongan_kendaraan (golongan, jenis_kendaraan, batas_maksimum_gram, tarif, keterangan)
VALUES
    ('A', 'Mobil', 55.00,  60000.00,  'Kendaraan penumpang roda 4 (Batas maks: 55.00 gram)'),
    ('B', 'Bus',   85.00,  120000.00, 'Kendaraan angkutan penumpang (Batas maks: 85.00 gram)'),
    ('C', 'Truk',  100.00, 250000.00, 'Kendaraan angkutan barang (Batas maks: 100.00 gram)')
ON DUPLICATE KEY UPDATE
    jenis_kendaraan = VALUES(jenis_kendaraan),
    batas_maksimum_gram = VALUES(batas_maksimum_gram);

-- ==============================================================================
-- 2. TABEL: riwayat_pemeriksaan (Log Utama — tampil di halaman Riwayat)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS riwayat_pemeriksaan (
    id INT AUTO_INCREMENT PRIMARY KEY,
    id_pemeriksaan VARCHAR(30) NOT NULL UNIQUE,
    nomor_tiket VARCHAR(30) NULL UNIQUE COMMENT 'NULL jika Overweight',
    waktu_pemeriksaan DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    nama_pengemudi VARCHAR(100) NOT NULL DEFAULT 'Pengemudi',
    jenis_kendaraan VARCHAR(30) NOT NULL,
    golongan CHAR(1) NOT NULL,
    panjang_cm DECIMAL(6, 2) NOT NULL DEFAULT 0.00,
    tinggi_cm DECIMAL(6, 2) NOT NULL DEFAULT 0.00,
    berat_aktual_gram DECIMAL(8, 2) NOT NULL,
    batas_maksimum_gram DECIMAL(8, 2) NOT NULL,
    status ENUM('Normal', 'Overweight') NOT NULL DEFAULT 'Normal',

    INDEX idx_status (status),
    INDEX idx_waktu (waktu_pemeriksaan),
    CONSTRAINT fk_golongan
        FOREIGN KEY (golongan) REFERENCES golongan_kendaraan(golongan)
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==============================================================================
-- 3. TABEL: detail_overweight (Detail analisis — dipakai oleh Asisten LLM)
--    Hanya diisi untuk kendaraan berstatus Overweight.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS detail_overweight (
    id INT AUTO_INCREMENT PRIMARY KEY,
    id_pemeriksaan VARCHAR(30) NOT NULL UNIQUE,
    kelebihan_berat_gram DECIMAL(8, 2) NOT NULL DEFAULT 0.00,
    persentase_kelebihan VARCHAR(15) NOT NULL DEFAULT '0%',
    kategori_overweight VARCHAR(50) NOT NULL DEFAULT '-',
    minimal_pengurangan_gram DECIMAL(8, 2) NOT NULL DEFAULT 0.00,
    status_tiket VARCHAR(100) NOT NULL,
    status_gerbang VARCHAR(100) NOT NULL,
    tindakan TEXT NOT NULL,

    CONSTRAINT fk_detail_pemeriksaan
        FOREIGN KEY (id_pemeriksaan) REFERENCES riwayat_pemeriksaan(id_pemeriksaan)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==============================================================================
-- SELESAI. Database FERQUEUE siap digunakan (3 tabel).
-- ==============================================================================
