"""Do tom8's recording names (family<session>_<item>) have numbering gaps?

Gaps mean the SpeechWorks session script held prompts that Speechify's database
does not carry, i.e. recorded-but-unused material existed in the masters.
Also cross-checks the VIN's own recording list (feat.filename) against the VDB indx.

    python -I tom8_name_gaps.py
"""
import collections
import re
import sys

import numpy as np
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPFY = os.path.join(os.path.dirname(ROOT), "Speechify")

sys.path.insert(0, SPFY + r"\reveng\spfy4\tools")
import vdb_index as vx  # noqa: E402
import vin_units  # noqa: E402

TOM8 = SPFY + r"\en-US\tom\tom8.vdb"
VIN = SPFY + r"\en-US\tom\tom.vin"
PAT = re.compile(r"^([A-Za-z]+?)(\d*)_(\d+)$")


def main():
    _, _, entries = vx.load(TOM8)
    vdb_names = [n for _, n in entries]
    _, vin_names = vin_units.load_units(VIN)
    vin_set = set(vin_names if isinstance(vin_names, list) else vin_names.values())
    print(f"VDB indx: {len(vdb_names)} names ({len(set(vdb_names))} unique);  VIN feat.filename: {len(vin_set)}")
    only_vdb = sorted(set(vdb_names) - vin_set)
    print(f"  in VDB but not referenced by the VIN: {len(only_vdb)}  e.g. {only_vdb[:10]}")
    print(f"  in VIN but not in VDB: {len(vin_set - set(vdb_names))}")

    sess = collections.defaultdict(set)
    odd = []
    for n in set(vdb_names):
        m = PAT.match(n)
        if not m:
            odd.append(n)
            continue
        sess[(m.group(1), m.group(2))].add(int(m.group(3)))
    fam = collections.defaultdict(lambda: [0, 0, 0])          # sessions, present, span
    rows = []
    for (f, s), items in sorted(sess.items()):
        lo, hi = min(items), max(items)
        missing = (hi - lo + 1) - len(items)
        fam[f][0] += 1
        fam[f][1] += len(items)
        fam[f][2] += hi - lo + 1
        rows.append((f, s, len(items), lo, hi, missing))
    print(f"\nnames not matching family<session>_<item>: {len(odd)} e.g. {odd[:8]}")
    print(f"\n{'family':10} {'sessions':>8} {'present':>8} {'1..max span':>11} {'missing':>8} {'kept':>6}")
    tot_p = tot_s = 0
    for f, (ns, p, span) in sorted(fam.items(), key=lambda x: -x[1][1]):
        tot_p += p
        tot_s += span
        print(f"{f:10} {ns:8d} {p:8d} {span:11d} {span - p:8d} {p / span:6.1%}")
    print(f"{'ALL':10} {len(sess):8d} {tot_p:8d} {tot_s:11d} {tot_s - tot_p:8d} {tot_p / tot_s:6.1%}")
    hi_counts = collections.Counter(r[4] for r in rows)
    print("\nmost common highest item number per session:", hi_counts.most_common(6))
    print("example gappy sessions:")
    for r in sorted(rows, key=lambda r: -r[5])[:6]:
        f, s, n, lo, hi, miss = r
        have = sess[(f, s)]
        gaps = [i for i in range(lo, hi + 1) if i not in have][:12]
        print(f"  {f}{s}: {n} of {lo}..{hi}, missing {miss}: {gaps}{' ...' if miss > 12 else ''}")


if __name__ == "__main__":
    main()
