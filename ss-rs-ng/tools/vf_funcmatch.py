import glob
import hashlib
import os
from concurrent.futures import ProcessPoolExecutor

from vf_codecmp import norm_text

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def chunks(path):
    t = norm_text(path)
    out = []
    cur = []
    for ins in t:
        if ins.startswith(("nop", "int3")) and not cur:
            continue
        cur.append(ins)
        if ins.startswith("ret"):
            if len(cur) >= 8:
                out.append(hashlib.sha1("\n".join(cur).encode()).hexdigest())
            cur = []
    sizes = {}
    for ins_block in out:
        sizes[ins_block] = sizes.get(ins_block, 0) + 1
    return path, out


def main():
    vfs = sorted(glob.glob(os.path.join(ROOT, r"*\speech\components\voicefont\vf_*_full.dll")))
    with ProcessPoolExecutor(len(vfs)) as ex:
        res = dict(ex.map(chunks, vfs))
    names = {p: os.path.relpath(p, ROOT).split("\\")[0][:2] + ":" + os.path.basename(p)[3:-9] for p in vfs}
    allsets = {p: set(c) for p, c in res.items()}
    common = set.intersection(*allsets.values())
    rs = [p for p in vfs if "RealSpeak" in p]
    rs_common = set.intersection(*(allsets[p] for p in rs))
    tom = os.path.join(ROOT, r"RealSpeak\speech\components\voicefont\vf_tom_full.dll")
    print("ret-terminated blocks per VF; shared-with-RS-Tom fraction; in-all-RS fraction")
    for p in vfs:
        s = allsets[p]
        print("%-16s blocks=%5d  shared_w_rs_tom=%.2f  in_all_RS=%.2f  in_all_12=%.2f" % (
            names[p], len(s), len(s & allsets[tom]) / len(s), len(s & rs_common) / len(s), len(s & common) / len(s)))


if __name__ == "__main__":
    main()
