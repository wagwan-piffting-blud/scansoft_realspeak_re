"""Every x87 transcendental and constant-load site in the SS and RS DLLs."""
import os
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKS = {
    "RS": os.path.join(ROOT, "RealSpeak", "speech"),
    "SS": os.path.join(ROOT, "ScanSoft", "speech"),
}
WANT = {"f2xm1", "fyl2x", "fscale", "frndint", "fldl2e", "fldlg2", "fldl2t", "fldpi", "fldln2",
        "fsin", "fcos", "fsincos", "fptan", "fpatan", "fsqrt", "fprem", "fprem1", "fxtract", "fyl2xp1"}


def dlls(base):
    for dp, _, fn in os.walk(base):
        for f in fn:
            if f.lower().endswith(".dll"):
                yield os.path.join(dp, f)


def main():
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.skipdata = True
    for pk, base in PACKS.items():
        for path in sorted(dlls(base)):
            pe = pefile.PE(path, fast_load=True)
            for s in pe.sections:
                if not (s.Characteristics & 0x20000000):
                    continue
                va = pe.OPTIONAL_HEADER.ImageBase + s.VirtualAddress
                for ins in md.disasm(s.get_data(), va):
                    if ins.mnemonic in WANT:
                        print(f"{pk} {os.path.basename(path):24s} {ins.address:08x} {ins.mnemonic} {ins.op_str}")


if __name__ == "__main__":
    main()
