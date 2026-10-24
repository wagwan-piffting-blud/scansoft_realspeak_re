"""Are the crunches at run JOINS? Top-band energy spikes at run boundaries, per pack.

For every run edge inside verified audio (runs.json + cell_ok), compare the top-band
energy in the 10 ms around the edge with the median of the 60 ms on either side. Also
counts runs per second of verified audio per pack.

    python -I hybrid16_joins.py
"""
import json
import sys
from pathlib import Path

import numpy as np

OUT = Path(r"C:\tmp\hybrid16")
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    runs = json.loads((OUT / "runs.json").read_text())
    hi = np.load(OUT / "hi_real.f16.npy", mmap_mode="r")
    cell = np.load(OUT / "cell_ok.u8.npy")
    import hybrid16_bwe as B
    offs, names = B.entries()
    pos = dict(zip(names, offs))
    spikes = {"ss": [], "rs": []}
    ctrl = {"ss": [], "rs": []}
    nrun = {"ss": 0, "rs": 0}
    rng = np.random.default_rng(1)
    for nm, rr in runs.items():
        s0 = int(pos[nm])
        c = cell[s0 // 160:]
        for u in rr:
            pk = u["pack"]
            nrun[pk] += 1
            for e in (u["c0"], u["c1"]):
                if e < 4 or e + 4 >= len(c) or not (c[e - 3:e + 3] > 0).all():
                    continue
                for tgt, at in ((spikes, e), (ctrl, int(rng.integers(u["c0"] + 3, max(u["c0"] + 4, u["c1"] - 3))))):
                    if not (c[at - 3:at + 3] > 0).all():
                        continue
                    a = 2 * s0 + at * 320
                    x = np.asarray(hi[a - 1120:a + 1120], np.float64)
                    if len(x) < 2240:
                        continue
                    p = x.reshape(-1, 80) ** 2
                    p = p.mean(1)                                     # 5 ms frames
                    mid = p[13:15].mean()
                    ref = np.median(np.r_[p[:12], p[16:]]) + 1e-6
                    tgt[pk].append(10 * np.log10(mid / ref + 1e-9))
    sec = {k: (cell == (1 if k == "ss" else 2)).sum() * 0.02 for k in ("ss", "rs")}
    for pk in ("ss", "rs"):
        s, cc = np.array(spikes[pk]), np.array(ctrl[pk])
        print(f"{pk.upper()}: {nrun[pk]} runs, {nrun[pk] / sec[pk]:.2f} runs per verified second; "
              f"edges inside verified audio {len(s)}")
        print(f"   energy at edge vs surroundings: p50 {np.median(s):+.1f} dB  p90 {np.quantile(s, .9):+.1f} dB  "
              f"share > +6 dB {np.mean(s > 6):.0%}")
        print(f"   control (random mid-run point): p50 {np.median(cc):+.1f} dB  p90 {np.quantile(cc, .9):+.1f} dB  "
              f"share > +6 dB {np.mean(cc > 6):.0%}")


if __name__ == "__main__":
    main()
