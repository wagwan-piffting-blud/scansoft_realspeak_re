"""Is tom8's UNcovered speech the detector's blind spot, or just absent from SS/RS?

Reads C:\\tmp\\tom_overlap\\tom16_coverage_frames.npz written by tom16_coverage.py.

    python -I tom16_blindspot.py
"""
import numpy as np

z = np.load(r"C:\tmp\tom_overlap\tom16_coverage_frames.npz")
sp, rms, zcr = z["speech"], z["rms"], z["zcr"]
cov = z["cov_ss"] | z["cov_rs"]
voiced = zcr < 0.15
loud = rms > np.median(rms[sp])
covd, unc = sp & cov, sp & ~cov

print(f"speech frames {sp.sum()}   covered {covd.sum()} ({covd.sum()/sp.sum():.1%})")
print(f"{'':10} {'median RMS':>10} {'voiced':>7} {'loud+voiced':>12}")
for name, m in (("covered", covd), ("UNcovered", unc)):
    print(f"{name:10} {np.median(rms[m]):10.0f} {voiced[m].mean():7.0%} {(voiced & loud)[m].mean():12.0%}")

# coverage rate by frame type: if the detector were the limit, loud voiced frames
# (its best case) would be covered far more often than quiet or unvoiced ones
for name, m in (("loud voiced", sp & voiced & loud), ("quiet voiced", sp & voiced & ~loud),
                ("unvoiced", sp & ~voiced)):
    print(f"coverage of {name:13} frames: {cov[m].mean():.1%}  (n={m.sum()})")
