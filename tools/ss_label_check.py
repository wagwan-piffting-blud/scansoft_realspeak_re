"""Can ScanSoft's per-unit phone labels be READ? Calibrate them against Speechify ground truth.

At every LOCKED step of the SS<->tom8 alignments (runs_ss_W1600.json) the same instant of
the same recording is known on both sides. The tom8 side has a trusted phone (VIN unit
phone_center -> labl, Festival darpa). The SS side has its unit label (us_tom_full.dat
record +9, SAMPA). Sweep the SS label-to-audio offset; at the right one the two phone
streams must agree far above chance. Reports the best offset, the agreement, and the
empirical darpa -> SAMPA mapping.

    python -I ss_label_check.py
"""
import collections
import json
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tom_overlap as T  # noqa: E402
import vdb_index as vx  # noqa: E402
import vin_units  # noqa: E402
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPFY = os.path.join(os.path.dirname(ROOT), "Speechify")

VIN = SPFY + r"\en-US\tom\tom.vin"
WS, WIN, STEP, LAG_TOL = 1600, 800, 160, 16


def labl_table():
    buf = (np.fromfile(VIN, dtype=np.uint8) ^ 0xCE).tobytes()
    # the tag also occurs inside other data; the real one is a chunk holding a small count
    i = buf.find(b"labl")
    while i >= 0 and not (0 < struct.unpack_from("<I", buf, i + 8)[0] < 200):
        i = buf.find(b"labl", i + 1)
    (cnt,) = struct.unpack_from("<I", buf, i + 8)
    p, out = i + 12, []
    for _ in range(cnt):
        (n,) = struct.unpack_from("<H", buf, p)
        out.append(buf[p + 2:p + 2 + n].decode("latin1"))
        p += 2 + n
    return out


def main():
    labl = labl_table()
    units, names = vin_units.load_units(VIN)
    names = names if isinstance(names, list) else [names[str(i)] for i in range(len(names))]
    _, _, entries = vx.load(T.TOM8)
    offs = np.array([e[0] for e in entries])
    ename = [e[1] for e in entries]
    fidx = {n: i for i, n in enumerate(names)}
    per_file = collections.defaultdict(list)
    for u in units:
        per_file[int(u["file_idx"])].append((int(u["local_pos"]), int(u["dur_like"]), int(u["phone_center"])))
    per_file = {k: np.array(sorted(v)) for k, v in per_file.items()}

    def tom8_phone(y):
        r = int(np.searchsorted(offs, y, side="right")) - 1
        f = fidx.get(ename[r])
        if f is None or f not in per_file:
            return None
        ms = (y - offs[r]) / 8.0
        a = per_file[f]
        j = int(np.searchsorted(a[:, 0], ms, side="right")) - 1
        if j < 0 or ms >= a[j, 0] + a[j, 1]:
            return None
        return labl[a[j, 2]]

    raw = np.memmap(T.SS_USELD, dtype=np.uint8, mode="r", offset=T.REC_OFF, shape=(T.N_UNITS, 16))
    pos = (raw[:, :4].copy().view("<u4").ravel() & 0x7FFFFFFF).astype(np.int64)
    ln = (raw[:, 11].astype(np.int64) << 4) | (raw[:, 12] >> 4)
    ph = raw[:, 9].copy()
    o = np.argsort(pos)
    pos, ln, ph = pos[o], ln[o], ph[o]
    st22, en22 = pos * T.TICK_TO_22K, (pos + ln) * T.TICK_TO_22K

    d = json.loads((T.OUT / "runs_ss_W1600.json").read_text())
    lthr = d["local_null_p99"]
    pairs = []
    for h in d["hits"]:
        rows = h["rows"]
        v = np.array([np.nan if r[1] is None else r[1] for r in rows], float)
        lag = np.array([r[2] for r in rows])
        c = len(rows) // 2
        if not (np.isfinite(v[c]) and v[c] > lthr):
            continue
        for i, r in enumerate(rows):
            if not (v[i] > lthr and abs(lag[i] - lag[c]) <= LAG_TOL):
                continue
            k = r[0]
            c8 = h["x0"] * 160 / 441 + WS // 2 - WIN // 2 + k * STEP + WIN // 2
            y = int(h["y0"] + WS // 2 - WIN // 2 + k * STEP + lag[i] + WIN // 2)
            tp = tom8_phone(y)
            if tp:
                pairs.append((c8 * 441 / 160, tp))
    s22 = np.array([p[0] for p in pairs])
    tp = [p[1] for p in pairs]
    print(f"{len(pairs)} locked instants with a tom8 phone")

    def ss_labels(off):
        j = np.searchsorted(st22 + off, s22, side="right") - 1
        ok = (j >= 0) & (s22 < en22[np.clip(j, 0, None)] + off)
        return [chr(ph[jj]) if k else None for jj, k in zip(j, ok)]

    def score(lab):
        cnt = collections.Counter((a, b) for a, b in zip(tp, lab) if b is not None)
        n = sum(cnt.values())
        if not n:
            return 0, 0, cnt
        best = collections.defaultdict(int)
        for (a, b), k in cnt.items():
            best[a] = max(best[a], k)
        acc = sum(best.values()) / n
        pa = collections.Counter(a for (a, _), k in cnt.items() for _ in range(k))
        pb = collections.Counter(b for (_, b), k in cnt.items() for _ in range(k))
        mi = sum(k / n * np.log2(k * n / (pa[a] * pb[b])) for (a, b), k in cnt.items())
        return acc, mi, cnt

    sweep = []
    for off in range(-6000, 3001, 110):
        acc, mi, _ = score(ss_labels(off))
        sweep.append((off, acc, mi))
    best_off, best_acc, best_mi = max(sweep, key=lambda x: x[2])
    null = [mi for off, acc, mi in sweep if abs(off - best_off) > 2500]
    print(f"best offset {best_off} samples @22k ({best_off / 22.05:+.0f} ms): MI {best_mi:.3f} bits, "
          f"many-to-one accuracy {best_acc:.1%};  far-offset MI {np.mean(null):.3f} +- {np.std(null):.3f}")
    print("  MI by offset (ms):", " ".join(f"{o / 22.05:+.0f}:{mi:.2f}" for o, _, mi in sweep[::4]))
    _, _, cnt = score(ss_labels(best_off))
    by = collections.defaultdict(collections.Counter)
    for (a, b), k in cnt.items():
        by[a][b] += k
    print("\ndarpa (tom8) -> SAMPA (SS) at the best offset, top labels with share:")
    rows = []
    for a, c in sorted(by.items(), key=lambda x: -sum(x[1].values())):
        tot = sum(c.values())
        top = c.most_common(3)
        rows.append({"darpa": a, "n": tot, "top": [(b, k / tot) for b, k in top]})
        print(f"  {a:4} n={tot:4d}  " + "  ".join(f"{b!r} {k / tot:.0%}" for b, k in top))
    (T.OUT / "ss_label_check.json").write_text(json.dumps(
        {"best_offset_22k": best_off, "mi": best_mi, "acc": best_acc, "sweep": sweep, "map": rows}, indent=1))


if __name__ == "__main__":
    main()
