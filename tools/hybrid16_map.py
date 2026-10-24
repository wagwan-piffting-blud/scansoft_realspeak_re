"""Full coverage map for the 16 kHz hybrid: every tom8 recording, every locked run in SS / RS.

Same seed-and-extend as tom16_coverage.py, at full scale:
  - seeds: every 200 ms tom8 window (100 ms hop, RMS > 200), global GPU search per pack
  - extend: per recording in a process pool; a hit whose seed cell is already locked at the
    same offset (+-2 ms) is skipped, so one take is traced once
  - local lock threshold is FIXED at the p99 reversed-window null measured by
    tom16_coverage.py --from-ckls (SS 0.6129, RS 0.6282)

Output: C:\\tmp\\hybrid16\\runs.json  {rec_name: [{pack, pol, D8, c0, c1, v}]}, D8 = 8 kHz
corpus index of the recording's sample 0, cells are 20 ms.

    python -I hybrid16_map.py
"""
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tom_overlap as T  # noqa: E402
import tom_overlap_runs as R  # noqa: E402
import tom_overlap_xpack as X  # noqa: E402
import tom16_coverage as C  # noqa: E402
import hybrid16_demo as HD  # noqa: E402

OUT = Path(r"C:\tmp\hybrid16")
TOM8_NPY = OUT / "tom8_f32.npy"
LTHR = {"ss": 0.6129, "rs": 0.6282}

_G = {}


def _init(pack):
    _G["tom8"] = np.load(TOM8_NPY, mmap_mode="r")
    _G["hay"] = np.load(X.CACHE / f"{pack}_tom_8k.f32.npy", mmap_mode="r")
    _G["pack"] = pack


def extend_rec(job):
    """job = (rec, s0, s1, [(s, p, pol), ...]) -> list of (pack, k, D8, v, pol)."""
    r, s0, s1, hits = job
    tom8, hay, pack = _G["tom8"], _G["hay"], _G["pack"]
    n = (s1 - s0) // C.STEP
    lthr = LTHR[pack]
    done = {}                                   # cell -> set of offsets already locked
    out = []
    for s, p, pol in hits:
        c = (s + C.WS // 2 - C.WIN // 2 - s0) // C.STEP
        off0 = p + C.WS // 2 - C.WIN // 2 - (s + C.WS // 2 - C.WIN // 2)
        if any(abs(o - off0) <= R.LAG_TOL for o in done.get(c, ())):
            continue
        v = np.full(n, np.nan)
        lag = np.zeros(n, np.int64)
        offs = np.zeros(n, np.int64)
        for k in range(n):
            xs = s0 + k * C.STEP
            if xs + C.WIN > s1:
                continue
            y = xs + off0
            vv, lg = R.local_ncc(hay, y, np.asarray(tom8[xs:xs + C.WIN]) * pol)
            v[k], lag[k], offs[k] = vv, lg, off0 + lg
        c = int(np.clip(c, 0, n - 1))
        lock = (np.nan_to_num(v, nan=-1) > lthr) & (np.abs(lag - lag[c]) <= R.LAG_TOL)
        if not lock[c]:
            continue
        for k in np.where(C.grow(lock, c))[0]:
            if lock[k]:
                out.append((pack, int(k), int(offs[k]) + s0, float(v[k]), int(pol)))
                done.setdefault(int(k), set()).add(int(offs[k]))
    return r, out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    thr = json.loads((T.OUT / "xpack_W1600.json").read_text())["thresholds"]
    t8 = T.Search(C.WS)
    tom8 = np.asarray(t8.s.full, np.float32)
    if not TOM8_NPY.exists():
        np.save(TOM8_NPY, tom8)
    offs, names = np.array(t8.offs), list(t8.names)
    ends = np.r_[offs[1:], len(tom8)]
    nrec = len(names)
    seeds, sm = [], []
    for r in range(nrec):
        s0, s1 = int(offs[r]), int(ends[r])
        for s in range(s0, s1 - C.WS, C.HOP_S):
            x = tom8[s:s + C.WS]
            if np.sqrt(np.mean(x.astype(np.float64) ** 2)) > 200:
                seeds.append(s)
                sm.append(r)
    sm = np.array(sm)
    print(f"{nrec} recordings, {len(seeds)} seeds", flush=True)
    del t8

    locks = {r: [] for r in range(nrec)}
    for pack, wav in (("ss", T.SS_WAV), ("rs", T.RS_WAV)):
        hp = OUT / f"hits_{pack}.npz"
        if hp.exists():
            z = np.load(hp)
            v, p, pol = z["v"], z["p"], z["pol"]
        else:
            t0 = time.time()
            hay = X.corpus8k(f"{pack}_tom", wav)
            H = X.ArraySearch(hay, C.WS, pack)
            vs, ps, pols = [], [], []
            for i in tqdm(range(0, len(seeds), 4096), desc=f"seed {pack}"):
                res = H.run([tom8[s:s + C.WS] for s in seeds[i:i + 4096]])
                vs.append(res["v"])
                ps.append(res["p"])
                pols.append(res["pol"])
            v, p, pol = np.concatenate(vs), np.concatenate(ps), np.concatenate(pols)
            np.savez(hp, v=v, p=p, pol=pol)
            del H
            print(f"{pack}: seed search {time.time() - t0:.0f}s", flush=True)
        hit = np.where(v > thr[pack])[0]
        print(f"{pack}: {len(hit)} / {len(seeds)} seeds hit (thr {thr[pack]:.4f})", flush=True)
        by = {}
        for i in hit[np.argsort(-v[hit])]:
            by.setdefault(int(sm[i]), []).append((seeds[i], int(p[i]), int(pol[i])))
        jobs = [(r, int(offs[r]), int(ends[r]), h) for r, h in by.items()]
        with ProcessPoolExecutor(max_workers=os.cpu_count() - 1, initializer=_init, initargs=(pack,)) as ex:
            for r, out in tqdm(ex.map(extend_rec, jobs, chunksize=8), total=len(jobs), desc=f"extend {pack}"):
                locks[r] += out

    runs, cov = {}, []
    for r in range(nrec):
        ncell = (int(ends[r]) - int(offs[r])) // C.STEP
        u = HD.runs_from_locks(locks[r], ncell)
        if u:
            runs[names[r]] = u
        m = np.zeros(ncell, bool)
        for x in u:
            m[x["c0"]:x["c1"]] = True
        cov.append((ncell, int(m.sum())))
    (OUT / "runs.json").write_text(json.dumps(runs))
    tot = sum(a for a, _ in cov)
    got = sum(b for _, b in cov)
    print(f"recordings with runs: {len(runs)}/{nrec}; cells covered {got}/{tot} = {got / tot:.1%} "
          f"({got * 0.02 / 60:.1f} min of {tot * 0.02 / 60:.1f})", flush=True)


if __name__ == "__main__":
    main()
