import math
import mpmath

N = 676
SCALE = 32767.0


def r53(x):
    return float(mpmath.mpf(x))


def r64(x):
    with mpmath.workprec(64):
        return +mpmath.mpf(x)


def trunc(x):
    return int(mpmath.floor(x)) if x >= 0 else int(mpmath.ceil(x))


# ---- (A) the oracle: cpu.c in doubles, its literals, host libm -----------
def oracle():
    lg2 = 0.301029995663981
    l2e = 1.442695040888963

    def exp_seq(v):
        x = v * l2e
        n = round(x)  # nearbyint, ties even (Python round)
        f = x - n
        y = (2.0 ** f) - 1.0
        y = 1.0 + y
        return math.ldexp(y, int(n))

    t1 = {}
    for i in range(0, N + 1):
        st = float(N - i + 1) * 9.0 / float(N + 1) + 1.0
        v = lg2 * (math.log(st) / math.log(2.0))
        t1[i] = trunc(v * SCALE)
    em1 = exp_seq(1.0) - 1.0
    t2 = {}
    for i in range(1, N + 1):
        st = float(N - i + 1) / float(N + 1)
        v = (exp_seq(st) - 1.0) / em1
        t2[i] = trunc(v * SCALE)
    return t1, t2


# ---- (B) accurate doubles: exact constants, correctly rounded f2xm1/fyl2x -
def accurate():
    mpmath.mp.prec = 200
    lg2 = r53(mpmath.log10(2))
    l2e = r53(1 / mpmath.log(2))

    def exp_seq(v):
        x = v * l2e
        n = round(x)
        f = x - n
        y = r53(mpmath.power(2, mpmath.mpf(f)) - 1)
        y = 1.0 + y
        return math.ldexp(y, int(n))

    t1 = {}
    for i in range(0, N + 1):
        st = float(N - i + 1) * 9.0 / float(N + 1) + 1.0
        v = r53(mpmath.mpf(lg2) * mpmath.log(mpmath.mpf(st), 2))
        t1[i] = trunc(v * SCALE)
    em1 = exp_seq(1.0) - 1.0
    t2 = {}
    for i in range(1, N + 1):
        st = float(N - i + 1) / float(N + 1)
        v = (exp_seq(st) - 1.0) / em1
        t2[i] = trunc(v * SCALE)
    return t1, t2


# ---- (C) native x87: 64-bit constants and transcendentals, PC=53 arith ----
def native():
    mpmath.mp.prec = 200
    lg2 = r64(mpmath.log10(2))
    l2e = r64(1 / mpmath.log(2))

    def a53(x):
        return mpmath.mpf(r53(x))

    def exp_seq(v):
        x = a53(mpmath.mpf(v) * l2e)
        n = mpmath.nint(x)
        f = a53(x - n)
        y = r64(mpmath.power(2, f) - 1)
        y = a53(1 + y)
        return y * mpmath.power(2, n)

    t1 = {}
    for i in range(0, N + 1):
        st = a53(a53(mpmath.mpf(N - i + 1) * 9) / (N + 1))
        st = a53(st + 1)
        v = r64(lg2 * mpmath.log(st, 2))
        t1[i] = trunc(a53(v * SCALE))
    em1 = a53(exp_seq(1.0) - 1)
    t2 = {}
    for i in range(1, N + 1):
        st = a53(mpmath.mpf(N - i + 1) / (N + 1))
        v = a53(a53(exp_seq(st) - 1) / em1)
        t2[i] = trunc(a53(v * SCALE))
    return t1, t2


def cmp(name, a, b):
    d = [k for k in a if a[k] != b[k]]
    print(f"{name}: {len(d)} entries differ" + (f" e.g. {[(k, a[k], b[k]) for k in d[:6]]}" if d else ""))


A, B, C = oracle(), accurate(), native()
for t, label in ((0, "T1 log10"), (1, "T2 exp")):
    cmp(f"{label} oracle vs native  ", A[t], C[t])
    cmp(f"{label} accurate vs native", B[t], C[t])
    cmp(f"{label} oracle vs accurate", A[t], B[t])
print("T1[0..3] native", [C[0][k] for k in range(4)], "T1[N]", C[0][N])
print("T2[1..3] native", [C[1][k] for k in range(1, 4)], "T2[N]", C[1][N])
