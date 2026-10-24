"""Query-by-example: does SS 2004 hold OTHER TAKES of words specific to Speechify's script?

Same speaker everywhere, so a word's own tom8 recording is a usable template for any other
take of that word: different waveform, same spectral trajectory. Features: 12 MFCC
(c1..c12) from 24 log-mel bands over 0-4 kHz, 25 ms / 10 ms, global CMN per corpus; both
corpora at 8 kHz. Similarity: cosine between the per-channel mean-removed query matrix and
every corpus window (GPU conv1d), at time scales 0.85 / 1.0 / 1.15.

CALIBRATION, inside tom8 (checklist words with tokens in >= 2 recordings):
  a query must retrieve ANOTHER checklist token of the same word from another recording
  (precision@1 vs chance), giving the score level of a TRUE RETAKE.
TEST, against SS:
  for each query, the best SS window that is NOT the Speechify take itself (waveform NCC
  against the query <= 0.6). Classes:
    COMMON   checklist words with zipf >= 5.0   -> any English script contains them: positive
    RARE     checklist words with zipf <= 3.8   -> only Speechify's script should: the question
    REVERSED every query time-reversed           -> chance level
  RARE scoring like COMMON = Speechify-script words recur in the non-Speechify audio
  (retakes of the same script). RARE at the REVERSED level = no sign of the script there.

    python -I qbe_retake_test.py
"""
import collections
import json
import sys
import wave
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from scipy.fft import dct
from wordfreq import zipf_frequency

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tom_overlap as T  # noqa: E402
import tom_overlap_xpack as X  # noqa: E402

SR, NFFT, WINL, HOP, NMEL = 8000, 256, 200, 80, 24
MIN_MS, SCALES = 350, (0.85, 1.0, 1.15)


def mel_fb():
    f = np.linspace(0, SR / 2, NFFT // 2 + 1)
    mel = lambda x: 2595 * np.log10(1 + x / 700)
    imel = lambda m: 700 * (10 ** (m / 2595) - 1)
    pts = imel(np.linspace(mel(60), mel(3800), NMEL + 2))
    fb = np.zeros((NMEL, len(f)))
    for i in range(NMEL):
        a, b, c = pts[i:i + 3]
        fb[i] = np.clip(np.minimum((f - a) / (b - a), (c - f) / (c - b)), 0, None)
    return torch.tensor(fb, dtype=torch.float32, device="cuda")


FB = None


def mfcc(x):
    """x: 1-D float array (8 kHz) -> (12, frames) torch on cuda."""
    global FB
    if FB is None:
        FB = mel_fb()
    t = torch.as_tensor(np.asarray(x, np.float32), device="cuda")
    # frame k covers samples [k*HOP, k*HOP + WINL); chunk by FRAMES so boundaries lose nothing
    nfr = (len(t) - WINL) // HOP + 1
    out, CH = [], 100_000
    for k0 in range(0, nfr, CH):
        k1 = min(nfr, k0 + CH)
        seg = t[k0 * HOP:(k1 - 1) * HOP + WINL]
        st = torch.stft(seg, NFFT, HOP, WINL, torch.hann_window(WINL, device="cuda"),
                        center=False, return_complex=True)
        out.append(st.abs() ** 2)
    ps = torch.cat(out, 1)
    lm = torch.log(FB @ ps + 1e-3)
    c = torch.tensor(dct(np.eye(NMEL), type=2, norm="ortho", axis=0)[1:13], dtype=torch.float32, device="cuda")
    return c @ lm


def search(feat, q, topk=8, nms=30):
    """Cosine of mean-removed q (12,L) against every window of feat (12,N). -> list of (score, frame)."""
    best = []
    for s in SCALES:
        L = max(8, int(round(q.shape[1] * s)))
        qs = F.interpolate(q.unsqueeze(0), size=L, mode="linear", align_corners=True)[0]
        qs = qs - qs.mean(1, keepdim=True)
        qn = qs.norm()
        num = F.conv1d(feat.unsqueeze(0), qs.unsqueeze(0))[0, 0]           # sum q*x
        c1 = F.pad(feat.cumsum(1), (1, 0))
        c2 = F.pad((feat * feat).cumsum(1), (1, 0))
        sx = c1[:, L:] - c1[:, :-L]
        sxx = c2[:, L:] - c2[:, :-L]
        den = torch.sqrt((sxx - sx * sx / L).sum(0).clamp_min(1e-6)) * qn
        sc = num / den[:num.numel()]
        v, i = torch.topk(sc, min(400, sc.numel()))
        best += [(float(a), int(b), L) for a, b in zip(v.cpu(), i.cpu())]
    best.sort(key=lambda x: -x[0])
    out = []
    for v, i, L in best:
        if all(abs(i - j) > nms for _, j, _ in out):
            out.append((v, i, L))
        if len(out) >= topk:
            break
    return out


def ncc_local(a, b):
    """Max NCC of shorter b inside a (both 8 kHz)."""
    if len(a) < len(b):
        a, b = b, a
    b = b - b.mean()
    num = np.correlate(a.astype(np.float64), b, mode="valid")
    c1 = np.r_[0, np.cumsum(a, dtype=np.float64)]
    c2 = np.r_[0, np.cumsum(a.astype(np.float64) ** 2)]
    L = len(b)
    e = c2[L:] - c2[:-L]
    m = (c1[L:] - c1[:-L]) / L
    den = np.sqrt(np.maximum(e - L * m * m, 1e-9)) * (np.linalg.norm(b) or 1e-9)
    return float(np.max(num / den))


SUB, SUB_STEP, SUB_THR = 800, 160, 0.75
EXCLUDED = collections.Counter()


def same_take(seg, tok):
    """Same physical take if ANY 100 ms slice of the token waveform-locks inside seg.

    A whole-token NCC is not enough: SS stores audio in ~0.4-0.5 s pieces, so a word
    can straddle a cut and score low even when it is the very same recording (the
    first run let Speechify's own `belgrade` through at < 0.6 this way)."""
    if len(tok) < SUB:
        return len(seg) >= len(tok) and ncc_local(seg, tok) > SUB_THR
    for s in range(0, len(tok) - SUB + 1, SUB_STEP):
        if len(seg) >= SUB and ncc_local(seg, tok[s:s + SUB]) > SUB_THR:
            return True
    return False


def main():
    rng = np.random.default_rng(61)
    words = [w for w in json.loads((T.OUT / "ckls_words.json").read_text())
             if w["group"] == "_WORD_" and w["abs8k_start"] is not None and w["end_ms"] - w["start_ms"] >= MIN_MS]
    S = T.Search(1600)
    tom8 = np.asarray(S.s.full, np.float32)
    ss8 = np.asarray(X.corpus8k("ss_tom", T.SS_WAV), np.float32)
    ft = mfcc(tom8)
    ft = ft - ft.mean(1, keepdim=True)
    fs = mfcc(ss8)
    fs = fs - fs.mean(1, keepdim=True)
    fr = lambda s8: s8 // HOP                          # sample -> frame
    print(f"features: tom8 {ft.shape[1]:,} frames, SS {fs.shape[1]:,} frames; {len(words)} checklist tokens >= {MIN_MS} ms")

    def query(w):
        a, b = fr(w["abs8k_start"]), fr(w["abs8k_end"])
        return ft[:, a:b] - ft[:, a:b].mean(1, keepdim=True)

    # ---- calibration inside tom8
    by = collections.defaultdict(list)
    for w in words:
        by[w["text"]].append(w)
    multi = [w for t, ws in by.items() if len({x["rec"] for x in ws}) >= 2 for w in ws]
    rng.shuffle(multi)
    multi = multi[:300]
    span = {t: [(fr(x["abs8k_start"]), fr(x["abs8k_end"]), x["rec"]) for x in ws] for t, ws in by.items()}
    allspans = [(fr(x["abs8k_start"]), fr(x["abs8k_end"]), x["text"]) for x in words]
    rec_of = lambda fidx: S.rec(np.array([fidx * HOP]))[0]
    hit, cal_true, cal_rev, chance = 0, [], [], []
    for w in multi:
        q = query(w)
        own = S.rec(np.array([w["abs8k_start"]]))[0]
        res = [r for r in search(ft, q, topk=12) if rec_of(r[1]) != own]
        rres = [r for r in search(ft, q.flip(1), topk=12) if rec_of(r[1]) != own]
        if not res:
            continue
        v, i, L = res[0]
        same = any(a - 10 <= i + L // 2 <= b + 10 for a, b, rr in span[w["text"]] if rr != w["rec"])
        hit += same
        (cal_true if same else chance).append(v)
        if rres:
            cal_rev.append(rres[0][0])
    n = len(multi)
    # chance that a random labelled-word landing is the same word: share of that word among labelled time
    print(f"\nCALIBRATION in tom8 ({n} queries, words with tokens in >= 2 recordings):")
    print(f"  best match (other recording) IS another checklist take of the same word: {hit}/{n} = {hit / n:.1%}")
    print(f"  score when it is: p50 {np.median(cal_true):.3f}   when not: p50 {np.median(chance):.3f}   "
          f"reversed query best: p50 {np.median(cal_rev):.3f} p95 {np.quantile(cal_rev, .95):.3f}")

    # ---- test against SS
    def ss_best(w, rev=False):
        q = query(w)
        q = q.flip(1) if rev else q
        a8, b8 = w["abs8k_start"], w["abs8k_end"]
        tok = tom8[a8:b8]
        for v, i, L in search(fs, q, topk=10):
            s8 = i * HOP
            seg = ss8[max(0, s8 - 400):s8 + L * HOP + 400]
            if not rev and same_take(seg, tok):
                EXCLUDED[w["text"]] += 1
                continue                               # the Speechify take itself, not a retake
            return v, s8, L
        return None

    cls = {"COMMON": [w for w in words if zipf_frequency(w["text"], "en") >= 5.0],
           "RARE": [w for w in words if zipf_frequency(w["text"], "en") <= 3.8]}
    for k in cls:                                        # one token per word type, capped
        seen, keep = set(), []
        for w in rng.permutation(len(cls[k])):
            ww = cls[k][int(w)]
            if ww["text"] not in seen:
                seen.add(ww["text"])
                keep.append(ww)
        cls[k] = keep[:150]
    out = {"calibration": {"precision_at_1": hit / n, "n": n, "true_p50": float(np.median(cal_true)),
                           "rev_p50": float(np.median(cal_rev)), "rev_p95": float(np.quantile(cal_rev, .95))}}
    rev_ss = []
    res_cls = {}
    for k, ws in cls.items():
        sc = []
        for w in ws:
            b = ss_best(w)
            r = ss_best(w, rev=True)
            if b:
                sc.append((w["text"], b[0], b[1], b[2], w))
            if r:
                rev_ss.append(r[0])
        res_cls[k] = sc
    rthr = float(np.quantile(rev_ss, 0.95))
    print(f"\nTEST against SS 2004 (best window that is NOT the Speechify take; reversed-query p95 = {rthr:.3f}):")
    for k, sc in res_cls.items():
        v = np.array([x[1] for x in sc])
        print(f"  {k:7} words {len(sc):4d}  score p50 {np.median(v):.3f}  p90 {np.quantile(v, .9):.3f}  "
              f"above reversed p95: {np.mean(v > rthr):.1%}   above tom8 true-retake p50 "
              f"({np.median(cal_true):.3f}): {np.mean(v > np.median(cal_true)):.1%}")
        out[k] = {"n": len(sc), "p50": float(np.median(v)), "above_rev95": float(np.mean(v > rthr)),
                  "above_true50": float(np.mean(v > np.median(cal_true)))}
    out["reversed_p95"] = rthr
    out["excluded_same_take"] = dict(EXCLUDED)
    print(f"  same-take candidates excluded: {sum(EXCLUDED.values())} across {len(EXCLUDED)} words "
          f"(e.g. {', '.join(list(EXCLUDED)[:10])})")

    outd = T.OUT / "qbe_listen"
    outd.mkdir(exist_ok=True)
    top = sorted(res_cls["RARE"], key=lambda x: -x[1])[:16]
    for text, v, s8, L, w in top:
        for tag, x in (("spfy", tom8[w["abs8k_start"] - 400:w["abs8k_end"] + 400]),
                       ("ss", ss8[max(0, s8 - 400):s8 + L * HOP + 400])):
            with wave.open(str(outd / f"{text}_{tag}.wav"), "wb") as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(8000)
                f.writeframes(np.clip(x, -32768, 32767).astype("<i2").tobytes())
    out["rare_top"] = [{"word": t, "score": v, "ss8": s8} for t, v, s8, L, w in top]
    print("  strongest RARE matches:", ", ".join(f"{t} {v:.3f}" for t, v, *_ in top[:12]))
    (T.OUT / "qbe_retake.json").write_text(json.dumps(out, indent=1))
    print(f"\nlistening pairs (word_spfy.wav vs word_ss.wav) in {outd}")


if __name__ == "__main__":
    main()
