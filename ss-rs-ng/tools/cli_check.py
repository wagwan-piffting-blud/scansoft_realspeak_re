"""The CLI against the real engine's corpus WAVs (oracle/corpus_gate.py):
one-shot renders with pack auto-detection, and --serve with every line
through one warm engine.

    cli_check.py [--exe target/release/ss-rs-ng.exe] [--ref C:/tmp/ssrsng_gate] [--builtin]
"""
import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
NG = os.path.dirname(HERE)
ROOT = os.path.dirname(NG)
PACKS = {"realspeak": "RealSpeak", "scansoft": "ScanSoft"}


def pcm(path):
    with open(path, "rb") as f:
        return f.read()[44:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=os.path.join(NG, "target", "release", "ss-rs-ng.exe"))
    ap.add_argument("--ref", default=r"C:\tmp\ssrsng_gate")
    ap.add_argument("--builtin", action="store_true", help="use the built-in voice files, not --speech")
    a = ap.parse_args()
    lines = [l.strip() for l in open(os.path.join(NG, "oracle", "corpus_en.txt"), encoding="utf-8") if l.strip()]
    work = os.path.join(tempfile.gettempdir(), "ssrsng_cli")
    os.makedirs(work, exist_ok=True)
    bad = 0
    for pack, folder in PACKS.items():
        src = ["--version", pack] if a.builtin else ["--speech", os.path.join(ROOT, folder, "speech")]
        out = os.path.join(work, "%s_once.wav" % pack)
        r = subprocess.run([a.exe, lines[0], "-o", out, "--volume", "100"] + src, capture_output=True, text=True)
        same = r.returncode == 0 and pcm(out) == pcm(os.path.join(a.ref, "%s_tom_00_native.wav" % pack))
        bad += not same
        print("%-9s one-shot line 0: %s  %s" % (pack, "OK" if same else "DIFF", r.stderr.strip()))
        req = "".join("%s\t%s\n" % (os.path.join(work, "%s_serve_%02d.wav" % (pack, k)), t) for k, t in enumerate(lines))
        r = subprocess.run([a.exe, "--serve", "-q", "--volume", "100"] + src, input=req.encode(), capture_output=True)
        ok = 0
        for k in range(len(lines)):
            p = os.path.join(work, "%s_serve_%02d.wav" % (pack, k))
            if os.path.exists(p) and pcm(p) == pcm(os.path.join(a.ref, "%s_tom_%02d_native.wav" % (pack, k))):
                ok += 1
        bad += ok != len(lines)
        print("%-9s --serve, one engine: %d/%d byte-identical" % (pack, ok, len(lines)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
