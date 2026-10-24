"""Do two codsb bodies share coded frames? Exact 49-byte frame identity, plus run lengths."""
import struct, sys, collections
import numpy as np

FB = 49

def body(path):
    d = open(path, "rb").read()
    toc = struct.unpack_from("<I", d, 0x7c)[0]
    b = d[toc:]
    n = len(b) // FB
    return np.frombuffer(b[:n * FB], dtype=np.uint8).reshape(n, FB)

def keys(a):
    # 49 bytes -> two 64-bit hashes is overkill; use bytes of a void view
    return a.view(np.dtype((np.void, FB))).ravel()

def main():
    a_path, b_path = sys.argv[1], sys.argv[2]
    A, B = body(a_path), body(b_path)
    ka, kb = keys(A), keys(B)
    print(f"A frames {len(A):,}   B frames {len(B):,}")
    # silence / repeated frames would inflate matches; measure self-duplication first
    ua, ca = np.unique(ka, return_counts=True)
    ub = np.unique(kb)
    print(f"A distinct {len(ua):,} ({len(ua)/len(A):.4f})   B distinct {len(ub):,} ({len(ub)/len(B):.4f})")
    common = np.intersect1d(ua, ub, assume_unique=True)
    print(f"distinct frames shared: {len(common):,}")
    inA = np.isin(kb, ua)
    print(f"B frames found anywhere in A: {inA.sum():,} ({inA.mean():.4%})")
    # uniquely-located matches: frame occurs exactly once in A -> gives an A index
    once = ua[ca == 1]
    idx_of = {k.tobytes(): i for i, k in enumerate(ka)} if len(A) < 3_000_000 else None
    once_set = set(k.tobytes() for k in once)
    pos = np.full(len(B), -1, dtype=np.int64)
    for j, k in enumerate(kb):
        kk = k.tobytes()
        if kk in once_set:
            pos[j] = idx_of[kk]
    m = pos >= 0
    print(f"B frames matching a UNIQUE A frame: {m.sum():,} ({m.mean():.4%})")
    # runs where B[j+1] maps to A[i+1]
    runs = collections.Counter()
    j = 0
    longest = (0, 0, 0)
    while j < len(B):
        if pos[j] < 0:
            j += 1
            continue
        s = j
        while j + 1 < len(B) and pos[j + 1] == pos[j] + 1:
            j += 1
        L = j - s + 1
        runs[min(L, 1000) // 10 * 10 if L >= 10 else L] += 1
        if L > longest[0]:
            longest = (L, s, int(pos[s]))
        j += 1
    print("run-length histogram (bucketed):", sorted(runs.items())[:40])
    print(f"longest aligned run: {longest[0]} frames ({longest[0]*320/22050:.2f} s) at B[{longest[1]}] = A[{longest[2]}]")
    tot = sum(1 for _ in range(1))

if __name__ == "__main__":
    main()
