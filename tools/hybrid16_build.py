"""Render the 16 kHz Tom: tom8 0-3.4 kHz + a synthetic 3.4-8 kHz band whose ENVELOPE comes
from the real SS / RS take where it is verified and from the Tom-trained net elsewhere.

The real band's own fine structure is not used: two independent encodes of the same take
agree only at NCC 0.635 above 3.4 kHz (hybrid16_packcmp.py), i.e. roughly a third of that
band is codec noise, which is the "crunch". One pitch-modulated noise excitation runs
through the whole recording, so the only thing that crossfades is the envelope.

Real-envelope mask: real islands shorter than MIN_ISLAND cells are dropped, then eroded
XF/2 and smoothed with an XF Hann.

    python -I hybrid16_build.py calibrate            held-out bias/gain -> bwe_eval.json
    python -I hybrid16_build.py demo                 10 demo recordings -> C:\\tmp\\hybrid16_demo4
    python -I hybrid16_build.py full                 -> C:\\tmp\\hybrid16\\tom16_retex.vdb
    python -I hybrid16_build.py full --bwe-only      -> C:\\tmp\\hybrid16\\tom16_bwe.vdb
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from scipy import signal as sg
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hybrid16_demo as HD  # noqa: E402
import hybrid16_bwe as B  # noqa: E402

OUT = Path(r"C:\tmp\hybrid16")
DEMO = Path(r"C:\tmp\hybrid16_demo4")
MIN_ISLAND = 5          # cells (100 ms)
XF = 480                # envelope crossfade, 16 kHz samples (30 ms)
TOM16_DATA_SIZE = 237_499_102


def mask16(cells, n16):
    ok = cells > 0
    k = 0
    while k < len(ok):
        if ok[k]:
            j = k
            while j < len(ok) and ok[j]:
                j += 1
            if j - k < MIN_ISLAND:
                ok[k:j] = False
            k = j
        else:
            k += 1
    m = np.repeat(ok, HD.CELL16).astype(float)
    m = np.r_[m, np.zeros(max(0, n16 - len(m)))][:n16]
    er = np.convolve(m, np.ones(XF + 1) / (XF + 1), mode="same") > 0.999
    w = np.hanning(XF + 1)
    return np.convolve(er.astype(float), w / w.sum(), mode="same")


def setup():
    tom8 = np.load(OUT / "tom8_f32.npy", mmap_mode="r")
    hi = np.load(OUT / "hi_real.f16.npy", mmap_mode="r")
    cell = np.load(OUT / "cell_ok.u8.npy")
    offs, names = B.entries()
    ends = np.r_[offs[1:], len(tom8)]
    return tom8, hi, cell, offs, names, ends


def rec_data(tom8, hi, cell, s0, s1):
    x16 = sg.resample_poly(np.asarray(tom8[s0:s1], np.float64), 2, 1) if s1 > s0 else np.zeros(0)
    real = np.asarray(hi[2 * s0:2 * s0 + len(x16)], np.float64)
    c = cell[s0 // 160:s0 // 160 + (s1 - s0) // 160]
    return x16, real, c


def calibrate():
    """Held-out recordings only: per-bin bias of the predicted envelope vs the real one, and
    the gain that makes a real-envelope resynthesis match the real band's level."""
    tom8, hi, cell, offs, names, ends = setup()
    diffs, ratios = [], []
    for i, nm in enumerate(names):
        if not (i % 20 == 0 or nm in HD.DEFAULT_RECS):
            continue
        x16, real, c = rec_data(tom8, hi, cell, int(offs[i]), int(ends[i]))
        if (c > 0).sum() < 10 or len(x16) < 2 * B.NFFT:
            continue
        _, ep, er = B.envelopes(x16, real)
        fm = np.repeat(c > 0, 2)
        fm = np.r_[fm, np.zeros(max(0, ep.shape[0] - len(fm)), bool)][:ep.shape[0]]
        fm &= np.roll(fm, 2) & np.roll(fm, -2)
        if fm.sum() < 5:
            continue
        diffs.append((er - ep)[torch.from_numpy(fm).to(B.DEV)].cpu().numpy())
        m = np.repeat(c > 0, HD.CELL16).astype(float)
        m = np.r_[m, np.zeros(max(0, len(x16) - len(m)))][:len(x16)]
        _, h = B.render2(x16, real, m)
        mm = m > 0.5
        ratios.append(np.sqrt(np.mean(real[mm] ** 2)) / (np.sqrt(np.mean(h[mm] ** 2)) + 1e-9))
    bias = np.median(np.concatenate(diffs), 0)
    gain = float(np.median(ratios))
    p = OUT / "bwe_eval.json"
    d = json.loads(p.read_text())
    d.update(rt_bias=bias.tolist(), rt_gain=gain)
    p.write_text(json.dumps(d))
    print(f"{len(ratios)} held-out recordings: predicted-envelope bias mean {10 * bias.mean():+.1f} dB "
          f"(per-bin range {10 * bias.min():+.1f}..{10 * bias.max():+.1f}), resynthesis gain {20 * np.log10(gain):+.1f} dB")


def cal():
    d = json.loads((OUT / "bwe_eval.json").read_text())
    return np.asarray(d["rt_bias"], np.float32), d["rt_gain"]


def limit(y, ceil=32000.0, L=64):
    """Look-ahead peak limiter. The x2 upsample of mu-law tom8 overshoots to ~38k on
    transients. Sliding-min of the needed gain over +-L, then a Hann of the same span:
    every output sample stays <= ceil, and gain is exactly 1 away from peaks."""
    need = np.minimum(1.0, ceil / np.maximum(np.abs(y), 1e-9))
    if need.min() >= 1.0:
        return y
    from scipy.ndimage import minimum_filter1d
    g = minimum_filter1d(need, 2 * L + 1, mode="nearest")
    w = np.hanning(2 * L + 3)[1:-1]
    g = np.convolve(np.pad(g, L, mode="edge"), w / w.sum(), mode="valid")
    return y * np.minimum(g, 1.0)


def render_rec(x16, real, c, bias, gain, bwe_only=False, deess=0.0):
    if len(x16) < 2 * B.NFFT:
        return limit(x16), np.zeros(len(x16))
    m = np.zeros(len(x16)) if bwe_only else mask16(c.copy(), len(x16))
    lo, h = B.render2(x16, None if bwe_only else real, m, bias=bias, gain=gain, deess=deess)
    return limit(lo + h), m


def deess_demo(levels=(0.0, 4.0, 8.0)):
    """BWE-only at several de-ess depths, plus AudioSR, for the 10 demo recordings."""
    tom8, hi, cell, offs, names, ends = setup()
    bias, gain = cal()
    out = Path(r"C:\tmp\hybrid16_demo5")
    out.mkdir(parents=True, exist_ok=True)
    gap = np.zeros(8000)
    seq, cat = [], {f"deess{int(d)}": [] for d in levels}
    for nm in HD.DEFAULT_RECS:
        i = names.index(nm)
        s0, s1 = int(offs[i]), int(ends[i])
        x16, real, c = rec_data(tom8, hi, cell, s0, s1)
        seq += [HD.tom16_slice(s0, s1 - s0), gap[:4000]]
        for d in levels:
            y, _ = render_rec(x16, real, c, bias, gain, bwe_only=True, deess=d)
            cat[f"deess{int(d)}"] += [y, gap]
            seq += [y, gap[:4000]]
        seq.append(gap)
    for k, x in cat.items():
        sf.write(out / f"ALL_{k}.wav", np.clip(np.concatenate(x), -32768, 32767).astype(np.int16), 16000)
    sf.write(out / "ALL_asr_0_4_8.wav", np.clip(np.concatenate(seq), -32768, 32767).astype(np.int16), 16000)
    print("wrote", out)


def demo():
    tom8, hi, cell, offs, names, ends = setup()
    bias, gain = cal()
    DEMO.mkdir(parents=True, exist_ok=True)
    gap = np.zeros(8000)
    seq, cat = [], {k: [] for k in ("B_audiosr", "F_retexture", "G_bwe_smooth")}
    for nm in HD.DEFAULT_RECS:
        i = names.index(nm)
        s0, s1 = int(offs[i]), int(ends[i])
        x16, real, c = rec_data(tom8, hi, cell, s0, s1)
        fy, m = render_rec(x16, real, c, bias, gain)
        gy, _ = render_rec(x16, real, c, bias, gain, bwe_only=True)
        asr = HD.tom16_slice(s0, s1 - s0)
        v = {"B_audiosr": asr, "F_retexture": fy, "G_bwe_smooth": gy}
        for k, x in v.items():
            sf.write(DEMO / f"{nm}_{k}.wav", np.clip(x, -32768, 32767).astype(np.int16), 16000)
            cat[k] += [x, gap]
        seq += [asr, gap[:4000], fy, gap[:4000], gy, gap]
        HD.spectro(DEMO / f"{nm}.png", nm, [("AudioSR", asr), ("retexture", fy), ("BWE smooth", gy)], m)
        print(f"{nm:12} real envelope on {np.mean(m > 0.5):.0%} of the recording", flush=True)
    for k, x in cat.items():
        sf.write(DEMO / f"ALL_{k}.wav", np.clip(np.concatenate(x), -32768, 32767).astype(np.int16), 16000)
    sf.write(DEMO / "ALL_B_F_G.wav", np.clip(np.concatenate(seq), -32768, 32767).astype(np.int16), 16000)
    print("wrote", DEMO)


def full(bwe_only, deess=0.0):
    tom8, hi, cell, offs, names, ends = setup()
    bias, gain = cal()
    dst = OUT / ((("tom16_bwe" if bwe_only else "tom16_retex") + (f"_deess{int(deess)}" if deess else "")) + ".vdb")
    shutil.copyfile(HD.TOM16, dst)
    data_end = HD.TOM16_DATA + TOM16_DATA_SIZE      # tom16 data is one 16 kHz sample short of 4 x tom8
    assert dst.stat().st_size == data_end
    real_s = 0.0
    with open(dst, "r+b") as f:
        for i in tqdm(range(len(names))):
            s0, s1 = int(offs[i]), int(ends[i])
            if s1 <= s0:
                continue
            x16, real, c = rec_data(tom8, hi, cell, s0, s1)
            y, m = render_rec(x16, real, c, bias, gain, bwe_only, deess)
            real_s += float(m.sum()) / 16000
            b = np.clip(np.round(y), -32768, 32767).astype("<i2").view(np.uint8) ^ 0xCE
            at = HD.TOM16_DATA + 4 * s0
            f.seek(at)
            f.write(b[:max(0, data_end - at)].tobytes())
    print(f"wrote {dst}  (real envelope on {real_s / 60:.1f} min of {len(tom8) / 8000 / 60:.1f})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("calibrate", "demo", "deess", "full"))
    ap.add_argument("--bwe-only", action="store_true")
    ap.add_argument("--deess", type=float, default=0.0, help="dB cut >= 6 kHz on sibilants (full)")
    a = ap.parse_args()
    if a.mode == "calibrate":
        calibrate()
    elif a.mode == "demo":
        demo()
    elif a.mode == "deess":
        deess_demo()
    else:
        full(a.bwe_only, a.deess)


if __name__ == "__main__":
    main()
