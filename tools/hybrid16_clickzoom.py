"""Zoom on the user's arrowed events in CMP_8k_asr_h3.wav: what are they, how long, which source?

Sentence 1 sits at 5.25 s (AudioSR) and 10.5 s (H3) in that file. Per arrow: a 300 ms
high-resolution spectrogram, plus the event's duration above 6 kHz.

    python -I hybrid16_clickzoom.py
"""
import numpy as np
import soundfile as sf
from scipy import signal as sg
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

F = r"C:\tmp\spfy16k_test\CMP_8k_asr_h3.wav"
ARROWS = [("AudioSR", 6.8), ("AudioSR", 7.4), ("AudioSR", 9.4), ("H3", 11.85), ("H3", 12.75), ("H3", 14.95)]


def main():
    x, fs = sf.read(F)
    hp = sg.butter(6, 6000, btype="high", fs=fs, output="sos")
    xh = sg.sosfiltfilt(hp, x)
    fig, ax = plt.subplots(2, len(ARROWS), figsize=(3.2 * len(ARROWS), 6.5))
    for k, (src, t0) in enumerate(ARROWS):
        a, b = int((t0 - 0.25) * fs), int((t0 + 0.25) * fs)
        seg, segh = x[a:b], xh[a:b]
        e = np.sqrt(np.convolve(segh ** 2, np.ones(32) / 32, mode="same"))
        pk = int(np.argmax(e))
        above = e > 0.25 * e[pk]
        lo = pk
        while lo > 0 and above[lo - 1]:
            lo -= 1
        hi = pk
        while hi < len(above) - 1 and above[hi + 1]:
            hi += 1
        dur_ms = (hi - lo) / fs * 1000
        f, t, S = sg.spectrogram(seg, fs, nperseg=128, noverlap=112)
        ax[0, k].pcolormesh(t + t0 - 0.25, f, 10 * np.log10(S + 1e-10), shading="auto", vmin=-90, vmax=-20, cmap="magma")
        ax[0, k].set_title(f"{src} @{t0:.2f}s\n>6k event {dur_ms:.1f} ms at {t0 - 0.25 + pk / fs:.3f}s", fontsize=8)
        tt = np.arange(len(seg)) / fs + t0 - 0.25
        ax[1, k].plot(tt, seg, lw=0.5)
        ax[1, k].plot(tt, segh * 4, lw=0.5, color="r")
        ax[1, k].set_xlim(t0 - 0.25 + pk / fs - 0.03, t0 - 0.25 + pk / fs + 0.03)
        print(f"{src:7} arrow {t0:5.2f}s  strongest >6 kHz event at {t0 - 0.25 + pk / fs:.3f}s, "
              f"width {dur_ms:5.1f} ms, peak >6k rms {e[pk]:.4f}, local full-band rms {np.sqrt(np.mean(seg ** 2)):.4f}")
    ax[1, 0].set_ylabel("wave (blue) / >6 kHz x4 (red), +-30 ms")
    fig.tight_layout()
    fig.savefig(r"C:\tmp\spfy16k_test\clickzoom.png", dpi=100)


if __name__ == "__main__":
    main()
