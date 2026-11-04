import numpy as np
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest

# Batas hukum disesuaikan untuk SKALA DIECAST (Hot Wheels / miniatur)
# Dimensi dalam CM, Berat dalam GRAM
LEGAL = dict(P_max=25.0, L_max=8.0, T_max=10.0)
TOL = 0.10                      # toleransi ukur 10% (karakteristik diecast bervariasi)
BATAS_PANJANG = (6, 9, 13)      # batas antar golongan dalam CM

# Rentang tiap golongan untuk skala diecast/miniatur.
# P, L, T dalam CM; W dalam GRAM.
# Acuan Hot Wheels 1:64: mobil ~6-8 cm (30-60 g), truk/bus ~7-14 cm (40-120 g)
RULES = {
    "A": dict(kelas="mobil", P=(4.0, 8.0),   L=(1.5, 4.0),  T=(1.0, 3.5), W=(10, 80)),
    "B": dict(kelas="bus",   P=(6.0, 9.0),   L=(1.5, 3.5),  T=(1.5, 4.0), W=(20, 100)),
    "C": dict(kelas="bus",   P=(9.0, 15.0),  L=(2.0, 4.0),  T=(2.0, 5.0), W=(40, 150)),
    "D": dict(kelas="truk",  P=(4.0, 6.0),   L=(1.5, 3.5),  T=(1.5, 4.0), W=(15, 90)),
    "E": dict(kelas="truk",  P=(6.0, 13.0),  L=(1.5, 4.5),  T=(2.0, 5.0), W=(30, 150)),
}
FEATS = ["P", "L", "T", "W"]


def golongan(jenis, p):
    """Golongan dari jenis dan panjang (cm). None = tidak terdefinisi."""
    if jenis == "mobil":
        return "A" if p <= 8 else None
    if jenis == "bus":
        if p <= 9:  return "B"
        if p <= 15: return "C"
        return None
    if jenis == "truk":
        if p <= 6:  return "D"
        if p <= 13: return "E"
        return None
    return None


def cek_aturan(jenis, P, L, T, W):
    """Lapis aturan: TOLAK (batas hukum) / INSPEKSI / OK. Satuan: cm & gram."""
    alasan, tolak, insp = [], False, False
    if L > LEGAL["L_max"]: tolak = True; alasan.append(f"lebar {L:.2f} cm melebihi batas {LEGAL['L_max']} cm")
    if T > LEGAL["T_max"]: tolak = True; alasan.append(f"tinggi {T:.2f} cm melebihi batas {LEGAL['T_max']} cm")
    if P > LEGAL["P_max"]: tolak = True; alasan.append(f"panjang {P:.2f} cm melebihi batas {LEGAL['P_max']} cm")
    g = golongan(jenis, P)
    if g is None:
        insp = True; alasan.append("panjang tidak masuk golongan manapun untuk jenis ini")
    else:
        r = RULES[g]
        if W > r["W"][1] * (1 + TOL):
            tolak = True; alasan.append(f"berat {W:.2f} g melebihi batas golongan {g} ({r['W'][1]} g)")
        for nama, key, val in (("panjang", "P", P), ("lebar", "L", L), ("tinggi", "T", T), ("berat", "W", W)):
            lo, hi = r[key]
            if nama == "berat" and val > hi:
                continue
            if val < lo * (1 - TOL) or val > hi * (1 + TOL):
                insp = True; alasan.append(f"{nama} {val:.2f} di luar rentang wajar {g} ({lo}-{hi})")
        if any(abs(P - b) / b <= TOL for b in BATAS_PANJANG):
            insp = True; alasan.append("panjang dekat batas golongan (zona toleransi)")
    status = "TOLAK" if tolak else ("INSPEKSI" if insp else "OK")
    return dict(golongan=g, status=status, alasan=alasan)


def feat(x):
    """Fitur anomali = log(P, L, T, W) dalam satuan cm & gram."""
    a = np.asarray(x[FEATS] if hasattr(x, "columns") else x, dtype=float)
    return np.log(a)


def fit_models(Z, k, seed):
    return dict(
        kmeans=KMeans(k, n_init=10, random_state=seed).fit(Z),
        iforest=IsolationForest(n_estimators=200, random_state=seed).fit(Z),
    )


def skor(name, model, Z):
    """Skor anomali: makin besar makin janggal."""
    if name == "kmeans":
        return model.transform(Z).min(axis=1)   # jarak ke centroid terdekat
    return -model.score_samples(Z)               # Isolation Forest
