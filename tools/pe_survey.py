import sys, os, re, hashlib, datetime, json
from concurrent.futures import ThreadPoolExecutor
import pefile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPFY = os.path.join(os.path.dirname(ROOT), "Speechify")

ROOTS = {
    "SS": ROOT + r"\ScanSoft\speech\components",
    "RS": ROOT + r"\RealSpeak\speech\components",
    "SPFY": SPFY + r"\bin",
}

MARKERS = [
    rb"\$Id[:$][^\x00]{0,120}", rb"[A-Za-z]:\\[^\x00]{4,200}\.pdb",
    rb"[A-Za-z]:\\[^\x00\"]{4,160}\.(?:c|cpp|h)\b",
    rb"[Cc]opyright[^\x00]{0,100}", rb"Lernout[^\x00]{0,60}", rb"L&H[^\x00]{0,60}",
    rb"SpeechWorks[^\x00]{0,60}", rb"ScanSoft[^\x00]{0,60}", rb"Nuance[^\x00]{0,60}",
    rb"Eloquen[^\x00]{0,60}", rb"Festival[^\x00]{0,60}", rb"[Ff]lite[^\x00]{0,60}",
    rb"cst_[a-z_]{3,40}", rb"item_add_daughter[^\x00]{0,40}", rb"[Ww]sola[^\x00]{0,40}",
    rb"[Kk]latt[^\x00]{0,40}", rb"ACELP[^\x00]{0,40}", rb"SCANSOFT",
]

def rich(pe):
    try:
        r = pe.parse_rich_header()
    except Exception:
        return None
    if not r:
        return None
    vals = r["values"]
    out = []
    for i in range(0, len(vals), 2):
        comp = vals[i]
        out.append((comp >> 16, comp & 0xFFFF, vals[i + 1]))
    return out

def one(tag_path):
    tag, path = tag_path
    d = open(path, "rb").read()
    rec = {"pack": tag, "file": os.path.relpath(path, ROOTS[tag]), "size": len(d),
           "sha": hashlib.sha256(d).hexdigest()[:16]}
    try:
        pe = pefile.PE(data=d, fast_load=False)
    except Exception as e:
        rec["err"] = str(e)
        return rec
    rec["ts"] = datetime.datetime.utcfromtimestamp(pe.FILE_HEADER.TimeDateStamp).isoformat()
    oh = pe.OPTIONAL_HEADER
    rec["linker"] = f"{oh.MajorLinkerVersion}.{oh.MinorLinkerVersion}"
    rec["base"] = hex(oh.ImageBase)
    last = pe.sections[-1]
    rec["overlay"] = len(d) - (last.PointerToRawData + last.SizeOfRawData)
    rec["rich"] = rich(pe)
    exps = []
    if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
        exps = [e.name.decode(errors="replace") if e.name else f"#{e.ordinal}"
                for e in pe.DIRECTORY_ENTRY_EXPORT.symbols]
    rec["exports"] = exps
    imps = {}
    if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
        for e in pe.DIRECTORY_ENTRY_IMPORT:
            imps[e.dll.decode(errors="replace")] = len(e.imports)
    rec["imports"] = imps
    hits = {}
    for m in MARKERS:
        found = sorted(set(x.decode("latin-1") for x in re.findall(m, d)))
        if found:
            hits[m.decode()[:24]] = found[:12]
    rec["markers"] = hits
    try:
        vi = {}
        for fi in getattr(pe, "FileInfo", []) or []:
            for e in fi:
                for st in getattr(e, "StringTable", []) or []:
                    for k, v in st.entries.items():
                        vi[k.decode()] = v.decode(errors="replace")
        rec["verinfo"] = vi
    except Exception:
        pass
    return rec

def main():
    jobs = []
    for tag, root in ROOTS.items():
        for dp, _, fs in os.walk(root):
            for f in fs:
                if f.lower().endswith((".dll", ".exe", ".ocx", ".orig")):
                    jobs.append((tag, os.path.join(dp, f)))
    with ThreadPoolExecutor(24) as ex:
        res = list(ex.map(one, jobs))
    json.dump(res, open(sys.argv[1], "w"), indent=1)
    print(len(res), "binaries")

if __name__ == "__main__":
    main()
