import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILES = {
    "SS": ROOT + r"\ScanSoft\speech\components\voicefont\vf_tom_full.dll",
    "RS": ROOT + r"\RealSpeak\speech\components\voicefont\vf_tom_full.dll",
}
IMMS = {80000: "beam 0.8", 0x9c4: "bin 2500", 500: "slope 500", 0x19064: "41 bins", 0xa0: "160",
        10000000: "miss 1e7", 4000000000: "inf 4e9", 6000: "dur x6000", 50000: "pen 5e4",
        0x3fc: "voic 1020", 0x32: "+50", 0x83: "radix 131", 0x220b14: "ctxfree key"}

def main():
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    for tag, path in FILES.items():
        pe = pefile.PE(path)
        base = pe.OPTIONAL_HEADER.ImageBase
        text = [s for s in pe.sections if s.Name.startswith(b".text")][0]
        code = text.get_data()
        va0 = base + text.VirtualAddress
        hits = {k: [] for k in IMMS}
        for ins in md.disasm(code, va0):
            for op in ins.op_str.replace("[", " ").replace("]", " ").replace(",", " ").split():
                if op.startswith("0x"):
                    try:
                        v = int(op, 16)
                    except ValueError:
                        continue
                    v = v & 0xffffffff
                    if v in hits:
                        hits[v].append(ins.address)
        print("==", tag)
        for k, v in hits.items():
            if k in (0x32, 0xa0, 500, 0x83):
                print(f"  {IMMS[k]:12} n={len(v)}")
            else:
                print(f"  {IMMS[k]:12} n={len(v)} {[hex(a) for a in v[:6]]}")

if __name__ == "__main__":
    main()
