"""Where do full-scale samples come from: tom8 itself, the x2 upsample, or the added top band?

    python -I hybrid16_clip.py C:\\tmp\\hybrid16\\tom16_bwe.vdb
"""
import sys
from pathlib import Path

import numpy as np
from scipy import signal as sg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hybrid16_demo as HD  # noqa: E402
import hybrid16_bwe as B  # noqa: E402


def i16(path):
    return (np.asarray(np.memmap(path, np.uint8, "r", offset=HD.TOM16_DATA)) ^ 0xCE).view("<i2")


def main():
    new, old = i16(sys.argv[1]).astype(np.int32), i16(HD.TOM16).astype(np.int32)
    tom8 = np.load(B.OUT / "tom8_f32.npy")
    up = sg.resample_poly(tom8.astype(np.float64), 2, 1)
    lo, _ = HD.split(up)
    print(f"tom8 (8 kHz)      peak {np.abs(tom8).max():.0f}  >= 32767: {(np.abs(tom8) >= 32767).sum()}")
    print(f"tom8 x2           peak {np.abs(up).max():.0f}  > 32767: {(np.abs(up) > 32767).sum()}")
    print(f"tom8 x2 low band  peak {np.abs(lo).max():.0f}  > 32767: {(np.abs(lo) > 32767).sum()}")
    print(f"AudioSR tom16     at full scale: {(np.abs(old) >= 32767).sum()}")
    clip = np.where(np.abs(new) >= 32767)[0]
    lo_c = lo[:len(new)]
    own = (np.abs(lo_c[clip]) > 32767).mean() if len(clip) else 0
    print(f"new build         at full scale: {len(clip)}; of those, low band alone already over: {own:.0%}")
    offs, names = B.entries()
    r = np.searchsorted(2 * offs, clip, side="right") - 1
    u, c = np.unique(r, return_counts=True)
    print(f"   spread over {len(u)} recordings; worst: " +
          ", ".join(f"{names[k]} {n}" for k, n in sorted(zip(u, c), key=lambda z: -z[1])[:6]))


if __name__ == "__main__":
    main()
