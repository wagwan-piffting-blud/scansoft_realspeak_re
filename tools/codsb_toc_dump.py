import struct, sys, glob, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROOTS = [ROOT + r"\ScanSoft\speech\components\data",
         ROOT + r"\RealSpeak\speech\components\data"]

for root in ROOTS:
    for p in sorted(glob.glob(os.path.join(root, "vf_*_full_*.dat"))):
        with open(p, "rb") as f:
            hdr = f.read(0x90)
            toc_len = struct.unpack_from("<I", hdr, 0x7c)[0]
            f.seek(0x90)
            toc = f.read(toc_len - 0x90)
        ints = struct.unpack_from("<24i", toc, 0)
        coder = hdr[0x54:0x74].decode("latin-1").strip()
        print(f"{os.path.basename(p):42} coder={coder!r} toc_len={toc_len:#x} toc_body={len(toc)}")
        print("   ints:", ints)
        # blob = toc[8:]? test the DLL's size identity at several start offsets
        for start in (0, 4, 8, 12):
            n = struct.unpack_from("<i", toc, start)[0]
            if not 0 < n < 16:
                continue
            dims = struct.unpack_from(f"<{n}i", toc, start + 4)
            need = n * 8 + 0x18 + sum(dims) * 0x20
            print(f"   start+{start}: n={n} dims={dims} need={need} avail={len(toc) - start}"
                  f" {'<== EXACT' if need == len(toc) - start else ''}")
            arr2 = struct.unpack_from(f"<{n}i", toc, start + 4 + 4 * n)
            tail = struct.unpack_from("<5i", toc, start + 4 + 8 * n)
            print(f"      arr2={arr2} tail5={tail} cb_off_in_toc={start + 4 + 8 * n + 20}")
