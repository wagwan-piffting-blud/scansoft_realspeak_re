"""Pilot for a REAL 16 kHz Speechify Tom: how much of tom8 has a 22 kHz source in SS 2004 / RS 2006?

Seed and extend, because a short window searched over a 4-5 h corpus has a high
chance maximum and so a high threshold. Per pack:

  SEED     200 ms tom8 windows at a 100 ms hop, global search (both polarities),
           hit = NCC > that pack's reversed-null p99.9 from tom_overlap_xpack.py
  EXTEND   from every seed, 100 ms windows at a 20 ms hop over the whole recording,
           each searched only +-25 ms around where slope 1 predicts. A step is LOCKED
           when it beats the local reversed-window null p99 and keeps the seed's lag
           (+-2 ms). Locks are grown out from the seed, tolerating gaps of up to 3 steps.

Coverage is counted on a 20 ms grid of SPEECH frames (RMS > max(200, recording p20)).

    python -I tom16_coverage.py --recs 60
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tom_overlap as T  # noqa: E402
import tom_overlap_runs as R  # noqa: E402
import tom_overlap_xpack as X  # noqa: E402

WS, HOP_S = 1600, 800          # seed window / hop
WIN, STEP, GAP = 800, 160, 3   # extension window / step / tolerated gap (steps)


def grow(lock, c):
    """Indices reachable from c through locked steps, allowing gaps <= GAP."""
    keep = np.zeros(len(lock), bool)
    for d in (-1, 1):
        k, miss = c, 0
        while 0 <= k < len(lock):
            if lock[k]:
                keep[k], miss = True, 0
            else:
                miss += 1
                if miss > GAP:
                    break
            k += d
    return keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recs", type=int, default=60)
    ap.add_argument("--seed", type=int, default=41)
    ap.add_argument("--from-ckls", action="store_true",
                    help="draw recordings only from those carrying ckls _WORD_ tokens")
    ap.add_argument("--tag", default="", help="suffix for the per-recording output file")
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    thr = json.loads((T.OUT / "xpack_W1600.json").read_text())["thresholds"]

    t8 = T.Search(WS)
    tom8 = np.asarray(t8.s.full, np.float32)
    ends = np.r_[t8.offs[1:], len(tom8)]
    dur = (ends - t8.offs) / 8000
    ok_dur = (dur > 0.6) & (dur < 12)
    if a.from_ckls:
        wanted = {w["rec"] for w in json.loads((T.OUT / "ckls_words.json").read_text())
                  if w["group"] == "_WORD_"}
        ok_dur &= np.array([n in wanted for n in t8.names])
    pool = np.where(ok_dur)[0]
    recs = [int(r) for r in rng.choice(pool, size=min(a.recs, len(pool)), replace=False)]

    # 20 ms speech grid per recording
    grid = {}
    for r in recs:
        s0, s1 = int(t8.offs[r]), int(ends[r])
        n = (s1 - s0) // STEP
        rms = np.sqrt(np.mean(tom8[s0:s0 + n * STEP].astype(np.float64).reshape(n, STEP) ** 2, 1))
        grid[r] = rms > max(200.0, np.percentile(rms, 20))

    cov = {}
    for pack, wav in (("ss", T.SS_WAV), ("rs", T.RS_WAV)):
        hay = X.corpus8k(f"{pack}_tom", wav)
        hay_f = np.asarray(hay, np.float32)
        H = X.ArraySearch(hay, WS, pack)
        H.s.verify()
        seeds, sm = [], []
        for r in recs:
            s0, s1 = int(t8.offs[r]), int(ends[r])
            for s in range(s0, s1 - WS, HOP_S):
                x = tom8[s:s + WS]
                if np.sqrt(np.mean(x.astype(np.float64) ** 2)) > 200:
                    seeds.append(x.copy())
                    sm.append((r, s))
        res = H.run(seeds)
        hits = [(sm[i], int(res["p"][i]), int(res["pol"][i])) for i in np.where(res["v"] > thr[pack])[0]]
        print(f"{pack.upper()}: {len(seeds)} seeds, {len(hits)} hits (thr {thr[pack]:.4f})", flush=True)

        traces = []
        for (r, s), p, pol in hits:
            s0 = int(t8.offs[r])
            n = len(grid[r])
            c = (s + WS // 2 - WIN // 2 - s0) // STEP
            rows = []
            for k in range(n):
                xs = s0 + k * STEP
                if xs + WIN > ends[r]:
                    rows.append((np.nan, 0, np.nan))
                    continue
                y = p + WS // 2 - WIN // 2 + (k - c) * STEP + (s + WS // 2 - WIN // 2 - s0 - c * STEP)
                pr = tom8[xs:xs + WIN] * pol
                v, lag = R.local_ncc(hay_f, y, pr)
                vr, _ = R.local_ncc(hay_f, y, pr[::-1].copy())
                rows.append((v, lag, vr))
            traces.append((r, c, rows))
        vr_all = np.array([row[2] for _, _, rows in traces for row in rows if np.isfinite(row[2])])
        lthr = float(np.quantile(vr_all, 0.99)) if len(vr_all) else 1.0
        cv = {r: np.zeros(len(grid[r]), bool) for r in recs}
        for r, c, rows in traces:
            v = np.array([x[0] for x in rows], float)
            lag = np.array([x[1] for x in rows])
            c = int(np.clip(c, 0, len(rows) - 1))
            lock = (v > lthr) & (np.abs(lag - lag[c]) <= R.LAG_TOL)
            if not lock[c]:
                continue
            keep = grow(lock, c)
            for k in np.where(keep)[0]:
                cv[r][k:k + WIN // STEP] = True        # a locked 100 ms window covers 5 grid cells
        cov[pack] = cv
        sp = np.concatenate([grid[r] for r in recs])
        cc = np.concatenate([cv[r] for r in recs])
        print(f"{pack.upper()}: local null p99 {lthr:.4f}; speech coverage {cc[sp].mean():.1%}", flush=True)
        del H

    sp = np.concatenate([grid[r] for r in recs])
    css = np.concatenate([cov["ss"][r] for r in recs])
    crs = np.concatenate([cov["rs"][r] for r in recs])
    per = []
    for r in recs:
        g = grid[r]
        if g.sum():
            e = (cov["ss"][r] | cov["rs"][r])[g].mean()
            per.append((t8.names[r], float(e), float(cov["ss"][r][g].mean()), float(cov["rs"][r][g].mean()),
                        float(g.sum() * STEP / 8000)))
    fr = np.array([p[1] for p in per])
    summ = {"coverage_speech": {"ss": float(css[sp].mean()), "rs": float(crs[sp].mean()),
                                "either": float((css | crs)[sp].mean()), "both": float((css & crs)[sp].mean())},
            "per_recording_either": {"p10": float(np.quantile(fr, .1)), "p50": float(np.median(fr)),
                                     "p90": float(np.quantile(fr, .9)), "ge90": float(np.mean(fr >= .9)),
                                     "ge50": float(np.mean(fr >= .5)), "zero": float(np.mean(fr == 0))},
            "recordings": per}
    (T.OUT / f"tom16_coverage{a.tag}.json").write_text(json.dumps(summ, indent=1))
    per_rec = {t8.names[r]: {"off": int(t8.offs[r]), "speech": grid[r].tolist(),
                             "ss": cov["ss"][r].tolist(), "rs": cov["rs"][r].tolist()} for r in recs}
    (T.OUT / f"tom16_coverage_perrec{a.tag}.json").write_text(json.dumps(per_rec))

    # per-frame dump: is the UNcovered speech the detector's blind spot (quiet / unvoiced),
    # or ordinary voiced speech that the packs simply do not contain?
    rms_l, zcr_l, nccmax_l = [], [], []
    for r in recs:
        s0 = int(t8.offs[r])
        n = len(grid[r])
        fr = tom8[s0:s0 + n * STEP].astype(np.float64).reshape(n, STEP)
        rms_l.append(np.sqrt(np.mean(fr ** 2, 1)))
        zcr_l.append(np.mean(np.abs(np.diff(np.sign(fr), axis=1)) > 0, 1))
    np.savez(T.OUT / "tom16_coverage_frames.npz", speech=sp, cov_ss=css, cov_rs=crs,
             rms=np.concatenate(rms_l), zcr=np.concatenate(zcr_l))
    rms, zcr = np.concatenate(rms_l), np.concatenate(zcr_l)
    covd, unc = sp & (css | crs), sp & ~(css | crs)
    voiced = zcr < 0.15
    print("\ncovered vs UNcovered speech frames (tom8 side):")
    for name, m in (("covered", covd), ("uncovered", unc)):
        print(f"  {name:9} n {m.sum():6d}  median RMS {np.median(rms[m]):7.0f}  "
              f"voiced share {voiced[m].mean():.0%}  loud-voiced share "
              f"{(voiced & (rms > np.median(rms[sp])))[m].mean():.0%}")
    # whole-recording view: uncovered frames inside recordings that ARE partly covered
    part = np.concatenate([np.full(len(grid[r]), bool((cov['ss'][r] | cov['rs'][r]).any())) for r in recs])
    print(f"  uncovered speech in recordings with SOME coverage: {(unc & part).sum() / max(1, unc.sum()):.0%}; "
          f"in recordings with none: {(unc & ~part).sum() / max(1, unc.sum()):.0%}")
    c = summ["coverage_speech"]
    p = summ["per_recording_either"]
    print(f"\nspeech-time coverage over {len(per)} recordings: SS {c['ss']:.1%}  RS {c['rs']:.1%}  "
          f"either {c['either']:.1%}  both {c['both']:.1%}")
    print(f"per recording (either): p10 {p['p10']:.0%}  p50 {p['p50']:.0%}  p90 {p['p90']:.0%}   "
          f">=90% {p['ge90']:.0%}   >=50% {p['ge50']:.0%}   none {p['zero']:.0%}")
    for row in sorted(per, key=lambda x: -x[1])[:8]:
        print(f"  {row[0]:22} either {row[1]:.0%}  SS {row[2]:.0%}  RS {row[3]:.0%}  ({row[4]:.1f} s speech)")


if __name__ == "__main__":
    main()
