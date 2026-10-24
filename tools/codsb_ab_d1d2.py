"""A/B the codsb decoder before/after the D1 (pitch sharpening) + D2 (DC-block) fixes.

Decodes the same span with both executables and reports, per voice:
  - share of subframes whose pitch lag < 80 (where D1 can act)
  - DC offset and energy below 40 Hz (what D2 should remove)
  - RMS, clipping, and the residual between the two decodes in the lag<80 vs lag>=80 frames
"""
import csv, os, subprocess, sys, tempfile, wave
from concurrent.futures import ThreadPoolExecutor
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SSRS_RE = os.path.join(os.path.dirname(ROOT), "ssrs_re")

CODSB = SSRS_RE + r"\codsb\build"
OLD = os.path.join(CODSB, "codsb_dump_pre_d1d2.exe")
NEW = os.path.join(CODSB, "codsb_dump.exe")
DATA = {
    "SS tom":      ROOT + r"\ScanSoft\speech\components\data\vf_tom_full_155mrf22_270_06.dat",
    "SS kyoko":    ROOT + r"\ScanSoft\speech\components\data\vf_kyoko_full_155mrf22_270_06.dat",
    "RS samantha": ROOT + r"\RealSpeak\speech\components\data\vf_samantha_full_155mrf22_270_06.dat",
}
START, COUNT, SR, FRAME = 200_000, 3000, 22050, 320


def decode(exe, dat, wav):
    subprocess.run([exe, dat, "--wav", wav, "--start", str(START), "--count", str(COUNT)],
                   check=True, stdout=subprocess.DEVNULL)
    with wave.open(wav) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64)


def lags(dat, csv_path):
    subprocess.run([NEW, dat, "--start", str(START), "--count", str(COUNT), "--csv", csv_path],
                   check=True, stdout=subprocess.DEVNULL)
    out = []
    with open(csv_path) as f:
        r = csv.DictReader(f)
        for row in r:
            prev, fr = 0, []
            for s in range(4):
                idx = int(row[f"sf{s}_lag"])
                lag = idx + 54 if s % 2 == 0 else prev - 15 + idx
                prev = lag
                fr.append(lag)
            out.append(fr)
    return np.array(out)


def low_band_db(x):
    spec = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return 10 * np.log10(spec[(f > 0) & (f < 40)].sum() / spec[f >= 40].sum() + 1e-30)


def one(item):
    name, dat = item
    tmp = tempfile.mkdtemp(prefix="codsb_ab_")
    a = decode(OLD, dat, os.path.join(tmp, "old.wav"))
    b = decode(NEW, dat, os.path.join(tmp, "new.wav"))
    lg = lags(dat, os.path.join(tmp, "f.csv"))
    short = (lg < 80).any(axis=1)
    frames_a = a.reshape(-1, FRAME)
    frames_b = b.reshape(-1, FRAME)
    # compare after removing what D2 removes, so the residual isolates D1
    hp = lambda x: x - np.convolve(x, np.ones(441) / 441, mode="same")
    ra, rb = hp(a).reshape(-1, FRAME), hp(b).reshape(-1, FRAME)
    def rel(mask):
        if not mask.any():
            return float("nan")
        num = ((ra[mask] - rb[mask]) ** 2).sum()
        return 10 * np.log10(num / ((ra[mask] ** 2).sum() + 1e-30) + 1e-30)
    return (name, (lg < 80).mean(), short.mean(), a.mean(), b.mean(), low_band_db(a), low_band_db(b),
            np.sqrt((a ** 2).mean()), np.sqrt((b ** 2).mean()),
            (np.abs(b) >= 32767).mean() * 100, rel(short), rel(~short))


def main():
    with ThreadPoolExecutor(len(DATA)) as ex:
        res = list(ex.map(one, DATA.items()))
    print(f"span: frames {START}..{START + COUNT} ({COUNT * FRAME / SR:.1f} s)\n")
    print(f"{'voice':12} {'sf lag<80':>9} {'fr lag<80':>9} {'DC old':>8} {'DC new':>8} "
          f"{'<40Hz old':>9} {'<40Hz new':>9} {'RMS old':>8} {'RMS new':>8} {'clip%':>6} "
          f"{'diff lag<80':>11} {'diff other':>10}")
    for r in res:
        print(f"{r[0]:12} {r[1]:9.1%} {r[2]:9.1%} {r[3]:8.1f} {r[4]:8.1f} {r[5]:8.1f}dB {r[6]:8.1f}dB "
              f"{r[7]:8.0f} {r[8]:8.0f} {r[9]:6.2f} {r[10]:9.1f}dB {r[11]:8.1f}dB")


if __name__ == "__main__":
    main()
