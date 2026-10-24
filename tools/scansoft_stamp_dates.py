"""Is the SCANSOFT header +0x84 u32 a date? Compare candidate epochs against file mtimes and DLL PE stamps.

    python -I scansoft_stamp_dates.py
"""
import datetime as dt
import glob
import os
import struct
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROOTS = [ROOT + r"\ScanSoft\speech\components",
         ROOT + r"\RealSpeak\speech\components"]
EPOCHS = {"unix1970": dt.datetime(1970, 1, 1), "dos1980": dt.datetime(1980, 1, 1)}


def pe_stamp(path):
    with open(path, "rb") as f:
        d = f.read(4096)
    o = struct.unpack_from("<I", d, 0x3c)[0]
    return dt.datetime(1970, 1, 1) + dt.timedelta(seconds=struct.unpack_from("<I", d, o + 8)[0])


for root in ROOTS:
    pack = "SS" if "ScanSoft" in root else "RS"
    for p in sorted(glob.glob(os.path.join(root, "data", "*_full*.dat"))):
        with open(p, "rb") as f:
            h = f.read(0x90)
        v = struct.unpack_from("<I", h, 0x84)[0]
        voice = os.path.basename(p).split("_")[1]
        vf = os.path.join(root, "voicefont", f"vf_{voice}_full.dll")
        cands = "  ".join(f"{k} {(e + dt.timedelta(seconds=v)):%Y-%m-%d %H:%M}" for k, e in EPOCHS.items())
        mt = dt.datetime.utcfromtimestamp(os.path.getmtime(p))
        print(f"{pack} {os.path.basename(p):40} +84={v:>10}  {cands}  mtime {mt:%Y-%m-%d}  "
              f"vf.dll PE {pe_stamp(vf):%Y-%m-%d}" if os.path.exists(vf) else "")
