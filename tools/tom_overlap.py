"""Do the ScanSoft / RealSpeak Tom corpora contain the SAME RECORDINGS as Speechify's tom8.vdb?

All three are Tom Glynn, so "sounds like the same man" is a given and proves nothing.
The question is TAKE identity: the same physical recording, re-coded. Only a
phase-coherent waveform match can show that, so the statistic is normalised
cross-correlation (NCC) at 8 kHz, best over the whole of tom8.vdb, both polarities.

Arms (all at 8 kHz, all W samples long, all searched the same way):

    TEST     ScanSoft 2004 Tom, intact contiguous stretches from us_tom_full.dat
    CEIL     tom8 windows round-tripped through AMR-WB 23.85k (ACELP), searched
             back into tom8: what a TRUE same-recording match scores across an
             ACELP boundary
    F-TAKE   the CEIL probes' best hit OUTSIDE their own recording: same speaker,
             same codec, similar sounds, a DIFFERENT take. The null that matters.
    F-REV    the TEST stretches time-reversed: same spectra, no waveform match
    F-SPK    SS Kyoko windows: different speaker
    B-SS     SS Tom blind windows (no segmentation), the comparator for B-RS
    B-RS     RS 2006 Tom blind windows (its position lane is not mapped yet)

Verdict rule, fixed before the run: a probe is a HIT if its NCC exceeds the
99.9th percentile of F-TAKE. Sensitivity = CEIL hit rate. If TEST's hit rate is
indistinguishable from F-REV / F-SPK, no shared recordings are detectable.

    python -I tom_overlap.py --W 1600 --n 3000
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
import torch
from scipy import signal as sg
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPFY = os.path.join(os.path.dirname(ROOT), "Speechify")

sys.path.insert(0, SPFY + r"\reveng\spfy4\tools")
import vdb_fast  # noqa: E402

TOM8 = SPFY + r"\en-US\tom\tom8.vdb"
SS_USELD = ROOT + r"\ScanSoft\speech\components\data\us_tom_full.dat"
CORPUS = r"C:\tmp\nomorekillmyvibe\codsb_corpus"
SS_WAV = ROOT + r"\ScanSoft\ss_tom_full.wav"     # fresh codsb_dump (D1+D2), SSoT
RS_WAV = ROOT + r"\RealSpeak\rs_tom_full.wav"     # fresh codsb_dump (D1+D2), SSoT
KY_WAV = os.path.join(CORPUS, "ctl_nextup_kyoko.wav")
OUT = Path(r"C:\tmp\tom_overlap")

N_UNITS = 324_263
REC_OFF = 0x2079EC4          # 16-byte unit records, ss_rs §4
TICK_TO_22K = 2.205          # pos is 100 us ticks, ss_rs §6
AUDIO_OFF_22K = -1764        # unit audio sits 80 ms before pos*2.205, ss_rs §6 (11.9 sd)
TRIM_8K = 160                # 20 ms guard against the offset's residual error
PAD = 128                    # fine-stage search radius, full rate
TOPK = 64


def wav_i16(path):
    with wave.open(path) as w:
        assert w.getframerate() == 22050 and w.getsampwidth() == 2
    return np.memmap(path, dtype="<i2", mode="r", offset=44)


def to8k(x22):
    return sg.resample_poly(np.asarray(x22, dtype=np.float64), 160, 441)


def cut8k(src22, start22, W):
    """W samples at 8 kHz starting at 22 kHz index start22, resampled with margins."""
    m = 400
    lo = max(0, start22 - m)
    seg = src22[lo:start22 + int(W * 441 / 160) + m]
    y = to8k(seg)
    o = int(round((start22 - lo) * 160 / 441))
    return y[o:o + W].astype(np.float32)


# ---------------------------------------------------------------- probe sets
def ss_stretches(W):
    raw = np.memmap(SS_USELD, dtype=np.uint8, mode="r", offset=REC_OFF, shape=(N_UNITS, 16))
    pos = raw[:, :4].copy().view("<u4").ravel() & 0x7FFFFFFF
    ln = (raw[:, 11].astype(np.int64) << 4) | (raw[:, 12] >> 4)
    ph = raw[:, 9].copy()
    o = np.argsort(pos, kind="stable")
    pos, ln, ph = pos[o].astype(np.int64), ln[o], ph[o]
    brk = np.r_[0, np.where(pos[1:] != pos[:-1] + ln[:-1])[0] + 1, len(pos)]
    out = []
    for a, b in zip(brk[:-1], brk[1:]):
        dur8 = (pos[b - 1] + ln[b - 1] - pos[a]) * 0.8          # ticks -> 8 kHz samples
        if dur8 >= W + 2 * TRIM_8K:
            s22 = int(round(pos[a] * TICK_TO_22K)) + AUDIO_OFF_22K + int(TRIM_8K * 441 / 160)
            out.append((s22, bytes(ph[a:b]).decode("latin1")))
    return out


def gate(probes, frac=0.4):
    r = np.array([np.sqrt(np.mean(p.astype(np.float64) ** 2)) for p in probes])
    return r >= np.quantile(r, frac)


def blind(src22, W, n, rng):
    span = len(src22) - int(W * 441 / 160) - 1000
    starts = rng.integers(1000, span, size=int(n * 1.8))
    pr = [cut8k(src22, int(s), W) for s in starts]
    keep = gate(pr)
    pr = [p for p, k in zip(pr, keep) if k][:n]
    return pr, [int(s) for s, k in zip(starts, keep) if k][:n]


def amr_wb_roundtrip(windows8, tmp):
    """Concatenate with 0.25 s gaps, AMR-WB 23.85k through ffmpeg, cut back out."""
    gap = np.zeros(2000, np.float32)
    x8 = np.concatenate([np.concatenate([w, gap]) for w in windows8])
    x16 = sg.resample_poly(x8, 2, 1)
    raw_in, amr, raw_out = (os.path.join(tmp, n) for n in ("in.raw", "x.amr", "out.raw"))
    np.clip(x16, -32768, 32767).astype("<i2").tofile(raw_in)
    q = ["-hide_banner", "-loglevel", "error", "-y"]
    subprocess.run(["ffmpeg", *q, "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", raw_in,
                    "-c:a", "libvo_amrwbenc", "-b:a", "23.85k", amr], check=True)
    subprocess.run(["ffmpeg", *q, "-i", amr, "-f", "s16le", "-ar", "16000", "-ac", "1", raw_out],
                   check=True)
    y16 = np.fromfile(raw_out, dtype="<i2").astype(np.float64)
    y8 = sg.resample_poly(y16, 1, 2)
    # global codec delay from the whole signal
    n = min(len(x8), len(y8), 400_000)
    c = sg.correlate(y8[:n], x8[:n], mode="full", method="fft")
    d = int(np.argmax(c[n - 1:n - 1 + 400]))
    W = len(windows8[0])
    out, p = [], 0
    for w in windows8:
        out.append(y8[p + d:p + d + W].astype(np.float32))
        p += W + len(gap)
    return out, d


# ------------------------------------------------------------------- search
class Search:
    def __init__(self, W):
        self.s = vdb_fast.VdbSearcher(TOM8, probe_len=W)
        self.W = W
        self.full_t = torch.from_numpy(np.asarray(self.s.full, dtype=np.float32)).cuda()
        self.offs = np.array([e[0] for e in self.s.entries], dtype=np.int64)
        self.names = [e[1] for e in self.s.entries]

    def rec(self, pos):
        return np.clip(np.searchsorted(self.offs, pos, side="right") - 1, 0, len(self.offs) - 1)

    def fine(self, probes, cand):
        """Exact NCC around every coarse candidate, on the GPU. -> values, positions (P, K)."""
        W, N = self.W, self.full_t.numel()
        L = W + 2 * PAD
        P, K = cand.shape
        st = np.clip(cand * self.s.decim - PAD, 0, N - L)
        st_t = torch.from_numpy(st).cuda()
        idx = st_t.unsqueeze(-1) + torch.arange(L, device="cuda")
        seg = self.full_t[idx]                                        # P,K,L
        pr = torch.from_numpy(np.asarray(probes, np.float32)).cuda()
        pr = pr - pr.mean(1, keepdim=True)
        pn = pr.norm(dim=1).clamp_min(1e-6)
        nf = 1 << int(np.ceil(np.log2(L + W)))
        corr = torch.fft.irfft(torch.fft.rfft(seg, nf) *
                               torch.conj(torch.fft.rfft(pr, nf)).unsqueeze(1), nf)[..., :2 * PAD + 1]
        seg64 = seg.double()
        c1 = torch.nn.functional.pad(seg64.cumsum(-1), (1, 0))
        c2 = torch.nn.functional.pad((seg64 * seg64).cumsum(-1), (1, 0))
        e = c2[..., W:W + 2 * PAD + 1] - c2[..., :2 * PAD + 1]
        m = (c1[..., W:W + 2 * PAD + 1] - c1[..., :2 * PAD + 1]) / W
        den = torch.sqrt((e - W * m * m).clamp_min(0)).clamp_min(vdb_fast.SIL_FLOOR_RMS * np.sqrt(W))
        ncc = corr.double() / (den * pn.double().view(P, 1, 1))
        v, j = ncc.max(-1)
        return v.cpu().numpy(), st + j.cpu().numpy()

    def run(self, probes, both_pol=True, batch=256):
        """-> dict of per-probe best, best_pos, best_rec, best_other_rec (NCC)."""
        res = {"v": [], "p": [], "r": [], "v_other": [], "pol": []}
        for i in range(0, len(probes), batch):
            grp = [np.asarray(x, np.float32) for x in probes[i:i + batch]]
            sets = [(grp, 1)] + ([([-x for x in grp], -1)] if both_pol else [])
            vs, ps, pols = [], [], []
            for g, pol in sets:
                cand = self.s._coarse(g, TOPK)
                v, p = self.fine(g, cand)
                vs.append(v)
                ps.append(p)
                pols.append(np.full(v.shape, pol))
            v, p, pol = np.concatenate(vs, 1), np.concatenate(ps, 1), np.concatenate(pols, 1)
            r = self.rec(p)
            for k in range(len(grp)):
                j = int(np.argmax(v[k]))
                other = v[k][r[k] != r[k][j]]
                res["v"].append(float(v[k][j]))
                res["p"].append(int(p[k][j]))
                res["r"].append(int(r[k][j]))
                res["pol"].append(int(pol[k][j]))
                res["v_other"].append(float(other.max()) if other.size else float("nan"))
        return {k: np.array(x) for k, x in res.items()}


def q(x):
    x = x[np.isfinite(x)]
    return {k: float(np.quantile(x, f)) for k, f in
            (("p50", .5), ("p90", .9), ("p99", .99), ("p999", .999), ("max", 1.0))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--W", type=int, default=1600)
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--hits", type=int, default=24, help="audio pairs to export for listening")
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    OUT.mkdir(parents=True, exist_ok=True)
    W = a.W

    S = Search(W)
    S.s.verify()
    full = np.asarray(S.s.full, dtype=np.float32)

    # CEIL / F-TAKE: windows inside one recording, away from its edges
    ends = np.r_[S.offs[1:], len(full)]
    long_recs = np.where(ends - S.offs > W + 4000)[0]
    picks = []
    while len(picks) < int(a.n * 1.8):
        r = int(rng.choice(long_recs))
        s = int(rng.integers(S.offs[r] + 1000, ends[r] - W - 1000))
        picks.append((s, r))
    clean = [full[s:s + W] for s, _ in picks]
    keep = gate(clean)
    picks = [pk for pk, k in zip(picks, keep) if k][:a.n]
    with tempfile.TemporaryDirectory() as tmp:
        ceil_pr, delay = amr_wb_roundtrip([full[s:s + W] for s, _ in picks], tmp)

    ss_all = ss_stretches(W)
    sel = rng.choice(len(ss_all), size=min(int(a.n * 1.8), len(ss_all)), replace=False)
    ss22 = wav_i16(SS_WAV)
    test_pr = [cut8k(ss22, ss_all[i][0], W) for i in sel]
    keep = gate(test_pr)
    test_idx = [int(i) for i, k in zip(sel, keep) if k][:a.n]
    test_pr = [p for p, k in zip(test_pr, keep) if k][:a.n]

    arms = {
        "CEIL (tom8 via AMR-WB)": (ceil_pr, False),
        "TEST SS stretches": (test_pr, True),
        "F-REV SS reversed": ([p[::-1].copy() for p in test_pr], True),
        "F-SPK Kyoko": (blind(wav_i16(KY_WAV), W, a.n, rng)[0], True),
        "B-SS blind windows": (blind(ss22, W, a.n, rng)[0], True),
        "B-RS blind windows": (blind(wav_i16(RS_WAV), W, a.n, rng)[0], True),
    }
    res = {name: S.run(pr, both_pol=bp) for name, (pr, bp) in arms.items()}

    c = res["CEIL (tom8 via AMR-WB)"]
    true_s = np.array([s for s, _ in picks])
    true_r = np.array([r for _, r in picks])
    found = (np.abs(c["p"] - true_s) <= 64) & (c["r"] == true_r)
    # F-TAKE: best score outside the probe's own recording
    ftake = np.where(c["r"] == true_r, c["v_other"], c["v"])
    thr = float(np.quantile(ftake[np.isfinite(ftake)], 0.999))

    summary = {"W": W, "W_ms": W / 8, "codec_delay_8k": delay, "threshold_p999_FTAKE": thr,
               "ceil_found_true_position": float(found.mean()), "arms": {}}
    rows = [("CEIL true position", c["v"][found]), ("F-TAKE other take", ftake)]
    rows += [(k, v["v"]) for k, v in res.items() if not k.startswith("CEIL")]
    for name, v in rows:
        summary["arms"][name] = {"n": int(np.isfinite(v).sum()), **q(v),
                                 "hit_rate": float(np.mean(v[np.isfinite(v)] > thr))}
    (OUT / f"summary_W{W}.json").write_text(json.dumps(summary, indent=1))

    print(f"\nW = {W} samples ({W/8:.0f} ms) at 8 kHz; AMR-WB delay {delay}; "
          f"CEIL found its true position {found.mean():.1%}")
    print(f"HIT threshold = F-TAKE p99.9 = {thr:.4f}\n")
    print(f"{'arm':26} {'n':>5} {'p50':>7} {'p90':>7} {'p99':>7} {'p99.9':>7} {'max':>7} {'hit rate':>9}")
    for name, s in summary["arms"].items():
        print(f"{name:26} {s['n']:5d} {s['p50']:7.4f} {s['p90']:7.4f} {s['p99']:7.4f} "
              f"{s['p999']:7.4f} {s['max']:7.4f} {s['hit_rate']:9.2%}")

    # export the strongest TEST hits for listening, with what they matched
    t = res["TEST SS stretches"]
    order = np.argsort(-t["v"])[:a.hits]
    hd = OUT / f"hits_W{W}"
    hd.mkdir(exist_ok=True)
    listing = []
    for rank, k in enumerate(order):
        p = int(t["p"][k])
        sp = full[max(0, p - 800):p + W + 800] * t["pol"][k]
        ss = cut8k(ss22, ss_all[test_idx[k]][0] - int(800 * 441 / 160), W + 1600)
        for tag, x in (("spfy", sp), ("ss", ss)):
            with wave.open(str(hd / f"{rank:02d}_{tag}.wav"), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(8000)
                w.writeframes(np.clip(x, -32768, 32767).astype("<i2").tobytes())
        rname = S.names[int(t["r"][k])]
        listing.append({"rank": rank, "ncc": float(t["v"][k]), "best_other_rec": float(t["v_other"][k]),
                        "spfy_rec": rname, "spfy_pos": p, "pol": int(t["pol"][k]),
                        "ss_phones": ss_all[test_idx[k]][1]})
        print(f"  hit {rank:02d}  ncc {t['v'][k]:.4f}  2nd-rec {t['v_other'][k]:.4f}  "
              f"{rname:28}  ss phones {ss_all[test_idx[k]][1]!r}")
    (hd / "hits.json").write_text(json.dumps(listing, indent=1))
    print(f"\nwrote {OUT / f'summary_W{W}.json'} and {len(order)} listening pairs in {hd}")


if __name__ == "__main__":
    main()
