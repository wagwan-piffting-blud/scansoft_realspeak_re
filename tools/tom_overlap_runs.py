"""Follow each shared-take hit along the ScanSoft corpus: how long does it stay locked?

A chance match is a point. A shared RECORDING is a line: step a short window
along the ScanSoft corpus and the matching tom8 position must step with it,
slope 1, for as long as both stores hold the same take contiguously.

For every hit from a blind global search (NCC > F-TAKE p99.9 from tom_overlap.py):
  - slide a 100 ms window in 20 ms steps over +-1.5 s of the ScanSoft corpus
  - at each step, search tom8 only within +-25 ms of where slope 1 predicts
  - the same with the window time-reversed, which is the local null
A step is LOCKED when its NCC beats the reversed-window null's p99 and its lag
stays within 2 ms of the hit's.

Reports run lengths, slope, and where runs end relative to
  (a) ScanSoft's 300-tick stretch gaps (us_tom_full.dat), and
  (b) tom8 recording boundaries (indx).

    python -I tom_overlap_runs.py --pack ss
    python -I tom_overlap_runs.py --pack rs     (no stretch map for RS yet)
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tom_overlap as T  # noqa: E402

STEP = 160           # 20 ms at 8 kHz
WIN = 800            # 100 ms
HALF = 75            # +-75 steps = +-1.5 s
RAD = 200            # +-25 ms local search
LAG_TOL = 16         # 2 ms


def local_ncc(hay, y, probe):
    lo, hi = y - RAD, y + RAD + len(probe)
    if lo < 0 or hi > len(hay):
        return np.nan, 0
    seg = hay[lo:hi].astype(np.float64)
    p = probe.astype(np.float64) - probe.mean()
    pn = np.linalg.norm(p) or 1e-9
    num = np.correlate(seg, p, mode="valid")
    c1 = np.r_[0, np.cumsum(seg)]
    c2 = np.r_[0, np.cumsum(seg * seg)]
    L = len(p)
    e = c2[L:] - c2[:-L]
    m = (c1[L:] - c1[:-L]) / L
    den = np.maximum(np.sqrt(np.maximum(e - L * m * m, 0)), T.vdb_fast.SIL_FLOOR_RMS * np.sqrt(L))
    ncc = num / (den * pn)
    k = int(np.argmax(ncc))
    return float(ncc[k]), k - RAD


def gap_positions_22k():
    raw = np.memmap(T.SS_USELD, dtype=np.uint8, mode="r", offset=T.REC_OFF, shape=(T.N_UNITS, 16))
    pos = (raw[:, :4].copy().view("<u4").ravel() & 0x7FFFFFFF).astype(np.int64)
    ln = (raw[:, 11].astype(np.int64) << 4) | (raw[:, 12] >> 4)
    o = np.argsort(pos, kind="stable")
    pos, ln = pos[o], ln[o]
    g = np.where(pos[1:] != pos[:-1] + ln[:-1])[0]
    # the gap starts where unit g ends
    return np.round((pos[g] + ln[g]) * T.TICK_TO_22K).astype(np.int64) + T.AUDIO_OFF_22K


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", choices=["ss", "rs"], default="ss")
    ap.add_argument("--W", type=int, default=1600)
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--maxhits", type=int, default=200)
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)

    thr = json.loads((T.OUT / f"summary_W{a.W}.json").read_text())["threshold_p999_FTAKE"]
    S = T.Search(a.W)
    hay = np.asarray(S.s.full, dtype=np.float32)
    src = T.wav_i16(T.SS_WAV if a.pack == "ss" else T.RS_WAV)

    probes, starts = T.blind(src, a.W, a.n, rng)
    r = S.run(probes)
    hits = np.where(r["v"] > thr)[0][:a.maxhits]
    print(f"{a.pack.upper()}: {len(hits)} hits of {len(probes)} blind windows above {thr:.4f}")

    gaps = gap_positions_22k() if a.pack == "ss" else None
    rec_starts = S.offs
    out = []
    for h in hits:
        x0 = starts[h]                       # 22 kHz start of the hit window
        y0 = int(r["p"][h])                  # tom8 8 kHz position
        pol = int(r["pol"][h])
        span22 = int((HALF * STEP + WIN + a.W) * 441 / 160) + 2000
        lo22 = max(0, x0 - span22)
        seg8 = T.to8k(src[lo22:x0 + span22]).astype(np.float32) * pol
        c8 = int(round((x0 - lo22) * 160 / 441)) + a.W // 2 - WIN // 2
        rows = []
        for k in range(-HALF, HALF + 1):
            s = c8 + k * STEP
            if s < 0 or s + WIN > len(seg8):
                rows.append((k, np.nan, 0, np.nan))
                continue
            pr = seg8[s:s + WIN]
            y = y0 + a.W // 2 - WIN // 2 + k * STEP
            v, lag = local_ncc(hay, y, pr)
            vr, _ = local_ncc(hay, y, pr[::-1].copy())
            rows.append((k, v, lag, vr))
        out.append({"x0": int(x0), "y0": y0, "ncc": float(r["v"][h]), "rows": rows})

    # local null from the reversed windows, pooled over all hits
    vr_all = np.array([row[3] for o in out for row in o["rows"] if np.isfinite(row[3])])
    lthr = float(np.quantile(vr_all, 0.99))
    runs, slopes, end_gap_dist, end_rec_dist, crossed_gaps = [], [], [], [], 0
    for o in out:
        rows = o["rows"]
        ks = np.array([x[0] for x in rows])
        v = np.array([x[1] for x in rows])
        lag = np.array([x[2] for x in rows])
        lag0 = lag[HALF]
        lock = (v > lthr) & (np.abs(lag - lag0) <= LAG_TOL)
        if not lock[HALF]:
            continue
        a_ = HALF
        while a_ - 1 >= 0 and lock[a_ - 1]:
            a_ -= 1
        b_ = HALF
        while b_ + 1 < len(lock) and lock[b_ + 1]:
            b_ += 1
        n_steps = b_ - a_ + 1
        dur_ms = (n_steps - 1) * STEP / 8 + WIN / 8
        runs.append(dur_ms)
        if n_steps >= 5:
            seg = slice(a_, b_ + 1)
            slopes.append(np.polyfit(ks[seg] * STEP, ks[seg] * STEP + lag[seg], 1)[0])
        # where do the run's ends sit relative to SS gaps and tom8 recording edges
        c22 = o["x0"] + int((a.W // 2) * 441 / 160)
        for edge_k, side in ((a_, -1), (b_, +1)):
            if (side < 0 and edge_k == 0) or (side > 0 and edge_k == len(lock) - 1):
                continue                     # run hit the analysis window, not a real end
            e22 = c22 + int((edge_k * STEP + side * WIN / 2) * 441 / 160)
            if gaps is not None:
                end_gap_dist.append(int(np.min(np.abs(gaps - e22))) / 22.05)
            e8 = o["y0"] + a.W // 2 + edge_k * STEP + side * WIN // 2
            end_rec_dist.append(int(np.min(np.abs(rec_starts - e8))) / 8.0)
        if gaps is not None:
            g_lo = c22 + int((a_ * STEP - WIN / 2) * 441 / 160)
            g_hi = c22 + int((b_ * STEP + WIN / 2) * 441 / 160)
            crossed_gaps += int(np.sum((gaps > g_lo) & (gaps < g_hi)))

    runs = np.array(runs)
    print(f"local null (reversed windows) p99 = {lthr:.4f}; locked at the hit: {len(runs)}/{len(out)}")
    if len(runs):
        print(f"run length ms  p10 {np.quantile(runs,.1):.0f}  p50 {np.median(runs):.0f}  "
              f"p90 {np.quantile(runs,.9):.0f}  max {runs.max():.0f}  "
              f"(window cap {(2*HALF)*STEP/8 + WIN/8:.0f})")
        print(f"runs reaching the +-1.5 s cap on a side: "
              f"{np.mean([r_ >= (2*HALF)*STEP/8 for r_ in runs]):.1%}")
    if slopes:
        print(f"slope (tom8 samples per SS sample) median {np.median(slopes):.5f}  "
              f"IQR {np.quantile(slopes,.25):.5f}..{np.quantile(slopes,.75):.5f}")
    if end_rec_dist:
        d = np.array(end_rec_dist)
        print(f"run ends within 30 ms of a tom8 recording boundary: {np.mean(d <= 30):.1%} "
              f"(n={len(d)})")
    if gaps is not None and end_gap_dist:
        d = np.array(end_gap_dist)
        print(f"run ends within 30 ms of an SS 300-tick gap: {np.mean(d <= 30):.1%}  "
              f"median distance {np.median(d):.0f} ms; SS gaps crossed INSIDE locked runs: {crossed_gaps}")
    (T.OUT / f"runs_{a.pack}_W{a.W}.json").write_text(json.dumps(
        {"local_null_p99": lthr, "runs_ms": runs.tolist(), "slopes": [float(s) for s in slopes],
         "end_gap_dist_ms": end_gap_dist, "end_rec_dist_ms": end_rec_dist,
         "crossed_gaps": crossed_gaps, "hits": out}, indent=0))


if __name__ == "__main__":
    main()
