"""The fresh codsb_dump WAVs (D1 + D2) replace the Aug-8 corpus copies. Confirm they are
sample-aligned with the old ones (so every position already measured still holds), then
rebuild the 8 kHz search caches from them. Old caches are kept as *.pre_d1d2.npy.

    python -I corpus_swap_check.py
"""
import sys
from pathlib import Path

import numpy as np
from scipy import signal as sg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tom_overlap as T  # noqa: E402
import tom_overlap_xpack as X  # noqa: E402

OLD = {"ss": r"C:\tmp\nomorekillmyvibe\codsb_corpus\nextup_tom_full.wav",
       "rs": r"C:\tmp\nomorekillmyvibe\codsb_corpus\rs4_tom_full.wav"}
NEW = {"ss": T.SS_WAV, "rs": T.RS_WAV}


def main():
    rng = np.random.default_rng(2)
    for pk in ("ss", "rs"):
        a, b = T.wav_i16(OLD[pk]), T.wav_i16(NEW[pk])
        print(f"{pk}: old {len(a):,} new {len(b):,} samples")
        lags, nccs, dc = [], [], []
        hp = sg.butter(4, 60, btype="high", fs=22050, output="sos")
        for s in rng.integers(22050, len(a) - 3 * 22050, 40):
            x = sg.sosfiltfilt(hp, np.asarray(a[s:s + 22050], np.float64))
            y = sg.sosfiltfilt(hp, np.asarray(b[s:s + 22050], np.float64))
            c = sg.correlate(y, x, mode="full")[22050 - 1 - 50:22050 + 50]
            lags.append(int(np.argmax(c)) - 50)
            nccs.append(float(np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y) + 1e-9)))
            dc.append((np.mean(a[s:s + 22050]), np.mean(b[s:s + 22050])))
        dc = np.array(dc)
        print(f"   best lag p50 {np.median(lags)} (min {min(lags)}, max {max(lags)}); NCC at lag 0 above 60 Hz "
              f"p10 {np.quantile(nccs, .1):.4f} p50 {np.median(nccs):.4f}; |DC| old {np.abs(dc[:, 0]).mean():.0f} "
              f"new {np.abs(dc[:, 1]).mean():.0f}")
        p = X.CACHE / f"{pk}_tom_8k.f32.npy"
        if p.exists():
            p.replace(p.with_suffix(".pre_d1d2.npy"))
        X.corpus8k(f"{pk}_tom", NEW[pk])
        print(f"   rebuilt {p}")


if __name__ == "__main__":
    main()
