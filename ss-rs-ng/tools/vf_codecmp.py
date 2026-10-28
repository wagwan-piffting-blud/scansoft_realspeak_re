import glob
import hashlib
import os

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def norm_text(path):
    pe = pefile.PE(path)
    base = pe.OPTIONAL_HEADER.ImageBase
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    out = []
    lo = hi = 0
    for s in pe.sections:
        if s.Name.rstrip(b"\0") == b".text":
            code = s.get_data()[:s.Misc_VirtualSize]
            va = base + s.VirtualAddress
            lo, hi = base, base + pe.OPTIONAL_HEADER.SizeOfImage
            off = 0
            while off < len(code):
                got = False
                for ins in md.disasm(code[off:], va + off):
                    got = True
                    off = ins.address - va + ins.size
                    ops = ins.op_str
                    # mask image-relative constants so relinked layouts compare by shape
                    toks = []
                    for t in ops.replace(",", " , ").replace("[", " [ ").replace("]", " ] ").split():
                        try:
                            v = int(t, 16) if t.startswith("0x") else None
                        except ValueError:
                            v = None
                        toks.append("A" if v is not None and lo <= v < hi else t)
                    out.append(ins.mnemonic + " " + " ".join(toks))
                if not got:
                    off += 1
    return out


def main():
    vfs = sorted(glob.glob(os.path.join(ROOT, r"*\speech\components\voicefont\vf_*_full.dll")))
    ref = norm_text(os.path.join(ROOT, r"RealSpeak\speech\components\voicefont\vf_tom_full.dll"))
    refset = set(ref)
    import difflib
    for p in vfs:
        t = norm_text(p)
        h = hashlib.sha1("\n".join(t).encode()).hexdigest()[:10]
        sm = difflib.SequenceMatcher(None, ref, t, autojunk=False)
        ratio = sm.ratio() if len(t) < 60000 else float("nan")
        pe = pefile.PE(p)
        ts = pe.FILE_HEADER.TimeDateStamp
        print("%-62s insns=%6d shape=%s  sim_to_RS_tom=%.3f  ts=%08x" % (os.path.relpath(p, ROOT), len(t), h, ratio, ts))


if __name__ == "__main__":
    main()
