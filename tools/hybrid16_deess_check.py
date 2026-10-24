"""How much did each de-ess level remove, in sibilant vs non-sibilant frames, by band?

    python -I hybrid16_deess_check.py
"""
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal as sg

D = Path(r"C:\tmp\hybrid16_demo5")


def main():
    x = {k: sf.read(D / f"ALL_deess{k}.wav")[0] for k in (0, 4, 8)}
    f, t, S0 = sg.stft(x[0], 16000, nperseg=512, noverlap=352)
    P0 = np.abs(S0) ** 2
    sib = P0[(f >= 2500) & (f < 3400)].sum(0) >= 4 * P0[f < 1000].sum(0)
    voc = P0[f < 1000].sum(0) >= 4 * P0[(f >= 2500) & (f < 3400)].sum(0)
    for k in (4, 8):
        _, _, S = sg.stft(x[k], 16000, nperseg=512, noverlap=352)
        P = np.abs(S) ** 2
        for nm, fr in (("sibilant", sib), ("vowel", voc)):
            row = []
            for a, b in ((0, 3400), (3400, 4500), (4500, 6000), (6000, 8000)):
                bb = (f >= a) & (f < b)
                row.append(10 * np.log10(P[bb][:, fr].sum() / P0[bb][:, fr].sum()))
            print(f"deess {k}  {nm:8}  0-3.4k {row[0]:+5.1f}  3.4-4.5k {row[1]:+5.1f}  "
                  f"4.5-6k {row[2]:+5.1f}  6-8k {row[3]:+5.1f} dB")


if __name__ == "__main__":
    main()
