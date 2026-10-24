"""Which tom8 recordings do the locked hits land in? Spread vs cluster, per pack.

    python -I tom_overlap_recs.py
"""
import collections
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tom_overlap as T  # noqa: E402


def main():
    import vdb_index as vx
    _, _, entries = vx.load(T.TOM8)
    offs = np.array([e[0] for e in entries])
    names = [e[1] for e in entries]
    fam_all = collections.Counter(re.sub(r"[_\d]+$", "", n) for n in names)
    print(f"tom8: {len(names)} recordings, {len(fam_all)} prompt families")
    recs = {}
    for pack in ("ss", "rs"):
        d = json.loads((T.OUT / f"runs_{pack}_W1600.json").read_text())
        r = [names[max(0, int(np.searchsorted(offs, h["y0"], side="right")) - 1)] for h in d["hits"]]
        recs[pack] = set(r)
        fam = collections.Counter(re.sub(r"[_\d]+$", "", n) for n in r)
        print(f"\n{pack.upper()}: {len(r)} hits -> {len(set(r))} distinct recordings, "
              f"{len(fam)} families; top: " + ", ".join(f"{k} {v}" for k, v in fam.most_common(8)))
    both = recs["ss"] & recs["rs"]
    print(f"\nrecordings hit by BOTH packs' independent samples: {len(both)} "
          f"(e.g. {', '.join(sorted(both)[:8])})")


if __name__ == "__main__":
    main()
