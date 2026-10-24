"""Speechify VIN: metadata dump + the ckls checklist as timed words inside tom8.vdb.

ckls grammar (Speechify\\reveng\\README_TECHNICAL.md, `ckls`): u32 group_count, then per group
u16 name_len + name + u32 token_count + u32 unk0, then alternating
    token record     u16 len + text + u32 span_start + u32 span_end
    filename record  u16 len + name + u32 file_id   (no u32 on the group's last one)
span_start/end are global unit ids; unit[span_start] is the first half of the first phone,
unit[span_end] the second half of the last.

Writes C:\\tmp\\tom_overlap\\ckls_words.json:
    [{"group", "text", "rec", "start_ms", "end_ms", "abs8k_start", "abs8k_end", "n_units"}, ...]

    python -I vin_ckls.py
"""
import json
import struct
import sys
from pathlib import Path

import numpy as np
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPFY = os.path.join(os.path.dirname(ROOT), "Speechify")

sys.path.insert(0, SPFY + r"\reveng\spfy4\tools")
import vdb_index as vx  # noqa: E402
import vin_units  # noqa: E402

VIN = SPFY + r"\en-US\tom\tom.vin"
TOM8 = SPFY + r"\en-US\tom\tom8.vdb"
OUT = Path(r"C:\tmp\tom_overlap\ckls_words.json")


def chunks(buf, start, end, depth=0, path=""):
    i = start
    while i + 8 <= end:
        cid = buf[i:i + 4]
        sz = struct.unpack_from("<I", buf, i + 4)[0]
        yield depth, path, cid, i + 8, sz
        if cid in (b"LIST", b"RIFF"):
            yield from chunks(buf, i + 12, i + 8 + sz, depth + 1, path + "/" + buf[i + 8:i + 12].decode("latin1"))
        i += 8 + sz + (sz & 1)


def parse_ckls(blob):
    p = 0
    (ngroups,) = struct.unpack_from("<I", blob, p)
    p += 4
    out = []
    for _ in range(ngroups):
        (nl,) = struct.unpack_from("<H", blob, p)
        name = blob[p + 2:p + 2 + nl].decode("latin1")
        p += 2 + nl
        ntok, _unk = struct.unpack_from("<II", blob, p)
        p += 8
        for t in range(ntok):
            (tl,) = struct.unpack_from("<H", blob, p)
            text = blob[p + 2:p + 2 + tl].decode("latin1")
            p += 2 + tl
            s0, s1 = struct.unpack_from("<II", blob, p)
            p += 8
            (fl,) = struct.unpack_from("<H", blob, p)
            fname = blob[p + 2:p + 2 + fl].decode("latin1")
            p += 2 + fl
            if t < ntok - 1:
                p += 4
            out.append((name, text, s0, s1, fname))
    return out, p


def main():
    raw = np.fromfile(VIN, dtype=np.uint8) ^ 0xCE
    buf = raw.tobytes()
    print(f"{VIN}  {len(buf):,} B  {buf[:4]} {buf[8:12]}")
    found = {}
    for depth, path, cid, off, sz in chunks(buf, 12, len(buf)):
        found.setdefault(cid, (off, sz))
        if path.endswith("INFO"):
            val = buf[off:off + sz].rstrip(b"\x00").decode("latin1")
            print(f"  INFO {cid.decode('latin1')}: {val!r}")
        elif depth == 0:
            print(f"  chunk {cid!r:8} {sz:>12,} B")
    vo, vs = found[b"vers"]
    (vl,) = struct.unpack_from("<H", buf, vo)
    print(f"  vers: {buf[vo + 2:vo + 2 + vl].decode('latin1')!r}")
    co, cs = found[b"cnts"]
    print(f"  cnts: {struct.unpack_from('<' + 'I' * (cs // 4), buf, co)}")

    toks, used = parse_ckls(buf[found[b"ckls"][0]:found[b"ckls"][0] + found[b"ckls"][1]])
    print(f"\nckls: {len(toks)} token records, parsed {used:,} of {found[b'ckls'][1]:,} B")

    units, names = vin_units.load_units(VIN)
    _, _, entries = vx.load(TOM8)
    rec_off = {name: off for off, name in entries}
    words, bad = [], 0
    for grp, text, s0, s1, fname in toks:
        u0, u1 = units[s0], units[s1]
        rec = names[int(u0["file_idx"])] if isinstance(names, list) else names[str(int(u0["file_idx"]))]
        if rec != fname or int(u1["file_idx"]) != int(u0["file_idx"]):
            bad += 1
            continue
        st = int(u0["local_pos"])
        en = int(u1["local_pos"]) + int(u1["dur_like"])
        base = rec_off.get(rec)
        words.append({"group": grp, "text": text, "rec": rec, "start_ms": st, "end_ms": en,
                      "abs8k_start": None if base is None else base + st * 8,
                      "abs8k_end": None if base is None else base + en * 8, "n_units": s1 - s0 + 1})
    w = [x for x in words if x["group"] == "_WORD_"]
    s = [x for x in words if x["group"] == "_SYL_"]
    recs = {x["rec"] for x in w}
    dur = np.array([x["end_ms"] - x["start_ms"] for x in w])
    print(f"  resolved {len(words)} (inconsistent filename/unit: {bad})")
    print(f"  _WORD_: {len(w)} tokens, {len({x['text'] for x in w})} unique, in {len(recs)} recordings; "
          f"word duration p50 {np.median(dur):.0f} ms, total {dur.sum() / 60000:.1f} min")
    print(f"  _SYL_ : {len(s)} tokens, {len({x['text'] for x in s})} unique")
    print("  sample:", ", ".join(f"{x['text']}@{x['rec']}" for x in w[:8]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(words))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
