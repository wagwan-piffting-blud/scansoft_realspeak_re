"""Correctly rounded reference vectors for xrt's f2xm1, fyl2x and FLD
constants, written to crates/ss-rs-ng-xrt/tests/x87_ref.txt."""
import os
import random
import struct
import mpmath

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "crates", "ss-rs-ng-xrt", "tests", "x87_ref.txt")
mpmath.mp.prec = 400


def bits(x):
    return struct.unpack("<Q", struct.pack("<d", x))[0]


def rn(v):
    # Through a decimal string: Python's parser rounds subnormals correctly,
    # mpmath's float() does not.
    return float(mpmath.nstr(mpmath.mpf(v), 60, strip_zeros=False, min_fixed=1, max_fixed=0))


def main():
    rnd = random.Random(0x5352)
    lines = []
    consts = {
        0xE9: mpmath.log(10, 2),
        0xEA: 1 / mpmath.log(2),
        0xEB: mpmath.pi,
        0xEC: mpmath.log10(2),
        0xED: mpmath.log(2),
    }
    for m, v in consts.items():
        lines.append("const %02x %016x" % (m, bits(rn(v))))
    xs = [0.0, -0.0, 1.0, -1.0, 0.5, -0.5, 2.0 ** -60, -(2.0 ** -60), 5e-324]
    xs += [rnd.uniform(-1, 1) for _ in range(4000)]
    xs += [rnd.uniform(-1, 1) * 2.0 ** -rnd.randint(1, 60) for _ in range(1000)]
    xs += [rnd.uniform(-60, 60) for _ in range(500)]
    n = 676
    l2e = rn(1 / mpmath.log(2))
    for i in range(1, n + 1):
        x = (n - i + 1) / (n + 1) * l2e
        xs.append(x - round(x))
    for x in xs:
        r = rn(mpmath.expm1(mpmath.mpf(x) * mpmath.log(2)))
        lines.append("f2xm1 %016x %016x" % (bits(x), bits(r)))
    lg2 = rn(mpmath.log10(2))
    pairs = []
    for i in range(0, n + 1):
        pairs.append((lg2, (n - i + 1) * 9.0 / (n + 1) + 1.0))
    for _ in range(4000):
        y = rnd.choice([lg2, 1.0, -1.0, rnd.uniform(-1e3, 1e3)])
        x = rnd.choice([
            rnd.uniform(0.5, 2.0),
            1.0 + rnd.uniform(-1, 1) * 2.0 ** -rnd.randint(1, 50),
            2.0 ** rnd.uniform(-1070, 1020),
        ])
        pairs.append((y, x))
    for y, x in pairs:
        if x == 1.0:
            r = -0.0 if y < 0 else 0.0
        else:
            r = rn(mpmath.mpf(y) * mpmath.log(mpmath.mpf(x), 2))
        lines.append("fyl2x %016x %016x %016x" % (bits(y), bits(x), bits(r)))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {len(lines)} vectors to {OUT}")


if __name__ == "__main__":
    main()
