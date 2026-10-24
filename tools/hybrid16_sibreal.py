"""The user wants NO sibilant energy reaching the top of the band (pure AudioSR rolls /s/ off
around 6-7 kHz; the real SS/RS take runs to 8 kHz). Measure, on the SAME strongly sibilant
frames, real arm minus H3 filler per bin; saved as "sib_real2fill" (dB) in v5_eq.json and
applied to the real arms by sibilance in hybrid16_v5.render(eq="h6").

    python -I hybrid16_sibreal.py --recs 1200
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy import signal as sg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hybrid16_bwe as B  # noqa: E402
import hybrid16_v5 as V  # noqa: E402
import hybrid16_v5_eq as E  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recs", type=int, default=1200)
    a = ap.parse_args()
    runs, tom8, offs, names, ends = V.setup()
    pos = {n: i for i, n in enumerate(names)}
    pick = np.random.default_rng(4).choice(sorted(runs), a.recs, replace=False)
    diffs = []
    for nm in pick:
        i = pos[nm]
        s0, s1 = int(offs[i]), int(ends[i])
        x16 = sg.resample_poly(np.asarray(tom8[s0:s1], np.float64), 2, 1)
        if len(x16) < 4 * B.NFFT:
            continue
        y, W, _ = V.render(tom8, s0, s1, runs[nm], eq="asr2real")
        yf, _, _ = V.render(tom8, s0, s1, [], eq="asr2real")
        lo, _ = V.HD.split(x16)
        s = B.sibilance(lo, len(x16) // B.HOP + 1).cpu().numpy()
        Lr = B.logpow(y[:len(x16)]).cpu().numpy()
        Lf = B.logpow(yf[:len(x16)]).cpu().numpy()
        n = min(len(s), len(Lr), len(Lf))
        w = W[np.clip(np.arange(n) * B.HOP, 0, len(W) - 1)]
        m = (s[:n] >= 0.8) & (w > 0.95)
        if m.any():
            diffs.append(10 * (Lr[:n][m] - Lf[:n][m]))
    d = np.concatenate(diffs)
    f = np.fft.rfftfreq(B.NFFT, 1 / 16000)
    curve = E.smooth_oct(f, np.median(d, 0))
    curve[f < 3000] = 0.0                       # leave the band below 3 kHz alone
    p = V.OUT / "v5_eq.json"
    j = json.loads(p.read_text())
    j["sib_real2fill"] = curve.tolist()
    p.write_text(json.dumps(j))
    print(f"{len(d)} strongly sibilant frames (real arm and filler, same frames) from {len(diffs)} recordings")
    for lo_, hi_ in ((3000, 3400), (3400, 4500), (4500, 6000), (6000, 7000), (7000, 8000)):
        k = (f >= lo_) & (f < hi_)
        print(f"  {lo_ / 1000:.1f}-{hi_ / 1000:.1f}k  real minus filler {curve[k].mean():+6.1f} dB")
    print("saved sib_real2fill ->", p)


if __name__ == "__main__":
    main()
