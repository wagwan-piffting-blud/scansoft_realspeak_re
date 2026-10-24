"""Does Tom 'switch' on sibilants? Top-band level of /s/ frames played from the REAL take
vs from the filler, inside the same build. Levels are dB re the frame's tom8 2.5-3.4 kHz
power, so loudness cancels. A small real-minus-filler gap = no audible switching.

    python -I hybrid16_switch.py --recs 150 --eq asr2real h5
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from scipy import signal as sg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hybrid16_v5 as V  # noqa: E402

BANDS = [(3400, 4500), (4500, 6000), (6000, 7000), (7000, 8000)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recs", type=int, default=150)
    ap.add_argument("--eq", nargs="+", default=["asr2real", "h5"])
    a = ap.parse_args()
    runs, tom8, offs, names, ends = V.setup()
    pos = {n: i for i, n in enumerate(names)}
    pick = np.random.default_rng(4).choice(sorted(runs), a.recs, replace=False)
    acc = {e: {"real": [], "fill": []} for e in a.eq}
    for nm in pick:
        i = pos[nm]
        s0, s1 = int(offs[i]), int(ends[i])
        x16 = sg.resample_poly(np.asarray(tom8[s0:s1], np.float64), 2, 1)
        f, t, X = sg.stft(x16, 16000, nperseg=512, noverlap=352, boundary=None, padded=False)
        P = np.abs(X) ** 2
        p_ref = P[(f >= 2500) & (f < 3400)].sum(0)
        sib = (p_ref >= 4 * P[f < 1000].sum(0)) & (p_ref > np.percentile(p_ref, 30))
        if sib.sum() < 2:
            continue
        tc = np.clip(np.arange(P.shape[1]) * 160 + 256, 0, len(x16) - 1)
        for e in a.eq:
            y, W, _ = V.render(tom8, s0, s1, runs[nm], eq=e)
            yf, _, _ = V.render(tom8, s0, s1, [], eq=e)       # the same recording, filler only
            m = sib & (W[tc] > 0.9)                             # SAME frames for both
            if not m.any():
                continue
            for key, src in (("real", y), ("fill", yf)):
                _, _, Y = sg.stft(src[:len(x16)], 16000, nperseg=512, noverlap=352, boundary=None, padded=False)
                Q = np.abs(Y) ** 2
                rel = np.array([10 * np.log10(Q[(f >= lo) & (f < hi)].sum(0) / (p_ref + 1e-9) + 1e-12)
                                for lo, hi in BANDS])
                acc[e][key].append(rel[:, m])
    print("sibilant frames, top band dB re tom8 2.5-3.4 kHz (median):")
    print("                     " + "  ".join(f"{lo / 1000:.1f}-{hi / 1000:.1f}k" for lo, hi in BANDS))
    for e in a.eq:
        med = {}
        for key in ("real", "fill"):
            v = np.concatenate(acc[e][key], 1)
            med[key] = np.median(v, 1)
            print(f"  {e:9} {key:4} n{v.shape[1]:5d} " + "  ".join(f"{x:+8.1f}" for x in med[key]))
        print(f"  {e:9} real-fill        " + "  ".join(f"{x:+8.1f}" for x in med["real"] - med["fill"]))


if __name__ == "__main__":
    main()
