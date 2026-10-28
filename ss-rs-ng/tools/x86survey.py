import os
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32, CS_GRP_JUMP, CS_GRP_CALL
from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DLLS = [
    ("RS", r"RealSpeak\speech\components\common\ttsengine.dll"),
    ("RS", r"RealSpeak\speech\components\common\xcoder.dll"),
    ("RS", r"RealSpeak\speech\components\xlit\xlit_1252.dll"),
    ("RS", r"RealSpeak\speech\components\common\combrk.dll"),
    ("RS", r"RealSpeak\speech\components\common\comrsrc.dll"),
    ("RS", r"RealSpeak\speech\components\common\comsyssvc.dll"),
    ("RS", r"RealSpeak\speech\components\pp\stdpp_enu.dll"),
    ("RS", r"RealSpeak\speech\components\g2p\g2p_enu.dll"),
    ("RS", r"RealSpeak\speech\components\voicefont\vf_tom_full.dll"),
    ("RS", r"RealSpeak\speech\components\synthesizer\synth_155mrf22.dll"),
    ("RS", r"RealSpeak\speech\components\common\rettt.dll"),
    ("RS", r"RealSpeak\speech\components\common\domain_mngr.dll"),
    ("RS", r"RealSpeak\speech\components\common\dcteg.dll"),
    ("RS", r"RealSpeak\speech\components\common\edct.dll"),
    ("SS", r"ScanSoft\speech\components\common\ttsengine.dll"),
    ("SS", r"ScanSoft\speech\components\pp\stdpp_enu.dll"),
    ("SS", r"ScanSoft\speech\components\pp\empp_enu.dll"),
    ("SS", r"ScanSoft\speech\components\g2p\g2p_enu.dll"),
    ("SS", r"ScanSoft\speech\components\voicefont\vf_tom_full.dll"),
    ("SS", r"ScanSoft\speech\components\common\combrk.dll"),
    ("SS", r"ScanSoft\speech\components\common\comrsrc.dll"),
]

X87 = {"fld", "fst", "fstp", "fild", "fist", "fistp", "fadd", "faddp", "fsub", "fsubp", "fsubr",
       "fsubrp", "fmul", "fmulp", "fdiv", "fdivp", "fdivr", "fdivrp", "fcom", "fcomp", "fcompp",
       "fucom", "fucomp", "fucompp", "fnstsw", "fstsw", "fldz", "fld1", "fchs", "fabs", "fsqrt",
       "fxch", "fnstcw", "fldcw", "frndint", "fcos", "fsin", "fpatan", "fyl2x", "f2xm1",
       "fscale", "fprem", "fistp", "ficom", "ficomp", "fiadd", "fimul", "fidiv", "fisub"}


def form(ins):
    kinds = []
    for op in ins.operands:
        if op.type == X86_OP_REG:
            kinds.append("r%d" % op.size)
        elif op.type == X86_OP_IMM:
            kinds.append("i")
        elif op.type == X86_OP_MEM:
            kinds.append("m%d" % op.size)
    pre = "rep_" if ins.prefix[0] in (0xF3, 0xF2) else ""
    return pre + ins.mnemonic + ":" + ",".join(kinds)


def survey(item):
    pack, rel = item
    path = os.path.join(ROOT, rel)
    pe = pefile.PE(path)
    base = pe.OPTIONAL_HEADER.ImageBase
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True
    n = 0
    forms = Counter()
    mnems = Counter()
    x87 = sse = indirect_jmp = indirect_call = 0
    text_bytes = 0
    for s in pe.sections:
        if not s.Characteristics & 0x20000000:
            continue
        code = s.get_data()[:s.Misc_VirtualSize]
        text_bytes += len(code)
        va = base + s.VirtualAddress
        off = 0
        while off < len(code):
            got = False
            for ins in md.disasm(code[off:], va + off):
                got = True
                off = ins.address - va + ins.size
                n += 1
                m = ins.mnemonic
                mnems[m] += 1
                forms[form(ins)] += 1
                if m in X87 or m.startswith("f") and m not in ("fwait",):
                    x87 += 1
                if any(r.startswith("xmm") for r in ins.op_str.replace(",", " ").split()) or m.startswith(("movs", "cvt")) and "xmm" in ins.op_str:
                    sse += 1
                if ins.group(CS_GRP_JUMP) and ins.operands and ins.operands[0].type != X86_OP_IMM:
                    indirect_jmp += 1
                if ins.group(CS_GRP_CALL) and ins.operands and ins.operands[0].type != X86_OP_IMM:
                    indirect_call += 1
            if not got:
                off += 1
    imps = {}
    if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
        for e in pe.DIRECTORY_ENTRY_IMPORT:
            imps[e.dll.decode().lower()] = [(i.name.decode() if i.name else "#%d" % i.ordinal) for i in e.imports]
    exps = 0
    if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
        exps = len(pe.DIRECTORY_ENTRY_EXPORT.symbols)
    return dict(pack=pack, name=os.path.basename(rel), text=text_bytes, ins=n, forms=forms, mnems=mnems,
                x87=x87, sse=sse, ijmp=indirect_jmp, icall=indirect_call, imps=imps, exps=exps,
                size=os.path.getsize(path))


def main():
    with ProcessPoolExecutor(min(len(DLLS), os.cpu_count())) as ex:
        res = list(ex.map(survey, DLLS))
    allforms = Counter()
    allmn = Counter()
    imports = {}
    print("%-3s %-22s %8s %8s %6s %6s %5s %5s %5s %s" % ("pk", "dll", "size", ".text", "insns", "forms", "x87", "ijmp", "icall", "imports (dll:count)"))
    tot = 0
    for r in res:
        tot += r["ins"]
        allforms.update(r["forms"])
        allmn.update(r["mnems"])
        for d, fs in r["imps"].items():
            imports.setdefault(d, set()).update(fs)
        print("%-3s %-22s %8d %8d %6d %6d %5d %5d %5d %s" % (
            r["pack"], r["name"], r["size"], r["text"], r["ins"], len(r["forms"]), r["x87"], r["ijmp"], r["icall"],
            " ".join("%s:%d" % (d.replace(".dll", ""), len(f)) for d, f in r["imps"].items())))
    print("total instructions (linear sweep, all listed DLLs): %d" % tot)
    print("distinct mnemonics: %d   distinct operand forms: %d" % (len(allmn), len(allforms)))
    print("mnemonics:", " ".join("%s:%d" % kv for kv in allmn.most_common()))
    for d in sorted(imports):
        print("IMPORT %-14s %3d  %s" % (d, len(imports[d]), " ".join(sorted(imports[d]))))


if __name__ == "__main__":
    main()
