//! The libm and conversion behaviour the oracle's x86-64 build has, done
//! exactly in Rust, so no target's libm or float-to-int rule leaks in.

/// `ldexp`/`scalbn`, correctly rounded (musl's algorithm).
pub fn scalbn(x: f64, mut n: i32) -> f64 {
    let mut y = x;
    if n > 1023 {
        y *= f64::from_bits(0x7fe0_0000_0000_0000);
        n -= 1023;
        if n > 1023 {
            y *= f64::from_bits(0x7fe0_0000_0000_0000);
            n -= 1023;
            if n > 1023 {
                n = 1023;
            }
        }
    } else if n < -1022 {
        // 2^-1022 * 2^53, keeping the final step clear of double rounding in
        // the subnormal range.
        let k = f64::from_bits(0x0010_0000_0000_0000) * f64::from_bits(0x4340_0000_0000_0000);
        y *= k;
        n += 1022 - 53;
        if n < -1022 {
            y *= k;
            n += 1022 - 53;
            if n < -1022 {
                n = -1022;
            }
        }
    }
    y * f64::from_bits(((0x3ff + n) as u64) << 52)
}

/// `pow(2.0, e)` for an integer `e`: exact where representable.
pub fn exp2i(e: i32) -> f64 {
    if e > 1023 {
        f64::INFINITY
    } else if e >= -1022 {
        f64::from_bits(((e + 1023) as u64) << 52)
    } else if e >= -1074 {
        f64::from_bits(1u64 << (e + 1074))
    } else {
        0.0
    }
}

/// `frexp` for finite non-zero `x`: `x = m * 2^e`, `0.5 <= |m| < 1`.
pub fn frexp(x: f64) -> (f64, i32) {
    let bits = x.to_bits();
    let ex = ((bits >> 52) & 0x7ff) as i32;
    if ex == 0 {
        let (m, e) = frexp(x * f64::from_bits(0x43f0_0000_0000_0000));
        return (m, e - 64);
    }
    let m = f64::from_bits((bits & 0x800f_ffff_ffff_ffff) | (0x3fe << 52));
    (m, ex - 0x3fe)
}

/// `(int32_t)x` as `cvttsd2si`: the integer indefinite on NaN or overflow.
#[inline(always)]
pub fn cvtt_i32(x: f64) -> i32 {
    if x.is_nan() || x >= 2147483648.0 || x <= -2147483649.0 {
        i32::MIN
    } else {
        x as i32
    }
}

#[inline(always)]
pub fn cvtt_i64(x: f64) -> i64 {
    if x.is_nan() || x >= 9223372036854775808.0 || x < -9223372036854775808.0 {
        i64::MIN
    } else {
        x as i64
    }
}

// ---- f2xm1 and fyl2x ------------------------------------------------------
//
// The engine's only transcendentals are the CRT log10 and exp that
// synth_155mrf22 inlines into its two u16 table builders. The oracle runs
// them through the host libm (`pow(2,x)-1`, `log(x)/log(2)`) and truncated
// constants; real x87 computes them to 64 bits. Here they are done in
// double-double and rounded once, which reproduces the hardware tables
// entry for entry (`ss-rs-ng/notes/x87_tables.md`) and is the same on every
// target.

#[derive(Clone, Copy)]
struct Dd(f64, f64);

#[inline]
fn two_sum(a: f64, b: f64) -> (f64, f64) {
    let s = a + b;
    let bb = s - a;
    (s, (a - (s - bb)) + (b - bb))
}

#[inline]
fn quick_two_sum(a: f64, b: f64) -> Dd {
    let s = a + b;
    Dd(s, b - (s - a))
}

#[inline]
fn split(a: f64) -> (f64, f64) {
    let t = 134217729.0 * a;
    let hi = t - (t - a);
    (hi, a - hi)
}

#[inline]
fn two_prod(a: f64, b: f64) -> (f64, f64) {
    let p = a * b;
    let (ah, al) = split(a);
    let (bh, bl) = split(b);
    (p, ((ah * bh - p) + ah * bl + al * bh) + al * bl)
}

fn dd_add(a: Dd, b: Dd) -> Dd {
    let (s1, s2) = two_sum(a.0, b.0);
    let (t1, t2) = two_sum(a.1, b.1);
    let r = quick_two_sum(s1, s2 + t1);
    quick_two_sum(r.0, r.1 + t2)
}

fn dd_mul(a: Dd, b: Dd) -> Dd {
    let (p, e) = two_prod(a.0, b.0);
    quick_two_sum(p, e + (a.0 * b.1 + a.1 * b.0))
}

fn dd_mul_d(a: Dd, b: f64) -> Dd {
    let (p, e) = two_prod(a.0, b);
    quick_two_sum(p, e + a.1 * b)
}

fn dd_div(a: Dd, b: Dd) -> Dd {
    let q1 = a.0 / b.0;
    let r = dd_add(a, dd_mul_d(Dd(-b.0, -b.1), q1));
    let q2 = r.0 / b.0;
    let r = dd_add(r, dd_mul_d(Dd(-b.0, -b.1), q2));
    let q3 = r.0 / b.0;
    let q = quick_two_sum(q1, q2);
    dd_add(q, Dd(q3, 0.0))
}

const LN2: Dd = Dd(
    f64::from_bits(0x3FE6_2E42_FEFA_39EF),
    f64::from_bits(0x3C7A_BC9E_3B39_803F),
);
const LOG2E: Dd = Dd(
    f64::from_bits(0x3FF7_1547_652B_82FE),
    f64::from_bits(0x3C77_77D0_FFDA_0D24),
);

/// The x87 invalid-operation result, a negative quiet NaN.
const INDEFINITE: f64 = f64::from_bits(0xFFF8_0000_0000_0000);

/// e^r - 1 for |r| < 0.75, by Taylor series in double-double.
fn dd_expm1(r: Dd) -> Dd {
    let mut sum = r;
    let mut term = r;
    for k in 2..60 {
        term = dd_div(dd_mul(term, r), Dd(k as f64, 0.0));
        sum = dd_add(sum, term);
        if term.0.abs() <= sum.0.abs() * 1e-34 {
            break;
        }
    }
    sum
}

/// `f2xm1`: 2^x - 1. Hardware defines it on [-1, 1], where the engine uses
/// it; outside that this is still 2^x - 1, as the oracle's `pow` gives.
pub fn f2xm1(x: f64) -> f64 {
    if x.is_nan() {
        return x;
    }
    if x.abs() <= 1.0 {
        return dd_expm1(dd_mul_d(LN2, x)).0;
    }
    if x > 1024.0 {
        return f64::INFINITY;
    }
    if x < -1100.0 {
        return -1.0;
    }
    let n = x.round_ties_even();
    let p = dd_add(Dd(1.0, 0.0), dd_expm1(dd_mul_d(LN2, x - n)));
    let k = n as i32;
    let p = Dd(scalbn(p.0, k), scalbn(p.1, k));
    dd_add(p, Dd(-1.0, 0.0)).0
}

/// ln(m) for m in [sqrt(1/2), sqrt(2)], by the atanh series.
fn dd_ln_mid(m: f64) -> Dd {
    let (d0, d1) = two_sum(m, 1.0);
    let s = dd_div(Dd(m - 1.0, 0.0), Dd(d0, d1));
    let s2 = dd_mul(s, s);
    let mut sum = s;
    let mut pow = s;
    for k in 1..80 {
        pow = dd_mul(pow, s2);
        let term = dd_div(pow, Dd((2 * k + 1) as f64, 0.0));
        sum = dd_add(sum, term);
        if term.0.abs() <= sum.0.abs() * 1e-34 {
            break;
        }
    }
    Dd(2.0 * sum.0, 2.0 * sum.1)
}

/// `fyl2x`: y * log2(x).
pub fn fyl2x(y: f64, x: f64) -> f64 {
    if x.is_nan() || y.is_nan() {
        return x + y;
    }
    if x < 0.0 {
        return INDEFINITE;
    }
    if x == 0.0 {
        return if y == 0.0 { INDEFINITE } else { -f64::INFINITY * y.signum() };
    }
    if x.is_infinite() {
        return if y == 0.0 { INDEFINITE } else { f64::INFINITY * y.signum() };
    }
    if x == 1.0 {
        return y * 0.0;
    }
    let (mut m, mut e) = frexp(x);
    if m < std::f64::consts::FRAC_1_SQRT_2 {
        m *= 2.0;
        e -= 1;
    }
    let l = dd_add(Dd(e as f64, 0.0), dd_mul(dd_ln_mid(m), LOG2E));
    dd_mul_d(l, y).0
}

/// `(uint64_t)x` as gcc emits it for x86-64: below 2^63 a signed convert,
/// at or above it a convert of `x - 2^63` with the top bit flipped back.
/// NaN fails the `comisd`/`jae` and takes the signed path.
pub fn cvtt_u64(x: f64) -> u64 {
    const T: f64 = 9223372036854775808.0;
    if !(x >= T) {
        cvtt_i64(x) as u64
    } else {
        (cvtt_i64(x - T) as u64) ^ 0x8000_0000_0000_0000
    }
}
