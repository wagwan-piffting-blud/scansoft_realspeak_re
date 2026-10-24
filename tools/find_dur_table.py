import os, sys
import numpy as np
from concurrent.futures import ThreadPoolExecutor
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPFY = os.path.join(os.path.dirname(ROOT), "Speechify")

SS_TABLE = np.array([109,109,109,109,109,109,109,102,109,109,109,109,109,109,109,109,109,109,109,109,
                     109,102,109,98,109,102,109,88,93,93,84,84,83,79,78,76,71,73,69,67,
                     67,60,54,48,41,33,25,17,8,0,2,13,21,28,34,39,42,45,47,49,
                     53,57,60,63,68,70,71,74,77,81,86,91,102,91,109,102,98,109,102,109,
                     109,109,109,109,109,109,109,109,109,109,109,109,109,109,109,109,109,109,109,109],
                    dtype=np.int64)
CORE = bytes(SS_TABLE[27:73].astype(np.uint8))

def scan_bytes(path):
    d = open(path, "rb").read()
    hits, i = [], d.find(CORE)
    while i >= 0:
        hits.append(i - 27)
        i = d.find(CORE, i + 1)
    return path, hits

def scan_f32(path):
    raw = open(path, "rb").read()
    out = []
    for key, d in (("xor", bytes(b ^ 0xCE for b in raw)), ("plain", raw)):
        for a in range(4):
            n = (len(d) - a) // 4
            arr = np.frombuffer(d, dtype="<f4", count=n, offset=a).astype(np.float64)
            with np.errstate(all="ignore"):
                q = np.where(np.isfinite(arr) & (np.abs(arr) < 1e6), np.floor(arr * 10), -999).astype(np.int64)
            if len(q) < 100:
                continue
            cand = np.nonzero((q[:-99] == SS_TABLE[0]) & (q[49:len(q) - 50] == 0) & (q[48:len(q) - 51] == 8))[0]
            for k in cand:
                w = q[k:k + 100]
                m = int((w == SS_TABLE).sum())
                if m >= 90:
                    out.append((key, a + 4 * int(k), m, [round(float(x), 3) for x in arr[k + 45:k + 52]]))
    return path, out

def main():
    roots = [ROOT, SPFY + r"\bin"]
    files = []
    for r in roots:
        for dp, _, fs in os.walk(r):
            for f in fs:
                if f.lower().endswith((".dll", ".dat")):
                    files.append(os.path.join(dp, f))
    with ThreadPoolExecutor(24) as ex:
        for p, h in ex.map(scan_bytes, files):
            if h:
                print("BYTE-TABLE", p, [hex(x) for x in h])
    with ThreadPoolExecutor(8) as ex:
        for p, h in ex.map(scan_f32, sys.argv[1:]):
            print("F32", p, h if h else "none >=90/100")

if __name__ == "__main__":
    main()
