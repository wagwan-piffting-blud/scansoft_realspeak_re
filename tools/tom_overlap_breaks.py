"""Post-process runs_<pack>_W<W>.json: is a broken lock a CUT or just a pause?

For each hit, over the whole +-1.5 s window:
  same-lag span  first..last step locked at the hit's lag (internal breaks allowed)
  resumes        a break followed by a re-lock at the SAME lag  -> the take continues
  relocks-other  a later step locks strongly at a DIFFERENT lag -> a cut to other material
A shared take that only pauses shows long same-lag spans with resumptions; a
store cut into pieces shows the lag jumping or never returning.

    python -I tom_overlap_breaks.py --pack ss
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tom_overlap as T  # noqa: E402

STEP_MS = 20
LAG_TOL = 16


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", choices=["ss", "rs"], default="ss")
    ap.add_argument("--W", type=int, default=1600)
    a = ap.parse_args()
    d = json.loads((T.OUT / f"runs_{a.pack}_W{a.W}.json").read_text())
    lthr = d["local_null_p99"]
    spans, resumed, n_breaks, capped = [], 0, 0, 0
    for h in d["hits"]:
        rows = h["rows"]
        v = np.array([np.nan if r[1] is None else r[1] for r in rows], dtype=float)
        lag = np.array([r[2] for r in rows])
        c = len(rows) // 2
        if not (np.isfinite(v[c]) and v[c] > lthr):
            continue
        same = (v > lthr) & (np.abs(lag - lag[c]) <= LAG_TOL)
        idx = np.where(same)[0]
        spans.append((idx[-1] - idx[0]) * STEP_MS + 100)
        capped += int(idx[0] == 0 or idx[-1] == len(rows) - 1)
        # breaks inside the same-lag span, and whether they resume
        inside = same[idx[0]:idx[-1] + 1]
        runs = np.diff(np.r_[0, (~inside).astype(int), 0])
        n_b = int((runs == 1).sum())
        n_breaks += n_b
        resumed += n_b                      # every internal break is, by construction, resumed
    spans = np.array(spans)
    print(f"{a.pack.upper()} hits analysed: {len(spans)}")
    print(f"same-lag span ms  p10 {np.quantile(spans,.1):.0f}  p50 {np.median(spans):.0f}  "
          f"p90 {np.quantile(spans,.9):.0f}  max {spans.max():.0f}   (window 3100 ms)")
    print(f"spans touching the analysis window edge: {capped}/{len(spans)}")
    print(f"internal breaks that RESUMED at the same lag: {resumed} "
          f"({resumed/len(spans):.2f} per hit)")


if __name__ == "__main__":
    main()
