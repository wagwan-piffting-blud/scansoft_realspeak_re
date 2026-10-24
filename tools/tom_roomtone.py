"""Room tone: is the ScanSoft/RealSpeak-only audio from the SAME sessions as the Speechify-shared audio?

Windows from each ACELP pack are classed by what their audio locks to:
    A   also in tom8                       (known SpeechWorks session audio)
    B   in the other ACELP pack, NOT tom8  (the material in question)
    C   in neither
Features per 200 ms window, from the 22,050 Hz corpus, level-normalised:
    floor   10th-percentile minus 90th-percentile band energy (noise floor / room tone)
    ltas    mean band energy minus its across-band mean (channel colour)
    hi      >8 kHz and 4-8 kHz energy against 1-4 kHz (mic / preamp / anti-alias)
    hum     50 and 60 Hz line energy against 70-90 Hz
Cross-validated logistic-regression AUC per class pair, per feature group. The null
is A vs A split at random. B ~ A at null level means the room tone gives no evidence
of a different session. Clear separation means a different recording condition, or
a content difference the features did not cancel. Both packs are run, so a real
session difference must replicate across two independent encodes.

    python -I tom_roomtone.py --n 5000
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tom_overlap as T  # noqa: E402
import tom_overlap_xpack as X  # noqa: E402

SR = 22050
EDGES = np.geomspace(60, 10500, 33)


def features(x):
    x = np.asarray(x, np.float64)
    x = x - x.mean()
    n, hop = 512, 128
    fr = np.lib.stride_tricks.sliding_window_view(x, n)[::hop] * np.hanning(n)
    ps = np.abs(np.fft.rfft(fr, axis=1)) ** 2 + 1e-3
    f = np.fft.rfftfreq(n, 1 / SR)
    # 43 Hz bins: the lowest log bands can be empty, so keep only bands that hold a bin
    sel = [(f >= lo) & (f < hi) for lo, hi in zip(EDGES[:-1], EDGES[1:])]
    bands = np.stack([ps[:, m].sum(1) for m in sel if m.any()], 1)
    db = 10 * np.log10(bands)
    floor = np.percentile(db, 10, axis=0) - np.percentile(db, 90, axis=0)
    ltas = db.mean(0) - db.mean()
    tot = ps.sum(0)

    def band(lo, hi):
        return tot[(f >= lo) & (f < hi)].sum()
    hi = 10 * np.log10(np.array([band(8000, 11025), band(4000, 8000)]) / band(1000, 4000))
    big = np.abs(np.fft.rfft(x * np.hanning(len(x)), 1 << 16)) ** 2 + 1e-3
    fb = np.fft.rfftfreq(1 << 16, 1 / SR)
    ref = big[(fb >= 70) & (fb < 90)].mean()
    hum = 10 * np.log10(np.array([big[np.abs(fb - h) < 2].max() for h in (50, 60, 100, 120)]) / ref)
    return {"floor": floor, "ltas": ltas, "hi": hi, "hum": hum}


def auc(Xa, Xb, seed=0):
    X_ = np.vstack([Xa, Xb])
    y = np.r_[np.zeros(len(Xa)), np.ones(len(Xb))]
    m = make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=2000))
    p = cross_val_predict(m, X_, y, cv=StratifiedKFold(5, shuffle=True, random_state=seed),
                          method="predict_proba")[:, 1]
    return float(roc_auc_score(y, p))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=31)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    W = 1600
    thr = json.loads((T.OUT / f"xpack_W{W}.json").read_text())["thresholds"]
    ss8, rs8 = X.corpus8k("ss_tom", T.SS_WAV), X.corpus8k("rs_tom", T.RS_WAV)
    H = {"tom8": T.Search(W), "ss": X.ArraySearch(ss8, W, "ss"), "rs": X.ArraySearch(rs8, W, "rs")}
    src22 = {"ss": T.wav_i16(T.SS_WAV), "rs": T.wav_i16(T.RS_WAV)}

    report = {}
    for pack, other, arr in (("ss", "rs", ss8), ("rs", "ss", rs8)):
        cache = T.OUT / f"roomtone_classes_{pack}_n{a.n}_s{a.seed}.npz"
        if cache.exists():
            z = np.load(cache)
            st, in_t8, in_ot = list(z["st"]), z["in_t8"], z["in_ot"]
        else:
            pr, st = X.windows(arr, W, a.n, rng)
            in_t8 = H["tom8"].run(pr)["v"] > thr["tom8"]
            in_ot = H[other].run(pr)["v"] > thr[other]
            np.savez(cache, st=np.array(st), in_t8=in_t8, in_ot=in_ot)
        cls = np.where(in_t8, "A", np.where(in_ot, "B", "C"))
        feats = [features(src22[pack][int(s * 441 / 160):int(s * 441 / 160) + 4410]) for s in st]
        groups = {g: np.stack([f[g] for f in feats]) for g in ("floor", "ltas", "hi", "hum")}
        groups["all"] = np.hstack([groups[g] for g in ("floor", "ltas", "hi", "hum")])
        cnt = {c: int((cls == c).sum()) for c in "ABC"}
        print(f"\n{pack.upper()} windows: A (in tom8) {cnt['A']}   B (in {other.upper()} only) {cnt['B']}   "
              f"C (neither) {cnt['C']}")
        rows = {}
        A = np.where(cls == "A")[0]
        perm = rng.permutation(A)
        for g, M in groups.items():
            r = {"A|A null": auc(M[perm[:len(A) // 2]], M[perm[len(A) // 2:]]),
                 "A|B": auc(M[cls == "A"], M[cls == "B"]),
                 "A|C": auc(M[cls == "A"], M[cls == "C"]),
                 "B|C": auc(M[cls == "B"], M[cls == "C"])}
            rows[g] = r
            print(f"  {g:6} AUC  " + "   ".join(f"{k} {v:.3f}" for k, v in r.items()))
        # interpretable differences, B minus A, median dB
        d = {"floor_dB": float(np.median(groups["floor"][cls == "B"]) - np.median(groups["floor"][cls == "A"])),
             "hi_8k_dB": float(np.median(groups["hi"][cls == "B", 0]) - np.median(groups["hi"][cls == "A", 0])),
             "hi_4k_dB": float(np.median(groups["hi"][cls == "B", 1]) - np.median(groups["hi"][cls == "A", 1])),
             "hum60_dB": float(np.median(groups["hum"][cls == "B", 1]) - np.median(groups["hum"][cls == "A", 1])),
             "hum50_dB": float(np.median(groups["hum"][cls == "B", 0]) - np.median(groups["hum"][cls == "A", 0]))}
        print("  B - A medians: " + "  ".join(f"{k} {v:+.2f}" for k, v in d.items()))
        report[pack] = {"counts": cnt, "auc": rows, "B_minus_A": d}
    (T.OUT / "roomtone.json").write_text(json.dumps(report, indent=1))
    print(f"\nwrote {T.OUT / 'roomtone.json'}")


if __name__ == "__main__":
    main()
