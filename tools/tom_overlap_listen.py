"""Export the longest locked spans as time-aligned STEREO pairs: L = Speechify tom8, R = SS/RS.

Both channels at 8 kHz, cut to the same span with 150 ms of context, the SS/RS side
polarity-corrected and lag-corrected so the two are sample-aligned. In phase they
should sound like one voice in the middle of the stereo field.

    python -I tom_overlap_listen.py --top 12
"""
import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tom_overlap as T  # noqa: E402
import vdb_index as vx  # noqa: E402

STEP, WIN, LAG_TOL, CTX = 160, 800, 16, 1200


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()
    full, _, entries = vx.load(T.TOM8)
    offs = np.array([e[0] for e in entries])
    out_dir = T.OUT / "listen"
    out_dir.mkdir(exist_ok=True)
    listing = []
    for pack, wav in (("ss", T.SS_WAV), ("rs", T.RS_WAV)):
        d = json.loads((T.OUT / f"runs_{pack}_W1600.json").read_text())
        src = T.wav_i16(wav)
        lthr = d["local_null_p99"]
        cands = []
        for h in d["hits"]:
            rows = h["rows"]
            v = np.array([np.nan if r[1] is None else r[1] for r in rows], dtype=float)
            lag = np.array([r[2] for r in rows])
            c = len(rows) // 2
            if not (np.isfinite(v[c]) and v[c] > lthr):
                continue
            same = np.where((v > lthr) & (np.abs(lag - lag[c]) <= LAG_TOL))[0]
            cands.append((same[-1] - same[0], h, same[0] - c, same[-1] - c, int(lag[c])))
        cands.sort(key=lambda t: -t[0])
        for rank, (_, h, k0, k1, lag0) in enumerate(cands[:a.top]):
            # window-centre coordinates used by tom_overlap_runs.py
            y_c = h["y0"] + 1600 // 2 - WIN // 2 + lag0
            y_lo = y_c + k0 * STEP - CTX
            y_hi = y_c + k1 * STEP + WIN + CTX
            x_c8 = h["x0"] * 160 / 441 + 1600 // 2 - WIN // 2
            x_lo22 = int((x_c8 + k0 * STEP - CTX) * 441 / 160)
            n8 = y_hi - y_lo
            sp = np.asarray(full[y_lo:y_hi], dtype=np.float64)
            ss = T.cut8k(src, x_lo22, n8).astype(np.float64)
            # polarity from the aligned pair itself
            if np.dot(sp - sp.mean(), ss - ss.mean()) < 0:
                ss = -ss
            core = slice(CTX, len(sp) - CTX)
            a_ = sp[core] - sp[core].mean()
            best_sh, span_ncc = 0, -2.0
            for sh in range(-200, 201):
                b_ = ss[CTX + sh:len(sp) - CTX + sh]
                b_ = b_ - b_.mean()
                r_ = float(np.dot(a_, b_) / (np.linalg.norm(a_) * np.linalg.norm(b_) + 1e-9))
                if r_ > span_ncc:
                    best_sh, span_ncc = sh, r_
            if best_sh:
                ss = np.roll(ss, -best_sh)
            # voiced-energy share of the core: ACELP keeps voiced waveforms, not noise
            fr = sp[core][: len(sp[core]) // 160 * 160].reshape(-1, 160)
            zc = np.mean(np.abs(np.diff(np.sign(fr), axis=1)) > 0, axis=1)
            en = (fr ** 2).sum(1)
            voiced_share = float(en[zc < 0.15].sum() / (en.sum() + 1e-9))
            g = (np.std(sp) or 1) / (np.std(ss) or 1)
            st = np.stack([sp, ss * g], 1)
            name = f"{pack}_{rank:02d}.wav"
            with wave.open(str(out_dir / name), "wb") as w:
                w.setnchannels(2)
                w.setsampwidth(2)
                w.setframerate(8000)
                w.writeframes(np.clip(st, -32768, 32767).astype("<i2").tobytes())
            rec = entries[max(0, int(np.searchsorted(offs, y_c, side="right")) - 1)][1]
            span = int((k1 - k0) * 20 + 100)
            listing.append({"file": name, "tom8_rec": rec, "span_ms": span,
                            "hit_ncc": float(h["ncc"]), "span_ncc": span_ncc,
                            "realign_8k": best_sh, "voiced_energy_share": voiced_share})
            print(f"{name}  {rec:22} span {span:5d} ms  hit {h['ncc']:.3f}  "
                  f"span NCC {span_ncc:.3f} (realign {best_sh:+4d})  voiced energy {voiced_share:.0%}")
    (out_dir / "listen.json").write_text(json.dumps(listing, indent=1))
    print(f"\n{len(listing)} stereo pairs in {out_dir}  (L = Speechify tom8, R = ScanSoft/RealSpeak)")


if __name__ == "__main__":
    main()
