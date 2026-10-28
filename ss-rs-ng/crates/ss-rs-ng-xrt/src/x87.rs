//! The x87 subset, as `cpu.c`'s `do_x87`: doubles, a rotating top, and the
//! condition codes C0 C2 C3 in the status word.
//!
//! The translator emits `c.x87_reg(op, modrm)` and `c.x87_mem(m, op, reg, a)`
//! with constant opcode bytes, so each call folds to its one arm. Both return
//! false where the oracle would trap. Forms `cpu.c` accepts as no-ops (the
//! environment saves, `fcmov`, `fprem` and others in the D9/DA ranges) are
//! no-ops here too: the oracle matched the real engine with them that way.

use crate::fmath::{cvtt_i32, cvtt_i64, cvtt_u64, exp2i, f2xm1, frexp, fyl2x, scalbn};
use crate::{Cpu, Mem, AF, CF, EAX, OF, PF, SF, ZF};

const C0: u16 = 1 << 8;
const C1: u16 = 1 << 9;
const C2: u16 = 1 << 10;
const C3: u16 = 1 << 14;

impl Cpu {
    #[inline(always)]
    pub fn st(&self, i: u32) -> f64 {
        self.st[((self.top + i) & 7) as usize]
    }

    #[inline(always)]
    pub fn set_st(&mut self, i: u32, v: f64) {
        self.st[((self.top + i) & 7) as usize] = v;
    }

    #[inline(always)]
    pub fn fpush(&mut self, v: f64) {
        self.top = self.top.wrapping_sub(1) & 7;
        self.st[self.top as usize] = v;
    }

    #[inline(always)]
    pub fn fpop(&mut self) -> f64 {
        let v = self.st[(self.top & 7) as usize];
        self.top = (self.top + 1) & 7;
        v
    }

    #[inline(always)]
    pub fn fcom(&mut self, a: f64, b: f64) {
        self.sw &= !(C0 | C2 | C3);
        if a.is_nan() || b.is_nan() {
            self.sw |= C0 | C2 | C3;
        } else if a < b {
            self.sw |= C0;
        } else if a == b {
            self.sw |= C3;
        }
    }

    #[inline(always)]
    pub fn fcomi(&mut self, a: f64, b: f64) {
        self.eflags &= !(OF | SF | AF | ZF | PF | CF);
        if a.is_nan() || b.is_nan() {
            self.eflags |= ZF | PF | CF;
        } else if a < b {
            self.eflags |= CF;
        } else if a == b {
            self.eflags |= ZF;
        }
    }

    #[inline(always)]
    pub fn fstatus(&self) -> u16 {
        (self.sw & !0x3800) | (((self.top & 7) as u16) << 11)
    }

    /// FIST/FRNDINT rounding by the control word's RC bits.
    #[inline(always)]
    pub fn fround(&self, v: f64) -> f64 {
        match (self.cw >> 10) & 3 {
            1 => v.floor(),
            2 => v.ceil(),
            3 => v.trunc(),
            _ => v.round_ties_even(),
        }
    }

    pub fn fxam(&mut self) {
        let v = self.st(0);
        let bits = v.to_bits();
        self.sw &= !(C0 | C1 | C2 | C3);
        if bits >> 63 != 0 {
            self.sw |= C1;
        }
        if v.is_nan() {
            self.sw |= C0;
        } else if v == 0.0 {
            self.sw |= C3;
        } else {
            let e = (bits >> 52) & 0x7ff;
            if e == 0x7ff {
                self.sw |= C0 | C2;
            } else if e == 0 {
                self.sw |= C2 | C3;
            } else {
                self.sw |= C2;
            }
        }
    }

    /// `_ftol`: ST0 truncated to EDX:EAX, popped (the MSVCRT import).
    pub fn ftol(&mut self) {
        let r = cvtt_i64(self.fpop());
        self.r[EAX] = r as u32;
        self.r[crate::EDX] = ((r as u64) >> 32) as u32;
    }

    /// D8 (and the D8/DC/DA memory forms): ST0 op= b. `sel` is the ModRM
    /// `reg` field: add mul com comp sub subr div divr.
    #[inline(always)]
    pub fn fop_st0(&mut self, sel: u32, b: f64) {
        let a = self.st(0);
        match sel & 7 {
            0 => self.set_st(0, a + b),
            1 => self.set_st(0, a * b),
            2 => self.fcom(a, b),
            3 => {
                self.fcom(a, b);
                self.fpop();
            }
            4 => self.set_st(0, a - b),
            5 => self.set_st(0, b - a),
            6 => self.set_st(0, a / b),
            _ => self.set_st(0, b / a),
        }
    }

    /// DC and DE register forms: ST(i) is the destination, and the sub/div
    /// pairs are reversed against the D8 forms (the operand-order fix).
    /// `pops` is 0 for DC, 1 for DE; DE /3 (fcompp) pops twice and DC /3
    /// does not pop, as in `cpu.c`.
    #[inline(always)]
    pub fn fop_sti(&mut self, sel: u32, i: u32, pops: u32) {
        let (s0, si) = (self.st(0), self.st(i));
        match sel & 7 {
            0 => self.set_st(i, si + s0),
            1 => self.set_st(i, si * s0),
            2 => self.fcom(s0, si),
            3 => {
                self.fcom(s0, si);
                if pops != 0 {
                    self.fpop();
                }
            }
            4 => self.set_st(i, s0 - si),
            5 => self.set_st(i, si - s0),
            6 => self.set_st(i, s0 / si),
            _ => self.set_st(i, si / s0),
        }
        if pops != 0 {
            self.fpop();
        }
    }

    /// Register forms (`mod` = 3): `op` D8..DF, `modrm` C0..FF.
    #[inline(always)]
    pub fn x87_reg(&mut self, op: u8, modrm: u8) -> bool {
        let reg = ((modrm >> 3) & 7) as u32;
        let i = (modrm & 7) as u32;
        match op {
            0xD8 => {
                let b = self.st(i);
                self.fop_st0(reg, b);
            }
            0xDC => self.fop_sti(reg, i, 0),
            0xDE => {
                if modrm == 0xD9 {
                    let (a, b) = (self.st(0), self.st(1));
                    self.fcom(a, b);
                    self.fpop();
                    self.fpop();
                } else {
                    self.fop_sti(reg, i, 1);
                }
            }
            0xD9 => return self.x87_d9(modrm),
            0xDD => match reg {
                0 => {}
                2 => {
                    let v = self.st(0);
                    self.set_st(i, v);
                }
                3 => {
                    let v = self.st(0);
                    self.set_st(i, v);
                    self.fpop();
                }
                4 => {
                    let (a, b) = (self.st(0), self.st(i));
                    self.fcom(a, b);
                }
                5 => {
                    let (a, b) = (self.st(0), self.st(i));
                    self.fcom(a, b);
                    self.fpop();
                }
                _ => return false,
            },
            0xDA => {
                if modrm == 0xE9 {
                    let (a, b) = (self.st(0), self.st(1));
                    self.fcom(a, b);
                    self.fpop();
                    self.fpop();
                }
            }
            0xDB => match modrm {
                0xE2 => self.sw = 0,
                0xE3 => {
                    self.top = 0;
                    self.sw = 0;
                    self.cw = 0x037f;
                }
                0xE0 | 0xE1 | 0xE4 => {}
                _ if reg == 5 || reg == 6 => {
                    let (a, b) = (self.st(0), self.st(i));
                    self.fcomi(a, b);
                }
                _ => return false,
            },
            0xDF => {
                if modrm == 0xE0 {
                    let s = self.fstatus() as u32;
                    self.setreg(EAX, 2, s);
                } else if reg == 5 || reg == 6 {
                    let (a, b) = (self.st(0), self.st(i));
                    self.fcomi(a, b);
                    self.fpop();
                } else {
                    return false;
                }
            }
            _ => return false,
        }
        true
    }

    #[inline(always)]
    fn x87_d9(&mut self, modrm: u8) -> bool {
        let reg = (modrm >> 3) & 7;
        let i = (modrm & 7) as u32;
        if reg == 0 {
            let v = self.st(i);
            self.fpush(v);
            return true;
        }
        if reg == 1 {
            let (a, b) = (self.st(0), self.st(i));
            self.set_st(0, b);
            self.set_st(i, a);
            return true;
        }
        if reg == 2 || reg == 3 {
            return true;
        }
        let s0 = self.st(0);
        match modrm {
            0xE0 => self.set_st(0, -s0),
            0xE1 => {
                if s0 < 0.0 {
                    self.set_st(0, -s0);
                }
            }
            0xE4 => self.fcom(s0, 0.0),
            0xE5 => self.fxam(),
            // The correctly rounded constants, as the hardware loads them;
            // cpu.c's decimal literals are a few ulps short.
            0xE8 => self.fpush(1.0),
            0xE9 => self.fpush(f64::from_bits(0x400A_934F_0979_A371)),
            0xEA => self.fpush(f64::from_bits(0x3FF7_1547_652B_82FE)),
            0xEB => self.fpush(f64::from_bits(0x4009_21FB_5444_2D18)),
            0xEC => self.fpush(f64::from_bits(0x3FD3_4413_509F_79FF)),
            0xED => self.fpush(f64::from_bits(0x3FE6_2E42_FEFA_39EF)),
            0xEE => self.fpush(0.0),
            0xF0 => self.set_st(0, f2xm1(s0)),
            0xF1 => {
                let (y, x) = (self.st(1), s0);
                self.fpop();
                self.set_st(0, fyl2x(y, x));
            }
            // tan, atan2, sin and cos: no vendor DLL contains these four, so
            // the host libm is acceptable here.
            0xF2 => {
                self.set_st(0, s0.tan());
                self.fpush(1.0);
            }
            0xF3 => {
                let (y, x) = (self.st(1), s0);
                self.fpop();
                self.set_st(0, y.atan2(x));
            }
            0xFA => self.set_st(0, s0.sqrt()),
            0xFC => {
                let v = self.fround(s0);
                self.set_st(0, v);
            }
            0xFD => {
                let n = cvtt_i32(self.st(1));
                self.set_st(0, scalbn(s0, n));
            }
            0xFE => self.set_st(0, s0.sin()),
            0xFF => self.set_st(0, s0.cos()),
            _ => {}
        }
        true
    }

    /// Memory forms (`mod` != 3) at guest address `a`; `reg` is the ModRM
    /// `reg` field.
    #[inline(always)]
    pub fn x87_mem(&mut self, m: &mut Mem, op: u8, reg: u8, a: u32) -> bool {
        match (op, reg) {
            (0xD9, 0) => self.fpush(f32::from_bits(m.r32(a)) as f64),
            (0xD9, 2) => m.w32(a, (self.st(0) as f32).to_bits()),
            (0xD9, 3) => {
                m.w32(a, (self.st(0) as f32).to_bits());
                self.fpop();
            }
            (0xD9, 5) => self.cw = m.r16(a),
            (0xD9, 7) => m.w16(a, self.cw),
            (0xD9, 4) | (0xD9, 6) => {}
            (0xDD, 0) => self.fpush(f64::from_bits(m.r64(a))),
            (0xDD, 2) => m.w64(a, self.st(0).to_bits()),
            (0xDD, 3) => {
                m.w64(a, self.st(0).to_bits());
                self.fpop();
            }
            (0xDD, 7) => m.w16(a, self.fstatus()),
            (0xDD, 4) | (0xDD, 6) => {}
            (0xDB, 0) => self.fpush(m.r32(a) as i32 as f64),
            (0xDB, 2) => m.w32(a, cvtt_i32(self.fround(self.st(0))) as u32),
            (0xDB, 3) => {
                m.w32(a, cvtt_i32(self.fround(self.st(0))) as u32);
                self.fpop();
            }
            (0xDB, 5) => {
                let mant = m.r64(a);
                let se = m.r16(a + 8);
                let exp = (se & 0x7fff) as i32;
                let mut val = if exp == 0 && mant == 0 {
                    0.0
                } else {
                    mant as f64 * exp2i(exp - 16383 - 63)
                };
                if se >> 15 != 0 {
                    val = -val;
                }
                self.fpush(val);
            }
            (0xDB, 7) => {
                let mut d = self.st(0);
                let sign = d < 0.0;
                if sign {
                    d = -d;
                }
                let (mant, mut se) = if d == 0.0 {
                    (0u64, 0u16)
                } else {
                    let (mf, e) = if d.is_finite() { frexp(d) } else { (d, 0) };
                    (cvtt_u64(mf * 18446744073709551616.0), (e - 1 + 16383) as u16)
                };
                if sign {
                    se |= 0x8000;
                }
                m.w64(a, mant);
                m.w16(a + 8, se);
                self.fpop();
            }
            (0xDF, 0) => self.fpush(m.r16(a) as i16 as f64),
            (0xDF, 2) => m.w16(a, cvtt_i32(self.fround(self.st(0))) as u16),
            (0xDF, 3) => {
                m.w16(a, cvtt_i32(self.fround(self.st(0))) as u16);
                self.fpop();
            }
            (0xDF, 4) => {
                let mut acc: u64 = 0;
                for k in (0..9).rev() {
                    let by = m.r8(a + k) as u64;
                    acc = acc.wrapping_mul(100).wrapping_add((by >> 4) * 10 + (by & 0xf));
                }
                let mut dv = acc as f64;
                if m.r8(a + 9) & 0x80 != 0 {
                    dv = -dv;
                }
                self.fpush(dv);
            }
            (0xDF, 5) => self.fpush(m.r64(a) as i64 as f64),
            (0xDF, 6) => {
                let v = self.st(0);
                let neg = v < 0.0;
                let mag = if neg { -v } else { v };
                let mut acc = if mag >= 1.8e19 {
                    u64::MAX
                } else {
                    cvtt_u64(mag + 0.5)
                };
                for k in 0..9 {
                    m.w8(a + k, ((acc % 10) | (((acc / 10) % 10) << 4)) as u8);
                    acc /= 100;
                }
                m.w8(a + 9, if neg { 0x80 } else { 0x00 });
                self.fpop();
            }
            (0xDF, 7) => {
                m.w64(a, cvtt_i64(self.fround(self.st(0))) as u64);
                self.fpop();
            }
            (0xD8, _) => self.fop_st0(reg as u32, f32::from_bits(m.r32(a)) as f64),
            (0xDC, _) => self.fop_st0(reg as u32, f64::from_bits(m.r64(a))),
            (0xDA, _) => self.fop_st0(reg as u32, m.r32(a) as i32 as f64),
            _ => return false,
        }
        true
    }
}
