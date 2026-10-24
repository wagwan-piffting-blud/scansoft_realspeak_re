"""Sanity checks on a built 16 kHz Tom .vdb against the AudioSR tom16.vdb it replaces.

    python -I hybrid16_verify.py C:\\tmp\\hybrid16\\tom16_bwe.vdb
"""
import hashlib
import sys
from pathlib import Path

import numpy as np
from scipy import signal as sg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hybrid16_demo as HD  # noqa: E402
import hybrid16_bwe as B  # noqa: E402
import hybrid16_mirror as MI  # noqa: E402


def data(path):
    raw = np.memmap(path, np.uint8, "r", offset=HD.TOM16_DATA)
    return raw


def main():
    new = Path(sys.argv[1])
    old = Path(HD.TOM16)
    print(f"size  new {new.stat().st_size:,}  old {old.stat().st_size:,}  "
          f"{'SAME' if new.stat().st_size == old.stat().st_size else 'DIFFERENT'}")
    with open(new, "rb") as f, open(old, "rb") as g:
        hn, ho = f.read(HD.TOM16_DATA), g.read(HD.TOM16_DATA)
    print(f"header (RIFF..indx, {HD.TOM16_DATA:#x} B): {'IDENTICAL' if hn == ho else 'DIFFERENT'}  "
          f"sha1 {hashlib.sha1(hn).hexdigest()[:12]}")
    x = (np.asarray(data(new)) ^ 0xCE).view("<i2")
    print(f"samples {len(x):,}  peak {np.abs(x.astype(np.int32)).max()}  "
          f"at full scale {(np.abs(x.astype(np.int32)) >= 32767).sum()}")
    tom8 = np.load(B.OUT / "tom8_f32.npy", mmap_mode="r")
    offs, names = B.entries()
    ends = np.r_[offs[1:], len(tom8)]
    rng = np.random.default_rng(5)
    pick = rng.choice(np.where((ends - offs) > 8000)[0], 200, replace=False)
    ncc, ratio, mir = [], [], []
    for i in pick:
        s0, s1 = int(offs[i]), int(ends[i])
        y = x[2 * s0:2 * s1].astype(np.float64)
        t = sg.resample_poly(np.asarray(tom8[s0:s1], np.float64), 2, 1)[:len(y)]
        yl, yh = HD.split(y)
        tl, _ = HD.split(t)
        ncc.append(np.dot(yl, tl) / (np.linalg.norm(yl) * np.linalg.norm(tl) + 1e-9))
        ratio.append(20 * np.log10(np.sqrt(np.mean(yh ** 2)) / (np.sqrt(np.mean(yl ** 2)) + 1e-9)))
        f, S = MI.frames(y)
        il = np.where((f >= 600) & (f <= 3400))[0]
        im = np.array([np.argmin(np.abs(f - (8000 - v))) for v in f[il]])
        sp = S[il].mean(0) > np.percentile(S[il].mean(0), 40)
        mir.append(np.median(MI.corr(S[il], S[im])[sp]))
    print(f"200 random recordings: low band vs tom8 NCC p1 {np.quantile(ncc, .01):.5f}  p50 {np.median(ncc):.5f}")
    print(f"   top band / low band level p10 {np.quantile(ratio, .1):+.1f} dB  p50 {np.median(ratio):+.1f}  p90 {np.quantile(ratio, .9):+.1f}")
    print(f"   mirror r, median of per-recording medians {np.median(mir):+.2f}  "
          f"(same 200 recordings: raw AudioSR +0.98, BWE build -0.00)")


if __name__ == "__main__":
    main()
