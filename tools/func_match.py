import hashlib, collections, struct
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPFY = os.path.join(os.path.dirname(ROOT), "Speechify")

FILES = {
    "SS": (ROOT + r"\ScanSoft\speech\components\voicefont\vf_tom_full.dll", 0x10017068),
    "RS": (ROOT + r"\RealSpeak\speech\components\voicefont\vf_tom_full.dll", 0x100190a0),
    "SPFY": (SPFY + r"\bin\SWIttsUSel.dll", None),
}

def load(path, iface):
    pe = pefile.PE(path)
    base = pe.OPTIONAL_HEADER.ImageBase
    text = [s for s in pe.sections if s.Name.startswith(b".text")][0]
    code = text.get_data()
    va0 = base + text.VirtualAddress
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    ins = list(md.disasm(code, va0))
    entries = set()
    for i in ins:
        if i.mnemonic == "call" and i.op_str.startswith("0x"):
            t = int(i.op_str, 16)
            if va0 <= t < va0 + len(code):
                entries.add(t)
    if iface:
        raw = pe.get_data(iface - base, 28 * 4)
        for k in range(28):
            p = struct.unpack_from("<I", raw, k * 4)[0]
            if va0 <= p < va0 + len(code):
                entries.add(p)
    for e in pe.DIRECTORY_ENTRY_EXPORT.symbols if hasattr(pe, "DIRECTORY_ENTRY_EXPORT") else []:
        entries.add(base + e.address)
    entries = sorted(entries)
    addr_idx = {i.address: n for n, i in enumerate(ins)}
    funcs = {}
    for k, e in enumerate(entries):
        end = entries[k + 1] if k + 1 < len(entries) else va0 + len(code)
        if e not in addr_idx:
            continue
        seq = []
        n = addr_idx[e]
        while n < len(ins) and ins[n].address < end:
            seq.append(ins[n].mnemonic)
            if ins[n].mnemonic in ("int3",):
                break
            n += 1
        # strip trailing padding
        while seq and seq[-1] in ("int3", "nop"):
            seq.pop()
        funcs[e] = seq
    return funcs

def shingles(seq, k=6):
    return {tuple(seq[i:i + k]) for i in range(max(0, len(seq) - k + 1))}

def main():
    F = {t: load(p, i) for t, (p, i) in FILES.items()}
    for t, f in F.items():
        print(t, "functions (call-target entries):", len(f))
    # exact normalised match SS vs RS
    hs = collections.defaultdict(list)
    for t in ("SS", "RS"):
        for a, s in F[t].items():
            if len(s) >= 8:
                hs[hashlib.md5(" ".join(s).encode()).hexdigest()].append((t, a))
    both = [v for v in hs.values() if {x[0] for x in v} == {"SS", "RS"}]
    print("SS/RS functions with IDENTICAL mnemonic sequence (>=8 ins):", len(both))
    # best Jaccard per function, SS vs RS and SS/RS vs SPFY
    def best(src, dst, minlen=30):
        dsh = {a: shingles(s) for a, s in F[dst].items() if len(s) >= minlen}
        res = []
        for a, s in F[src].items():
            if len(s) < minlen:
                continue
            sa = shingles(s)
            bj, ba = 0.0, None
            for b, sb in dsh.items():
                j = len(sa & sb) / max(1, len(sa | sb))
                if j > bj:
                    bj, ba = j, b
            res.append((bj, a, ba, len(s)))
        return sorted(res, reverse=True)
    for src, dst in (("SS", "RS"), ("SS", "SPFY"), ("RS", "SPFY")):
        r = best(src, dst)
        js = [x[0] for x in r]
        bands = [sum(1 for j in js if j >= t) for t in (0.9, 0.7, 0.5, 0.3)]
        print(f"{src}->{dst}: n={len(r)} (>=30 ins)  J>=.9:{bands[0]} >=.7:{bands[1]} >=.5:{bands[2]} >=.3:{bands[3]}  median={sorted(js)[len(js)//2]:.3f}")
        for j, a, b, n in r[:6]:
            print(f"    {a:#x} -> {b:#x}  J={j:.3f} len={n}")

if __name__ == "__main__":
    main()
