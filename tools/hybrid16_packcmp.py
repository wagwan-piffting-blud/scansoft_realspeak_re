"""SS 2004 vs RS 2006 top band on the SAME moments of the SAME take.

Recordings where both packs cover >= 40% of speech (tom16_coverage_perrec_ckls.json) are
re-mapped with hybrid16_demo.find_locks, runs are built per pack separately, and every
20 ms cell verified in BOTH packs is compared:
    roughness       30-150 Hz AM of the 3.4-8 kHz envelope (hybrid16_rough.roughness)
    modulation      envelope modulation spectrum; peaks at the codec frame rate
                    (22050/320 = 68.9 Hz) or subframe rate (275.6 Hz) mean frame artifacts
    spectrum        mean 3.4-8 kHz log spectrum, SS minus RS
    coherence       NCC of the two top-band waveforms

    python -I hybrid16_packcmp.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal as sg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tom_overlap as T  # noqa: E402
import hybrid16_demo as HD  # noqa: E402
import hybrid16_rough as RG  # noqa: E402

OUT = Path(r"C:\tmp\hybrid16_packcmp")


def pack_band(locks, pack, t8_22, t8_16, hay, rms8, ncell):
    lk = [x for x in locks if x[0] == pack]
    hi = np.zeros(len(t8_16))
    ok = np.zeros(ncell, bool)
    for u in HD.runs_from_locks(lk, ncell):
        g = HD.real_high(u, hay, t8_22, t8_16)
        if g is None:
            continue
        h16, fn, _ = g
        hi[u["c0"] * HD.CELL16:u["c0"] * HD.CELL16 + len(h16)] = h16
        ok[u["c0"]:u["c1"]] |= (fn >= HD.FRAME_NCC) & (rms8[u["c0"]:u["c1"]] >= 300)
    return hi, ok


def modspec(h, m):
    sos = sg.butter(4, [3400, 7800], btype="band", fs=16000, output="sos")
    env = sg.resample_poly(np.abs(sg.hilbert(sg.sosfiltfilt(sos, h))), 1, 8)      # 2 kHz
    mk = m[::8][:len(env)]
    segs = []
    k = 0
    while k + 256 <= len(env):
        if mk[k:k + 256].all():
            e = env[k:k + 256]
            segs.append(np.abs(np.fft.rfft((e - e.mean()) * np.hanning(256))) ** 2 / (e.mean() ** 2 + 1e-9))
        k += 128
    return np.array(segs)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    per = json.loads((T.OUT / "tom16_coverage_perrec_ckls.json").read_text())
    pick = []
    for n, v in per.items():
        sp = np.array(v["speech"])
        if sp.sum() > 50 and np.array(v["ss"])[sp].mean() >= .4 and np.array(v["rs"])[sp].mean() >= .4:
            pick.append(n)
    pick = pick[:40]
    print(f"{len(pick)} recordings with both packs >= 40%", flush=True)
    thr = json.loads((T.OUT / "xpack_W1600.json").read_text())["thresholds"]
    t8 = T.Search(HD.C.WS)
    tom8 = np.asarray(t8.s.full, np.float32)
    ends = np.r_[t8.offs[1:], len(tom8)]
    recs = [t8.names.index(n) for n in pick]
    locks, hays = HD.find_locks(t8, tom8, ends, recs, thr)

    res = {"ss": {"rough": [], "ms": []}, "rs": {"rough": [], "ms": []}}
    spec, coh, nsec = [], [], 0.0
    cat_ss, cat_rs = [], []
    for r in recs:
        s0, s1 = int(t8.offs[r]), int(ends[r])
        x8 = tom8[s0:s1].astype(np.float64)
        t8_16, t8_22 = sg.resample_poly(x8, 2, 1), sg.resample_poly(x8, 441, 160)
        ncell = len(t8_16) // HD.CELL16
        rms8 = np.sqrt(np.mean(x8[:ncell * 160].reshape(ncell, 160) ** 2, 1))
        hs, oks = pack_band(locks[r], "ss", t8_22, t8_16, hays["ss"], rms8, ncell)
        hr, okr = pack_band(locks[r], "rs", t8_22, t8_16, hays["rs"], rms8, ncell)
        both = oks & okr
        if both.sum() < 10:
            continue
        m = np.repeat(both, HD.CELL16)
        m = np.r_[m, np.zeros(len(t8_16) - len(m), bool)]
        g = np.sqrt(np.mean(hs[m] ** 2)) / (np.sqrt(np.mean(hr[m] ** 2)) + 1e-9)
        hr = hr * g                                       # compare texture, not level
        nsec += m.sum() / 16000
        for pk, h in (("ss", hs), ("rs", hr)):
            res[pk]["rough"].append(RG.roughness(h, m))
            ms = modspec(h, m)
            if len(ms):
                res[pk]["ms"].append(ms)
        f, Ps = sg.welch(hs[m], 16000, nperseg=512)
        _, Pr = sg.welch(hr[m], 16000, nperseg=512)
        spec.append(10 * np.log10(Ps + 1e-9) - 10 * np.log10(Pr + 1e-9))
        coh.append(float(np.dot(hs[m], hr[m]) / (np.linalg.norm(hs[m]) * np.linalg.norm(hr[m]) + 1e-9)))
        lo, _ = HD.split(t8_16)
        cat_ss += [lo + hs * m, np.zeros(6000)]
        cat_rs += [lo + hr * m, np.zeros(6000)]

    print(f"\nshared verified speech: {nsec:.1f} s over {len(coh)} recordings")
    for pk in ("ss", "rs"):
        print(f"{pk.upper()} roughness median {np.nanmedian(res[pk]['rough']):.3f}")
    fm = np.fft.rfftfreq(256, 1 / 2000)
    M = {pk: np.mean(np.concatenate(res[pk]["ms"]), 0) for pk in ("ss", "rs")}
    print("\nmodulation spectrum of the top-band envelope, SS/RS power ratio (dB):")
    for lo_, hi_ in ((5, 30), (30, 60), (60, 80), (80, 150), (150, 260), (260, 290), (290, 500), (500, 1000)):
        k = (fm >= lo_) & (fm < hi_)
        print(f"  {lo_:4d}-{hi_:4d} Hz  {10 * np.log10(M['ss'][k].sum() / M['rs'][k].sum()):+5.1f}")
    for f0 in (68.9, 137.8, 275.6, 344.5):
        k = int(round(f0 / (2000 / 256)))
        nb = np.r_[M["ss"][k - 6:k - 2], M["ss"][k + 3:k + 7]].mean()
        nr = np.r_[M["rs"][k - 6:k - 2], M["rs"][k + 3:k + 7]].mean()
        print(f"  peak at {f0:5.1f} Hz over neighbours: SS {10 * np.log10(M['ss'][k] / nb):+5.1f} dB  "
              f"RS {10 * np.log10(M['rs'][k] / nr):+5.1f} dB")
    S = np.mean(spec, 0)
    print("\nmean top-band spectrum, SS minus RS (dB), after level match:")
    for a, b in ((3400, 4000), (4000, 5000), (5000, 6000), (6000, 7000), (7000, 8000)):
        k = (f >= a) & (f < b)
        print(f"  {a}-{b}  {S[k].mean():+5.1f}")
    print(f"\ntop-band waveform NCC SS vs RS: median {np.median(coh):.3f}")
    sf.write(OUT / "ALL_ss_band.wav", np.clip(np.concatenate(cat_ss), -32768, 32767).astype(np.int16), 16000)
    sf.write(OUT / "ALL_rs_band.wav", np.clip(np.concatenate(cat_rs), -32768, 32767).astype(np.int16), 16000)
    np.savez(OUT / "modspec.npz", fm=fm, ss=M["ss"], rs=M["rs"])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
