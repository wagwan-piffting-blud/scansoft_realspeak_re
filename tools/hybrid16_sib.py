"""Why are /s/ sounds harsh in tom16_bwe.vdb? Sibilant frames, held-out recordings only.

Sibilant frame (from tom8 itself): 2.5-3.4 kHz carries >= 4x the 0-1 kHz power and the
frame is not silent. Per frame, every top-band spectrum is referenced to that frame's
tom8 2.5-3.4 kHz power, so loudness cancels and only the extension's shape/level remains.

Compared where the REAL band is verified: real, BWE build, AudioSR.
Also the 30-150 Hz AM roughness of the top band inside sibilant stretches.

    python -I hybrid16_sib.py
"""
import json
import sys
from pathlib import Path

import numpy as np
from scipy import signal as sg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hybrid16_demo as HD  # noqa: E402
import hybrid16_bwe as B  # noqa: E402
import hybrid16_rough as RG  # noqa: E402

BUILT = r"C:\tmp\hybrid16\tom16_bwe.vdb"
CAL = json.loads((B.OUT / "bwe_eval.json").read_text())
BANDS = [(3400, 4000), (4000, 5000), (5000, 6000), (6000, 7000), (7000, 8000)]


def vdb_slice(path, off8, n8):
    with open(path, "rb") as f:
        f.seek(HD.TOM16_DATA + 4 * off8)
        b = np.frombuffer(f.read(4 * n8), np.uint8) ^ 0xCE
    return b.view("<i2").astype(np.float64)


def spec(x):
    f, t, S = sg.stft(x, 16000, nperseg=512, noverlap=352, boundary=None, padded=False)
    return f, np.abs(S) ** 2


def main():
    tom8 = np.load(B.OUT / "tom8_f32.npy", mmap_mode="r")
    hi = np.load(B.OUT / "hi_real.f16.npy", mmap_mode="r")
    cell = np.load(B.OUT / "cell_ok.u8.npy")
    offs, names = B.entries()
    ends = np.r_[offs[1:], len(tom8)]
    acc = {k: [] for k in ("real", "bwe", "asr")}
    rough = {k: [] for k in ("real", "bwe", "asr", "bwe_d0")}
    nsib = 0
    for i, nm in enumerate(names):
        if not (i % 20 == 0 or nm in HD.DEFAULT_RECS):
            continue
        s0, s1 = int(offs[i]), int(ends[i])
        if s1 - s0 < 4000:
            continue
        c = cell[s0 // 160:s0 // 160 + (s1 - s0) // 160]
        if (c > 0).sum() < 10:
            continue
        x16 = sg.resample_poly(np.asarray(tom8[s0:s1], np.float64), 2, 1)
        lo, _ = HD.split(x16)
        real = np.asarray(hi[2 * s0:2 * s1], np.float64)[:len(x16)]
        _, bwe = HD.split(vdb_slice(BUILT, s0, s1 - s0)[:len(x16)])
        _, asr = HD.split(HD.tom16_slice(s0, s1 - s0)[:len(x16)])
        f, L = spec(x16)
        p_lo = L[(f < 1000)].sum(0)
        p_ref = L[(f >= 2500) & (f < 3400)].sum(0)
        tc = (np.arange(L.shape[1]) * 160 + 256)
        cov = np.repeat(c > 0, 320)
        cov = np.r_[cov, np.zeros(len(x16) - len(cov), bool)]
        sib = (p_ref >= 2 * p_lo) & (p_ref > np.percentile(p_ref, 30)) & cov[np.clip(tc, 0, len(cov) - 1)]
        if sib.sum() < 2:
            continue
        nsib += int(sib.sum())
        for k, h in (("real", real), ("bwe", bwe), ("asr", asr)):
            _, H = spec(h)
            rel = [10 * np.log10(H[(f >= a) & (f < b)].sum(0)[sib] / p_ref[sib] + 1e-12) for a, b in BANDS]
            acc[k].append(np.array(rel))
        m16 = np.zeros(len(x16), bool)
        for t in np.where(sib)[0]:
            m16[t * 160:t * 160 + 512] = True
        _, h0 = B.render2(x16, None, None, depth=0.0,
                          bias=np.asarray(CAL["rt_bias"], np.float32),
                          gain=CAL["rt_gain"])
        for k, h in (("real", real), ("bwe", bwe), ("asr", asr), ("bwe_d0", h0)):
            rough[k].append(h[m16])
    print(f"{nsib} sibilant frames with a verified real band\n")
    print("top band per sub-band, dB re the frame's tom8 2.5-3.4 kHz power (median):")
    print("            " + "  ".join(f"{a // 100 / 10:.1f}-{b // 100 / 10:.1f}k" for a, b in BANDS))
    med = {}
    for k, v in acc.items():
        v = np.concatenate(v, 1)
        med[k] = np.median(v, 1)
        print(f"  {k:6}  " + "  ".join(f"{x:+8.1f}" for x in med[k]))
    print("  bwe-real" + "  ".join(f"{x:+8.1f}" for x in med["bwe"] - med["real"]))
    print("  asr-real" + "  ".join(f"{x:+8.1f}" for x in med["asr"] - med["real"]))
    print("\nroughness inside sibilants (30-150 Hz AM of the top band):")
    for k, v in rough.items():
        v = np.concatenate(v)
        print(f"  {k:7} {RG.roughness(v, np.ones(len(v), bool)):.3f}")


if __name__ == "__main__":
    main()
