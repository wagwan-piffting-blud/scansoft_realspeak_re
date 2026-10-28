#!/usr/bin/env python3
"""The M3 gate: the translation covers everything the oracle executes.

Runs the corpus through `oracle/emu/build/rs_oracle_trace.exe`, collects
every (previous EIP, EIP) pair, and checks against `x86xlate.py`'s decode:
  - every executed instruction start is a translated instruction
  - every sequential step agrees with the translator's instruction length
  - every indirect transfer and every entry from the host lands on a block
    `dispatch::enter` knows
  - every `ret` lands just after a call, where `check_ret` expects it

    xlate_cover.py --pack rs|ss
"""
import argparse
import json
import os
import struct
import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import x86xlate as X

EXE = os.path.join(X.NG, "oracle", "emu", "build", "rs_oracle_trace.exe")
CORPUS = os.path.join(X.NG, "oracle", "corpus_en.txt")


def trace(job):
    speech, i, text, out = job
    env = dict(os.environ, SSRS_EIPTRACE=out)
    wav = out + ".wav"
    r = subprocess.run([EXE, speech, "Tom", wav, "\x1b\\vol=100\\" + text, X.PRODUCT],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0 or not os.path.exists(out):
        return i, None, (r.stdout + r.stderr)[-400:]
    data = open(out, "rb").read()
    return i, set(struct.iter_unpack("<II", data)), ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", choices=sorted(X.PACKS), required=True)
    ap.add_argument("--show", type=int, default=8)
    a = ap.parse_args()
    man = json.load(open(X.manifest_path(a.pack)))
    speech = os.path.join(X.ROOT, man["speech"].replace("/", os.sep))
    mods = [X.Module(m["name"], m["file"], int(m["base"], 16), speech) for m in man["modules"]]
    xl = X.Xlate(a.pack, mods)
    xl.discover()
    insn, blocks, ret_sites = {}, set(), set()
    for fn in xl.funcs.values():
        blocks |= fn["blocks"]
        for va, i in fn["insns"].items():
            insn.setdefault(va, i)
            if i.kind in ("call", "calli"):
                ret_sites.add(i.next)

    work = os.path.join(tempfile.gettempdir(), "ssrsng_cover_%s" % a.pack)
    os.makedirs(work, exist_ok=True)
    lines = [l.strip() for l in open(CORPUS, encoding="utf-8") if l.strip()]
    jobs = [(speech, k, t, os.path.join(work, "line%02d.bin" % k)) for k, t in enumerate(lines)]
    pairs = set()
    with ThreadPoolExecutor(os.cpu_count()) as ex:
        for k, s, err in ex.map(trace, jobs):
            if s is None:
                print("line %d: trace failed: %s" % (k, err))
                return 1
            pairs |= s

    def guest(v):
        return xl.module_of(v) is not None

    bad = {k: [] for k in ("missing", "length", "indirect", "host_entry", "ret", "trap_hit")}
    executed = set()
    kinds = Counter()
    for p, c in sorted(pairs):
        if not guest(c):
            continue
        executed.add(c)
        if c not in insn:
            bad["missing"].append((p, c))
            continue
        if insn[c].kind == "trap":
            bad["trap_hit"].append((p, c))
        pi = insn.get(p)
        if pi is None:
            if c not in blocks and c not in ret_sites:
                bad["host_entry"].append((p, c))
            kinds["from host"] += 1
            continue
        if c == pi.next and pi.kind in ("seq", "jcc", "call", "calli"):
            continue
        k = pi.kind
        kinds[k] += 1
        if k in ("jcc", "jmp", "call"):
            if c != pi.target:
                bad["length"].append((p, c))
        elif k in ("calli", "jmpi"):
            if c not in blocks:
                bad["indirect"].append((p, c))
        elif k == "ret":
            # A return to the host's sentinel is not traced, so the pair after
            # it is the host's next call into the guest: that must be a block.
            if c not in ret_sites and c not in blocks:
                bad["ret"].append((p, c))
            if c not in ret_sites:
                kinds["ret then host entry"] += 1
        else:
            bad["length"].append((p, c))
    total = sum(len(v) for v in bad.values())
    print("%s: %d corpus lines, %d unique transitions, %d guest instructions executed" % (
        a.pack, len(lines), len(pairs), len(executed)))
    print("  transfers checked: " + ", ".join("%s %d" % kv for kv in sorted(kinds.items())))
    for k, v in bad.items():
        print("  %-10s %d%s" % (k, len(v), ("  e.g. " + ", ".join("%08x->%08x" % x for x in v[:a.show])) if v else ""))
    print("cover: %s" % ("PASS" if total == 0 else "FAIL (%d)" % total))
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
