import numpy as np
from sklearn.cluster import KMeans

# ==============================================================================
LEGAL = dict(P_max=25.0, L_max=8.0, T_max=10.0)
TOL = 0.10


RULES = {
    "A": dict(kelas="mobil", P=(4.0, 7.0),   L=(1.8, 2.7),  T=(1.8, 2.5),  W_max=40.0),
    "B":   dict(kelas="bus",   P=(7.0, 15.0),  L=(2.0, 4.0),  T=(2.5, 4.0), W_max=150.0),
    "C":  dict(kelas="truk",  P=(10.0, 12.0),  L=(2.0, 4.0),  T=(2.5, 4.0),  W_max=200.0),
}
FEATS = ["P", "L", "T", "W"]


def golongan(jenis, P=None):
    """
    Menentukan golongan ('A', 'B', 'C') berdasarkan jenis kendaraan ('mobil', 'bus', 'truk')
    atau langsung mengembalikan golongan jika input sudah 'A', 'B', atau 'C'.
    """
    if not jenis:
        return None
    j = str(jenis).strip()

    # Jika input sudah berupa kode golongan (A, B, C)
    if j.upper() in RULES:
        return j.upper()

    # Cari golongan yang memiliki atribut kelas == jenis (misal 'mobil' -> 'A')
    j_lower = j.lower()
    for g, info in RULES.items():
        if info.get("kelas") == j_lower:
            return g

    return None


def cek_aturan(jenis, P, L, T, W):
    """
    LAPIS 1: Rule-Based System (Penegakan Batas Hukum & Over Dimension Over Load)
    Returns: dict(golongan, status, alasan)
    """
    alasan, tolak, insp = [], False, False
    g = golongan(jenis, P)

    # --- A. Cek Batas Legal Absolut Pelabuhan (ODOL) ---
    if L > LEGAL["L_max"]:
        tolak = True
        alasan.append(f"Lebar {L:.2f} cm melebihi batas legal ({LEGAL['L_max']} cm)")
    if T > LEGAL["T_max"]:
        tolak = True
        alasan.append(f"Tinggi {T:.2f} cm melebihi batas legal ({LEGAL['T_max']} cm)")
    if P > LEGAL["P_max"]:
        tolak = True
        alasan.append(f"Panjang {P:.2f} cm melebihi batas legal ({LEGAL['P_max']} cm)")

    if g is None:
        insp = True
        alasan.append(f"Jenis kendaraan '{jenis}' tidak terdefinisi dalam sistem")
    else:
        r = RULES[g]

        # --- B. Cek Berat Melebihi Batas Maksimum Golongan (TOLAK) ---
        if W > r["W_max"] * (1 + TOL):
            tolak = True
            alasan.append(f"Berat {W:.2f} g melebihi batas maksimum {g} ({r['W_max']} g)")

        # --- C. Cek Dimensi di Luar Rentang Kewajaran Sejenis (INSPEKSI) ---
        for nama, val, (lo, hi) in [("panjang", P, r["P"]), ("lebar", L, r["L"]), ("tinggi", T, r["T"])]:
            if val < lo * (1 - TOL) or val > hi * (1 + TOL):
                insp = True
                alasan.append(f"{nama} {val:.2f} cm di luar rentang wajar {g} ({lo}-{hi} cm)")

    status = "TOLAK" if tolak else ("INSPEKSI" if insp else "OK")
    return dict(golongan=g, status=status, alasan=alasan)


def feat(x):
    """Fitur anomali ML = log(P, L, T, W) dalam satuan cm & gram."""
    a = np.asarray(x[FEATS] if hasattr(x, "columns") else x, dtype=float)
    return np.log(a)


def fit_models(Z, k=3, seed=42):
    """
    LAPIS 2: Melatih model K-Means dengan K=3 (mewakili pusat klaster Mobil, Bus, Truk Normal).
    """
    return dict(
        kmeans=KMeans(n_clusters=k, n_init=10, random_state=seed).fit(Z),
    )


def skor(name, model, Z):
    """
    Skor Anomali K-Means: Jarak Euclidean terdekat ke centroid kendaraan normal.
    Semakin besar skor, semakin menyimpang dari proporsi fisik wajar.
    """
    if hasattr(model, "transform"):
        return model.transform(Z).min(axis=1)
    return np.zeros(len(Z))