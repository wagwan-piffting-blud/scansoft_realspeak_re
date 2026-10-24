"""Cross-pack take overlap: tom8 <-> SS 2004 <-> RS 2006, every direction, with lock confirmation.

Haystacks (8 kHz): tom8.vdb, the SS 2004 Tom corpus, the RS 2006 Tom corpus.
Probes (W samples, RMS-gated, both polarities): tom8 windows, SS blind windows, RS blind
windows, each also TIME-REVERSED as the null, plus Kyoko windows (other speaker).

Per haystack the HIT threshold is the p99.9 of all reversed-probe best scores against
THAT haystack: bigger haystacks have higher chance maxima, so one global threshold
would be wrong. tom8's threshold is the F-TAKE p99.9 from tom_overlap.py.

Every hit class that is reported is then lock-tested: a 100 ms window slid over
+-1.5 s of the probe's source must keep its lag at slope 1 against the haystack.

    python -I tom_overlap_xpack.py --n 2000
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy import signal as sg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tom_overlap as T  # noqa: E402
import tom_overlap_runs as R  # noqa: E402

CACHE = T.OUT / "cache"


def corpus8k(name, wav):
    p = CACHE / f"{name}_8k.f32.npy"
    if not p.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        x = np.asarray(T.wav_i16(wav), dtype=np.float32)
        y = sg.resample_poly(x, 160, 441).astype(np.float32)
        np.save(p, y)
        del x, y
    return np.load(p, mmap_mode="r")


class ArraySearch(T.Search):
    """T.Search over an arbitrary 8 kHz array instead of a .vdb."""

    def __init__(self, arr, W, label):
        s = T.vdb_fast.VdbSearcher.__new__(T.vdb_fast.VdbSearcher)
        s.decim, s.nfft, s.plen = 4, 1 << 18, W
        s.clen = max(8, W // 4)
        s.full = arr
        s.dec = sg.resample_poly(np.asarray(arr, np.float32), 1, 4).astype(np.float32)
        s.entries = [[0, label]]
        s.device, s.verbose = "cuda", True
        s._prep()
        self.s, self.W = s, W
        self.full_t = T.torch.from_numpy(np.asarray(arr, dtype=np.float32)).cuda()
        self.offs = np.array([0], dtype=np.int64)
        self.names = [label]


def windows(arr, W, n, rng, lo=8000):
    starts = rng.integers(lo, len(arr) - W - lo, size=int(n * 1.8))
    pr = [np.asarray(arr[s:s + W], np.float32) for s in starts]
    keep = T.gate(pr)
    return [p for p, k in zip(pr, keep) if k][:n], [int(s) for s, k in zip(starts, keep) if k][:n]


def lock_test(src, starts, hay, res, idx, W, maxn=100):
    """Slope-1 lock test at 8 kHz for the probes in idx. -> summary dict."""
    locked, runs, slopes = 0, [], []
    vr_all, traces = [], []
    for i in idx[:maxn]:
        x0, y0, pol = starts[i], int(res["p"][i]), int(res["pol"][i])
        rows = []
        for k in range(-R.HALF, R.HALF + 1):
            s = x0 + W // 2 - R.WIN // 2 + k * R.STEP
            if s < 0 or s + R.WIN > len(src):
                rows.append((k, np.nan, 0, np.nan))
                continue
            pr = np.asarray(src[s:s + R.WIN], np.float32) * pol
            y = y0 + W // 2 - R.WIN // 2 + k * R.STEP
            v, lag = R.local_ncc(hay, y, pr)
            vr, _ = R.local_ncc(hay, y, pr[::-1].copy())
            rows.append((k, v, lag, vr))
            if np.isfinite(vr):
                vr_all.append(vr)
        traces.append(rows)
    if not traces:
        return {"n": 0}
    lthr = float(np.quantile(vr_all, 0.99))
    for rows in traces:
        v = np.array([r[1] for r in rows], float)
        lag = np.array([r[2] for r in rows])
        c = R.HALF
        lk = (v > lthr) & (np.abs(lag - lag[c]) <= R.LAG_TOL)
        if not lk[c]:
            continue
        locked += 1
        a = b = c
        while a > 0 and lk[a - 1]:
            a -= 1
        while b < len(lk) - 1 and lk[b + 1]:
            b += 1
        runs.append((b - a) * R.STEP / 8 + R.WIN / 8)
        if b - a >= 4:
            ks = np.arange(a, b + 1) - c
            slopes.append(np.polyfit(ks * R.STEP, ks * R.STEP + lag[a:b + 1], 1)[0])
    return {"n": len(traces), "locked": locked, "local_null_p99": lthr,
            "run_p50_ms": float(np.median(runs)) if runs else None,
            "run_p90_ms": float(np.quantile(runs, .9)) if runs else None,
            "slope_p50": float(np.median(slopes)) if slopes else None,
            "slope_iqr": [float(np.quantile(slopes, .25)), float(np.quantile(slopes, .75))] if slopes else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--W", type=int, default=1600)
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=23)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    W = a.W

    thr_tom8 = json.loads((T.OUT / f"summary_W{W}.json").read_text())["threshold_p999_FTAKE"]
    ss8 = corpus8k("ss_tom", T.SS_WAV)
    rs8 = corpus8k("rs_tom", T.RS_WAV)
    ky8 = corpus8k("ss_kyoko", T.KY_WAV)

    H = {"tom8": T.Search(W), "ss": ArraySearch(ss8, W, "ss"), "rs": ArraySearch(rs8, W, "rs")}
    for h in H.values():
        h.s.verify()
    tom8 = np.asarray(H["tom8"].s.full, np.float32)
    SRC = {"tom8": tom8, "ss": ss8, "rs": rs8}

    P, ST = {}, {}
    for k, arr in (("tom8", tom8), ("ss", ss8), ("rs", rs8), ("ky", ky8)):
        P[k], ST[k] = windows(arr, W, a.n, rng)

    plan = [("tom8", "ss"), ("tom8", "rs"), ("ss", "rs"), ("rs", "ss"),
            ("ss", "tom8"), ("rs", "tom8"), ("ky", "ss"), ("ky", "rs")]
    res, rev = {}, {}
    for src, hay in plan:
        print(f"\n=== {src} -> {hay}", flush=True)
        res[(src, hay)] = H[hay].run(P[src])
        if src != "ky" and hay != "tom8":
            rev[(src, hay)] = H[hay].run([p[::-1].copy() for p in P[src]])

    thr = {"tom8": thr_tom8}
    for hay in ("ss", "rs"):
        pool = np.concatenate([v["v"] for (s, h), v in rev.items() if h == hay])
        thr[hay] = float(np.quantile(pool, 0.999))
    hit = {key: r["v"] > thr[key[1]] for key, r in res.items()}

    out = {"W": W, "n": a.n, "thresholds": thr, "rates": {}, "contingency": {}, "locks": {}}
    print("\nthresholds (p99.9 of reversed probes per haystack; tom8 = F-TAKE):",
          {k: round(v, 4) for k, v in thr.items()})
    print(f"\n{'probe -> haystack':18} {'hit rate':>9} {'rev-null rate':>14} {'p50':>7} {'p99':>7} {'max':>7}")
    for key, r in res.items():
        rv = rev.get(key)
        rr = float(np.mean(rv["v"] > thr[key[1]])) if rv is not None else float("nan")
        out["rates"][f"{key[0]}->{key[1]}"] = {"hit": float(hit[key].mean()), "rev_null": rr,
                                               "p50": float(np.median(r["v"])),
                                               "p99": float(np.quantile(r["v"], .99)),
                                               "max": float(r["v"].max())}
        print(f"{key[0] + ' -> ' + key[1]:18} {hit[key].mean():9.2%} {rr:14.2%} "
              f"{np.median(r['v']):7.4f} {np.quantile(r['v'], .99):7.4f} {r['v'].max():7.4f}")

    def table(src, h1, h2):
        A, B = hit[(src, h1)], hit[(src, h2)]
        t = {f"{h1}&{h2}": int((A & B).sum()), f"{h1} only": int((A & ~B).sum()),
             f"{h2} only": int((~A & B).sum()), "neither": int((~A & ~B).sum())}
        out["contingency"][f"{src} probes"] = t
        print(f"\n{src} probes (n={len(A)}): " + "  ".join(f"{k} {v}" for k, v in t.items()))
        return A, B

    a1, b1 = table("tom8", "ss", "rs")
    a2, b2 = table("ss", "tom8", "rs")
    a3, b3 = table("rs", "tom8", "ss")

    print("\nlock tests (slope-1 confirmation):")
    groups = {
        "tom8->ss": ("tom8", "ss", np.where(a1)[0]),
        "tom8->rs": ("tom8", "rs", np.where(b1)[0]),
        "ss->rs  (also in tom8)": ("ss", "rs", np.where(a2 & b2)[0]),
        "ss->rs  (NOT in tom8)": ("ss", "rs", np.where(~a2 & b2)[0]),
        "rs->ss  (also in tom8)": ("rs", "ss", np.where(a3 & b3)[0]),
        "rs->ss  (NOT in tom8)": ("rs", "ss", np.where(~a3 & b3)[0]),
    }
    for name, (src, hay, idx) in groups.items():
        lt = lock_test(SRC[src], ST[src], np.asarray(SRC[hay], np.float32),
                       res[(src, hay)], list(idx), W)
        out["locks"][name] = lt
        if lt["n"]:
            print(f"  {name:24} {lt['locked']:3d}/{lt['n']:3d} locked   run p50 {lt['run_p50_ms']} ms   "
                  f"slope {lt['slope_p50']:.5f}  IQR {lt['slope_iqr'][0]:.5f}..{lt['slope_iqr'][1]:.5f}"
                  if lt["locked"] else f"  {name:24} 0/{lt['n']} locked")
        else:
            print(f"  {name:24} no hits to test")
    (T.OUT / f"xpack_W{W}.json").write_text(json.dumps(out, indent=1))
    print(f"\nwrote {T.OUT / f'xpack_W{W}.json'}")


if __name__ == "__main__":
    main()
