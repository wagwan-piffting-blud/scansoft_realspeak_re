"""Pre-flight for the 16 kHz hybrid: is AudioSR tom16.vdb sample-aligned to tom8 (x2), and
where does each source's spectrum actually stop?

    python -I hybrid16_probe.py
"""
import struct
import sys
from pathlib import Path

import numpy as np
from scipy import signal as sg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tom_overlap as T  # noqa: E402
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPFY = os.path.join(os.path.dirname(ROOT), "Speechify")

TOM16 = SPFY + r"\en-US\tom\audiosr_tom16.vdb"
DATA_OFF = 0x20960


def tom16_rec(off_bytes, n_bytes):
    with open(TOM16, "rb") as f:
        f.seek(DATA_OFF + off_bytes)
        b = np.frombuffer(f.read(n_bytes), np.uint8) ^ 0xCE
    return b.view("<i2").astype(np.float64)


def band_db(x, fs, edges):
    f, p = sg.welch(x, fs, nperseg=1024)
    return [10 * np.log10(p[(f >= a) & (f < b)].mean() + 1e-12) for a, b in edges]


def main():
    t8 = T.vdb_fast.VdbSearcher(T.TOM8, probe_len=320)
    full = np.asarray(t8.full, np.float64)
    offs = np.array([e[0] for e in t8.entries], np.int64)
    names = [e[1] for e in t8.entries]
    ends = np.r_[offs[1:], len(full)]
    picks = ["news7_030", "news5_038", "news19_061", "letter_088"]
    edges = [(0, 1000), (1000, 3000), (3000, 3500), (3500, 3800), (3800, 4000),
             (4000, 4500), (4500, 6000), (6000, 8000)]
    print("bands:", edges)
    for nm in picks:
        r = names.index(nm)
        x8 = full[offs[r]:ends[r]]
        x16 = sg.resample_poly(x8, 2, 1)
        a = tom16_rec(int(offs[r]) * 4, int(ends[r] - offs[r]) * 4)
        n = min(len(a), len(x16))
        lp = sg.firwin(255, 3400, fs=16000)
        al, xl = sg.filtfilt(lp, 1, a[:n]), sg.filtfilt(lp, 1, x16[:n])
        c = sg.correlate(al, xl, mode="full")
        mid = n - 1
        k = int(np.argmax(c[mid - 50:mid + 51])) - 50
        ncc0 = float(np.dot(al, xl) / (np.linalg.norm(al) * np.linalg.norm(xl)))
        g = float(np.linalg.norm(al) / np.linalg.norm(xl))
        print(f"{nm:12} len8 {len(x8)} len16 {len(a)}  lag {k:+d}  NCC@0 {ncc0:.4f}  gain {g:.3f}")
        print("   tom8 ", " ".join(f"{v:6.1f}" for v in band_db(x8, 8000, edges[:5])))
        print("   tom16", " ".join(f"{v:6.1f}" for v in band_db(a, 16000, edges)))
    ss = T.wav_i16(T.SS_WAV)
    rs = T.wav_i16(T.RS_WAV)
    e22 = edges + [(8000, 10000), (10000, 11025)]
    for nm, w in (("SS", ss), ("RS", rs)):
        x = np.asarray(w[22050 * 600:22050 * 660], np.float64)
        print(f"{nm} 22k   ", " ".join(f"{v:6.1f}" for v in band_db(x, 22050, e22)))


if __name__ == "__main__":
    main()
