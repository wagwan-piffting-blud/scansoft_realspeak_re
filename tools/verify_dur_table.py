import struct, math
import numpy as np
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPFY = os.path.join(os.path.dirname(ROOT), "Speechify")

SS = bytes.fromhex(
    "6d6d6d6d6d6d6d666d6d6d6d6d6d6d6d6d6d6d6d6d666d626d666d585d5d5454534f4e4c47494543433c3630"
    "292119110800020d151c22272a2d2f3135393c3f4446474a4d51565b665b6d66626d666d6d6d6d6d6d6d6d6d6d"
    "6d6d6d6d6d6d6d6d6d6d6d6d6d6d")
VIN = SPFY + r"\en-US\tom\tom.vin"

raw = np.frombuffer(open(VIN, "rb").read(), dtype=np.uint8) ^ 0xCE
off = 34_264_578
f = struct.unpack_from("<100f", raw.tobytes(), off)
fl = [math.floor(10 * x) for x in f]
match = sum(a == b for a, b in zip(fl, SS))
print(f"floor(10x) matches: {match}/100")
print("vin :", " ".join(f"{x:.3f}" for x in f[40:60]))
print("ss  :", " ".join(f"{b:5d}" for b in SS[40:60]))
# independent search: does the byte pattern's float source appear anywhere else in the vin?
arr = np.frombuffer(raw.tobytes()[: (len(raw) // 4) * 4], dtype="<f4")
hits = []
for a in range(4):
    v = np.frombuffer(raw.tobytes()[a: a + ((len(raw) - a) // 4) * 4], dtype="<f4")
    ok = np.isfinite(v)
    q = np.where(ok, np.floor(10 * np.where(ok, v, 0)), -999).astype(np.int64)
    target = np.frombuffer(SS, dtype=np.uint8).astype(np.int64)
    # sliding match on the distinctive middle 20 entries
    mid = target[40:60]
    for i in np.where(q[:-100] == mid[0])[0]:
        if np.array_equal(q[i:i + 20], mid):
            hits.append(a + 4 * i - 160)
print("offsets where the 20-entry core recurs:", hits[:10])
