#!/usr/bin/env python3
"""Translate every reachable function of one pack's vendor DLLs into Rust.

Each module is translated at the base the oracle loads it at, from its image
relocated there, so every address in the output is the oracle's. A function
becomes

    pub fn f_XXXXXXXX(c: &mut Cpu, m: &mut Mem, h: &mut dyn Host)

with a block `match` loop inside; `call` is a Rust call after pushing the
real return address, `ret` pops it and returns, and anything indirect goes
through the generated `dispatch::enter`. Every instruction is decoded and
given the semantics `oracle/emu/cpu.c` gives it, including where that is not
what an x86 does; xrt holds the bodies (`xtask opgate` proves them).

    x86xlate.py manifest              # run the oracle, record module bases
    x86xlate.py translate --pack rs   # -> crates/ss-rs-ng-eng/src/rs/
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from collections import Counter

import pefile

HERE = os.path.dirname(os.path.abspath(__file__))
NG = os.path.dirname(HERE)
ROOT = os.path.dirname(NG)
PACKS = {"rs": "RealSpeak", "ss": "ScanSoft"}
PRODUCT = "RealSpeak Solo v4.0"
THUNK_BASE = 0x71000000
SHARD_BYTES = 1_500_000

PREFIXES = {0x66, 0x67, 0xF0, 0xF2, 0xF3, 0x2E, 0x36, 0x3E, 0x26, 0x64, 0x65}
SSE = {0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F,
       0x50, 0x51, 0x52, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5A, 0x5B, 0x5C, 0x5D, 0x5E, 0x5F,
       0x60, 0x61, 0x62, 0x64, 0x65, 0x66, 0x68, 0x69, 0x6A, 0x6C, 0x6D, 0x74, 0x75, 0x76,
       0x6E, 0x6F, 0x70, 0x71, 0x72, 0x73, 0x7E, 0x7F, 0xD7, 0xC2, 0xC4, 0xC5, 0xC6,
       0xD1, 0xD2, 0xD3, 0xD4, 0xD6, 0xDA, 0xDB, 0xDE, 0xDF, 0xE1, 0xE2, 0xE6, 0xEA, 0xEB, 0xEE, 0xEF,
       0xF1, 0xF2, 0xF3, 0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE}
ALU = ["add", "or", "adc", "sbb", "and", "sub", "xor", "cmp"]
SEGSEL = [0x23, 0x1b, 0x23, 0x23, 0x3b, 0x63, 0, 0]


class Unsupported(Exception):
    pass


def hx(v):
    return "0x%x" % (v & 0xFFFFFFFF)


# ---- modules ---------------------------------------------------------------

class Module:
    def __init__(self, name, rel, base, speech):
        self.name, self.rel, self.base = name, rel, base
        self.path = os.path.join(speech, rel.replace("/", os.sep))
        data = open(self.path, "rb").read()
        self.sha256 = hashlib.sha256(data).hexdigest()
        pe = pefile.PE(data=data)
        self.pref = pe.OPTIONAL_HEADER.ImageBase
        self.size = pe.OPTIONAL_HEADER.SizeOfImage
        self.entry = base + pe.OPTIONAL_HEADER.AddressOfEntryPoint if pe.OPTIONAL_HEADER.AddressOfEntryPoint else 0
        img = bytearray(pe.get_memory_mapped_image())
        img += bytes(max(0, self.size - len(img)))
        delta = (base - self.pref) & 0xFFFFFFFF
        self.relocs = set()
        if hasattr(pe, "DIRECTORY_ENTRY_BASERELOC"):
            for blk in pe.DIRECTORY_ENTRY_BASERELOC:
                for e in blk.entries:
                    if e.type == 3:
                        v = struct.unpack_from("<I", img, e.rva)[0]
                        struct.pack_into("<I", img, e.rva, (v + delta) & 0xFFFFFFFF)
                        self.relocs.add(base + e.rva)
        self.img = bytes(img)
        self.text = []
        for s in pe.sections:
            if s.Characteristics & 0x20000000:
                self.text.append((base + s.VirtualAddress, base + s.VirtualAddress + s.Misc_VirtualSize))
        self.exports = {}
        self.ordinals = {}
        if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
            for x in pe.DIRECTORY_ENTRY_EXPORT.symbols:
                if x.address:
                    if x.name:
                        self.exports[x.name.decode()] = base + x.address
                    self.ordinals[x.ordinal] = base + x.address
        self.imports = []
        if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
            for d in pe.DIRECTORY_ENTRY_IMPORT:
                dll = d.dll.decode().lower()
                for imp in d.imports:
                    slot = (imp.address - self.pref + base) & 0xFFFFFFFF
                    self.imports.append((slot, dll, imp.name.decode() if imp.name else None, imp.ordinal))

    def has(self, va):
        return self.base <= va < self.base + self.size

    def in_text(self, va):
        return any(lo <= va < hi for lo, hi in self.text)

    def b(self, va):
        return self.img[va - self.base]

    def u16(self, va):
        return struct.unpack_from("<H", self.img, va - self.base)[0]

    def u32(self, va):
        return struct.unpack_from("<I", self.img, va - self.base)[0]

    def s8(self, va):
        return struct.unpack_from("<b", self.img, va - self.base)[0]

    def s16(self, va):
        return struct.unpack_from("<h", self.img, va - self.base)[0]

    def s32(self, va):
        return struct.unpack_from("<i", self.img, va - self.base)[0]


def manifest_path(pack):
    return os.path.join(NG, "xlate", "%s_modules.json" % pack)


def cmd_manifest(_args):
    exe = os.path.join(NG, "oracle", "emu", "build", "rs_oracle.exe")
    os.makedirs(os.path.join(NG, "xlate"), exist_ok=True)
    for pack, folder in PACKS.items():
        speech = os.path.join(ROOT, folder, "speech")
        out = os.path.join(tempfile.gettempdir(), "ssrsng_manifest_%s.wav" % pack)
        r = subprocess.run([exe, speech, "Tom", out, "Hi.", PRODUCT], capture_output=True, text=True)
        mods = []
        for line in (r.stdout + r.stderr).splitlines():
            if not line.startswith("module "):
                continue
            _, base, path = line.split(" ", 2)
            full = os.path.normpath(path)
            rel = os.path.relpath(full, os.path.normpath(speech)).replace(os.sep, "/")
            name = os.path.splitext(os.path.basename(rel))[0].lower()
            mods.append({"name": name, "file": rel, "base": base})
        if not mods:
            raise SystemExit("oracle printed no modules for %s:\n%s" % (pack, (r.stdout + r.stderr)[-2000:]))
        with open(manifest_path(pack), "w", newline="\n") as f:
            json.dump({"pack": pack, "speech": "%s/speech" % folder, "modules": mods}, f, indent=1)
            f.write("\n")
        print("%s: %d modules -> %s" % (pack, len(mods), manifest_path(pack)))
    return 0


# ---- decoding, exactly as cpu.c's cpu_run_core -------------------------------

class Insn:
    """One instruction. `kind` drives discovery and emission:
    seq, jcc, jmp, call, calli, jmpi, ret, trap."""

    def __init__(self, mod, va):
        self.mod, self.va = mod, va
        p = va
        self.opsz, self.rep, self.repne, self.seg = 4, False, False, None
        while mod.b(p) in PREFIXES:
            x = mod.b(p)
            if x == 0x66:
                self.opsz = 2
            elif x == 0xF2:
                self.repne = True
            elif x == 0xF3:
                self.rep = True
            elif x == 0x64:
                self.seg = "c.fs_base"
            elif x == 0x65:
                self.seg = "c.gs_base"
            p += 1
            if p - va > 14:
                raise Unsupported("prefix run")
        self.op = mod.b(p)
        p += 1
        self.op2 = None
        if self.op == 0x0F:
            self.op2 = mod.b(p)
            p += 1
        self.p = p
        self.mem = False
        self.reg = self.rm = 0
        self.ea = None
        self.imm_sites = []
        self.kind, self.target = "seq", None

    # operand fetches, in cpu.c's order
    def modrm(self):
        m, p = self.mod, self.p
        b = m.b(p)
        p += 1
        mod, self.reg, self.rm = b >> 6, (b >> 3) & 7, b & 7
        self.modrm_byte = b
        if mod == 3:
            self.mem = False
            self.p = p
            return
        self.mem = True
        parts, disp = [], 0
        if self.rm == 4:
            sib = m.b(p)
            p += 1
            scale, idx, base = sib >> 6, (sib >> 3) & 7, sib & 7
            if base == 5 and mod == 0:
                disp = m.u32(p)
                self.disp_site = p
                p += 4
            else:
                parts.append("c.r[%d]" % base)
            if idx != 4:
                parts.append("(c.r[%d] << %d)" % (idx, scale) if scale else "c.r[%d]" % idx)
            self.sib = (scale, idx, base)
        elif self.rm == 5 and mod == 0:
            disp = m.u32(p)
            self.disp_site = p
            p += 4
            self.sib = None
        else:
            parts.append("c.r[%d]" % self.rm)
            self.sib = None
        if mod == 1:
            disp = (disp + m.s8(p)) & 0xFFFFFFFF
            p += 1
        elif mod == 2:
            disp = (disp + m.s32(p)) & 0xFFFFFFFF
            p += 4
        self.modv, self.disp = mod, disp
        if self.seg:
            parts.append(self.seg)
        if not parts:
            self.ea = hx(disp) + "_u32"
        else:
            e = parts[0]
            for q in parts[1:]:
                e += ".wrapping_add(%s)" % q
            if disp:
                e += ".wrapping_add(%s)" % hx(disp)
            self.ea = e
        self.p = p

    def imm8(self):
        v = self.mod.b(self.p)
        self.p += 1
        return v

    def simm8(self):
        v = self.mod.s8(self.p)
        self.p += 1
        return v & 0xFFFFFFFF

    def imm16(self):
        v = self.mod.u16(self.p)
        self.p += 2
        return v

    def imm32(self):
        self.imm_sites.append(self.p)
        v = self.mod.u32(self.p)
        self.p += 4
        return v

    def immz(self):
        return self.imm16() if self.opsz == 2 else self.imm32()


# ---- emission helpers --------------------------------------------------------

def greg(r, sz):
    return "c.r[%d]" % r if sz == 4 else "c.getreg(%d, %d)" % (r, sz)


def sreg(r, sz, v):
    return "c.r[%d] = %s;" % (r, v) if sz == 4 else "c.setreg(%d, %d, %s);" % (r, sz, v)


def rd(i, sz):
    if i.mem:
        return {1: "m.r8(ea) as u32", 2: "m.r16(ea) as u32", 4: "m.r32(ea)"}[sz]
    return greg(i.rm, sz)


def wr(i, sz, v):
    if i.mem:
        return {1: "m.w8(ea, (%s) as u8);", 2: "m.w16(ea, (%s) as u16);", 4: "m.w32(ea, %s);"}[sz] % v
    return sreg(i.rm, sz, v)


def ea(i):
    return ["let ea = %s;" % i.ea] if i.mem else []


class Xlate:
    def __init__(self, pack, mods):
        self.pack, self.mods = pack, mods
        self.by_name = {m.name: m for m in mods}
        self.imports, self.imp_index = [], {}
        self.iat = {}
        for m in mods:
            for slot, dll, name, ordinal in m.imports:
                guest = self.by_name.get(os.path.splitext(dll)[0])
                if guest is not None:
                    va = guest.exports.get(name) if name else guest.ordinals.get(ordinal)
                    if va is None:
                        raise SystemExit("%s imports %s!%s, which it does not export" % (m.name, dll, name or ordinal))
                    self.iat[slot] = ("guest", va)
                else:
                    key = (dll, name or "#%d" % ordinal)
                    if key not in self.imp_index:
                        self.imp_index[key] = len(self.imports)
                        self.imports.append(key)
                    self.iat[slot] = ("host", self.imp_index[key])
        self.funcs = {}
        self.entries = set()
        self.stats = Counter()
        self.unsupported = Counter()

    def module_of(self, va):
        for m in self.mods:
            if m.has(va):
                return m
        return None

    def in_text(self, va):
        m = self.module_of(va)
        return m is not None and m.in_text(va)

    # -- decode one instruction: semantics into lines, plus control flow --
    def decode(self, mod, va):
        i = Insn(mod, va)
        try:
            i.lines = self.semantics(i)
        except Unsupported as e:
            i.lines = ['xrt::trap("%s", %s);' % (str(e).replace('"', "'"), hx(va))]
            i.kind = "trap"
            self.unsupported[str(e)] += 1
            if i.p == va:
                i.p = va + 1
        i.next = i.p
        return i

    def semantics(self, i):
        op, sz, va = i.op, i.opsz, i.va
        if i.op2 is not None:
            return self.semantics_0f(i)
        if op < 0x40 and (op & 7) <= 5 and op not in (0x26, 0x2E, 0x36, 0x3E):
            g, form = op >> 3, op & 7
            if g == 7 and form >= 6 or (op & 7) >= 6:
                raise Unsupported("opcode %02x" % op)
            name = ALU[g]
            if form <= 3:
                i.modrm()
                s = 1 if form in (0, 2) else sz
                if form <= 1:
                    a, b = rd(i, s), greg(i.reg, s)
                    dst = lambda v: wr(i, s, v)
                else:
                    a, b = greg(i.reg, s), rd(i, s)
                    dst = lambda v: sreg(i.reg, s, v)
            else:
                s = 1 if form == 4 else sz
                v = i.imm8() if form == 4 else i.immz()
                a, b = greg(0, s), hx(v) + "_u32"
                dst = lambda v: sreg(0, s, v)
            out = ea(i) + ["let a = %s;" % a, "let b = %s;" % b]
            if g == 7:
                return out + ["c.sub(a, b, %d);" % s]
            return out + ["let v = c.%s(a, b, %d);" % (name, s), dst("v")]
        if 0x40 <= op <= 0x4F:
            r, fn = op & 7, "inc" if op < 0x48 else "dec"
            return ["let v = c.%s(%s, %d);" % (fn, greg(r, sz), sz), sreg(r, sz, "v")]
        if 0x50 <= op <= 0x57:
            return ["let v = c.r[%d];" % (op - 0x50), "c.push32(m, v);"]
        if 0x58 <= op <= 0x5F:
            return ["let v = c.pop32(m);", "c.r[%d] = v;" % (op - 0x58)]
        if op == 0x68:
            return ["c.push32(m, %s);" % hx(i.imm32())]
        if op == 0x6A:
            return ["c.push32(m, %s);" % hx(i.simm8())]
        if op in (0x69, 0x6B):
            i.modrm()
            if op == 0x6B:
                b = i.simm8()
            else:
                b = (i.mod.s16(i.p) & 0xFFFFFFFF) if sz == 2 else None
                if sz == 2:
                    i.p += 2
                else:
                    b = i.imm32()
            return ea(i) + ["let a = %s;" % rd(i, sz), "let v = c.imul(a, %s);" % hx(b), sreg(i.reg, sz, "v")]
        if 0x70 <= op <= 0x7F:
            d = i.simm8()
            i.kind, i.cc, i.target = "jcc", "c.cond(%d)" % (op - 0x70), (i.p + d) & 0xFFFFFFFF
            return []
        if op in (0x80, 0x81, 0x83):
            i.modrm()
            s = 1 if op == 0x80 else sz
            b = i.imm8() if op == 0x80 else (i.immz() if op == 0x81 else i.simm8())
            out = ea(i) + ["let a = %s;" % rd(i, s)]
            if i.reg == 7:
                return out + ["c.sub(a, %s, %d);" % (hx(b), s)]
            return out + ["let v = c.%s(a, %s, %d);" % (ALU[i.reg], hx(b), s), wr(i, s, "v")]
        if op in (0x84, 0x85):
            i.modrm()
            s = 1 if op == 0x84 else sz
            return ea(i) + ["let v = %s & %s;" % (rd(i, s), greg(i.reg, s)), "c.logic(v, %d);" % s]
        if op in (0x86, 0x87):
            i.modrm()
            s = 1 if op == 0x86 else sz
            return ea(i) + ["let a = %s;" % rd(i, s), "let b = %s;" % greg(i.reg, s), wr(i, s, "b"), sreg(i.reg, s, "a")]
        if op in (0x88, 0x89):
            i.modrm()
            s = 1 if op == 0x88 else sz
            return ea(i) + ["let v = %s;" % greg(i.reg, s), wr(i, s, "v")]
        if op in (0x8A, 0x8B):
            i.modrm()
            s = 1 if op == 0x8A else sz
            return ea(i) + ["let v = %s;" % rd(i, s), sreg(i.reg, s, "v")]
        if op == 0x8D:
            i.modrm()
            return [sreg(i.reg, sz, i.ea if i.mem else "0")]
        if op == 0x8C:
            i.modrm()
            return ea(i) + [wr(i, 2, hx(SEGSEL[i.reg]) + "_u32")]
        if op == 0x8E:
            i.modrm()
            return ea(i) + (["let _ = m.r16(ea);"] if i.mem else [])
        if op == 0x8F:
            i.modrm()
            return ea(i) + ["let v = c.pop32(m);", wr(i, sz, "v")]
        if op in (0x90, 0x9B):
            return []
        if 0x91 <= op <= 0x97:
            return ["c.r.swap(0, %d);" % (op - 0x90)]
        if op == 0x98:
            return ["c.cbw(%d);" % sz]
        if op == 0x99:
            return ["c.cwd(%d);" % sz]
        if 0xA0 <= op <= 0xA3:
            a = hx(i.imm32()) + "_u32" + (".wrapping_add(%s)" % i.seg if i.seg else "")
            out = ["let ea = %s;" % a]
            if op == 0xA0:
                return out + [sreg(0, 1, "m.r8(ea) as u32")]
            if op == 0xA1:
                return out + [sreg(0, sz, "m.r16(ea) as u32" if sz == 2 else "m.r32(ea)")]
            if op == 0xA2:
                return out + ["m.w8(ea, c.r[0] as u8);"]
            return out + (["m.w16(ea, c.r[0] as u16);"] if sz == 2 else ["m.w32(ea, c.r[0]);"])
        if op in (0xA8, 0xA9):
            s = 1 if op == 0xA8 else sz
            v = i.imm8() if op == 0xA8 else i.immz()
            return ["let v = %s & %s;" % (greg(0, s), hx(v)), "c.logic(v, %d);" % s]
        if 0xA4 <= op <= 0xAF and op not in (0xA8, 0xA9):
            s = 1 if op % 2 == 0 else sz
            anyrep = "true" if (i.rep or i.repne) else "false"
            if op in (0xA4, 0xA5):
                return ["c.movs(m, %d, %s);" % (s, anyrep)]
            if op in (0xAA, 0xAB):
                return ["c.stos(m, %d, %s);" % (s, anyrep)]
            if op in (0xAC, 0xAD):
                return ["c.lods(m, %d, %s);" % (s, anyrep)]
            fn = "scas" if op in (0xAE, 0xAF) else "cmps"
            return ["c.%s(m, %d, %s, %s);" % (fn, s, str(i.rep).lower(), str(i.repne).lower())]
        if 0xB0 <= op <= 0xB7:
            return [sreg(op - 0xB0, 1, hx(i.imm8()) + "_u32")]
        if 0xB8 <= op <= 0xBF:
            return [sreg(op - 0xB8, sz, hx(i.immz()) + "_u32")]
        if op in (0xC0, 0xC1, 0xD0, 0xD1, 0xD2, 0xD3):
            i.modrm()
            s = 1 if op in (0xC0, 0xD0, 0xD2) else sz
            out = ea(i) + ["let v = %s;" % rd(i, s)]
            cnt = "%d" % i.imm8() if op in (0xC0, 0xC1) else ("1" if op in (0xD0, 0xD1) else "c.r[1] & 0xff")
            return out + ["let v = c.shift(%d, v, %s, %d);" % (i.reg, cnt, s), wr(i, s, "v")]
        if op == 0xC2:
            i.kind, i.retn = "ret", i.imm16()
            return []
        if op == 0xC3:
            i.kind, i.retn = "ret", 0
            return []
        if op in (0xC6, 0xC7):
            i.modrm()
            s = 1 if op == 0xC6 else sz
            v = i.imm8() if op == 0xC6 else i.immz()
            return ea(i) + [wr(i, s, hx(v) + "_u32")]
        if op == 0xC9:
            return ["c.r[4] = c.r[5];", "c.r[5] = c.pop32(m);"]
        if op == 0xCC:
            raise Unsupported("int3")
        if op == 0xE8:
            d = i.mod.s32(i.p)
            i.p += 4
            i.kind, i.target = "call", (i.p + d) & 0xFFFFFFFF
            return []
        if op in (0xE9, 0xEB):
            if op == 0xE9:
                d = i.mod.s32(i.p)
                i.p += 4
            else:
                d = i.mod.s8(i.p)
                i.p += 1
            i.kind, i.target = "jmp", (i.p + d) & 0xFFFFFFFF
            return []
        if op == 0xE3:
            d = i.simm8()
            i.kind, i.target = "jcc", (i.p + d) & 0xFFFFFFFF
            i.cc = "(c.r[1] & 0xffff) == 0" if sz == 2 else "c.r[1] == 0"
            return []
        if op in (0xE0, 0xE1, 0xE2):
            d = i.simm8()
            i.kind, i.target = "jcc", (i.p + d) & 0xFFFFFFFF
            i.cc = {0xE2: "c.r[1] != 0", 0xE1: "c.r[1] != 0 && c.flag(ZF)", 0xE0: "c.r[1] != 0 && !c.flag(ZF)"}[op]
            return ["c.r[1] = c.r[1].wrapping_sub(1);"]
        if op in (0xF6, 0xF7):
            i.modrm()
            s = 1 if op == 0xF6 else sz
            g = i.reg
            out = ea(i) + ["let a = %s;" % rd(i, s)]
            if g in (0, 1):
                v = i.imm8() if op == 0xF6 else i.immz()
                return out + ["c.logic(a & %s, %d);" % (hx(v), s)]
            if g == 2:
                return out + [wr(i, s, "!a")]
            if g == 3:
                return out + ["let v = c.neg(a, %d);" % s, wr(i, s, "v")]
            if g == 4:
                return out + ["c.mul1(a, %d);" % s]
            if g == 5:
                return out + ["c.imul1(a, %d);" % s]
            fn, what = ("div1", "div0") if g == 6 else ("idiv1", "idiv0")
            return out + ['if !c.%s(a, %d) { xrt::trap("%s", %s); }' % (fn, s, what, hx(va))]
        if op == 0xF5:
            return ["let f = c.flag(CF);", "c.setf(CF, !f);"]
        if op in (0xF8, 0xF9):
            return ["c.setf(CF, %s);" % ("true" if op == 0xF9 else "false")]
        if op in (0xFC, 0xFD):
            return ["c.setf(DF, %s);" % ("true" if op == 0xFD else "false")]
        if op == 0xFE:
            i.modrm()
            fn = "inc" if i.reg == 0 else "dec"
            return ea(i) + ["let a = %s;" % rd(i, 1), "let v = c.%s(a, 1);" % fn, wr(i, 1, "v")]
        if op == 0xFF:
            i.modrm()
            g = i.reg
            if g in (0, 1):
                fn = "inc" if g == 0 else "dec"
                return ea(i) + ["let a = %s;" % rd(i, sz), "let v = c.%s(a, %d);" % (fn, sz), wr(i, sz, "v")]
            if g in (2, 3):
                i.kind = "calli"
                i.tgt = ea(i) + ["let t = %s;" % rd(i, sz)]
                return []
            if g in (4, 5):
                i.kind = "jmpi"
                i.tgt = ea(i) + ["let t = %s;" % rd(i, sz)]
                return []
            if g == 6:
                return ea(i) + ["let v = %s;" % rd(i, sz), "c.push32(m, v);"]
            return []
        if op == 0xD7:
            a = "c.r[3].wrapping_add(c.r[0] & 0xff)" + (".wrapping_add(%s)" % i.seg if i.seg else "")
            return ["let ea = %s;" % a, sreg(0, 1, "m.r8(ea) as u32")]
        if op == 0x9C:
            return ["let v = c.eflags;", "c.push32(m, v);"]
        if op == 0x9D:
            return ["let v = c.pop32(m);", "c.popf_value(v);"]
        if op == 0x9E:
            return ["c.sahf();"]
        if op == 0x9F:
            return ["c.lahf();"]
        if op == 0x60:
            return ["let sp = c.r[4];"] + ["let v = c.r[%d]; c.push32(m, v);" % r for r in (0, 1, 2, 3)] + \
                   ["c.push32(m, sp);"] + ["let v = c.r[%d]; c.push32(m, v);" % r for r in (5, 6, 7)]
        if op == 0x61:
            return ["c.r[7] = c.pop32(m);", "c.r[6] = c.pop32(m);", "c.r[5] = c.pop32(m);", "c.pop32(m);",
                    "c.r[3] = c.pop32(m);", "c.r[2] = c.pop32(m);", "c.r[1] = c.pop32(m);", "c.r[0] = c.pop32(m);"]
        if 0xD8 <= op <= 0xDF:
            i.modrm()
            if i.mem:
                return ea(i) + ['if !c.x87_mem(m, %s, %d, ea) { xrt::trap("x87", %s); }' % (hx(op), i.reg, hx(va))]
            return ['if !c.x87_reg(%s, %s) { xrt::trap("x87", %s); }' % (hx(op), hx(i.modrm_byte), hx(va))]
        raise Unsupported("opcode %02x" % op)

    def semantics_0f(self, i):
        o, sz = i.op2, i.opsz
        if o in SSE:
            raise Unsupported("sse 0f %02x" % o)
        if 0x80 <= o <= 0x8F:
            if sz == 2:
                d = i.mod.s16(i.p)
                i.p += 2
            else:
                d = i.mod.s32(i.p)
                i.p += 4
            i.kind, i.cc, i.target = "jcc", "c.cond(%d)" % (o - 0x80), (i.p + d) & 0xFFFFFFFF
            return []
        if 0x90 <= o <= 0x9F:
            i.modrm()
            return ea(i) + ["let v = c.cond(%d) as u32;" % (o - 0x90), wr(i, 1, "v")]
        if 0x40 <= o <= 0x4F:
            i.modrm()
            return ea(i) + ["let v = %s;" % rd(i, sz), "if c.cond(%d) { %s }" % (o - 0x40, sreg(i.reg, sz, "v"))]
        if o in (0xB6, 0xB7, 0xBE, 0xBF):
            i.modrm()
            src = rd(i, 1 if o in (0xB6, 0xBE) else 2)
            v = {0xB6: src, 0xB7: src, 0xBE: "(%s) as u8 as i8 as i32 as u32" % src,
                 0xBF: "(%s) as u16 as i16 as i32 as u32" % src}[o]
            return ea(i) + ["let v = %s;" % v, sreg(i.reg, sz, "v")]
        if o == 0xAF:
            i.modrm()
            return ea(i) + ["let a = %s;" % greg(i.reg, sz), "let b = %s;" % rd(i, sz),
                            "let v = c.imul(a, b);", sreg(i.reg, sz, "v")]
        if o == 0xA2:
            return ["c.cpuid();"]
        if o == 0x31:
            return ["c.r[0] = 0;", "c.r[2] = 0;"]
        if o in (0xA3, 0xAB, 0xB3, 0xBB):
            i.modrm()
            sel = {0xA3: 4, 0xAB: 5, 0xB3: 6, 0xBB: 7}[o]
            if i.mem:
                return ea(i) + ["let off = %s;" % greg(i.reg, sz), "c.bt_mem(m, %d, ea, off, %d);" % (sel, sz)]
            out = ["let bit = %s;" % greg(i.reg, sz), "let v = %s;" % rd(i, sz),
                   "let nv = c.bt(%d, v, bit, %d);" % (sel, sz)]
            return out + ([wr(i, sz, "nv")] if sel != 4 else [])
        if o == 0xBA:
            i.modrm()
            imm = i.imm8()
            out = ea(i) + ["let v = %s;" % rd(i, sz), "let nv = c.bt(%d, v, %d, %d);" % (i.reg, imm, sz)]
            return out + ([wr(i, sz, "nv")] if i.reg in (5, 6, 7) else [])
        if o in (0xBC, 0xBD):
            i.modrm()
            fn = "bsf" if o == 0xBC else "bsr"
            return ea(i) + ["let v = %s;" % rd(i, sz), "if let Some(k) = c.%s(v) { %s }" % (fn, sreg(i.reg, sz, "k"))]
        if o in (0xA4, 0xA5, 0xAC, 0xAD):
            i.modrm()
            cnt = "%d" % i.imm8() if o in (0xA4, 0xAC) else "c.r[1] & 0xff"
            fn = "shld" if o in (0xA4, 0xA5) else "shrd"
            return ea(i) + ["let d = %s;" % rd(i, sz), "let s = %s;" % greg(i.reg, sz),
                            "let v = c.%s(d, s, %s, %d);" % (fn, cnt, sz), wr(i, sz, "v")]
        if o in (0xC0, 0xC1):
            i.modrm()
            s = 1 if o == 0xC0 else sz
            return ea(i) + ["let a = %s;" % rd(i, s), "let b = %s;" % greg(i.reg, s), "let v = c.add(a, b, %d);" % s,
                            sreg(i.reg, s, "a"), wr(i, s, "v")]
        if o in (0xB0, 0xB1):
            i.modrm()
            s = 1 if o == 0xB0 else sz
            return ea(i) + ["let a = %s;" % rd(i, s), "let acc = %s;" % greg(0, s), "c.sub(acc, a, %d);" % s,
                            "if acc == a { let v = %s; %s } else { %s }" % (greg(i.reg, s), wr(i, s, "v"), sreg(0, s, "a"))]
        if 0xC8 <= o <= 0xCF:
            return ["c.r[%d] = c.r[%d].swap_bytes();" % (o - 0xC8, o - 0xC8)]
        if o == 0x1F or 0x18 <= o <= 0x1E or o == 0xAE:
            i.modrm()
            return []
        if o == 0x77:
            return []
        raise Unsupported("0f %02x" % o)

    # -- discovery --
    def jump_table(self, i):
        """`jmp [disp + idx*4]`: entries run while each slot is relocated."""
        if not (i.mem and i.modv == 0 and i.sib and i.sib[0] == 2 and i.sib[2] == 5 and not i.seg):
            return None
        mod = self.module_of(i.disp)
        if mod is None:
            return None
        out, a = [], i.disp
        while a in mod.relocs and len(out) < 4096:
            v = mod.u32(a)
            if not self.in_text(v):
                break
            out.append(v)
            a += 4
        return out or None

    def seeds(self):
        s = set()
        for m in self.mods:
            s.update(m.exports.values())
            if m.entry:
                s.add(m.entry)
            for site in m.relocs:
                if m.in_text(site):
                    continue
                v = m.u32(site)
                if self.in_text(v):
                    s.add(v)
        for kind, v in self.iat.values():
            if kind == "guest":
                s.add(v)
        return {v for v in s if self.in_text(v)}

    def descend(self, entry):
        mod = self.module_of(entry)
        blocks, insns, calls, ptrs = set(), {}, set(), set()
        tables = {}
        queue = [entry]
        while queue:
            b = queue.pop()
            if b in blocks:
                continue
            blocks.add(b)
            va = b
            while True:
                if not mod.in_text(va):
                    insns[va] = self.trap_insn(mod, va, "off text")
                    break
                if va in insns:
                    break
                i = self.decode(mod, va)
                insns[va] = i
                for site in i.imm_sites:
                    if site in mod.relocs and self.in_text(mod.u32(site)):
                        ptrs.add(mod.u32(site))
                k = i.kind
                if k == "jcc":
                    if i.target not in self.entries or i.target == entry:
                        queue.append(i.target)
                elif k == "jmp":
                    if i.target not in self.entries or i.target == entry:
                        queue.append(i.target)
                    break
                elif k == "jmpi":
                    t = self.jump_table(i)
                    if t:
                        tables[va] = t
                        for x in t:
                            if self.module_of(x) is mod:
                                queue.append(x)
                    break
                elif k == "call":
                    if self.in_text(i.target) and i.target != i.next:
                        calls.add(i.target)
                elif k in ("ret", "trap"):
                    break
                va = i.next
        return {"entry": entry, "mod": mod, "blocks": blocks, "insns": insns, "calls": calls,
                "ptrs": ptrs, "tables": tables}

    def trap_insn(self, mod, va, why):
        i = Insn.__new__(Insn)
        i.va, i.mod, i.kind, i.next = va, mod, "trap", va + 1
        i.lines = ['xrt::trap("%s", %s);' % (why, hx(va))]
        self.unsupported[why] += 1
        return i

    def discover(self):
        self.entries = self.seeds()
        work = sorted(self.entries)
        while work:
            e = work.pop()
            if e in self.funcs:
                continue
            fn = self.descend(e)
            self.funcs[e] = fn
            for t in sorted(fn["calls"] | fn["ptrs"]):
                if t not in self.entries:
                    self.entries.add(t)
                    work.append(t)

    # -- emission --
    def call_to(self, t):
        if t in self.funcs:
            return "f_%08x(c, m, h);" % t
        return "dispatch::enter(c, m, h, %s);" % hx(t)

    def tail(self, t):
        return [self.call_to(t), "return;"]

    def emit_control(self, fn, i, out):
        k = i.kind
        if k == "jcc":
            if i.target in fn["blocks"]:
                out.append("if %s { pc = %s; continue; }" % (i.cc, hx(i.target)))
            else:
                out.append("if %s { %s return; }" % (i.cc, self.call_to(i.target)))
            return False
        if k == "jmp":
            if i.target in fn["blocks"]:
                out += ["pc = %s;" % hx(i.target), "continue;"]
            else:
                out += self.tail(i.target)
            return True
        if k == "call":
            ret = i.next
            out.append("c.push32(m, %s);" % hx(ret))
            if i.target == ret:
                return False
            out += [self.call_to(i.target), "xrt::check_ret(c, %s, %s);" % (hx(ret), hx(i.va))]
            self.stats["call"] += 1
            return False
        if k == "calli":
            ret = i.next
            slot = self.iat_slot(i)
            if slot is not None:
                kind, v = self.iat[slot]
                out.append("c.push32(m, %s);" % hx(ret))
                out.append("h.import(%d, c, m);" % v if kind == "host" else self.call_to(v))
                self.stats["call_" + kind] += 1
            else:
                out += i.tgt + ["c.push32(m, %s);" % hx(ret), "dispatch::enter(c, m, h, t);"]
                self.stats["call_indirect"] += 1
            out.append("xrt::check_ret(c, %s, %s);" % (hx(ret), hx(i.va)))
            return False
        if k == "jmpi":
            slot = self.iat_slot(i)
            if slot is not None:
                kind, v = self.iat[slot]
                out += ["h.import(%d, c, m);" % v, "return;"] if kind == "host" else self.tail(v)
                self.stats["tail_" + kind] += 1
            else:
                out += i.tgt + ["pc = t;", "continue;"]
                self.stats["jmp_table" if i.va in fn["tables"] else "jmp_indirect"] += 1
            return True
        if k == "ret":
            out += ["c.ret(m, %d);" % i.retn, "return;"]
            return True
        if k == "trap":
            return True
        return False

    def iat_slot(self, i):
        if i.mem and i.modv == 0 and i.rm == 5 and not i.seg and i.disp in self.iat:
            return i.disp
        return None

    def emit_function(self, fn):
        e = fn["entry"]
        blocks = sorted(fn["blocks"])
        out = [
            "pub fn f_%08x(c: &mut Cpu, m: &mut Mem, h: &mut dyn Host) {" % e,
            "    f_%08x_at(c, m, h, %s)" % (e, hx(e)),
            "}",
            "",
            "pub fn f_%08x_at(c: &mut Cpu, m: &mut Mem, h: &mut dyn Host, start: u32) {" % e,
            "    let mut pc: u32 = start;",
            "    loop {",
            "        #[cfg(feature = \"cover\")]",
            "        xrt::hit(pc);",
            "        match pc {",
        ]
        for b in blocks:
            out.append("            %s => {" % hx(b))
            va = b
            while True:
                i = fn["insns"].get(va)
                if i is None:
                    out.append('                xrt::trap("undecoded", %s);' % hx(va))
                    break
                body = []
                for line in i.lines:
                    body.append(line)
                ends = self.emit_control(fn, i, body)
                self.stats["insns"] += 1
                if len(body) == 1 and body[0].endswith(";") and "let " not in body[0]:
                    out.append("                " + body[0])
                elif body:
                    out.append("                {")
                    out += ["                    " + q for q in body]
                    out.append("                }")
                if ends or i.kind == "trap":
                    break
                va = i.next
                if va in fn["blocks"]:
                    out += ["                pc = %s;" % hx(va), "                continue;"]
                    break
            out.append("            }")
        out += [
            "            _ => {",
            "                dispatch::enter(c, m, h, pc);",
            "                return;",
            "            }",
            "        }",
            "    }",
            "}",
            "",
        ]
        return out

    # -- output --
    def write(self, out_dir):
        if os.path.isdir(out_dir):
            shutil.rmtree(out_dir)
        os.makedirs(out_dir)
        header = [
            "//! Generated by `tools/x86xlate.py` -- do not edit.",
            "",
            "#![allow(clippy::all, unused_assignments, unused_mut, unused_parens, unused_braces,",
            "         unreachable_code, unused_variables, unused_imports, non_snake_case)]",
            "",
            "use super::*;",
            "use ss_rs_ng_xrt::{self as xrt, Cpu, Host, Mem, CF, DF, ZF};",
            "",
        ]
        shards, cur, size = [], [], 0
        for m in self.mods:
            fns = [f for f in self.funcs.values() if f["mod"] is m]
            k = 0
            for fn in sorted(fns, key=lambda f: f["entry"]):
                lines = self.emit_function(fn)
                cur += lines
                size += sum(len(x) + 1 for x in lines)
                if size > SHARD_BYTES:
                    shards.append(("%s_%d" % (m.name, k), cur))
                    cur, size, k = [], 0, k + 1
            if cur:
                shards.append(("%s_%d" % (m.name, k), cur))
                cur, size = [], 0
        for name, lines in shards:
            with open(os.path.join(out_dir, name + ".rs"), "w", encoding="ascii", newline="\n") as f:
                f.write("\n".join(header + lines) + "\n")
        self.write_dispatch(out_dir)
        self.write_modules(out_dir)
        mod_rs = ["//! Generated by `tools/x86xlate.py` -- do not edit.", ""]
        mod_rs += ["pub mod dispatch;", "pub mod modules;", "pub use dispatch::*;", "",
                   "pub static PACK: crate::Pack = crate::Pack {",
                   '    name: "%s",' % self.pack,
                   "    modules: modules::MODULES,",
                   "    imports: modules::IMPORTS,",
                   "    enter: dispatch::enter,",
                   "};", ""]
        for name, _ in shards:
            mod_rs += ["mod %s;" % name, "pub use %s::*;" % name]
        with open(os.path.join(out_dir, "mod.rs"), "w", encoding="ascii", newline="\n") as f:
            f.write("\n".join(mod_rs) + "\n")
        return len(shards)

    def write_dispatch(self, out_dir):
        blocks = {}
        for e, fn in self.funcs.items():
            for b in fn["blocks"]:
                if b not in blocks or e == b:
                    blocks[b] = e
        out = [
            "//! Generated by `tools/x86xlate.py` -- do not edit.",
            "//!",
            "//! Every block of every translated function, so an indirect transfer",
            "//! can land anywhere the guest can, and the host thunk range.",
            "",
            "use super::*;",
            "use ss_rs_ng_xrt::{self as xrt, Cpu, Host, Mem, THUNK_BASE, THUNK_END};",
            "",
            "type Enter = fn(&mut Cpu, &mut Mem, &mut dyn Host, u32);",
            "",
            "static BLOCKS: &[(u32, Enter)] = &[",
        ]
        for b in sorted(blocks):
            out.append("    (%s, f_%08x_at)," % (hx(b), blocks[b]))
        out += [
            "];",
            "",
            "/// Transfer to guest code at `pc` (or a host thunk), as an indirect",
            "/// `call` or a tail jump: the return address is already on the stack.",
            "pub fn enter(c: &mut Cpu, m: &mut Mem, h: &mut dyn Host, pc: u32) {",
            "    if (THUNK_BASE..THUNK_END).contains(&pc) {",
            "        h.import((pc - THUNK_BASE) / 16, c, m);",
            "        return;",
            "    }",
            "    match BLOCKS.binary_search_by_key(&pc, |e| e.0) {",
            "        Ok(k) => (BLOCKS[k].1)(c, m, h, pc),",
            "        Err(_) => xrt::no_code(pc),",
            "    }",
            "}",
            "",
            "/// Whether `pc` is translated code.",
            "pub fn is_code(pc: u32) -> bool {",
            "    BLOCKS.binary_search_by_key(&pc, |e| e.0).is_ok()",
            "}",
            "",
        ]
        with open(os.path.join(out_dir, "dispatch.rs"), "w", encoding="ascii", newline="\n") as f:
            f.write("\n".join(out) + "\n")

    def write_modules(self, out_dir):
        out = [
            "//! Generated by `tools/x86xlate.py` -- do not edit.",
            "//!",
            "//! What the host's loader needs: where each module goes, the file it",
            "//! must be, and how to fill its import table.",
            "",
            "use crate::Module;",
            "",
            "/// Host imports, by index: `(dll, name)`.",
            "pub static IMPORTS: &[(&str, &str)] = &[",
        ]
        out += ['    ("%s", "%s"),' % (d, n) for d, n in self.imports]
        out += ["];", "", "pub static MODULES: &[Module] = &["]
        for m in self.mods:
            iat = []
            for slot, _d, _n, _o in m.imports:
                kind, v = self.iat[slot]
                iat.append((slot, v if kind == "guest" else THUNK_BASE + 16 * v))
            out += [
                "    Module {",
                '        name: "%s",' % m.name,
                '        file: "%s",' % m.rel,
                "        base: %s," % hx(m.base),
                "        size: %s," % hx(m.size),
                '        sha256: "%s",' % m.sha256,
                "        entry: %s," % hx(m.entry),
                "        exports: &[%s]," % ", ".join('("%s", %s)' % (n, hx(v)) for n, v in sorted(m.exports.items())),
                "        ordinals: &[%s]," % ", ".join("(%d, %s)" % (o, hx(v)) for o, v in sorted(m.ordinals.items())),
                "        iat: &[%s]," % ", ".join("(%s, %s)" % (hx(s), hx(v)) for s, v in iat),
                "    },",
            ]
        out += ["];", ""]
        with open(os.path.join(out_dir, "modules.rs"), "w", encoding="ascii", newline="\n") as f:
            f.write("\n".join(out) + "\n")

    def unclaimed_text_relocs(self):
        claimed = set()
        for fn in self.funcs.values():
            for i in fn["insns"].values():
                claimed.update(range(i.va, i.next))
            for at, t in fn["tables"].items():
                pass
        tbl = set()
        for fn in self.funcs.values():
            for i in fn["insns"].values():
                if i.kind == "jmpi" and getattr(i, "va", None) in fn["tables"]:
                    tbl.update(range(i.disp, i.disp + 4 * len(fn["tables"][i.va])))
        out = []
        for m in self.mods:
            for site in sorted(m.relocs):
                if m.in_text(site) and site not in claimed and site not in tbl and self.in_text(m.u32(site)):
                    out.append((site, m.u32(site)))
        return out


def cmd_translate(args):
    man = json.load(open(manifest_path(args.pack)))
    speech = os.path.join(ROOT, man["speech"].replace("/", os.sep))
    mods = [Module(x["name"], x["file"], int(x["base"], 16), speech) for x in man["modules"]]
    xl = Xlate(args.pack, mods)
    xl.discover()
    out_dir = args.out or os.path.join(NG, "crates", "ss-rs-ng-eng", "src", args.pack)
    n_shards = xl.write(out_dir)
    nblocks = sum(len(f["blocks"]) for f in xl.funcs.values())
    print("%s: %d modules, %d functions, %d blocks, %d instructions -> %s (%d shards)" % (
        args.pack, len(mods), len(xl.funcs), nblocks, xl.stats["insns"], out_dir, n_shards))
    print("  control: " + ", ".join("%s %d" % kv for kv in sorted(xl.stats.items()) if kv[0] != "insns"))
    print("  host imports: %d" % len(xl.imports))
    if xl.unsupported:
        print("  trapping (as cpu.c would): " + ", ".join("%s x%d" % kv for kv in xl.unsupported.most_common()))
    un = xl.unclaimed_text_relocs()
    print("  relocated code pointers inside .text not reached: %d%s" % (
        len(un), (" e.g. " + ", ".join("%08x->%08x" % x for x in un[:8])) if un else ""))
    cov = Counter()
    for fn in xl.funcs.values():
        for i in fn["insns"].values():
            cov[fn["mod"].name] += i.next - i.va
    for m in mods:
        tot = sum(hi - lo for lo, hi in m.text)
        print("  %-16s %6.1f%% of .text decoded" % (m.name, 100.0 * min(cov[m.name], tot) / max(1, tot)))
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("manifest")
    t = sub.add_parser("translate")
    t.add_argument("--pack", choices=sorted(PACKS), required=True)
    t.add_argument("--out")
    a = ap.parse_args()
    return cmd_manifest(a) if a.cmd == "manifest" else cmd_translate(a)


if __name__ == "__main__":
    sys.exit(main())
