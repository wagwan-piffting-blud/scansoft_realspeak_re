"""ckls words x 22 kHz coverage: which checklist words did ScanSoft / RealSpeak keep?

Inputs:
  C:\\tmp\\tom_overlap\\ckls_words.json                    (vin_ckls.py)
  C:\\tmp\\tom_overlap\\tom16_coverage_perrec_ckls.json    (tom16_coverage.py --from-ckls --tag _ckls)
Per _WORD_ token: share of its speech frames (20 ms grid) covered by SS, RS, either.
Also: are coverage-run edges aligned to word boundaries (vs random positions)?

    python -I ckls_coverage.py
"""
import collections
import json
import re

import numpy as np

OUT = r"C:\tmp\tom_overlap"
STEP_MS = 20


def runs_edges(mask):
    d = np.diff(np.r_[0, mask.astype(int), 0])
    return np.where(d != 0)[0]                       # frame indices where coverage switches


def main():
    words = [w for w in json.load(open(fr"{OUT}\ckls_words.json")) if w["group"] == "_WORD_"]
    cov = json.load(open(fr"{OUT}\tom16_coverage_perrec_ckls.json"))
    rng = np.random.default_rng(5)
    toks, edge_d, null_d = [], [], []
    by_rec = collections.defaultdict(list)
    for w in words:
        if w["rec"] in cov:
            by_rec[w["rec"]].append(w)
    for rec, ws in by_rec.items():
        c = cov[rec]
        sp = np.array(c["speech"], bool)
        ss, rs = np.array(c["ss"], bool), np.array(c["rs"], bool)
        ei = ss | rs
        bounds = []
        for w in ws:
            a, b = w["start_ms"] // STEP_MS, -(-w["end_ms"] // STEP_MS)
            m = np.zeros(len(sp), bool)
            m[a:b] = True
            m &= sp
            bounds += [a, b]
            if m.sum() == 0:
                continue
            toks.append({"text": w["text"], "rec": rec, "fam": re.sub(r"\d*_\d+$", "", rec),
                         "either": float(ei[m].mean()), "ss": float(ss[m].mean()), "rs": float(rs[m].mean()),
                         "ms": w["end_ms"] - w["start_ms"]})
        # edge alignment, only for recordings with partial coverage
        if 0 < ei[sp].mean() < 1 and bounds:
            bnd = np.array(sorted(set(bounds)))
            for e in runs_edges(ei):
                edge_d.append(np.min(np.abs(bnd - e)) * STEP_MS)
            for e in rng.choice(np.where(sp)[0], size=len(runs_edges(ei)), replace=True):
                null_d.append(np.min(np.abs(bnd - e)) * STEP_MS)

    e = np.array([t["either"] for t in toks])
    print(f"ckls _WORD_ tokens in mapped recordings: {len(toks)} ({len({t['text'] for t in toks})} unique) "
          f"in {len(by_rec)} recordings")
    print(f"word coverage (either): full >=80% {np.mean(e >= .8):.1%}   partial {np.mean((e > .2) & (e < .8)):.1%}   "
          f"none <=20% {np.mean(e <= .2):.1%}   mean {e.mean():.1%}")
    print(f"  SS mean {np.mean([t['ss'] for t in toks]):.1%}   RS mean {np.mean([t['rs'] for t in toks]):.1%}")
    if edge_d:
        ed, nd = np.array(edge_d), np.array(null_d)
        print(f"coverage-edge distance to nearest checklist word boundary: median {np.median(ed):.0f} ms "
              f"(random-position null {np.median(nd):.0f} ms); within 40 ms: {np.mean(ed <= 40):.0%} vs null "
              f"{np.mean(nd <= 40):.0%}   (n={len(ed)})")
    fam = collections.defaultdict(list)
    for t in toks:
        fam[t["fam"]].append(t["either"])
    print("\nby prompt family (mean word coverage, tokens):")
    for f, v in sorted(fam.items(), key=lambda x: -len(x[1])):
        print(f"  {f:10} {np.mean(v):6.1%}  n={len(v)}")
    wd = collections.defaultdict(list)
    for t in toks:
        wd[t["text"]].append(t["either"])
    rep = {k: v for k, v in wd.items() if len(v) >= 4}
    srt = sorted(rep.items(), key=lambda x: np.mean(x[1]))
    print(f"\nwords with >=4 tokens: {len(rep)}")
    print("  least kept:", ", ".join(f"{k} {np.mean(v):.0%}/{len(v)}" for k, v in srt[:12]))
    print("  most kept: ", ", ".join(f"{k} {np.mean(v):.0%}/{len(v)}" for k, v in srt[-12:][::-1]))
    # is keeping a property of the WORD, or of the recording it sits in?
    if rep:
        within = np.mean([np.var(v) for v in rep.values()])
        allv = np.var([x for v in rep.values() for x in v])
        print(f"  share of coverage variance that is BETWEEN words: {1 - within / allv:.0%} "
              f"(0% = keeping ignores which word it is)")
    json.dump({"tokens": toks}, open(fr"{OUT}\ckls_coverage.json", "w"))


if __name__ == "__main__":
    main()
