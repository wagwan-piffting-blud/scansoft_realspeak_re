# The engine's transcendentals, and why xrt departs from the oracle there

## Where they are

`tools\x87_sites.py` lists every x87 transcendental and constant load in both packs. The only
ones are in the three `synth_*` DLLs. `synth_155mrf22` (Tom, 22 kHz) has them at:
- `0x1000bd34`: `fldlg2; fxch; fyl2x` (inlined `log10`)
- `0x1000bd74` and `0x1000bdb9`: `fldl2e; fmul; frndint; fsub; f2xm1; fld1; faddp; fscale`
  (inlined `exp`, twice)

No DLL in either pack contains `fsin`, `fcos`, `fptan`, `fpatan` or `fsqrt`.

`tools\x87_probe.py` shows the oracle executes all three sites on every one of the 20 corpus
lines, in both packs.

## What they compute

They are one table builder, run when the synth is set up. With `n = [esi+0x32]` = 676 for RS
Tom, it fills two u16 tables through `_ftol`, which truncates:

| table | entry `i` | `i` runs | entry 0 |
|---|---|---|---|
| `[esi+0x40]` | `log10(1 + 9 (n-i+1)/(n+1)) * 32767` | 1..n | hardcoded `0x7fff` |
| `[esi+0x3c]` | `(e^((n-i+1)/(n+1)) - 1) / (e - 1) * 32767` | 1..n | hardcoded `0x7fff` |

The constants are at `0x10011dc8` (f32 32767), `0x10011dd0` (1.0) and `0x10011dd8` (9.0).

## Three models of the arithmetic

`tools\x87_tables.py` computes both tables three ways:

| model | constants | f2xm1 / fyl2x | arithmetic |
|---|---|---|---|
| oracle | cpu.c's decimal literals (`fldlg2` = 0.301029995663981, `fldl2e` = 1.442695040888963) | `pow(2,x)-1`, `y*(log(x)/log(2))` | doubles |
| accurate (xrt) | correctly rounded doubles | correctly rounded | doubles |
| native | 64-bit, as the hardware loads them | 64-bit results | 53-bit mantissa (MSVC6 PC=53), 15-bit exponent |

| comparison | log10 table | exp table |
|---|---|---|
| accurate vs native | identical | identical |
| oracle vs native | differs only at `i = 0` (32766 vs 32767: `log10(10)` lands just under 1.0) | identical |

The builder never computes `i = 0`: the entry is stored as `0x7fff` before the loop starts at 1.
The oracle's first value is `0x7fec` = 32748, the native value. So all three models agree on
every entry the engine uses, which is why the oracle matched the real engine.

## What xrt does

xrt follows the hardware, not cpu.c:
- **Constants:** the five `fld` constants are the correctly rounded doubles.
- **`f2xm1` and `fyl2x`:** double-double in pure Rust, rounded once (`src\fmath.rs`). No
  target's libm is involved, so all release targets give the same bits.
- **`fsqrt`:** IEEE `sqrt`. mingw's `sqrt` double-rounds; `f64::MAX` is the case the gate finds.

`tests\x87_ref.rs` checks these against 10,867 values that mpmath computes and rounds
correctly (`tools\x87_ref.py`). The values include every argument the two tables use, and all
of them match on x86-64 and i686.

`xtask opgate` reports these groups as "native" instead of failing on them:
- f2xm1
- fyl2x
- `fldl2e`, `fldlg2`, `fldln2` (cpu.c's literals for `fldl2t` and `fldpi` already round to the
  exact values)
- fsqrt

`tan`, `atan2`, `sin` and `cos` still call the host libm. No vendor DLL uses them.
