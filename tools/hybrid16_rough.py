"""Why does the BWE top band sound crunchy? Roughness of the 3.4-8 kHz band, real vs synthetic.

Roughness here = amplitude modulation of the top band in the 30-150 Hz range (the
psychoacoustic roughness range), per sub-band: rms of the envelope band-passed to 30-150 Hz
over the envelope's mean, on frames where the REAL band is verified. Also the top-band
log-spectral distance to real, and frame-to-frame band-energy jitter.

Variants (all on the 10 held-out demo recordings, level-matched to real):
    v1  rect excitation, envelope smoothed 5 bins          (demo v2's E)
    v2  pitch-modulated noise (depth 0.6), 9 bins x 3 frames
    v3  plain noise, 9 bins x 3 frames
    v4  pitch-modulated noise (depth 0.3), 9 bins x 3 frames

    python -I hybrid16_rough.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal as sg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hybrid16_demo as HD  # noqa: E402
import hybrid16_bwe as B  # noqa: E402

OUT = Path(r"C:\tmp\hybrid16_demo3")
VARS = {"v1": dict(exc="rect", tsm=1, fsm=5),
        "v2": dict(exc="modnoise", tsm=3, fsm=9, depth=0.6),
        "v3": dict(exc="noise", tsm=3, fsm=9),
        "v4": dict(exc="modnoise", tsm=3, fsm=9, depth=0.3)}
SUBS = [(3400, 4500), (4500, 5700), (5700, 7800)]
BP_MOD = sg.butter(2, [30, 150], btype="band", fs=1000, output="sos")


def roughness(h, m):
    vals = []
    for a, b in SUBS:
        sos = sg.butter(4, [a, b], btype="band", fs=16000, output="sos")
        env = np.abs(sg.hilbert(sg.sosfiltfilt(sos, h)))
        e1 = sg.resample_poly(env, 1, 16)
        mk = m[::16][:len(e1)]
        am = sg.sosfiltfilt(BP_MOD, e1)
        if mk.sum() > 200:
            vals.append(np.sqrt(np.mean(am[mk] ** 2)) / (np.mean(e1[mk]) + 1e-9))
    return float(np.mean(vals)) if vals else np.nan


def jitter(h, m):
    f, t, S = sg.spectrogram(h, 16000, nperseg=256, noverlap=96)
    band = 10 * np.log10(S[(f > 3400)].sum(0) + 1e-3)
    mk = m[np.clip((t * 16000).astype(int), 0, len(m) - 1)]
    d = np.abs(np.diff(band))[mk[1:] & mk[:-1]]
    return float(np.median(d)) if len(d) else np.nan


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tom8 = np.load(B.OUT / "tom8_f32.npy", mmap_mode="r")
    hi = np.load(B.OUT / "hi_real.f16.npy", mmap_mode="r")
    cell = np.load(B.OUT / "cell_ok.u8.npy")
    offs, names = B.entries()
    ends = np.r_[offs[1:], len(tom8)]
    recs = []
    for nm in HD.DEFAULT_RECS:
        i = names.index(nm)
        s0, s1 = int(offs[i]), int(ends[i])
        x16 = sg.resample_poly(np.asarray(tom8[s0:s1], np.float64), 2, 1)
        lo, _ = HD.split(x16)
        real = np.asarray(hi[2 * s0:2 * s1], np.float64)
        c = cell[s0 // 160:s0 // 160 + (s1 - s0) // 160]
        m = np.repeat(c > 0, 320)
        m = np.r_[m, np.zeros(len(x16) - len(m), bool)][:len(x16)]
        sp = np.repeat(np.sqrt(np.mean(x16[:len(x16) // 320 * 320].reshape(-1, 320) ** 2, 1)) > 300, 320)
        sp = np.r_[sp, np.zeros(len(x16) - len(sp), bool)]
        _, asr = HD.split(HD.tom16_slice(s0, s1 - s0))
        syn = {k: B.render(x16, 1.0, **kw) for k, kw in VARS.items()}
        recs.append((nm, lo, real, m & sp, asr, syn))

    gains = {}
    for k in VARS:
        r = [np.sqrt(np.mean(real[mm] ** 2)) / (np.sqrt(np.mean(syn[k][mm] ** 2)) + 1e-9)
             for _, _, real, mm, _, syn in recs if mm.sum() > 1600]
        gains[k] = float(np.median(r))
    r = [np.sqrt(np.mean(real[mm] ** 2)) / (np.sqrt(np.mean(asr[mm] ** 2)) + 1e-9)
         for _, _, real, mm, asr, _ in recs if mm.sum() > 1600]
    gains["asr"] = float(np.median(r))

    rows = {k: {"rough": [], "jitter": [], "lsd": []} for k in ["real", "asr", *VARS]}
    cat = {k: [] for k in ["real_masked", "asr", *VARS]}
    gap = np.zeros(8000)
    for nm, lo, real, mm, asr, syn in recs:
        if mm.sum() < 1600:
            continue
        cands = {"real": real, "asr": asr * gains["asr"], **{k: syn[k] * gains[k] for k in VARS}}
        Lr = B.logpow(real)[:, B.KX:].cpu().numpy()
        fm = mm[::B.HOP][:len(Lr)]
        for k, h in cands.items():
            rows[k]["rough"].append(roughness(h, mm))
            rows[k]["jitter"].append(jitter(h, mm))
            L = B.logpow(h)[:, B.KX:].cpu().numpy()
            rows[k]["lsd"].append(float(np.median(10 * np.sqrt(np.mean((L[fm] - Lr[fm]) ** 2, 1)))))
        cat["real_masked"] += [lo + real * mm, gap]
        cat["asr"] += [lo + cands["asr"], gap]
        for k in VARS:
            cat[k] += [lo + cands[k], gap]
    print(f"{'':6} {'roughness':>10} {'jitter dB':>10} {'LSD dB':>8}   (covered speech frames, 10 held-out recs)")
    for k, v in rows.items():
        print(f"{k:6} {np.nanmedian(v['rough']):10.3f} {np.nanmedian(v['jitter']):10.2f} {np.nanmedian(v['lsd']):8.2f}")
    print("level gains applied:", {k: round(20 * np.log10(g), 1) for k, g in gains.items()})
    for k, x in cat.items():
        sf.write(OUT / f"ALL_{k}.wav", np.clip(np.concatenate(x), -32768, 32767).astype(np.int16), 16000)
    (OUT / "rough.json").write_text(json.dumps({"rows": rows, "gains": gains}))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
