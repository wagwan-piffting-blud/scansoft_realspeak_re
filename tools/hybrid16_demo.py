"""16 kHz hybrid Speechify Tom, listening demo on a handful of tom8 recordings.

Per recording, on tom8's own time axis at 16 kHz (tom16.vdb's indx = tom8's x4, so the
output is a drop-in for that recording's slice of the tom16 data chunk):

    LOW  0-3.4 kHz   tom8, upsampled x2 (above 3.4 kHz tom8 is mostly mu-law noise)
    HIGH 3.4-8 kHz   the SAME TAKE out of SS 2004 / RS 2006 at 22.05 kHz where it is
                     found and verified, AudioSR tom16 everywhere else

Finding the take is the seed-and-extend of tom16_coverage.py (8 kHz). Each locked run is
then re-aligned at 22.05 kHz to a fractional sample on the 0.3-3.4 kHz band, gain-matched
on 1-3 kHz, resampled onto the 16 kHz grid, and kept only in the 20 ms frames whose low
band still matches tom8 (NCC >= FRAME_NCC). AudioSR's high band is scaled per recording
to the real one so switching sources does not change brightness.

Variants written per recording (16 kHz mono):
    A_tom8       tom8 x2, band-limited
    B_audiosr    tom16.vdb as shipped
    C_hybrid     the proposal
    D_realonly   tom8 low + real high band only where covered (silent high band elsewhere)

    python -I hybrid16_demo.py
    python -I hybrid16_demo.py --recs news7_030 letter_088
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal as sg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tom_overlap as T  # noqa: E402
import tom_overlap_runs as R  # noqa: E402
import tom_overlap_xpack as X  # noqa: E402
import tom16_coverage as C  # noqa: E402
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPFY = os.path.join(os.path.dirname(ROOT), "Speechify")

TOM16 = SPFY + r"\en-US\tom\audiosr_tom16.vdb"   # the AudioSR original
TOM16_DATA = 0x20960
OUT = Path(r"C:\tmp\hybrid16_demo")
DEFAULT_RECS = ["news7_030", "news5_038", "news09_060", "news09_021", "news10_053",
                "news6_018", "news10_091", "usCity_022", "news19_061", "letter_088"]

XOVER = 3400.0
FRAME_NCC = 0.70
R22 = 60                 # +-22 kHz samples for the fractional re-align
M22 = 882                # block margin at 22.05 kHz (= 640 at 16 kHz, exact)
CELL16 = 2 * C.STEP      # 20 ms at 16 kHz
CELL22 = 441             # 20 ms at 22.05 kHz

H_LP = sg.firwin(511, XOVER, fs=16000)
BP_ALIGN22 = sg.firwin(801, [300, 3400], fs=22050, pass_zero=False)
BP_GAIN16 = sg.firwin(401, [1000, 3000], fs=16000, pass_zero=False)
BP_NCC16 = sg.firwin(401, [300, 3400], fs=16000, pass_zero=False)


def zconv(x, h):
    return sg.oaconvolve(x, h, mode="same")


def split(x):
    lo = zconv(x, H_LP)
    return lo, x - lo


def tom16_slice(off8, n8):
    with open(TOM16, "rb") as f:
        f.seek(TOM16_DATA + 4 * off8)
        b = np.frombuffer(f.read(4 * n8), np.uint8) ^ 0xCE
    return b.view("<i2").astype(np.float64)


def frac_shift(x, d):
    """y[n] = x(n + d), d in [0, 1), by FFT phase."""
    n = len(x)
    nf = 1 << int(np.ceil(np.log2(n + 64)))
    X_ = np.fft.rfft(np.r_[x, np.zeros(nf - n)])
    f = np.fft.rfftfreq(nf)
    return np.fft.irfft(X_ * np.exp(2j * np.pi * f * d), nf)[:n]


def find_locks(t8, tom8, ends, recs, thr):
    """-> {rec: [(pack, cell, D8, v, pol)]}, one entry per locked 100 ms step."""
    out = {r: [] for r in recs}
    hays = {}
    for pack, wav in (("ss", T.SS_WAV), ("rs", T.RS_WAV)):
        hay = X.corpus8k(f"{pack}_tom", wav)
        hay_f = np.asarray(hay, np.float32)
        H = X.ArraySearch(hay, C.WS, pack)
        seeds, sm = [], []
        for r in recs:
            s0, s1 = int(t8.offs[r]), int(ends[r])
            for s in range(s0, s1 - C.WS, C.HOP_S):
                x = tom8[s:s + C.WS]
                if np.sqrt(np.mean(x.astype(np.float64) ** 2)) > 200:
                    seeds.append(x.copy())
                    sm.append((r, s))
        res = H.run(seeds)
        hits = [(sm[i], int(res["p"][i]), int(res["pol"][i])) for i in np.where(res["v"] > thr[pack])[0]]
        print(f"{pack.upper()}: {len(seeds)} seeds, {len(hits)} hits", flush=True)
        traces = []
        for (r, s), p, pol in hits:
            s0 = int(t8.offs[r])
            n = (int(ends[r]) - s0) // C.STEP
            c = (s + C.WS // 2 - C.WIN // 2 - s0) // C.STEP
            rows = []
            for k in range(n):
                xs = s0 + k * C.STEP
                if xs + C.WIN > ends[r]:
                    rows.append((np.nan, 0, np.nan, 0))
                    continue
                y = p + C.WS // 2 - C.WIN // 2 + (k - c) * C.STEP + (s + C.WS // 2 - C.WIN // 2 - s0 - c * C.STEP)
                pr = tom8[xs:xs + C.WIN] * pol
                v, lag = R.local_ncc(hay_f, y, pr)
                vr, _ = R.local_ncc(hay_f, y, pr[::-1].copy())
                rows.append((v, lag, vr, y + lag - xs))
            traces.append((r, c, pol, rows))
        vr_all = np.array([row[2] for *_, rows in traces for row in rows if np.isfinite(row[2])])
        lthr = float(np.quantile(vr_all, 0.99)) if len(vr_all) else 1.0
        for r, c, pol, rows in traces:
            v = np.array([x[0] for x in rows], float)
            lag = np.array([x[1] for x in rows])
            c = int(np.clip(c, 0, len(rows) - 1))
            lock = (v > lthr) & (np.abs(lag - lag[c]) <= R.LAG_TOL)
            if not lock[c]:
                continue
            for k in np.where(C.grow(lock, c))[0]:
                if lock[k]:
                    out[r].append((pack, int(k), int(rows[k][3]) + int(t8.offs[r]), float(v[k]), pol))
        hays[pack] = T.wav_i16(wav)
        del H
    return out, hays


def runs_from_locks(locks, ncell):
    """Best lock per 20 ms cell, then runs of cells sharing pack, polarity and offset (+-2 ms)."""
    best = [None] * ncell
    for pack, k, D8, v, pol in locks:
        for cc in range(k, min(ncell, k + C.WIN // C.STEP)):
            if best[cc] is None or v > best[cc][3]:
                best[cc] = (pack, k, D8, v, pol)
    runs, cur = [], None
    for cc, b in enumerate(best):
        if b is not None and cur and b[0] == cur["pack"] and b[4] == cur["pol"] \
                and abs(b[2] - cur["D8"]) <= R.LAG_TOL and cc == cur["c1"]:
            cur["c1"] = cc + 1
            cur["D8s"].append(b[2])
            continue
        if cur:
            runs.append(cur)
        cur = None if b is None else {"pack": b[0], "pol": b[4], "D8": b[2], "D8s": [b[2]], "c0": cc, "c1": cc + 1}
    if cur:
        runs.append(cur)
    for u in runs:
        u["D8"] = int(np.median(u["D8s"]))
        del u["D8s"]
    return runs


def real_high(run, hay, t8_22, t8_16):
    """The run's pack audio on tom8's 16 kHz grid -> (high band, frame NCCs, info), gain-matched.

    run["D8"] is the 8 kHz corpus index of the recording's sample 0, so the 22 kHz corpus
    index of recording-local 22 kHz sample i is i + D8 * 441 / 160 (8k corpus = 22k x 160/441).
    """
    c0, c1 = run["c0"], run["c1"]
    base22 = run["D8"] * 441 / 160
    a22, b22 = c0 * CELL22, c1 * CELL22
    i0 = int(np.floor(a22 + base22)) - R22 - 1200
    i1 = int(np.ceil(b22 + base22)) + R22 + 1200
    if i0 < 0 or i1 > len(hay):
        return None
    blk = np.asarray(hay[i0:i1], np.float64) * run["pol"]
    ref = t8_22[a22:b22]
    if len(ref) < 64:
        return None
    blk_bp = zconv(blk, BP_ALIGN22)
    ref_bp = zconv(np.r_[np.zeros(1200), ref, np.zeros(1200)], BP_ALIGN22)[1200:-1200]
    st = int(np.floor(a22 + base22)) - i0
    seg = blk_bp[st - R22:st + R22 + len(ref_bp)]
    num = np.correlate(seg, ref_bp, mode="valid")
    c1s = np.r_[0, np.cumsum(seg ** 2)]
    den = np.sqrt(np.maximum(c1s[len(ref_bp):] - c1s[:-len(ref_bp)], 1e-9)) * (np.linalg.norm(ref_bp) or 1e-9)
    ncc = num / den
    k = int(np.argmax(ncc))
    fr = 0.0
    if 0 < k < len(ncc) - 1:
        y0, y1, y2 = ncc[k - 1], ncc[k], ncc[k + 1]
        dd = y0 - 2 * y1 + y2
        fr = 0.5 * (y0 - y2) / dd if dd else 0.0
    pos = st - R22 + k + fr                     # block index of tom8's a22
    pi = int(np.floor(pos))
    pf = pos - pi
    lo = pi - M22
    hi = pi + (b22 - a22) + M22
    if lo < 0 or hi > len(blk):
        return None
    sh = frac_shift(blk[lo:hi + 2], pf)[:hi - lo]
    yf = sg.resample_poly(sh, 320, 441)
    n16 = (c1 - c0) * CELL16
    if len(yf) < 640 + n16:
        return None
    _, hf = split(yf)                           # filter with the margins, then crop
    y16, h16 = yf[640:640 + n16], hf[640:640 + n16]
    ref16 = t8_16[c0 * CELL16:c1 * CELL16]
    g_ref = np.sqrt(np.mean(zconv(ref16, BP_GAIN16) ** 2))
    g_y = np.sqrt(np.mean(zconv(y16, BP_GAIN16) ** 2)) or 1e-9
    g = g_ref / g_y
    y16, h16 = y16 * g, h16 * g
    a_bp, b_bp = zconv(y16, BP_NCC16), zconv(ref16, BP_NCC16)
    fn = []
    for j in range(c1 - c0):
        u, w = a_bp[j * CELL16:(j + 1) * CELL16], b_bp[j * CELL16:(j + 1) * CELL16]
        fn.append(float(np.dot(u, w) / ((np.linalg.norm(u) * np.linalg.norm(w)) or 1e-9)))
    return h16, np.array(fn), {"ncc22": float(ncc[k]), "shift22": float(k - R22 + fr), "gain_db": float(20 * np.log10(g))}


def spectro(path, title, sigs, mask):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(len(sigs), 1, figsize=(11, 2.3 * len(sigs)), sharex=True)
    for a, (nm, x) in zip(ax, sigs):
        f, t, S = sg.spectrogram(x, 16000, nperseg=512, noverlap=384)
        a.pcolormesh(t, f, 10 * np.log10(S + 1e-6), shading="auto", vmin=-10, vmax=60, cmap="magma")
        a.set_ylabel(nm, fontsize=8)
        a.axhline(XOVER, color="c", lw=0.6, ls="--")
        tm = np.arange(len(mask)) / 16000
        a.fill_between(tm, 7600, 8000, where=mask > 0.5, color="lime", step="mid")
    ax[0].set_title(title + "   (green bar = real 22 kHz high band)", fontsize=9)
    ax[-1].set_xlabel("s")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recs", nargs="*", default=DEFAULT_RECS)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    thr = json.loads((T.OUT / "xpack_W1600.json").read_text())["thresholds"]
    t8 = T.Search(C.WS)
    tom8 = np.asarray(t8.s.full, np.float32)
    ends = np.r_[t8.offs[1:], len(tom8)]
    recs = [t8.names.index(n) for n in a.recs]
    locks, hays = find_locks(t8, tom8, ends, recs, thr)

    report, cat = [], {k: [] for k in ("A_tom8", "B_audiosr", "C_hybrid", "D_realonly")}
    gap = np.zeros(8000)
    for r in recs:
        nm = t8.names[r]
        s0, s1 = int(t8.offs[r]), int(ends[r])
        x8 = tom8[s0:s1].astype(np.float64)
        t8_16 = sg.resample_poly(x8, 2, 1)
        t8_22 = sg.resample_poly(x8, 441, 160)
        asr = tom16_slice(s0, s1 - s0)
        n16 = len(t8_16)
        assert len(asr) == n16
        ncell = n16 // CELL16
        runs = runs_from_locks(locks[r], ncell)
        hi_real = np.zeros(n16)
        mcell = np.zeros(ncell, bool)
        rinfo = []
        rms8 = np.sqrt(np.mean(x8[:ncell * C.STEP].reshape(ncell, C.STEP) ** 2, 1))
        for u in runs:
            got = real_high(u, hays[u["pack"]], t8_22, t8_16)
            if got is None:
                continue
            h16, fn, info = got
            ok = (fn >= FRAME_NCC) | (rms8[u["c0"]:u["c1"]] < 200)
            hi_real[u["c0"] * CELL16:u["c1"] * CELL16] = h16
            mcell[u["c0"]:u["c1"]] |= ok
            rinfo.append({**{k: u[k] for k in ("pack", "c0", "c1")}, **info,
                          "frames_ok": float(ok.mean()), "frame_ncc_p50": float(np.median(fn))})
        m = np.repeat(mcell, CELL16).astype(float)
        m = np.r_[m, np.zeros(n16 - len(m))]
        er = np.convolve(m, np.ones(161) / 161, mode="same") > 0.999     # shrink 5 ms each side
        w = np.hanning(161)
        m = np.convolve(er.astype(float), w / w.sum(), mode="same")

        lo8, _ = split(t8_16)
        _, hi_asr = split(asr)
        sel = (m > 0.99) & (np.abs(lo8) > 0)
        e_r = np.sqrt(np.mean(hi_real[sel] ** 2)) if sel.sum() > 1600 else np.nan
        e_a = np.sqrt(np.mean(hi_asr[sel] ** 2)) if sel.sum() > 1600 else np.nan
        asr_g = e_r / e_a if np.isfinite(e_r) and e_a > 0 else 1.0
        hi_coh = float(np.dot(hi_real[sel], hi_asr[sel]) /
                       ((np.linalg.norm(hi_real[sel]) * np.linalg.norm(hi_asr[sel])) or 1e-9)) if sel.sum() > 1600 else np.nan
        hyb = lo8 + m * hi_real + (1 - m) * asr_g * hi_asr
        variants = {"A_tom8": lo8, "B_audiosr": asr, "C_hybrid": hyb, "D_realonly": lo8 + m * hi_real}
        for k, v in variants.items():
            sf.write(OUT / f"{nm}_{k}.wav", np.clip(v, -32768, 32767).astype(np.int16), 16000)
            cat[k] += [v, gap]
        spectro(OUT / f"{nm}.png", nm, [("tom8 x2", lo8), ("AudioSR", asr), ("hybrid", hyb)], m)
        sp = np.repeat(rms8 > max(200.0, np.percentile(rms8, 20)), CELL16)
        sp = np.r_[sp, np.zeros(n16 - len(sp), bool)]
        row = {"rec": nm, "sec": n16 / 16000, "speech_real_hi": float((m[sp] > 0.5).mean()),
               "runs": rinfo, "asr_hi_vs_real_db": float(20 * np.log10(1 / asr_g)) if asr_g > 0 else None,
               "hi_band_ncc_real_vs_asr": hi_coh}
        report.append(row)
        g = [x["gain_db"] for x in rinfo]
        n22 = [x["ncc22"] for x in rinfo]
        print(f"{nm:12} {row['sec']:4.1f}s  real high band on {row['speech_real_hi']:4.0%} of speech  "
              f"runs {len(rinfo):2d} (SS {sum(x['pack'] == 'ss' for x in rinfo)}, RS {sum(x['pack'] == 'rs' for x in rinfo)})  "
              f"align NCC p50 {np.median(n22) if n22 else float('nan'):.3f}  gain {np.median(g) if g else float('nan'):+.1f} dB  "
              f"AudioSR hi vs real {row['asr_hi_vs_real_db'] or 0:+.1f} dB  hi-band NCC real/ASR {hi_coh:.2f}", flush=True)
    for k, v in cat.items():
        sf.write(OUT / f"ALL_{k}.wav", np.clip(np.concatenate(v), -32768, 32767).astype(np.int16), 16000)
    ab = []
    for i in range(0, len(cat["B_audiosr"]), 2):
        ab += [cat["B_audiosr"][i], gap[:4000], cat["C_hybrid"][i], gap]
    sf.write(OUT / "ALL_B_then_C.wav", np.clip(np.concatenate(ab), -32768, 32767).astype(np.int16), 16000)
    (OUT / "report.json").write_text(json.dumps(report, indent=1))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
