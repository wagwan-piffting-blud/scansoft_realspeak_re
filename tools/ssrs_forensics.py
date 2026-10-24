"""Forensic sweep of the ScanSoft 2004 / RealSpeak 2006 packs, one section per evidence class.

    python -I ssrs_forensics.py > C:\\tmp\\tom_overlap\\forensics.txt

Sections: [PE] debug/NB10 + Rich + version resources; [VER] build-number-as-date test;
[HDR] .hdr fields; [DAT] SCANSOFT headers + tails + embedded ASCII; [SAPI] NextUp patch diff;
[OCX] GUIDs / typelib strings; [STR] people / machines / codenames / dates / tools scan.
"""
import collections
import datetime as dt
import glob
import hashlib
import os
import re
import struct

import pefile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROOTS = {"SS": ROOT + r"\ScanSoft\speech",
         "RS": ROOT + r"\RealSpeak\speech"}
PE_EXT = (".dll", ".ocx", ".orig", ".exe")


def files(ext):
    for tag, root in ROOTS.items():
        for dp, _, fs in os.walk(root):
            for f in sorted(fs):
                if f.lower().endswith(ext):
                    yield tag, os.path.join(dp, f), os.path.relpath(os.path.join(dp, f), root)


def utc(t):
    return dt.datetime(1970, 1, 1) + dt.timedelta(seconds=t)


def pe_section():
    print("=" * 30, "[PE] debug records, Rich profiles, version resources")
    rich_groups = collections.defaultdict(list)
    ver_rows = []
    for tag, path, rel in files(PE_EXT):
        try:
            pe = pefile.PE(path)
        except Exception as e:
            print(f"{tag} {rel}: not PE ({e})")
            continue
        ts = pe.FILE_HEADER.TimeDateStamp
        dbg = []
        for d in getattr(pe, "DIRECTORY_ENTRY_DEBUG", []):
            raw_off = d.struct.PointerToRawData
            blob = pe.__data__[raw_off:raw_off + d.struct.SizeOfData]
            if blob[:4] == b"NB10":
                sig, age = struct.unpack_from("<II", blob, 8)
                pdb = blob[16:].split(b"\0")[0].decode("latin1")
                dbg.append(f"NB10 sig {utc(sig):%Y-%m-%d %H:%M:%S} (PE-sig {(ts - sig) / 60:+.1f} min) age {age} {pdb}")
            elif blob[:4] == b"RSDS":
                age = struct.unpack_from("<I", blob, 20)[0]
                dbg.append(f"RSDS age {age} {blob[24:].split(b'\0')[0].decode('latin1')}")
            else:
                dbg.append(f"debug type {d.struct.Type} size {d.struct.SizeOfData} @raw {raw_off:#x}"
                           f" ts {utc(d.struct.TimeDateStamp):%Y-%m-%d}")
        try:
            r = pe.parse_rich_header()
            vals = r["values"] if r else []
            prof = tuple((vals[i] >> 16, vals[i] & 0xFFFF, vals[i + 1]) for i in range(0, len(vals), 2))
        except Exception:
            prof = ()
        rich_groups[prof].append(f"{tag}:{rel}")
        vi = {}
        trans = []
        for fi in getattr(pe, "FileInfo", []) or []:
            for e in fi:
                for st in getattr(e, "StringTable", []) or []:
                    vi["_lang"] = st.LangID.decode() if isinstance(st.LangID, bytes) else str(st.LangID)
                    for k, v in st.entries.items():
                        vi[k.decode("latin1")] = v.decode("latin1", "replace")
                for var in getattr(e, "Var", []) or []:
                    trans.append(var.entry)
        ffi = getattr(pe, "VS_FIXEDFILEINFO", None)
        fixed = ""
        if ffi:
            f0 = ffi[0]
            fixed = (f"{f0.FileVersionMS >> 16}.{f0.FileVersionMS & 0xFFFF}."
                     f"{f0.FileVersionLS >> 16}.{f0.FileVersionLS & 0xFFFF} flags {f0.FileFlags:#x}")
        print(f"\n{tag} {rel}  PE {utc(ts):%Y-%m-%d %H:%M:%S}  linker "
              f"{pe.OPTIONAL_HEADER.MajorLinkerVersion}.{pe.OPTIONAL_HEADER.MinorLinkerVersion}")
        for x in dbg:
            print("   ", x)
        print("    fixed:", fixed)
        for k, v in vi.items():
            print(f"    {k}: {v!r}")
        ver_rows.append((tag, rel, ts, fixed, vi.get("FileVersion", "")))
    print("\n--- modules sharing an identical Rich profile")
    for prof, mods in sorted(rich_groups.items(), key=lambda x: -len(x[1])):
        tools = ", ".join(f"id{p}/b{b}x{c}" for p, b, c in prof[:12])
        print(f"  [{len(mods)}] {tools}{' ...' if len(prof) > 12 else ''}")
        for m in mods:
            print("       ", m)
    return ver_rows


def ver_section(rows):
    print("\n" + "=" * 30, "[VER] does the 4th version field encode the build date?")
    for tag, rel, ts, fixed, fv in rows:
        m = re.match(r"^\s*(\d+)\.(\d+)\.(\d+)\.(\d+)", fixed)
        if not m:
            continue
        b = int(m.group(4))
        pe = utc(ts)
        cands = []
        if 1000 <= b <= 9999:
            y, ddd = 2000 + b // 1000, b % 1000
            if 1 <= ddd <= 366:
                cands.append(("YDDD", dt.datetime(y, 1, 1) + dt.timedelta(days=ddd - 1)))
        if b > 0:
            for name, base in (("days-since-1990", dt.datetime(1990, 1, 1)), ("days-since-2000", dt.datetime(2000, 1, 1))):
                cands.append((name, base + dt.timedelta(days=b)))
        s = "  ".join(f"{n} {d:%Y-%m-%d} ({(pe - d).days:+d} d)" for n, d in cands)
        print(f"  {tag} {rel:42} {fixed:28} PE {pe:%Y-%m-%d}  {s}")


def hdr_section():
    print("\n" + "=" * 30, "[HDR] .hdr files: all distinct tags and per-file values")
    tags = collections.defaultdict(set)
    for tag, path, rel in files(".hdr"):
        txt = open(path, "rb").read().decode("latin1")
        for k, v in re.findall(r"<\s*([A-Za-z_]+)\s*>\s*([^<\r\n]*)", txt):
            tags[k].add(v.strip())
        for k, v in re.findall(r"^\s*([A-Z_]{3,})\s+(.+?)\s*$", txt, re.M):
            tags[k].add(v.strip())
    for k, vs in sorted(tags.items()):
        vs = sorted(vs)
        print(f"  {k:18} ({len(vs):3}) {vs[:14]}{' ...' if len(vs) > 14 else ''}")
    one = next(files(".hdr"))[1]
    print("\n  sample file", one, ":\n", open(one, "rb").read().decode("latin1"))


ASCII = re.compile(rb"[\x20-\x7e]{6,}")


def dat_section():
    print("\n" + "=" * 30, "[DAT] SCANSOFT headers in full, tails, embedded ASCII")
    for tag, path, rel in files(".dat"):
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(0x90)
            if head[4:12] != b"SCANSOFT":
                body = open(path, "rb").read(4096)
                print(f"\n{tag} {rel} ({size} B): not SCANSOFT; head {body[:64]!r}")
                continue
            f.seek(max(0, size - 64))
            tail = f.read()
            f.seek(0)
            first = f.read(1 << 20)
            f.seek(max(0, size - (1 << 20)))
            last = f.read()
        flds = {"magic": hex(struct.unpack_from("<I", head, 0)[0]), "type": head[0x0c:0x14],
                "hdr_len": struct.unpack_from("<I", head, 0x14)[0], "version": head[0x18:0x20],
                "lang": head[0x20:0x2c], "voice": head[0x2c:0x4c], "variant": head[0x4c:0x7c],
                "toc_len": struct.unpack_from("<I", head, 0x7c)[0], "+80": head[0x80:0x84],
                "+84": struct.unpack_from("<I", head, 0x84)[0], "+88": head[0x88:0x90].hex()}
        print(f"\n{tag} {rel} ({size:,} B)")
        print("   ", {k: (v.decode('latin1').rstrip() if isinstance(v, bytes) else v) for k, v in flds.items()})
        print("    raw 0x54..0x7c:", head[0x54:0x7c])
        print("    tail 64 B:", tail.hex())
        for nm, blob in (("first 1 MB", first[0x90:]), ("last 1 MB", last)):
            hits = [m.group().decode() for m in ASCII.finditer(blob)]
            words = [h for h in hits if re.search(r"[A-Za-z]{4,}", h) and not re.fullmatch(r"(.)\1+", h)]
            print(f"    {nm}: {len(hits)} ASCII runs >= 6; wordy sample {words[:8]}")


def sapi_section():
    print("\n" + "=" * 30, "[SAPI] rs_sapi5_solo variants")
    d = ROOT + r"\ScanSoft\speech\components\common"
    a = open(os.path.join(d, "rs_sapi5_solo.dll"), "rb").read()
    o = open(os.path.join(d, "rs_sapi5_solo_nextup.dll.orig"), "rb").read()
    n = open(os.path.join(d, "rs_sapi5_solo_nextup.dll"), "rb").read()
    for name, x in (("rs_sapi5_solo.dll", a), (".orig", o), ("_nextup.dll", n)):
        print(f"  {name:20} {len(x):7} sha {hashlib.sha256(x).hexdigest()[:16]}")
    print("  solo == orig:", a == o)
    pe = pefile.PE(data=n)
    m = min(len(o), len(n))
    diffs = [i for i in range(m) if o[i] != n[i]]
    runs = []
    for i in diffs:
        if runs and i - runs[-1][1] <= 8:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    print(f"  orig vs nextup: {len(diffs)} differing bytes in {len(runs)} runs; size delta {len(n) - len(o)}")
    for s, e in runs[:40]:
        try:
            rva = pe.get_rva_from_offset(s)
            sec = next((x.Name.rstrip(b'\0').decode() for x in pe.sections if x.contains_rva(rva)), "?")
        except Exception:
            rva, sec = None, "?"
        print(f"    file {s:#07x}..{e:#07x} ({e - s + 1} B) rva {rva and hex(rva)} {sec}: "
              f"orig {o[s:e + 1][:32].hex()}  new {n[s:e + 1][:32].hex()}")
    if len(n) > len(o):
        extra = n[len(o):]
        print("  appended tail ascii:", [m.group().decode() for m in ASCII.finditer(extra)][:20])
    pe_o = pefile.PE(data=o)
    print("  sections orig:", [(x.Name.rstrip(b'\0').decode(), hex(x.PointerToRawData), hex(x.SizeOfRawData)) for x in pe_o.sections])
    print("  sections new :", [(x.Name.rstrip(b'\0').decode(), hex(x.PointerToRawData), hex(x.SizeOfRawData)) for x in pe.sections])


GUID = re.compile(rb"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}")


def ocx_section():
    print("\n" + "=" * 30, "[OCX] ssftrssolo.ocx GUIDs / typelib / interesting strings")
    p = ROOT + r"\ScanSoft\speech\components\common\ssftrssolo.ocx"
    d = open(p, "rb").read()
    print("  text GUIDs:", sorted({g.decode() for g in GUID.findall(d)})[:20])
    i = d.find(b"MSFT")
    print("  typelib 'MSFT' at", hex(i) if i >= 0 else None)
    wide = [m.group().replace(b"\0", b"").decode() for m in re.finditer(rb"(?:[\x20-\x7e]\x00){5,}", d)]
    keep = [w for w in wide if re.search(r"(?i)scansoft|speak|voice|tts|solo|l&h|lernout|version|build|copyright|\.ocx|\.dll", w)]
    print("  wide strings of interest:", keep[:40])
    asc = [m.group().decode() for m in ASCII.finditer(d)]
    keep = [a for a in asc if re.search(r"(?i)scansoft|speak|voice|solo|l&h|lernout|\.pdb|\\|build|author|copyright", a)]
    print("  ascii strings of interest:", keep[:40])


STR_PAT = re.compile(
    rb"(?i)(?:[a-z]:\\[^\x00\r\n\"]{3,120})|(?:\\\\[a-z0-9_-]{2,}\\[^\x00\r\n\"]{2,80})|"
    rb"(?:[a-z0-9._-]+@[a-z0-9.-]+\.[a-z]{2,})|"
    rb"(?:(?:19|20)\d\d[-/.](?:0[1-9]|1[0-2])[-/.](?:0[1-9]|[12]\d|3[01]))|"
    rb"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+(?:19|20)\d\d)|"
    rb"(?:\b(?:jennifer|tom|samantha|jill|kyoko|narae|isabel|paulina|karen|lee|daniel|emily)[a-z_]*\b)|"
    rb"(?:\b(?:build|builder|vbuild|voicebuild|recorded|session|prompt|script|corpus|labeler|aligner|"
    rb"segment(?:ation|er)|bootstrap|retrain|vfgen|mkvoice|makevoice|codsbgen|useldgen)\w*)")


def str_section():
    print("\n" + "=" * 30, "[STR] paths, mails, dates, voice names, tooling words (PE + small files)")
    for tag, path, rel in list(files(PE_EXT)) + list(files(".hdr")):
        d = open(path, "rb").read()
        hits = collections.Counter(m.group().decode("latin1").strip() for m in STR_PAT.finditer(d))
        if hits:
            print(f"  {tag} {rel}: " + " | ".join(f"{k}" + (f" x{v}" if v > 1 else "") for k, v in hits.most_common(25)))


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = pe_section()
    ver_section(rows)
    hdr_section()
    dat_section()
    sapi_section()
    ocx_section()
    str_section()
