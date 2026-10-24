"""Debug the sibilant fill: band levels on /s/ frames of each ingredient vs the output.

    python -I hybrid16_sibdbg.py
"""
import sys
from pathlib import Path

import numpy as np
from scipy import signal as sg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hybrid16_demo as HD  # noqa: E402
import hybrid16_bwe as B  # noqa: E402
import hybrid16_build as HB  # noqa: E402
import hybrid16_v5 as V  # noqa: E402

BANDS = [(3400, 4500), (4500, 6000), (6000, 7000), (7000, 8000)]


def rel(x, f, p_ref, m):
    _, _, Y = sg.stft(x, 16000, nperseg=512, noverlap=352, boundary=None, padded=False)
    Q = np.abs(Y) ** 2
    return [np.median(10 * np.log10(Q[(f >= lo) & (f < hi)].sum(0)[m] / p_ref[m] + 1e-12)) for lo, hi in BANDS]


def main():
    tom8, hi, cell, offs, names, ends = HB.setup()
    bias, gain = HB.cal()
    rows = {k: [] for k in ("asr_eq", "bwe_d0", "sib_fill", "s16_mean")}
    for nm in HD.DEFAULT_RECS:
        i = names.index(nm)
        s0, s1 = int(offs[i]), int(ends[i])
        x16 = sg.resample_poly(np.asarray(tom8[s0:s1], np.float64), 2, 1)
        f, t, X = sg.stft(x16, 16000, nperseg=512, noverlap=352, boundary=None, padded=False)
        P = np.abs(X) ** 2
        p_ref = P[(f >= 2500) & (f < 3400)].sum(0)
        m = (p_ref >= 4 * P[f < 1000].sum(0)) & (p_ref > np.percentile(p_ref, 30))
        if m.sum() < 2:
            continue
        asr = HD.tom16_slice(s0, s1 - s0)[:len(x16)]
        asr = np.r_[asr, np.zeros(len(x16) - len(asr))]
        asr_eq = HD.zconv(asr, V.eq_fir("asr2real"))
        lo, h = B.render2(x16, None, None, depth=0.0, bias=bias, gain=gain)
        sf_ = V.sib_fill(asr_eq, x16)
        s = B.sibilance(lo, len(x16) // B.HOP + 1).cpu().numpy()
        tc = np.clip(np.arange(P.shape[1]) * 160 + 256, 0, len(x16) - 1)
        s16 = np.interp(np.arange(len(x16)), np.arange(len(s)) * B.HOP, s)
        rows["asr_eq"].append(rel(asr_eq, f, p_ref, m))
        rows["bwe_d0"].append(rel(h, f, p_ref, m))
        rows["sib_fill"].append(rel(sf_, f, p_ref, m))
        rows["s16_mean"].append([float(s16[tc][m].mean())] * 4)
    print("            " + "  ".join(f"{lo / 1000:.1f}-{hi / 1000:.1f}k" for lo, hi in BANDS))
    for k, v in rows.items():
        print(f"  {k:9} " + "  ".join(f"{x:+8.2f}" for x in np.median(np.array(v), 0)))


if __name__ == "__main__":
    main()
