import numpy as np
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest

# Batas hukum: PP 30/2021 (lebar 2,55 m; panjang 18 m), tinggi 4,2 m. Satuan: meter dan ton (dunia nyata)
LEGAL = dict(P_max=18.0, L_max=2.55, T_max=4.2)
TOL = 0.03                      # toleransi ukur 3%
BATAS_PANJANG = (5, 7, 10)      # batas antar golongan (poster ASDP)

# Rentang tiap golongan (tabel aturan Anda). P, L, T dalam meter; W dalam ton (satuan dunia nyata).
# Padanan tarif ASDP: A=IV Pnp, B=V Pnp, C=VI Pnp, D=IV Brg, E=V Brg
RULES = {
    "A": dict(kelas="mobil", P=(3.3, 5.0),  L=(1.4, 2.1),  T=(1.2, 2.2), W=(0.8, 3.5)),
    "B": dict(kelas="bus",   P=(4.5, 7.0),  L=(1.7, 2.1),  T=(2.0, 3.2), W=(2.0, 8.0)),
    "C": dict(kelas="bus",   P=(7.0, 10.0), L=(2.0, 2.55), T=(2.5, 4.2), W=(5.0, 16.0)),
    "D": dict(kelas="truk",  P=(3.5, 5.0),  L=(1.5, 2.1),  T=(1.5, 2.8), W=(0.8, 5.5)),
    "E": dict(kelas="truk",  P=(5.0, 7.0),  L=(1.7, 2.5),  T=(2.0, 4.2), W=(2.3, 8.3)),
}
FEATS = ["P", "L", "T", "W"]


def golongan(jenis, p):
    """Golongan dari jenis dan panjang (m). None = tidak terdefinisi."""
    if jenis == "mobil":
        return "A" if p <= 5 else None
    if jenis == "bus":
        if p <= 7:  return "B"
        if p <= 10: return "C"
        return None
    if jenis == "truk":
        if p <= 5: return "D"
        if p <= 7: return "E"
        return None
    return None


def cek_aturan(jenis, P, L, T, W):
    """Lapis aturan: TOLAK (batas hukum) / INSPEKSI / OK."""
    alasan, tolak, insp = [], False, False
    if L > LEGAL["L_max"]: tolak = True; alasan.append(f"lebar {L:.2f} m melebihi batas hukum {LEGAL['L_max']} m")
    if T > LEGAL["T_max"]: tolak = True; alasan.append(f"tinggi {T:.2f} m melebihi batas hukum {LEGAL['T_max']} m")
    if P > LEGAL["P_max"]: tolak = True; alasan.append(f"panjang {P:.2f} m melebihi batas hukum {LEGAL['P_max']} m")
    g = golongan(jenis, P)
    if g is None:
        insp = True; alasan.append("panjang tidak masuk golongan manapun untuk jenis ini")
    else:
        r = RULES[g]
        if W > r["W"][1] * (1 + TOL):
            tolak = True; alasan.append(f"berat {W:.2f} t melebihi batas golongan {g} ({r['W'][1]} t)")
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
    """Fitur anomali = log(P, L, T, W) supaya sebaran relatif antar golongan sebanding."""
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
