"""Does ScanSoft 2004 Tom contain RETAKES of words specific to Speechify's recording script?

The SS label stream (us_tom_full.dat +9, pos order, labels at pos*2.205 - 2370 @22k,
calibrated by ss_label_check.py) is read as phones. Words are fuzzy-matched in it:

  TARGET   rare checklist words (ckls _WORD_, wordfreq zipf <= ZIPF_MAX, >= MIN_PH phones)
  CONTROL  equally rare CMUdict words NOT in the checklist, matched on phone count and zipf
  SHUFFLE  each target's phone string permuted: same phones, no word

Pronunciations for all three come from CMUdict through one ARPAbet -> SS-SAMPA map, so the
matcher is identical across classes. Every hit's audio (200 ms) is then searched against
tom8: LOCKED = the Speechify take itself; UNLOCKED = some other take of the same sounds.

Under "SS-only audio holds other takes of Speechify's script", TARGET's UNLOCKED hits per
word must exceed CONTROL's and SHUFFLE's. If they all sit at the same chance level, there
is no sign of the Speechify script outside the shared takes.

Label sensitivity is calibrated on checklist tokens whose Speechify take IS in SS: does the
matcher find the word at the SS place the waveform lock puts it?

    python -I ss_retake_test.py
"""
import collections
import json
import sys
import wave
from pathlib import Path

import numpy as np
import regex
from nltk.corpus import cmudict
from wordfreq import zipf_frequency

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tom_overlap as T  # noqa: E402
import tom_overlap_xpack as X  # noqa: E402

LABEL_OFF_22K = -2370
ZIPF_MAX, ZIPF_MIN, MIN_PH = 3.3, 1.0, 5
N_CTRL, N_SHUF = 3, 3
W = 1600

A2S = {"AA": "a", "AE": "\x91", "AH": "^", "AO": "A", "AW": "@", "AY": "Y", "B": "b", "CH": "C",
       "D": "d", "DH": "D", "EH": "E", "ER": "e", "EY": "J", "F": "f", "G": "g", "HH": "h",
       "IH": "I", "IY": "i", "JH": "G", "K": "k", "L": "l", "M": "m", "N": "n", "NG": "N",
       "OW": "O", "OY": "o", "P": "p", "R": "r", "S": "s", "SH": "S", "T": "t", "TH": "T",
       "UH": "U", "UW": "u", "V": "v", "W": "w", "Y": "j", "Z": "z", "ZH": "Z"}


def sampa(pron):
    out = []
    for i, p in enumerate(pron):
        base, st = p.rstrip("012"), p[-1] if p[-1].isdigit() else ""
        if base == "AH" and st == "0":
            out.append("$")
        elif base == "IH" and st == "0":
            out.append("\x8b")
        else:
            out.append(A2S[base])
    s = "".join(out)
    if s.endswith("$l"):
        s = s[:-2] + "L"
    return s


def ss_stream():
    raw = np.memmap(T.SS_USELD, dtype=np.uint8, mode="r", offset=T.REC_OFF, shape=(T.N_UNITS, 16))
    pos = (raw[:, :4].copy().view("<u4").ravel() & 0x7FFFFFFF).astype(np.int64)
    ph = raw[:, 9].copy()
    o = np.argsort(pos, kind="stable")
    pos, ph = pos[o], ph[o]
    chars, starts = [], []
    prev = None
    for p, c in zip(pos, ph):
        ch = chr(c)
        if ch == "q" or ch == prev:
            prev = ch if ch != "q" else prev
            continue
        chars.append(ch)
        starts.append(int(round(p * T.TICK_TO_22K)) + LABEL_OFF_22K)
        prev = ch
    return "".join(chars), np.array(starts, np.int64)


def k_for(n):
    return 2 if n >= 7 else 1


def find_all(text, q):
    pat = regex.compile("(?:%s){e<=%d}" % (regex.escape(q), k_for(len(q))))
    return [m.start() for m in pat.finditer(text, overlapped=False)]


def main():
    rng = np.random.default_rng(53)
    cmu = cmudict.dict()
    words = [w for w in json.loads((T.OUT / "ckls_words.json").read_text()) if w["group"] == "_WORD_"]
    vocab = sorted({w["text"] for w in words})
    vocab_set = set(vocab)

    def entry(w):
        if w not in cmu or not w.isalpha():
            return None
        s = sampa(cmu[w][0])
        return s if len(s) >= MIN_PH else None

    targets = {}
    for w in vocab:
        z = zipf_frequency(w, "en")
        s = entry(w)
        if s and ZIPF_MIN <= z <= ZIPF_MAX:
            targets[w] = (s, z)
    pool = collections.defaultdict(list)
    for w in cmu:
        if w in vocab_set or not w.isalpha():
            continue
        z = zipf_frequency(w, "en")
        if not (ZIPF_MIN <= z <= ZIPF_MAX):
            continue
        s = entry(w)
        if s:
            pool[(len(s), round(z * 2) / 2)].append((w, s, z))
    controls = {}
    for w, (s, z) in targets.items():
        cands = pool.get((len(s), round(z * 2) / 2), [])
        for j in rng.choice(len(cands), size=min(N_CTRL, len(cands)), replace=False) if cands else []:
            cw, cs, cz = cands[int(j)]
            controls[cw] = (cs, cz)
    shuffles = {}
    for w, (s, z) in targets.items():
        for i in range(N_SHUF):
            p = "".join(rng.permutation(list(s)))
            if p != s:
                shuffles[f"{w}~{i}"] = (p, z)
    print(f"targets {len(targets)}  controls {len(controls)}  shuffles {len(shuffles)}")
    print("  e.g. targets:", ", ".join(f"{w}={s!r}" for w, (s, _) in list(targets.items())[:10]))

    text, starts = ss_stream()
    print(f"SS label stream: {len(text):,} phones")

    hits = {}
    for cls, d in (("TARGET", targets), ("CONTROL", controls), ("SHUFFLE", shuffles)):
        for w, (s, _) in d.items():
            hits[(cls, w)] = find_all(text, s)
    n_hits = {c: sum(len(v) for (cc, _), v in hits.items() if cc == c) for c in ("TARGET", "CONTROL", "SHUFFLE")}
    print("raw label hits:", n_hits)

    # waveform check of every hit against tom8: is it the Speechify take?
    S = T.Search(W)
    ss22 = T.wav_i16(T.SS_WAV)
    flat = [(k, i) for k, v in hits.items() for i in v]
    probes = [T.cut8k(ss22, max(0, int(starts[i]) - 2205 + 1500), W) for _, i in flat]
    res = S.run(probes) if probes else {"v": np.array([])}
    thr = json.loads((T.OUT / f"summary_W{W}.json").read_text())["threshold_p999_FTAKE"]
    locked = res["v"] > thr
    per = collections.defaultdict(lambda: [0, 0])
    for (k, i), lk in zip(flat, locked):
        per[k][0 if lk else 1] += 1

    def rate(cls, d):
        u = np.array([per[(cls, w)][1] for w in d])
        lk = np.array([per[(cls, w)][0] for w in d])
        bs = [rng.choice(u, len(u)).mean() for _ in range(2000)]
        return u.mean(), np.quantile(bs, [.025, .975]), lk.sum(), u.sum(), float(np.mean(u > 0))

    print(f"\n{'class':8} {'words':>6} {'unlocked hits/word':>19} {'95% CI':>15} {'words w/ >=1':>12} "
          f"{'locked (Speechify take)':>24}")
    summ = {}
    for cls, d in (("TARGET", targets), ("CONTROL", controls), ("SHUFFLE", shuffles)):
        m, ci, lk, u, share = rate(cls, d)
        summ[cls] = {"words": len(d), "unlocked_per_word": float(m), "ci95": [float(ci[0]), float(ci[1])],
                     "locked_total": int(lk), "unlocked_total": int(u), "share_words_with_unlocked": share}
        print(f"{cls:8} {len(d):6d} {m:19.3f} {ci[0]:7.3f}..{ci[1]:<7.3f} {share:12.1%} {lk:24d}")

    # sensitivity: covered checklist tokens -> their SS place via waveform -> does the matcher find the word?
    cov = json.loads((T.OUT / "tom16_coverage_perrec_ckls.json").read_text())
    tom8 = np.asarray(S.s.full, np.float32)
    toks = []
    for w in words:
        c = cov.get(w["rec"])
        if not c or w["abs8k_start"] is None:
            continue
        a, b = w["start_ms"] // 20, -(-w["end_ms"] // 20)
        sp = np.array(c["speech"][a:b], bool)
        ei = (np.array(c["ss"][a:b], bool))
        s = entry(w["text"])
        if s and sp.any() and ei[sp].mean() >= 0.8:
            mid = (w["abs8k_start"] + w["abs8k_end"]) // 2
            toks.append((w["text"], s, mid))
    H = X.ArraySearch(X.corpus8k("ss_tom", T.SS_WAV), W, "ss")
    pr = [tom8[m - W // 2:m + W // 2].copy() for _, _, m in toks]
    r = H.run(pr)
    thr_ss = json.loads((T.OUT / "xpack_W1600.json").read_text())["thresholds"]["ss"]
    found = tested = 0
    for (word, s, _), v, p, pol in zip(toks, r["v"], r["p"], r["pol"]):
        if v <= thr_ss:
            continue
        tested += 1
        c22 = int(p * 441 / 160) + int(W // 2 * 441 / 160)
        idx = np.where(np.abs(starts - c22) < 22050 * 0.35)[0]
        if len(idx) == 0:
            continue
        seg = text[max(0, idx[0] - 2):idx[-1] + 3]
        pat = regex.compile("(?:%s){e<=%d}" % (regex.escape(s), k_for(len(s))))
        found += bool(pat.search(seg))
    sens = found / tested if tested else float("nan")
    print(f"\nlabel-matcher sensitivity on known Speechify takes inside SS: {found}/{tested} = {sens:.1%}")
    summ["sensitivity"] = {"found": found, "tested": tested}

    # listening pairs: strongest TARGET unlocked hits next to a tom8 token of the same word
    outd = T.OUT / "retake_listen"
    outd.mkdir(exist_ok=True)
    tokmid = collections.defaultdict(list)
    for w in words:
        if w["abs8k_start"] is not None:
            tokmid[w["text"]].append((w["abs8k_start"], w["abs8k_end"]))
    listing = []
    tgt_unl = [(k, i, v) for (k, i), lk, v in zip(flat, locked, res["v"]) if k[0] == "TARGET" and not lk]
    seen = set()
    for (cls, w), i, v in tgt_unl:
        if w in seen or not tokmid.get(w):
            continue
        seen.add(w)
        a8, b8 = tokmid[w][0]
        sp = tom8[max(0, a8 - 800):b8 + 800]
        ss = T.cut8k(ss22, max(0, int(starts[i]) - 1764 - 2205), int((b8 - a8) + 1600 + 800))
        for tag, x in (("spfy", sp), ("ss", ss)):
            with wave.open(str(outd / f"{w}_{tag}.wav"), "wb") as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(8000)
                f.writeframes(np.clip(x, -32768, 32767).astype("<i2").tobytes())
        listing.append({"word": w, "ss_22k": int(starts[i]), "matched": text[i:i + len(targets[w][0]) + 2],
                        "tom8_ncc": float(v)})
        if len(listing) >= 20:
            break
    summ["listen"] = listing
    (T.OUT / "retake_test.json").write_text(json.dumps(summ, indent=1))
    print(f"\n{len(listing)} listening pairs in {outd}:", ", ".join(x["word"] for x in listing))


if __name__ == "__main__":
    main()
