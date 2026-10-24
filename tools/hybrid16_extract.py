"""Pull every verified real 3.4-8 kHz band out of SS / RS onto tom8's 16 kHz axis.

Input  C:\\tmp\\hybrid16\\runs.json (hybrid16_map.py)
Output C:\\tmp\\hybrid16\\hi_real.f16.npy   2 x len(tom8) samples, same layout as tom16.vdb data
       C:\\tmp\\hybrid16\\cell_ok.u8.npy    one byte per 20 ms tom8 cell: 0 none, 1 SS, 2 RS
       C:\\tmp\\hybrid16\\extract.json      per-recording gains and coverage

Per recording, runs are realigned and verified exactly as in hybrid16_demo.real_high. The
gain is then unified per pack (length-weighted median of the runs) so neighbouring pieces
do not step in level.

    python -I hybrid16_extract.py
"""
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from scipy import signal as sg
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tom_overlap as T  # noqa: E402
import tom16_coverage as C  # noqa: E402
import hybrid16_demo as HD  # noqa: E402

OUT = Path(r"C:\tmp\hybrid16")
_G = {}


def _init():
    _G["tom8"] = np.load(OUT / "tom8_f32.npy", mmap_mode="r")
    _G["hay"] = {"ss": T.wav_i16(T.SS_WAV), "rs": T.wav_i16(T.RS_WAV)}


def work(job):
    name, s0, s1, runs = job
    x8 = np.asarray(_G["tom8"][s0:s1], np.float64)
    t8_16 = sg.resample_poly(x8, 2, 1)
    t8_22 = sg.resample_poly(x8, 441, 160)
    n16 = len(t8_16)
    ncell = n16 // HD.CELL16
    rms8 = np.sqrt(np.mean(x8[:ncell * C.STEP].reshape(ncell, C.STEP) ** 2, 1))
    got = []
    for u in runs:
        g = HD.real_high(u, _G["hay"][u["pack"]], t8_22, t8_16)
        if g is not None:
            got.append((u, *g))
    hi = np.zeros(n16, np.float32)
    cell = np.zeros(ncell, np.uint8)
    gains = {}
    for pack in ("ss", "rs"):
        gs = [(i["gain_db"], u["c1"] - u["c0"]) for u, _, _, i in got if u["pack"] == pack]
        if gs:
            v, w = np.array(gs).T
            o = np.argsort(v)
            gains[pack] = float(v[o][np.searchsorted(np.cumsum(w[o]), w.sum() / 2)])
    for u, h16, fn, info in got:
        ok = (fn >= HD.FRAME_NCC) | (rms8[u["c0"]:u["c1"]] < 200)
        scale = 10 ** ((gains[u["pack"]] - info["gain_db"]) / 20)
        a = u["c0"] * HD.CELL16
        hi[a:a + len(h16)] = h16 * scale
        cell[u["c0"]:u["c1"]][ok] = 1 if u["pack"] == "ss" else 2
    return name, s0, hi, cell, gains, [i["ncc22"] for *_, i in got]


def main():
    runs = json.loads((OUT / "runs.json").read_text())
    tom8 = np.load(OUT / "tom8_f32.npy", mmap_mode="r")
    entries = T.vdb_fast.VdbSearcher(T.TOM8, probe_len=320).entries
    offs = np.array([e[0] for e in entries], np.int64)
    names = [e[1] for e in entries]
    ends = np.r_[offs[1:], len(tom8)]
    hi_all = np.lib.format.open_memmap(OUT / "hi_real.f16.npy", "w+", np.float16, (2 * len(tom8),))
    cell_all = np.zeros(len(tom8) // C.STEP + 1, np.uint8)
    jobs = [(n, int(offs[i]), int(ends[i]), runs[n]) for i, n in enumerate(names) if n in runs]
    meta = {}
    with ProcessPoolExecutor(max_workers=os.cpu_count() - 1, initializer=_init) as ex:
        for name, s0, hi, cell, gains, n22 in tqdm(ex.map(work, jobs, chunksize=4), total=len(jobs)):
            hi_all[2 * s0:2 * s0 + len(hi)] = np.clip(hi, -65000, 65000).astype(np.float16)
            c0 = s0 // C.STEP
            cell_all[c0:c0 + len(cell)] = np.maximum(cell_all[c0:c0 + len(cell)], cell)
            meta[name] = {"gains": gains, "cells_ok": int((cell > 0).sum()), "cells": len(cell),
                          "ncc22_p50": float(np.median(n22)) if n22 else None}
    hi_all.flush()
    np.save(OUT / "cell_ok.u8.npy", cell_all)
    (OUT / "extract.json").write_text(json.dumps(meta))
    g = {p: [m["gains"][p] for m in meta.values() if p in m["gains"]] for p in ("ss", "rs")}
    tot = (len(tom8) // C.STEP)
    print(f"verified real band on {np.mean(cell_all[:tot] > 0):.1%} of all tom8 cells "
          f"(SS {np.mean(cell_all[:tot] == 1):.1%}, RS {np.mean(cell_all[:tot] == 2):.1%}), "
          f"{(cell_all > 0).sum() * 0.02 / 60:.1f} min")
    for p, v in g.items():
        if v:
            print(f"{p} gain dB per recording: p10 {np.quantile(v, .1):+.1f}  p50 {np.median(v):+.1f}  p90 {np.quantile(v, .9):+.1f}")


if __name__ == "__main__":
    main()
