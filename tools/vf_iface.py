import struct, sys
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PACKS = {
    "SS": (ROOT + r"\ScanSoft\speech\components\voicefont\vf_tom_full.dll", 0x10017068),
    "RS": (ROOT + r"\RealSpeak\speech\components\voicefont\vf_tom_full.dll", 0x100190a0),
}
NSLOTS = 28

def cstr(pe, va):
    try:
        b = pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, 120)
    except Exception:
        return None
    s = b.split(b"\x00")[0]
    if len(s) >= 6 and all(32 <= c < 127 or c in (9, 10) for c in s):
        return s.decode()
    return None

def strings_in(pe, md, va, limit=0x600):
    base = pe.OPTIONAL_HEADER.ImageBase
    code = pe.get_data(va - base, limit)
    out, calls = [], []
    for ins in md.disasm(code, va):
        if ins.mnemonic == "push" and ins.op_str.startswith("0x"):
            s = cstr(pe, int(ins.op_str, 16))
            if s and s not in out:
                out.append(s)
        if ins.mnemonic == "call" and ins.op_str.startswith("0x"):
            calls.append(ins.op_str)
        if ins.mnemonic == "int3" or (ins.mnemonic == "nop" and ins.size == 1):
            break
    return out, calls

def main():
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    for tag, (path, tbl) in PACKS.items():
        pe = pefile.PE(path)
        base = pe.OPTIONAL_HEADER.ImageBase
        raw = pe.get_data(tbl - base, NSLOTS * 4 + 8)
        print(f"== {tag} interface @ {tbl:#x}")
        for i in range(NSLOTS):
            p = struct.unpack_from("<I", raw, i * 4)[0]
            if p == 0:
                print(f"  [{i:2}] 0")
                continue
            ss, calls = strings_in(pe, md, p)
            names = [s for s in ss if ("vf_" in s or "_" in s) and len(s) < 70]
            print(f"  [{i:2}] {p:#010x}  {' | '.join(names[:3])}   calls={len(calls)} {calls[:4] if len(calls) <= 7 else ''}")
        tail = struct.unpack_from("<HHI", raw, NSLOTS * 4)
        print(f"  tail: {tail}")

if __name__ == "__main__":
    main()
