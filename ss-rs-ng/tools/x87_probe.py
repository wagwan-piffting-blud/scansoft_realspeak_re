"""Whether the corpus reaches synth_155mrf22's inlined log10 (fyl2x) and exp
(f2xm1) sites, via the oracle's EMU_DUMPAT hook."""
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NG = os.path.join(ROOT, "ss-rs-ng")
EMU = os.path.join(NG, "oracle", "emu", "build", "rs_oracle.exe")
CORPUS = os.path.join(NG, "oracle", "corpus_en.txt")
OUT = os.path.join(tempfile.gettempdir(), "ssrsng_x87probe")
PRODUCT = "RealSpeak Solo v4.0"
PACKS = {"RS": os.path.join(ROOT, "RealSpeak", "speech"), "SS": os.path.join(ROOT, "ScanSoft", "speech")}
SITES = {"log10.fyl2x": 0xBD38, "exp1.f2xm1": 0xBD84, "exp2.f2xm1": 0xBDC5}


def base_of(pack):
    r = subprocess.run([EMU, PACKS[pack], "Tom", os.path.join(OUT, f"base_{pack}.wav"), "Hi.", PRODUCT],
                       capture_output=True, text=True)
    for line in (r.stdout + r.stderr).splitlines():
        if line.startswith("module") and "synth_155mrf22" in line:
            return int(line.split()[1], 16)
    raise SystemExit(f"no synth_155mrf22 base for {pack}")


def probe(job):
    pack, base, name, rva, i, text = job
    env = dict(os.environ, EMU_DUMPAT="%08x" % (base + rva))
    out = os.path.join(OUT, f"{pack}_{name}_{i:02d}.wav")
    r = subprocess.run([EMU, PACKS[pack], "Tom", out, "\x1b\\vol=100\\" + text, PRODUCT],
                       capture_output=True, text=True, env=env)
    return pack, name, i, "[dumpat" in (r.stdout + r.stderr)


def main():
    os.makedirs(OUT, exist_ok=True)
    lines = [l.strip() for l in open(CORPUS, encoding="utf-8") if l.strip()]
    jobs = []
    for pack in PACKS:
        base = base_of(pack)
        print(f"{pack} synth_155mrf22 at {base:08x}")
        jobs += [(pack, base, n, rva, i, t) for n, rva in SITES.items() for i, t in enumerate(lines)]
    with ThreadPoolExecutor(os.cpu_count()) as ex:
        res = list(ex.map(probe, jobs))
    for pack in PACKS:
        for name in SITES:
            hit = sum(1 for p, n, _, h in res if p == pack and n == name and h)
            print(f"{pack} {name}: reached on {hit}/{len(lines)} lines")


if __name__ == "__main__":
    main()
