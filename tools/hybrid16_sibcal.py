"""Calibrate v5's sibilant fill: per-bin correction (3.4-8 kHz) that makes the Tom BWE in
pure-noise mode match the REAL take's top band on strongly sibilant frames.

Real top band: hi_real.f16.npy / cell_ok.u8.npy (hybrid16_extract.py; gain-matched to tom8),
thousands of verified frames across all covered recordings. Saved as "sib_bwe" (dB per bin)
in C:\\tmp\\hybrid16\\v5_eq.json.

    python -I hybrid16_sibcal.py --recs 1500
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
from scipy import signal as sg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hybrid16_demo as HD  # noqa: E402
import hybrid16_bwe as B  # noqa: E402
import hybrid16_build as HB  # noqa: E402
import hybrid16_v5_eq as E  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recs", type=int, default=1500)
    a = ap.parse_args()
    tom8, hi, cell, offs, names, ends = HB.setup()
    bias, gain = HB.cal()
    cand = [i for i in range(len(names)) if names[i] not in HD.DEFAULT_RECS
            and (cell[offs[i] // 160:ends[i] // 160] > 0).sum() >= 10]
    pick = np.random.default_rng(8).choice(cand, min(a.recs, len(cand)), replace=False)
    diffs = []
    for i in pick:
        s0, s1 = int(offs[i]), int(ends[i])
        x16, real, c = HB.rec_data(tom8, hi, cell, s0, s1)
        if len(x16) < 4 * B.NFFT:
            continue
        lo, h = B.render2(x16, None, None, depth=0.0, bias=bias, gain=gain)
        nf = len(x16) // B.HOP + 1
        s = B.sibilance(lo, nf).cpu().numpy()
        Lr = B.logpow(real)[:, B.KX:].cpu().numpy()
        Lb = B.logpow(h)[:, B.KX:].cpu().numpy()
        n = min(len(s), len(Lr), len(Lb))
        cov = np.repeat(c > 0, 2)
        cov = np.r_[cov, np.zeros(max(0, n - len(cov)), bool)][:n]
        cov &= np.roll(cov, 2) & np.roll(cov, -2)
        m = cov & (s[:n] >= 0.8)
        if m.any():
            diffs.append(10 * (Lr[:n][m] - Lb[:n][m]))
    d = np.concatenate(diffs)
    f = np.fft.rfftfreq(B.NFFT, 1 / 16000)[B.KX:]
    med = np.median(d, 0)
    full_f = np.fft.rfftfreq(B.NFFT, 1 / 16000)
    curve = np.zeros(len(full_f))
    curve[B.KX:] = E.smooth_oct(f, med)
    curve[:B.KX] = curve[B.KX]
    p = HD.Path(r"C:\tmp\hybrid16\v5_eq.json") if hasattr(HD, "Path") else Path(r"C:\tmp\hybrid16\v5_eq.json")
    j = json.loads(p.read_text())
    j["sib_bwe"] = curve.tolist()
    p.write_text(json.dumps(j))
    print(f"{len(d)} strongly sibilant verified frames from {len(diffs)} recordings")
    for lo_, hi_ in ((3400, 4500), (4500, 6000), (6000, 7000), (7000, 8000)):
        k = (full_f >= lo_) & (full_f < hi_)
        print(f"  {lo_ / 1000:.1f}-{hi_ / 1000:.1f}k  real minus BWE {curve[k].mean():+5.1f} dB")
    print("saved sib_bwe ->", p)


if __name__ == "__main__":
    main()
