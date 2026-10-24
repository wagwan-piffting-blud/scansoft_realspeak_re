"""16 kHz Tom v5: the SS 2004 / RS 2006 take itself, FULL band, wherever it is verified;
the AudioSR tom16 everywhere else.

Per run of runs.json (hybrid16_map.py; positions hold for the fresh D1+D2 corpora, which
are sample-identical in layout):
  1. fractional alignment at 22.05 kHz against tom8 (0.3-3.4 kHz, parabolic peak)
  2. ONE resampling step: a Kaiser-windowed sinc (HW taps each side, cutoff FC) evaluated
     directly at tom8's 16 kHz sample times, on the GPU; no intermediate resample
  3. one gain per pack per recording (1-3 kHz vs tom8)
  4. 20 ms cells kept only if their 0.3-3.4 kHz NCC vs tom8 >= CELL_NCC (or tom8 is silent)
Mixing: each run gets its own weight (verified cells, islands < MIN_ISLAND dropped,
eroded XF/2, Hann XF); out = sum(w_i * run_i) + (1 - sum w) * AudioSR. Every source is the
same take, phase-aligned, so the crossfades are coherent. Then the look-ahead limiter.

    python -I hybrid16_v5.py demo               10 demo recordings -> C:\\tmp\\hybrid16_v5
    python -I hybrid16_v5.py full               -> C:\\tmp\\hybrid16\\tom16_v5.vdb
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from scipy import signal as sg
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tom_overlap as T  # noqa: E402
import hybrid16_demo as HD  # noqa: E402
import hybrid16_build as HB  # noqa: E402

OUT = Path(r"C:\tmp\hybrid16")
DEMO = Path(r"C:\tmp\hybrid16_v5")
FC, HW, BETA = 7750.0, 128, 9.0
CELL_NCC = 0.80
MIN_ISLAND = 5
XF = 320
R22 = 60
DEV = "cuda"

BP_ALIGN22 = sg.firwin(801, [300, 3400], fs=22050, pass_zero=False)
BP_GAIN16 = sg.firwin(401, [1000, 3000], fs=16000, pass_zero=False)
BP_NCC16 = sg.firwin(401, [300, 3400], fs=16000, pass_zero=False)
_J = torch.arange(-HW + 1, HW + 1, device=DEV, dtype=torch.float64)


def sinc_at(src, t):
    """Band-limited value of src (22.05 kHz) at fractional indices t: Kaiser-windowed
    sinc, cutoff FC, HW taps per side, DC-normalised."""
    s = torch.from_numpy(np.ascontiguousarray(src, np.float64)).to(DEV)
    tt = torch.from_numpy(np.asarray(t, np.float64)).to(DEV)
    out = torch.empty_like(tt)
    a = 2 * FC / 22050
    for i in range(0, len(tt), 1 << 16):
        tb = tt[i:i + (1 << 16)]
        k0 = torch.floor(tb)
        idx = (k0[:, None] + _J[None]).long().clamp(0, len(s) - 1)
        x = tb[:, None] - (k0[:, None] + _J[None])
        u = (x / HW).clamp(-1, 1)
        win = torch.special.i0(BETA * torch.sqrt(1 - u * u)) / torch.special.i0(torch.tensor(BETA, dtype=torch.float64))
        h = a * torch.sinc(a * x) * win
        out[i:i + (1 << 16)] = (h * s[idx]).sum(1) / h.sum(1)
    return out.cpu().numpy()


def align(run, hay, t8_22):
    """-> absolute 22 kHz corpus index of recording-local 22 kHz sample 0 (float), NCC."""
    c0, c1 = run["c0"], run["c1"]
    base22 = run["D8"] * 441 / 160
    a22, b22 = c0 * HD.CELL22, c1 * HD.CELL22
    i0 = int(np.floor(a22 + base22)) - R22 - 1200
    i1 = int(np.ceil(b22 + base22)) + R22 + 1200
    if i0 < 0 or i1 > len(hay) or b22 - a22 < 64:
        return None
    blk_bp = HD.zconv(np.asarray(hay[i0:i1], np.float64) * run["pol"], BP_ALIGN22)
    ref = t8_22[a22:b22]
    ref_bp = HD.zconv(np.r_[np.zeros(1200), ref, np.zeros(1200)], BP_ALIGN22)[1200:-1200]
    st = int(np.floor(a22 + base22)) - i0
    seg = blk_bp[st - R22:st + R22 + len(ref_bp)]
    num = np.correlate(seg, ref_bp, mode="valid")
    cs = np.r_[0, np.cumsum(seg ** 2)]
    ncc = num / (np.sqrt(np.maximum(cs[len(ref_bp):] - cs[:-len(ref_bp)], 1e-9)) * (np.linalg.norm(ref_bp) or 1e-9))
    k = int(np.argmax(ncc))
    fr = 0.0
    if 0 < k < len(ncc) - 1:
        y0, y1, y2 = ncc[k - 1], ncc[k], ncc[k + 1]
        dd = y0 - 2 * y1 + y2
        fr = 0.5 * (y0 - y2) / dd if dd else 0.0
    return i0 + st - R22 + k + fr - a22, float(ncc[k])


def run_audio(run, hay, t8_22, t8_16, rms8, asr):
    """The run's full-band audio on tom8's 16 kHz grid over its cells, gain-matched to the
    AudioSR filler it crossfades with, plus per-cell verification against tom8.
    -> (a16, y16, ok cells, gain dB, align NCC) or None."""
    al = align(run, hay, t8_22)
    if al is None:
        return None
    off22, nc = al
    c0, c1 = run["c0"], run["c1"]
    a16, b16 = c0 * HD.CELL16, c1 * HD.CELL16
    t = np.arange(a16, b16) * (22050 / 16000) + off22
    lo, hi = int(np.floor(t[0])) - HW - 2, int(np.ceil(t[-1])) + HW + 2
    if lo < 0 or hi > len(hay):
        return None
    y = sinc_at(np.asarray(hay[lo:hi], np.float64) * run["pol"], t - lo)
    ref = t8_16[a16:b16]
    g = np.sqrt(np.mean(HD.zconv(asr[a16:b16], BP_GAIN16) ** 2)) / (np.sqrt(np.mean(HD.zconv(y, BP_GAIN16) ** 2)) or 1e-9)
    ya, rb = HD.zconv(y * g, BP_NCC16), HD.zconv(ref, BP_NCC16)
    n = c1 - c0
    fn = np.array([np.dot(ya[j * HD.CELL16:(j + 1) * HD.CELL16], rb[j * HD.CELL16:(j + 1) * HD.CELL16]) /
                   ((np.linalg.norm(ya[j * HD.CELL16:(j + 1) * HD.CELL16]) *
                     np.linalg.norm(rb[j * HD.CELL16:(j + 1) * HD.CELL16])) or 1e-9) for j in range(n)])
    ok = (fn >= CELL_NCC) | (rms8[c0:c1] < 200)
    return a16, y, ok, float(20 * np.log10(g)), nc


def weight(ok_cells, c0, n16):
    ok = ok_cells.copy()
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
    m = np.zeros(n16)
    m[c0 * HD.CELL16:c0 * HD.CELL16 + len(ok) * HD.CELL16] = np.repeat(ok, HD.CELL16)[:max(0, n16 - c0 * HD.CELL16)]
    er = np.convolve(m, np.ones(XF + 1) / (XF + 1), mode="same") > 0.999
    w = np.hanning(XF + 1)
    return np.convolve(er.astype(float), w / w.sum(), mode="same")


_HAY = {}


def hays():
    if not _HAY:
        _HAY.update(ss=T.wav_i16(T.SS_WAV), rs=T.wav_i16(T.RS_WAV))
    return _HAY


_EQ = {}


def eq_fir(key):
    """Linear-phase FIRs from hybrid16_v5_eq.py's real-minus-AudioSR curves (dB).
    'asr2real': AudioSR -> SS curve.  'meet_asr' / 'meet_ss' / 'meet_rs': half each way."""
    if key not in _EQ:
        d = json.loads((OUT / "v5_eq.json").read_text())
        f = np.asarray(d["f"])
        src, s = {"asr2real": ("ss", 1.0), "meet_asr": ("ss", 0.5),
                  "meet_ss": ("ss", -0.5), "meet_rs": ("rs", -0.5),
                  "sib_cut": ("sib_real2fill", -1.0),
                  "real2asr_ss": ("ss", -1.0), "real2asr_rs": ("rs", -1.0)}[key]
        g = 10 ** (s * np.asarray(d[src]) / 20)
        _EQ[key] = sg.firwin2(511, f / 8000, g)
    return _EQ[key]


def sib_cut(acc, x16):
    """The real take's /s/ runs to 8 kHz; pure AudioSR (the user's reference) rolls it off at
    6-7 kHz. Blend the real arms toward the measured real->filler sibilant curve
    (hybrid16_sibreal.py) by per-frame tom8 sibilance; vowels are untouched."""
    import hybrid16_bwe as B
    if len(x16) < 2 * B.NFFT:
        return acc
    lo, _ = HD.split(x16)
    s = B.sibilance(lo, len(x16) // B.HOP + 1).cpu().numpy()
    s = np.clip((s - 0.2) / 0.6, 0, 1)          # saturate: a 14% uncut leak is a -17 dB floor
    s16 = np.interp(np.arange(len(x16)), np.arange(len(s)) * B.HOP, s)
    return (1 - s16) * acc + s16 * HD.zconv(acc, eq_fir("sib_cut"))


CEIL_HZ, CEIL_MARGIN_DB = 4500.0, 2.0


def asr_ceiling(acc, W, asr):
    """Cap the real arms' energy above CEIL_HZ at the (EQ'd) AudioSR filler's level for the
    SAME instant, + CEIL_MARGIN_DB. Cut only. Keyed on the audio itself, so every /s/ that
    reaches the top of the band in the real take is trimmed back to the user's reference,
    however weakly tom8 shows it; vowels sit 6-11 dB under AudioSR up there and pass."""
    n, hop = 512, 128
    dev = "cuda"
    w = torch.hann_window(n, device=dev)
    A = torch.stft(torch.from_numpy(acc.astype(np.float32)).to(dev), n, hop, window=w, center=True, return_complex=True)
    R = torch.stft(torch.from_numpy((W * asr).astype(np.float32)).to(dev), n, hop, window=w, center=True, return_complex=True)
    pa = torch.nn.functional.avg_pool1d((A.abs() ** 2)[None], 3, 1, 1, count_include_pad=False)[0]
    pr = torch.nn.functional.avg_pool1d((R.abs() ** 2)[None], 3, 1, 1, count_include_pad=False)[0]
    pa = torch.nn.functional.avg_pool1d(pa.T[:, None], 9, 1, 4, count_include_pad=False)[:, 0].T
    pr = torch.nn.functional.avg_pool1d(pr.T[:, None], 9, 1, 4, count_include_pad=False)[:, 0].T
    g = torch.sqrt((pr * 10 ** (CEIL_MARGIN_DB / 10) + 1e-3) / (pa + 1e-3)).clamp(max=1.0)
    f = torch.fft.rfftfreq(n, 1 / 16000).to(dev)
    ramp = ((f - (CEIL_HZ - 500)) / 500).clamp(0, 1)[:, None]
    g = 1 - ramp * (1 - g)
    y = torch.istft(A * g, n, hop, window=w, center=True, length=len(acc))
    return y.cpu().numpy().astype(np.float64)


LP_SIB = sg.firwin(511, 4500, fs=16000)
SIB_BOOST_DB = 1.5          # the BWE sat 1-2 dB under the real take on held-out sibilants


def sib_fill(asr, x16):
    """AudioSR has almost nothing above ~6 kHz on /s/ (hybrid16_sib.py), the real take is
    full-band there. Above 4.5 kHz, blend the filler toward the Tom-trained BWE in pure-noise
    mode by per-frame tom8 sibilance; vowels (sibilance 0) keep AudioSR untouched."""
    import hybrid16_bwe as B
    if len(x16) < 2 * B.NFFT:
        return asr
    bias, gain = HB.cal()
    lo, h = B.render2(x16, None, None, depth=0.0, bias=bias, gain=gain * 10 ** (SIB_BOOST_DB / 20))
    s = B.sibilance(lo, len(x16) // B.HOP + 1).cpu().numpy()
    s16 = np.interp(np.arange(len(x16)), np.arange(len(s)) * B.HOP, s)
    a_lo = HD.zconv(asr, LP_SIB)
    return a_lo + (1 - s16) * (asr - a_lo) + s16 * (h - HD.zconv(h, LP_SIB))


LP_H8 = sg.firwin(511, 4000, fs=16000)


def render(tom8, s0, s1, runs, eq=None):
    """-> (out16, real weight, info). eq: None, 'asr2real', 'meet', 'h5' (= asr2real on
    vowels + Tom BWE noise on the filler's sibilants), 'h6' (= asr2real filler + the real
    arms' sibilants rolled off like AudioSR's), 'h7' (= asr2real filler + real arms capped
    at AudioSR above 4.5 kHz) or 'h8' (= the real take EQ'd to AudioSR BELOW 4 kHz only,
    pure AudioSR above it everywhere, so the top band never changes source)."""
    x8 = np.asarray(tom8[s0:s1], np.float64)
    t8_16 = sg.resample_poly(x8, 2, 1)
    asr = HD.tom16_slice(s0, s1 - s0)[:len(t8_16)]
    asr = np.r_[asr, np.zeros(len(t8_16) - len(asr))]      # the last record is one sample short
    if eq in ("asr2real", "h5", "h6", "h7"):
        asr = HD.zconv(asr, eq_fir("asr2real"))
    elif eq == "meet":
        asr = HD.zconv(asr, eq_fir("meet_asr"))
    if eq == "h5":
        asr = sib_fill(asr, t8_16)
    if len(t8_16) < 2 * HD.CELL16 or not runs:
        return HB.limit(asr), np.zeros(len(asr)), {}
    t8_22 = sg.resample_poly(x8, 441, 160)
    ncell = len(t8_16) // HD.CELL16
    rms8 = np.sqrt(np.mean(x8[:ncell * 160].reshape(ncell, 160) ** 2, 1))
    got = []
    for u in runs:
        r = run_audio(u, hays()[u["pack"]], t8_22, t8_16, rms8, asr)
        if r is not None:
            got.append((u, *r))
    gains = {}
    for pk in ("ss", "rs"):
        gs = [(g, u["c1"] - u["c0"]) for u, _, _, _, g, _ in got if u["pack"] == pk]
        if gs:
            v, w = np.array(gs).T
            o = np.argsort(v)
            gains[pk] = float(v[o][np.searchsorted(np.cumsum(w[o]), w.sum() / 2)])
    acc = np.zeros(len(t8_16))
    W = np.zeros(len(t8_16))
    for u, a16, y, ok, g, nc in got:
        w = weight(ok, u["c0"], len(t8_16))
        seg = np.zeros(len(t8_16))
        seg[a16:a16 + len(y)] = y[:len(t8_16) - a16] * 10 ** (gains[u["pack"]] / 20)
        if eq == "meet":
            seg = HD.zconv(seg, eq_fir("meet_" + u["pack"]))
        elif eq == "h8":
            seg = HD.zconv(seg, eq_fir("real2asr_" + u["pack"]))
        acc += w * seg
        W += w
    W = np.minimum(W, 1.0)
    if eq == "h7":
        acc = asr_ceiling(acc, W, asr)
    elif eq == "h6":
        acc = sib_cut(acc, t8_16)
    out = acc + (1 - W) * asr
    if eq == "h8":
        lo_ = HD.zconv(out, LP_H8)
        out = lo_ + (asr - HD.zconv(asr, LP_H8))
    info = {"gains": gains, "align_ncc": [nc for *_, nc in got], "runs": len(got)}
    return HB.limit(out), W, info


def setup():
    runs = json.loads((OUT / "runs.json").read_text())
    tom8 = np.load(OUT / "tom8_f32.npy", mmap_mode="r")
    import hybrid16_bwe as B
    offs, names = B.entries()
    ends = np.r_[offs[1:], len(tom8)]
    return runs, tom8, offs, names, ends


def demo():
    runs, tom8, offs, names, ends = setup()
    DEMO.mkdir(parents=True, exist_ok=True)
    gap = np.zeros(8000)
    seq, cat = [], {"B_audiosr": [], "H_v5": [], "H3_asr2real": [], "Hm_meet": []}
    for nm in HD.DEFAULT_RECS:
        i = names.index(nm)
        s0, s1 = int(offs[i]), int(ends[i])
        y, W, info = render(tom8, s0, s1, runs.get(nm, []))
        y3, _, _ = render(tom8, s0, s1, runs.get(nm, []), eq="asr2real")
        ym, _, _ = render(tom8, s0, s1, runs.get(nm, []), eq="meet")
        asr = HD.tom16_slice(s0, s1 - s0)[:len(y)]
        v = {"B_audiosr": asr, "H_v5": y, "H3_asr2real": y3, "Hm_meet": ym}
        for k, x in v.items():
            sf.write(DEMO / f"{nm}_{k}.wav", np.clip(x, -32768, 32767).astype(np.int16), 16000)
            cat[k] += [x, gap]
        seq += [asr, gap[:4000], y, gap[:4000], y3, gap[:4000], ym, gap]
        HD.spectro(DEMO / f"{nm}.png", nm, [("AudioSR", asr), ("v5", y)], W)
        print(f"{nm:12} real take on {np.mean(W > 0.5):4.0%}  runs {info.get('runs', 0):2d}  "
              f"align NCC p50 {np.median(info['align_ncc']) if info.get('align_ncc') else float('nan'):.3f}  "
              f"gains {', '.join(f'{k} {v:+.1f}' for k, v in info.get('gains', {}).items())}", flush=True)
    for k, x in cat.items():
        sf.write(DEMO / f"ALL_{k}.wav", np.clip(np.concatenate(x), -32768, 32767).astype(np.int16), 16000)
    sf.write(DEMO / "ALL_B_H_H3_Hm.wav", np.clip(np.concatenate(seq), -32768, 32767).astype(np.int16), 16000)
    print("wrote", DEMO)


def full(eq=None):
    runs, tom8, offs, names, ends = setup()
    dst = OUT / (f"tom16_v5_{eq}.vdb" if eq else "tom16_v5.vdb")
    shutil.copyfile(HD.TOM16, dst)
    data_end = HD.TOM16_DATA + HB.TOM16_DATA_SIZE
    assert dst.stat().st_size == data_end
    real_s = 0.0
    with open(dst, "r+b") as f:
        for i in tqdm(range(len(names))):
            s0, s1 = int(offs[i]), int(ends[i])
            if s1 <= s0 or (names[i] not in runs and not eq):
                continue
            y, W, _ = render(tom8, s0, s1, runs.get(names[i], []), eq)
            real_s += float(W.sum()) / 16000
            b = np.clip(np.round(y), -32768, 32767).astype("<i2").view(np.uint8) ^ 0xCE
            at = HD.TOM16_DATA + 4 * s0
            f.seek(at)
            f.write(b[:max(0, data_end - at)].tobytes())
    print(f"wrote {dst}  (real take on {real_s / 60:.1f} min of {len(tom8) / 8000 / 60:.1f}; AudioSR elsewhere)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("demo", "full"))
    ap.add_argument("--eq", choices=("asr2real", "meet", "h5", "h6", "h7", "h8"), default=None)
    a = ap.parse_args()
    demo() if a.mode == "demo" else full(a.eq)


if __name__ == "__main__":
    main()
