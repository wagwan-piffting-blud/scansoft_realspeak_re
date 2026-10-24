"""Is AudioSR's 4-8 kHz band in tom16.vdb an IMAGE of the 0-4 kHz band?

Per 32 ms frame, the detrended log spectrum over f = 600..3400 Hz is correlated with
    MIRROR  the same frame at 8000 - f   (what zero-stuffing / aliasing leaves)
    SHIFT   the same frame at f + 4000   (what spectral replication leaves)
for AudioSR (B) and for the real 22 kHz high band (D, covered frames only).

    python -I hybrid16_mirror.py
"""
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal as sg

D = Path(r"C:\tmp\hybrid16_demo")


def frames(x):
    f, t, S = sg.spectrogram(x, 16000, nperseg=512, noverlap=256)
    return f, 10 * np.log10(S + 1e-3)


def detr(y):
    k = np.arange(y.shape[0])
    A = np.c_[k, np.ones_like(k)]
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    return y - A @ coef


def corr(a, b):
    a, b = detr(a), detr(b)
    return np.sum(a * b, 0) / np.sqrt(np.sum(a * a, 0) * np.sum(b * b, 0) + 1e-12)


def main():
    rows = {"B mirror": [], "B shift": [], "D mirror": [], "D shift": [], "B mirror (same frames as D)": []}
    for p in sorted(D.glob("*_B_audiosr.wav")):
        nm = p.name[:-len("_B_audiosr.wav")]
        if nm == "ALL":
            continue
        b, _ = sf.read(p)
        d, _ = sf.read(D / f"{nm}_D_realonly.wav")
        f, Sb = frames(b)
        _, Sd = frames(d)
        lo = (f >= 600) & (f <= 3400)
        il = np.where(lo)[0]
        im = np.array([np.argmin(np.abs(f - (8000 - x))) for x in f[il]])
        ish = np.array([np.argmin(np.abs(f - (x + 4000))) for x in f[il]])
        sp = Sb[il].mean(0) > np.percentile(Sb[il].mean(0), 40)
        hid = Sd[(f > 4500) & (f < 7500)].mean(0)
        cov = sp & (hid > np.percentile(hid, 30))
        mb, sb = corr(Sb[il], Sb[im]), corr(Sb[il], Sb[ish])
        md, sd = corr(Sd[il], Sd[im]), corr(Sd[il], Sd[ish])
        rows["B mirror"].append(mb[sp])
        rows["B shift"].append(sb[sp])
        rows["D mirror"].append(md[cov])
        rows["D shift"].append(sd[cov])
        rows["B mirror (same frames as D)"].append(mb[cov])
        print(f"{nm:12} AudioSR mirror r p50 {np.median(mb[sp]):+.2f}  shift {np.median(sb[sp]):+.2f}   "
              f"real mirror {np.median(md[cov]):+.2f}  shift {np.median(sd[cov]):+.2f}")
    print()
    for k, v in rows.items():
        v = np.concatenate(v)
        print(f"{k:28} n {len(v):5d}  r p25 {np.quantile(v, .25):+.2f}  p50 {np.median(v):+.2f}  "
              f"p75 {np.quantile(v, .75):+.2f}  share r>0.5 {np.mean(v > 0.5):.0%}")


def v2(d2=r"C:\tmp\hybrid16_demo2", vars_=("B_audiosr", "C2_hybrid", "E_bwe_only")):
    """Mirror r for every variant in hybrid16_demo2, speech frames only."""
    d2 = Path(d2)
    for var in vars_:
        rs = []
        for p in sorted(d2.glob(f"*_{var}.wav")):
            if p.name.startswith("ALL_"):
                continue
            x, _ = sf.read(p)
            f, S = frames(x)
            il = np.where((f >= 600) & (f <= 3400))[0]
            im = np.array([np.argmin(np.abs(f - (8000 - v))) for v in f[il]])
            sp = S[il].mean(0) > np.percentile(S[il].mean(0), 40)
            rs.append(corr(S[il], S[im])[sp])
        v = np.concatenate(rs)
        print(f"{var:12} mirror r p50 {np.median(v):+.2f}  share r>0.5 {np.mean(v > 0.5):.0%}  (n {len(v)})")


if __name__ == "__main__":
    if sys.argv[1:2] == ["v2"]:
        v2(*([sys.argv[2], sys.argv[3:]] if len(sys.argv) > 3 else []))
    else:
        main()
