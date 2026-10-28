import os
import struct
from concurrent.futures import ProcessPoolExecutor

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32, CS_GRP_JUMP, CS_GRP_CALL, CS_GRP_RET
from capstone.x86 import X86_OP_IMM, X86_OP_MEM

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DLLS = [
    r"RealSpeak\speech\components\common\ttsengine.dll",
    r"RealSpeak\speech\components\common\xcoder.dll",
    r"RealSpeak\speech\components\xlit\xlit_1252.dll",
    r"RealSpeak\speech\components\common\combrk.dll",
    r"RealSpeak\speech\components\common\comrsrc.dll",
    r"RealSpeak\speech\components\common\comsyssvc.dll",
    r"RealSpeak\speech\components\pp\stdpp_enu.dll",
    r"RealSpeak\speech\components\g2p\g2p_enu.dll",
    r"RealSpeak\speech\components\voicefont\vf_tom_full.dll",
    r"RealSpeak\speech\components\synthesizer\synth_155mrf22.dll",
    r"ScanSoft\speech\components\common\ttsengine.dll",
    r"ScanSoft\speech\components\pp\stdpp_enu.dll",
    r"ScanSoft\speech\components\g2p\g2p_enu.dll",
    r"ScanSoft\speech\components\voicefont\vf_tom_full.dll",
]
NORET = set()


def analyse(rel):
    pe = pefile.PE(os.path.join(ROOT, rel))
    base = pe.OPTIONAL_HEADER.ImageBase
    img = pe.get_memory_mapped_image()
    text = [s for s in pe.sections if s.Characteristics & 0x20000000]
    lo = base + min(s.VirtualAddress for s in text)
    hi = base + max(s.VirtualAddress + s.Misc_VirtualSize for s in text)

    def in_text(va):
        return lo <= va < hi

    seeds = {}
    if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
        for x in pe.DIRECTORY_ENTRY_EXPORT.symbols:
            if in_text(base + x.address):
                seeds[base + x.address] = "export"
    seeds[base + pe.OPTIONAL_HEADER.AddressOfEntryPoint] = "entry"
    reloc_ptrs = 0
    if hasattr(pe, "DIRECTORY_ENTRY_BASERELOC"):
        for blk in pe.DIRECTORY_ENTRY_BASERELOC:
            for e in blk.entries:
                if e.type != 3:
                    continue
                site = e.rva
                if lo <= base + site < hi:
                    continue
                v = struct.unpack_from("<I", img, site)[0]
                if in_text(v):
                    seeds.setdefault(v, "reloc")
                    reloc_ptrs += 1
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True
    seen = set()
    covered = bytearray(hi - lo)
    work = list(seeds)
    ijmp_unres = 0
    fn_entries = set(seeds)
    while work:
        va = work.pop()
        while in_text(va) and va not in seen:
            seen.add(va)
            off = va - base
            try:
                ins = next(md.disasm(bytes(img[off:off + 16]), va))
            except StopIteration:
                break
            for i in range(ins.size):
                if va + i < hi:
                    covered[va + i - lo] = 1
            nxt = va + ins.size
            if ins.group(CS_GRP_RET) or ins.mnemonic == "hlt":
                break
            if ins.group(CS_GRP_CALL):
                op = ins.operands[0]
                if op.type == X86_OP_IMM:
                    work.append(op.imm)
                    fn_entries.add(op.imm)
                va = nxt
                continue
            if ins.group(CS_GRP_JUMP):
                op = ins.operands[0]
                if op.type == X86_OP_IMM:
                    work.append(op.imm)
                    if ins.mnemonic == "jmp":
                        break
                    va = nxt
                    continue
                if ins.mnemonic == "jmp":
                    if op.type == X86_OP_MEM and op.mem.disp and op.mem.index != 0:
                        t = op.mem.disp & 0xFFFFFFFF
                        k = 0
                        while k < 512:
                            o = t - base + 4 * k
                            if o < 0 or o + 4 > len(img):
                                break
                            v = struct.unpack_from("<I", img, o)[0]
                            if not in_text(v):
                                break
                            work.append(v)
                            k += 1
                    elif op.type == X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0:
                        pass
                    else:
                        ijmp_unres += 1
                    break
            va = nxt
    code = bytearray()
    for s in text:
        code += s.get_data()[:s.Misc_VirtualSize]
    padding = 0
    i = 0
    raw = bytes(img[lo - base:hi - base])
    for i, b in enumerate(raw):
        if not covered[i] and b in (0xCC, 0x90, 0x00):
            padding += 1
    total = hi - lo
    cov = sum(covered)
    return (rel, total, cov, padding, len(fn_entries), reloc_ptrs, ijmp_unres)


def main():
    with ProcessPoolExecutor(min(len(DLLS), os.cpu_count())) as ex:
        res = list(ex.map(analyse, DLLS))
    print("%-58s %7s %7s %6s %6s %6s %5s" % ("module", "text", "reached", "cov%", "cov+pad%", "funcs", "ijmp?"))
    for rel, total, cov, pad, nf, rp, ij in res:
        print("%-58s %7d %7d %5.1f%% %6.1f%% %6d %5d" % (rel, total, cov, 100 * cov / total, 100 * (cov + pad) / total, nf, ij))


if __name__ == "__main__":
    main()
