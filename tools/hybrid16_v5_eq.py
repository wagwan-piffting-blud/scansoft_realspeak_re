"""Timbre gap between v5's arms: the real SS / RS take vs AudioSR on the SAME frames.

Over many recordings, frames where one run's weight is ~1 give paired spectra of the same
moment of the same take. Per pack:
    static curve   median over frames of (L_real - L_asr), dB per bin
    explained      how much of the per-frame difference variance a static EQ removes
The curves are 1/6-octave smoothed and saved to C:\\tmp\\hybrid16\\v5_eq.json for the
linear-phase EQ in hybrid16_v5.py.

    python -I hybrid16_v5_eq.py --recs 400
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy import signal as sg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hybrid16_demo as HD  # noqa: E402
import hybrid16_v5 as V  # noqa: E402

NFFT = 512


def logspec(x):
    f, t, S = sg.stft(x, 16000, nperseg=NFFT, noverlap=NFFT - 160, boundary=None, padded=False)
    return f, 10 * np.log10(np.abs(S) ** 2 + 1e-2)


def smooth_oct(f, d, frac=6):
    out = np.empty_like(d)
    for i, fc in enumerate(f):
        if fc < 60:
            out[i] = d[(f >= 30) & (f < 120)].mean()
            continue
        lo, hi = fc * 2 ** (-0.5 / frac), fc * 2 ** (0.5 / frac)
        out[i] = d[(f >= lo) & (f <= hi)].mean()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recs", type=int, default=400)
    a = ap.parse_args()
    runs, tom8, offs, names, ends = V.setup()
    rng = np.random.default_rng(11)
    cand = [n for n in runs if n not in HD.DEFAULT_RECS]
    pick = rng.choice(cand, min(a.recs, len(cand)), replace=False)
    pos = {n: i for i, n in enumerate(names)}
    D = {"ss": [], "rs": []}
    for nm in pick:
        i = pos[nm]
        s0, s1 = int(offs[i]), int(ends[i])
        x8 = np.asarray(tom8[s0:s1], np.float64)
        t8_16 = sg.resample_poly(x8, 2, 1)
        if len(t8_16) < 4 * HD.CELL16:
            continue
        t8_22 = sg.resample_poly(x8, 441, 160)
        asr = HD.tom16_slice(s0, s1 - s0)[:len(t8_16)]
        ncell = len(t8_16) // HD.CELL16
        rms8 = np.sqrt(np.mean(x8[:ncell * 160].reshape(ncell, 160) ** 2, 1))
        f, La = logspec(asr)
        tc = np.arange(La.shape[1]) * 160 + NFFT // 2
        for u in runs[nm]:
            r = V.run_audio(u, V.hays()[u["pack"]], t8_22, t8_16, rms8, asr)
            if r is None:
                continue
            a16, y, ok, g, _ = r
            w = V.weight(ok, u["c0"], len(t8_16))
            seg = np.zeros(len(t8_16))
            seg[a16:a16 + len(y)] = y[:len(t8_16) - a16] * 10 ** (g / 20)
            _, Lr = logspec(seg)
            full = np.array([w[max(0, c - NFFT // 2):c + NFFT // 2].min() > 0.99 for c in tc])
            loud = La.mean(0) > np.percentile(La.mean(0), 30)
            sel = full & loud
            if sel.any():
                D[u["pack"]].append(Lr[:, sel] - La[:, sel])
    out = {"f": f.tolist()}
    bands = [(0, 300), (300, 1000), (1000, 2000), (2000, 3400), (3400, 4000), (4000, 5000),
             (5000, 6000), (6000, 7000), (7000, 8000)]
    for pk, v in D.items():
        if not v:
            continue
        d = np.concatenate(v, 1)
        med = np.median(d, 1)
        tot = np.var(d, 1).mean()
        res = np.var(d - med[:, None], 1).mean() + 0 * tot
        mse0 = np.mean(d ** 2)
        mse1 = np.mean((d - med[:, None]) ** 2)
        curve = smooth_oct(f, med)
        out[pk] = curve.tolist()
        print(f"{pk.upper()}: {d.shape[1]} paired frames; real minus AudioSR, dB (median, 1/6-oct smoothed):")
        print("   " + "  ".join(f"{a_ / 1000:.1f}-{b_ / 1000:.1f}k {curve[(f >= a_) & (f < b_)].mean():+5.1f}"
                            for a_, b_ in bands))
        print(f"   per-frame mean-square difference {mse0:.1f} dB^2 -> {mse1:.1f} after a static EQ "
              f"({1 - mse1 / mse0:.0%} removed)")
    (V.OUT / "v5_eq.json").write_text(json.dumps(out))
    print("saved", V.OUT / "v5_eq.json")


if __name__ == "__main__":
    main()
