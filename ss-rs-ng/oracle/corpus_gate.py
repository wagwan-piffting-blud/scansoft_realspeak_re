"""Gate: the emulator oracle must reproduce the real engine byte for byte.

Renders every corpus line through oracle/native (vendor DLLs on the real CPU)
and oracle/emu (the same DLLs under the interpreter), in parallel, and
compares the PCM. Exit status 0 only if every line matches.

    python corpus_gate.py [--pack realspeak|scansoft] [--voice Tom] [--corpus corpus_en.txt] [--out C:\\tmp\\ssrsng_gate]
"""
import argparse
import hashlib
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
NATIVE = os.path.join(HERE, "native", "build", "rs_native.exe")
EMU = os.path.join(HERE, "emu", "build", "rs_oracle.exe")
PACKS = {"realspeak": "RealSpeak", "scansoft": "ScanSoft"}
ESC = "\x1b"


def pcm_sha(path):
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha256(data[44:]).hexdigest()[:16], (len(data) - 44) // 2


def render(exe, speech, voice, out, text, product):
    t = time.perf_counter()
    r = subprocess.run([exe, speech, voice, out, text, product], capture_output=True, text=True)
    dt = time.perf_counter() - t
    if r.returncode != 0 or not os.path.exists(out):
        return None, 0, dt, (r.stdout + r.stderr)[-400:]
    sha, n = pcm_sha(out)
    return sha, n, dt, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="realspeak", choices=sorted(PACKS))
    ap.add_argument("--voice", default="Tom")
    ap.add_argument("--product", default="RealSpeak Solo v4.0")
    ap.add_argument("--corpus", default=os.path.join(HERE, "corpus_en.txt"))
    ap.add_argument("--out", default=r"C:\tmp\ssrsng_gate")
    args = ap.parse_args()
    speech = os.path.join(ROOT, PACKS[args.pack], "speech")
    os.makedirs(args.out, exist_ok=True)
    lines = [l.strip() for l in open(args.corpus, encoding="utf-8") if l.strip()]
    jobs = []
    for i, line in enumerate(lines):
        text = ESC + "\\vol=100\\" + line
        for kind, exe in (("native", NATIVE), ("emu", EMU)):
            out = os.path.join(args.out, "%s_%s_%02d_%s.wav" % (args.pack, args.voice.lower(), i, kind))
            jobs.append((i, kind, exe, out, text))
    with ThreadPoolExecutor(os.cpu_count()) as ex:
        res = list(ex.map(lambda j: (j[0], j[1]) + render(j[2], speech, args.voice, j[3], j[4], args.product), jobs))
    by = {}
    for i, kind, sha, n, dt, err in res:
        by.setdefault(i, {})[kind] = (sha, n, dt, err)
    bad = 0
    for i in range(len(lines)):
        nat, emu = by[i]["native"], by[i]["emu"]
        ok = nat[0] is not None and nat[0] == emu[0]
        bad += not ok
        print("%-4s %02d  %7.2f s audio  native %5.2fs  emu %5.2fs  %s  %s" % (
            "OK" if ok else "FAIL", i, nat[1] / 22050, nat[2], emu[2], nat[0], lines[i][:48]))
        for kind, r in (("native", nat), ("emu", emu)):
            if r[3]:
                print("      %s error: %s" % (kind, r[3].replace("\n", " | ")))
        if not ok and nat[0] and emu[0]:
            print("      emu sha %s, %d vs %d samples" % (emu[0], nat[1], emu[1]))
    print("%d/%d byte-identical" % (len(lines) - bad, len(lines)))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
