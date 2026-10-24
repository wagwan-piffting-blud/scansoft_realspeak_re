"""Print the RIFF chunk layout, fmt, and indx stats of an XOR-0xCE Speechify .vdb.

    python -I vdb_layout.py ..\\Speechify\\en-US\\tom\\tom8.vdb [more.vdb ...]
"""
import struct
import sys


def rd(f, off, n):
    f.seek(off)
    return bytes(b ^ 0xCE for b in f.read(n))


def main():
    for path in sys.argv[1:]:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            hdr = rd(f, 0, 12)
            print(f"\n{path}  {size:,} B  {hdr[:4]} {hdr[8:12]}")
            i = 12
            while i + 8 <= size:
                h = rd(f, i, 8)
                cid, sz = h[:4], struct.unpack("<I", h[4:])[0]
                line = f"  {cid!r:8} @{i + 8:#x}  {sz:,} B"
                if cid == b"fmt ":
                    tag, ch, sr, br, ba, bps = struct.unpack("<HHIIHH", rd(f, i + 8, 16))
                    line += f"  tag {tag} ch {ch} rate {sr} byterate {br} align {ba} bits {bps}"
                if cid == b"indx":
                    blob = rd(f, i + 8, sz)
                    cnt = struct.unpack("<I", blob[:4])[0]
                    p, offs, names = 4, [], []
                    for _ in range(cnt):
                        o, nl = struct.unpack("<IH", blob[p:p + 6])
                        p += 6
                        offs.append(o)
                        names.append(blob[p:p + nl].decode("latin1"))
                        p += nl
                    line += f"  entries {cnt}  first {list(zip(offs[:3], names[:3]))}  last off {max(offs):,}"
                print(line)
                i += 8 + sz + (sz & 1)


if __name__ == "__main__":
    main()
