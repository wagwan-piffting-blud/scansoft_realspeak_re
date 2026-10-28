//! Runtime for code translated from the vendor DLLs by `tools/x86xlate.py`.
//!
//! A translated function is ordinary Rust, one statement per original
//! instruction, over the eight registers, EFLAGS and the x87 stack in [`Cpu`]
//! and the guest memory in [`Mem`]. Nothing here decodes an instruction.
//!
//! The reference is not the Intel manual but the M1 oracle, spfy's
//! `host_emu` (`oracle/emu/cpu.c`, `cpu_ops.h`), which is byte-identical to the
//! real engine on the corpus. Every helper is a port of the corresponding C,
//! quirks included; `xtask opgate` runs both on the same random states.

pub mod mem;
pub mod x87;
mod fmath;

pub use mem::Mem;

pub const EAX: usize = 0;
pub const ECX: usize = 1;
pub const EDX: usize = 2;
pub const EBX: usize = 3;
pub const ESP: usize = 4;
pub const EBP: usize = 5;
pub const ESI: usize = 6;
pub const EDI: usize = 7;

pub const CF: u32 = 0x0001;
pub const PF: u32 = 0x0004;
pub const AF: u32 = 0x0010;
pub const ZF: u32 = 0x0040;
pub const SF: u32 = 0x0080;
pub const DF: u32 = 0x0400;
pub const OF: u32 = 0x0800;

/// Indexed by operand size in bytes (1, 2 or 4), as in `cpu_ops.h`.
pub const SZMASK: [u32; 5] = [0, 0xff, 0xffff, 0, 0xffff_ffff];
pub const SIGN: [u32; 5] = [0, 0x80, 0x8000, 0, 0x8000_0000];

#[derive(Clone, Debug, PartialEq)]
pub struct Cpu {
    pub r: [u32; 8],
    pub eflags: u32,
    pub fs_base: u32,
    pub gs_base: u32,
    /// The address the last `ret` popped. A translated `call` returns to the
    /// instruction after it, so it checks this is that instruction.
    pub ret_to: u32,
    /// x87 stack as f64. MSVC6 runs with 53-bit precision, and the oracle
    /// matched the real engine with doubles.
    pub st: [f64; 8],
    pub top: u32,
    pub sw: u16,
    pub cw: u16,
}

impl Default for Cpu {
    fn default() -> Self {
        Cpu {
            r: [0; 8],
            eflags: 0x202,
            fs_base: 0,
            gs_base: 0,
            ret_to: 0,
            st: [0.0; 8],
            top: 0,
            sw: 0,
            cw: 0x037f,
        }
    }
}

/// A guest fault the oracle would trap on. Translated code panics with it.
#[cold]
#[inline(never)]
pub fn trap(what: &str, eip: u32) -> ! {
    panic!("guest trap ({what}) at 0x{eip:08x}{}", where_from());
}

/// After a translated `call` at `at`: the callee's `ret` must have popped
/// `ret`, or the guest returned somewhere a Rust return cannot follow.
#[inline(always)]
pub fn check_ret(c: &Cpu, ret: u32, at: u32) {
    if c.ret_to != ret {
        bad_return(c.ret_to, ret, at);
    }
}

#[cold]
#[inline(never)]
fn bad_return(got: u32, want: u32, at: u32) -> ! {
    panic!("call at 0x{at:08x} returned to 0x{got:08x}, not 0x{want:08x}{}", where_from());
}

/// An indirect transfer to an address with no translated code.
#[cold]
#[inline(never)]
pub fn no_code(pc: u32) -> ! {
    panic!("indirect transfer to 0x{pc:08x}, which is not translated code{}", where_from());
}

#[inline(always)]
fn parity8(v: u32) -> bool {
    (v & 0xff).count_ones() & 1 == 0
}

impl Cpu {
    // ---- flags ---------------------------------------------------------

    #[inline(always)]
    pub fn setf(&mut self, bit: u32, on: bool) {
        if on {
            self.eflags |= bit;
        } else {
            self.eflags &= !bit;
        }
    }

    #[inline(always)]
    pub fn flag(&self, bit: u32) -> bool {
        self.eflags & bit != 0
    }

    #[inline(always)]
    pub fn set_szp(&mut self, res: u32, sz: usize) {
        let res = res & SZMASK[sz];
        let mut f = self.eflags & !(ZF | SF | PF);
        if res == 0 {
            f |= ZF;
        }
        if res & SIGN[sz] != 0 {
            f |= SF;
        }
        if parity8(res) {
            f |= PF;
        }
        self.eflags = f;
    }

    #[inline(always)]
    pub fn cond(&self, cc: u32) -> bool {
        let f = self.eflags;
        let cf = f & CF != 0;
        let zf = f & ZF != 0;
        let sf = f & SF != 0;
        let of = f & OF != 0;
        let pf = f & PF != 0;
        match cc & 0xf {
            0x0 => of,
            0x1 => !of,
            0x2 => cf,
            0x3 => !cf,
            0x4 => zf,
            0x5 => !zf,
            0x6 => cf || zf,
            0x7 => !(cf || zf),
            0x8 => sf,
            0x9 => !sf,
            0xa => pf,
            0xb => !pf,
            0xc => sf != of,
            0xd => sf == of,
            0xe => zf || (sf != of),
            _ => !(zf || (sf != of)),
        }
    }

    // ---- partial registers ---------------------------------------------

    /// `idx` 4..7 at size 1 is AH, CH, DH, BH.
    #[inline(always)]
    pub fn getreg(&self, idx: usize, sz: usize) -> u32 {
        match sz {
            4 => self.r[idx],
            2 => self.r[idx] & 0xffff,
            _ => {
                if idx < 4 {
                    self.r[idx] & 0xff
                } else {
                    (self.r[idx - 4] >> 8) & 0xff
                }
            }
        }
    }

    #[inline(always)]
    pub fn setreg(&mut self, idx: usize, sz: usize, v: u32) {
        match sz {
            4 => self.r[idx] = v,
            2 => self.r[idx] = (self.r[idx] & !0xffff) | (v & 0xffff),
            _ => {
                if idx < 4 {
                    self.r[idx] = (self.r[idx] & !0xff) | (v & 0xff);
                } else {
                    self.r[idx - 4] = (self.r[idx - 4] & !0xff00) | ((v & 0xff) << 8);
                }
            }
        }
    }

    // ---- ALU -------------------------------------------------------------

    #[inline(always)]
    pub fn add(&mut self, a: u32, b: u32, sz: usize) -> u32 {
        let m = SZMASK[sz];
        let r = (a & m) as u64 + (b & m) as u64;
        let res = r as u32;
        self.set_szp(res, sz);
        self.setf(CF, (r >> (sz * 8)) & 1 != 0);
        self.setf(AF, (a ^ b ^ res) & 0x10 != 0);
        self.setf(OF, (!(a ^ b) & (a ^ res)) & SIGN[sz] != 0);
        res & m
    }

    #[inline(always)]
    pub fn adc(&mut self, a: u32, b: u32, sz: usize) -> u32 {
        let c = (self.eflags & CF) as u64;
        let m = SZMASK[sz];
        let r = (a & m) as u64 + (b & m) as u64 + c;
        let res = r as u32;
        self.set_szp(res, sz);
        self.setf(CF, (r >> (sz * 8)) & 1 != 0);
        self.setf(AF, (a ^ b ^ res) & 0x10 != 0);
        self.setf(OF, (!(a ^ b) & (a ^ res)) & SIGN[sz] != 0);
        res & m
    }

    #[inline(always)]
    pub fn sub(&mut self, a: u32, b: u32, sz: usize) -> u32 {
        let m = SZMASK[sz];
        let (aa, bb) = (a & m, b & m);
        let res = aa.wrapping_sub(bb) & m;
        self.set_szp(res, sz);
        self.setf(CF, aa < bb);
        self.setf(AF, (a ^ b ^ res) & 0x10 != 0);
        self.setf(OF, ((a ^ b) & (a ^ res)) & SIGN[sz] != 0);
        res
    }

    #[inline(always)]
    pub fn sbb(&mut self, a: u32, b: u32, sz: usize) -> u32 {
        let c = (self.eflags & CF) as u64;
        let m = SZMASK[sz];
        let aa = a & m;
        let bb = (b & m) as u64 + c;
        let res = ((aa as u64).wrapping_sub(bb) as u32) & m;
        self.set_szp(res, sz);
        self.setf(CF, (aa as u64) < bb);
        self.setf(AF, (a ^ b ^ res) & 0x10 != 0);
        self.setf(OF, ((a ^ b) & (a ^ res)) & SIGN[sz] != 0);
        res
    }

    /// The flags of a logical result: SZP from it, CF OF AF cleared.
    #[inline(always)]
    pub fn logic(&mut self, res: u32, sz: usize) -> u32 {
        self.set_szp(res, sz);
        self.eflags &= !(CF | OF | AF);
        res & SZMASK[sz]
    }

    #[inline(always)]
    pub fn and(&mut self, a: u32, b: u32, sz: usize) -> u32 {
        self.logic(a & b, sz)
    }

    #[inline(always)]
    pub fn or(&mut self, a: u32, b: u32, sz: usize) -> u32 {
        self.logic(a | b, sz)
    }

    #[inline(always)]
    pub fn xor(&mut self, a: u32, b: u32, sz: usize) -> u32 {
        self.logic(a ^ b, sz)
    }

    /// Group 1 by its ModRM `reg` field: add or adc sbb and sub xor cmp.
    /// `cmp` returns `a`, so the caller may write back unconditionally.
    #[inline(always)]
    pub fn alu(&mut self, op: u32, a: u32, b: u32, sz: usize) -> u32 {
        match op & 7 {
            0 => self.add(a, b, sz),
            1 => self.or(a, b, sz),
            2 => self.adc(a, b, sz),
            3 => self.sbb(a, b, sz),
            4 => self.and(a, b, sz),
            5 => self.sub(a, b, sz),
            6 => self.xor(a, b, sz),
            _ => {
                self.sub(a, b, sz);
                a
            }
        }
    }

    #[inline(always)]
    pub fn inc(&mut self, a: u32, sz: usize) -> u32 {
        let m = SZMASK[sz];
        let res = a.wrapping_add(1) & m;
        self.set_szp(res, sz);
        self.setf(AF, (a ^ 1 ^ res) & 0x10 != 0);
        self.setf(OF, (a & m) == SIGN[sz] - 1);
        res
    }

    #[inline(always)]
    pub fn dec(&mut self, a: u32, sz: usize) -> u32 {
        let m = SZMASK[sz];
        let res = a.wrapping_sub(1) & m;
        self.set_szp(res, sz);
        self.setf(AF, (a ^ 1 ^ res) & 0x10 != 0);
        self.setf(OF, (a & m) == SIGN[sz]);
        res
    }

    #[inline(always)]
    pub fn neg(&mut self, a: u32, sz: usize) -> u32 {
        self.sub(0, a, sz)
    }

    // ---- shifts and rotates ----------------------------------------------

    /// Group 2 by its ModRM `reg` field: rol ror rcl rcr shl shr sal sar.
    /// The count is masked to five bits for every size, as `do_shift` does,
    /// and a zero count leaves the flags alone.
    pub fn shift(&mut self, op: u32, v: u32, cnt: u32, sz: usize) -> u32 {
        let m = SZMASK[sz];
        let sign = SIGN[sz];
        let bits = (sz * 8) as u32;
        let v = v & m;
        let cnt = cnt & 31;
        if cnt == 0 {
            return v;
        }
        let res;
        let mut cf = false;
        let of;
        match op & 7 {
            4 | 6 => {
                res = if cnt >= bits { 0 } else { (v << cnt) & m };
                if cnt <= bits {
                    cf = (v >> (bits - cnt)) & 1 != 0;
                }
                of = cf ^ (res & sign != 0);
            }
            5 => {
                res = v >> cnt;
                cf = (v >> (cnt - 1)) & 1 != 0;
                of = v & sign != 0;
            }
            7 => {
                let sv = ((v << (32 - bits)) as i32) >> (32 - bits);
                res = ((sv >> cnt) as u32) & m;
                cf = (sv >> (cnt - 1)) & 1 != 0;
                of = false;
            }
            0 => {
                let mut r = v;
                for _ in 0..cnt {
                    cf = r & sign != 0;
                    r = ((r << 1) | cf as u32) & m;
                }
                res = r;
                of = cf ^ (res & sign != 0);
            }
            1 => {
                let mut r = v;
                for _ in 0..cnt {
                    cf = r & 1 != 0;
                    r = ((r >> 1) | (cf as u32 * sign)) & m;
                }
                res = r;
                of = (res & sign != 0) ^ ((res << 1) & sign != 0);
            }
            2 => {
                let mut r = v;
                for _ in 0..cnt {
                    let nc = r & sign != 0;
                    r = ((r << 1) | (self.eflags & CF)) & m;
                    self.setf(CF, nc);
                    cf = nc;
                }
                res = r;
                of = cf ^ (res & sign != 0);
            }
            _ => {
                let mut r = v;
                for _ in 0..cnt {
                    let nc = r & 1 != 0;
                    r = ((r >> 1) | ((self.eflags & CF) * sign)) & m;
                    self.setf(CF, nc);
                    cf = nc;
                }
                res = r;
                // `do_shift` never assigns `of` for rcr, so it stays 0.
                of = false;
            }
        }
        let op = op & 7;
        if op >= 4 {
            self.set_szp(res, sz);
        }
        if op < 2 || op > 3 {
            self.setf(CF, cf);
        }
        self.setf(OF, of);
        res & m
    }

    /// `shld`: `dst` is the r/m operand, `src` the register.
    pub fn shld(&mut self, dst: u32, src: u32, cnt: u32, sz: usize) -> u32 {
        let cnt = cnt & 31;
        if cnt == 0 {
            return dst;
        }
        let bits = (sz * 8) as u32;
        let lo = if sz == 2 { src & 0xffff } else { src } as u64;
        let wide = (((dst as u64) << bits) | lo) << cnt;
        let res = ((wide >> bits) as u32) & SZMASK[sz];
        // `dst >> (bits - cnt)` goes negative for a 16-bit shld past 16; the
        // oracle's x86-64 build masks the count, as `wrapping_shr` does.
        self.setf(CF, dst.wrapping_shr(bits.wrapping_sub(cnt)) & 1 != 0);
        self.set_szp(res, sz);
        res
    }

    pub fn shrd(&mut self, dst: u32, src: u32, cnt: u32, sz: usize) -> u32 {
        let cnt = cnt & 31;
        if cnt == 0 {
            return dst;
        }
        let bits = (sz * 8) as u32;
        let hi = if sz == 2 { src & 0xffff } else { src } as u64;
        let dl = if sz == 2 { dst & 0xffff } else { dst } as u64;
        let wide = ((hi << bits) | dl) >> cnt;
        let res = (wide as u32) & SZMASK[sz];
        self.setf(CF, (dst >> (cnt - 1)) & 1 != 0);
        self.set_szp(res, sz);
        res
    }

    // ---- multiply and divide ---------------------------------------------

    /// Two- and three-operand `imul`. The operands are passed already
    /// extended the way `cpu.c` extends them; the result is the low 32 bits,
    /// for the caller to `setreg` at the operand size.
    #[inline(always)]
    pub fn imul(&mut self, a: u32, b: u32) -> u32 {
        let r = (a as i32 as i64) * (b as i32 as i64);
        let ovf = r as i32 as i64 != r;
        self.setf(CF, ovf);
        self.setf(OF, ovf);
        r as u32
    }

    /// F6/F7 /4.
    pub fn mul1(&mut self, a: u32, sz: usize) {
        match sz {
            1 => {
                let r = (self.r[EAX] & 0xff) * (a & 0xff);
                self.setreg(EAX, 2, r);
                self.setf(CF, r & 0xff00 != 0);
                self.setf(OF, r & 0xff00 != 0);
            }
            2 => {
                let r = (self.r[EAX] & 0xffff) * (a & 0xffff);
                self.setreg(EAX, 2, r);
                self.setreg(EDX, 2, r >> 16);
                self.setf(CF, r >> 16 != 0);
                self.setf(OF, r >> 16 != 0);
            }
            _ => {
                let r = self.r[EAX] as u64 * a as u64;
                self.r[EAX] = r as u32;
                self.r[EDX] = (r >> 32) as u32;
                self.setf(CF, self.r[EDX] != 0);
                self.setf(OF, self.r[EDX] != 0);
            }
        }
    }

    /// F6/F7 /5. The 16-bit form sets no flags, as in `cpu.c`.
    pub fn imul1(&mut self, a: u32, sz: usize) {
        match sz {
            1 => {
                let r = (self.r[EAX] as u8 as i8 as i32) * (a as u8 as i8 as i32);
                self.setreg(EAX, 2, r as u32);
                self.setf(CF, r as i8 as i32 != r);
                self.setf(OF, r as i8 as i32 != r);
            }
            2 => {
                let r = (self.r[EAX] as u16 as i16 as i32) * (a as u16 as i16 as i32);
                self.setreg(EAX, 2, r as u32);
                self.setreg(EDX, 2, (r >> 16) as u32);
            }
            _ => {
                let r = (self.r[EAX] as i32 as i64) * (a as i32 as i64);
                self.r[EAX] = r as u32;
                self.r[EDX] = ((r as u64) >> 32) as u32;
                self.setf(CF, r as i32 as i64 != r);
                self.setf(OF, r as i32 as i64 != r);
            }
        }
    }

    /// F6/F7 /6. False on a zero divisor, where the oracle traps. A quotient
    /// too wide for the destination is truncated, not trapped, as in `cpu.c`.
    #[must_use]
    pub fn div1(&mut self, a: u32, sz: usize) -> bool {
        match sz {
            1 => {
                let d = a & 0xff;
                if d == 0 {
                    return false;
                }
                let ax = self.r[EAX] & 0xffff;
                let (q, rem) = (ax / d, ax % d);
                self.r[EAX] = (self.r[EAX] & !0xffff) | ((q & 0xff) | ((rem & 0xff) << 8));
            }
            2 => {
                let num = ((self.r[EDX] & 0xffff) << 16) | (self.r[EAX] & 0xffff);
                let d = a & 0xffff;
                if d == 0 {
                    return false;
                }
                self.setreg(EAX, 2, num / d);
                self.setreg(EDX, 2, num % d);
            }
            _ => {
                if a == 0 {
                    return false;
                }
                let num = ((self.r[EDX] as u64) << 32) | self.r[EAX] as u64;
                self.r[EAX] = (num / a as u64) as u32;
                self.r[EDX] = (num % a as u64) as u32;
            }
        }
        true
    }

    /// F6/F7 /7. As [`Cpu::div1`].
    #[must_use]
    pub fn idiv1(&mut self, a: u32, sz: usize) -> bool {
        match sz {
            1 => {
                if a & 0xff == 0 {
                    return false;
                }
                let ax = self.r[EAX] as u16 as i16 as i32;
                let d = a as u8 as i8 as i32;
                let (q, rem) = (ax / d, ax % d);
                self.r[EAX] =
                    (self.r[EAX] & !0xffff) | ((q as u8 as u32) | ((rem as u8 as u32) << 8));
            }
            2 => {
                let num = (((self.r[EDX] as u16 as i16 as i32) << 16) as u32
                    | (self.r[EAX] & 0xffff)) as i32;
                if a & 0xffff == 0 {
                    return false;
                }
                let d = a as u16 as i16 as i32;
                self.setreg(EAX, 2, num.wrapping_div(d) as u32);
                self.setreg(EDX, 2, num.wrapping_rem(d) as u32);
            }
            _ => {
                if a == 0 {
                    return false;
                }
                let num = ((self.r[EDX] as i32 as i64) << 32) | self.r[EAX] as i64;
                let d = a as i32 as i64;
                self.r[EAX] = num.wrapping_div(d) as u32;
                self.r[EDX] = num.wrapping_rem(d) as u32;
            }
        }
        true
    }

    // ---- bits ------------------------------------------------------------

    /// `bt`/`bts`/`btr`/`btc` on a value (register forms and `0F BA`):
    /// `op` 4 bt, 5 bts, 6 btr, 7 btc, as the `0F BA` `reg` field.
    #[inline(always)]
    pub fn bt(&mut self, op: u32, v: u32, bit: u32, sz: usize) -> u32 {
        let bit = bit & (sz as u32 * 8 - 1);
        self.setf(CF, (v >> bit) & 1 != 0);
        match op & 7 {
            5 => v | (1 << bit),
            6 => v & !(1 << bit),
            7 => v ^ (1 << bit),
            _ => v,
        }
    }

    /// `bt*` with a memory operand and a register bit offset: the offset is
    /// signed and may reach outside the operand (`cpu.c`'s BTNEW path).
    pub fn bt_mem(&mut self, m: &mut Mem, op: u32, addr: u32, off: u32, sz: usize) {
        let bit = if sz == 2 { off as u16 as i16 as i32 } else { off as i32 };
        let a = addr.wrapping_add((bit >> 3) as u32);
        let b = (bit & 7) as u32;
        let byte = m.r8(a);
        self.setf(CF, (byte >> b) & 1 != 0);
        match op & 7 {
            5 => m.w8(a, byte | (1 << b)),
            6 => m.w8(a, byte & !(1u8 << b)),
            7 => m.w8(a, byte ^ (1 << b)),
            _ => {}
        }
    }

    /// `bsf`: None for a zero source, which leaves the destination alone.
    #[inline(always)]
    pub fn bsf(&mut self, v: u32) -> Option<u32> {
        if v == 0 {
            self.setf(ZF, true);
            None
        } else {
            self.setf(ZF, false);
            Some(v.trailing_zeros())
        }
    }

    #[inline(always)]
    pub fn bsr(&mut self, v: u32) -> Option<u32> {
        if v == 0 {
            self.setf(ZF, true);
            None
        } else {
            self.setf(ZF, false);
            Some(31 - v.leading_zeros())
        }
    }

    // ---- conversions and flag moves --------------------------------------

    /// `98`: cwde at size 4, cbw at size 2.
    #[inline(always)]
    pub fn cbw(&mut self, sz: usize) {
        if sz == 4 {
            self.r[EAX] = self.r[EAX] as u16 as i16 as i32 as u32;
        } else {
            self.r[EAX] =
                (self.r[EAX] & !0xffff) | ((self.r[EAX] as u8 as i8 as i16 as u16) as u32);
        }
    }

    /// `99`: cdq at size 4, cwd at size 2.
    #[inline(always)]
    pub fn cwd(&mut self, sz: usize) {
        if sz == 4 {
            self.r[EDX] = if self.r[EAX] & 0x8000_0000 != 0 { 0xffff_ffff } else { 0 };
        } else {
            let v = if self.r[EAX] & 0x8000 != 0 { 0xffff } else { 0 };
            self.setreg(EDX, 2, v);
        }
    }

    #[inline(always)]
    pub fn sahf(&mut self) {
        let ah = (self.r[EAX] >> 8) & 0xff;
        self.eflags = (self.eflags & !0xd5) | ((ah & 0xd5) | 0x2);
    }

    #[inline(always)]
    pub fn lahf(&mut self) {
        let f = (self.eflags & 0xd5) | 0x2;
        self.r[EAX] = (self.r[EAX] & !0xff00) | (f << 8);
    }

    #[inline(always)]
    pub fn popf_value(&mut self, v: u32) {
        self.eflags = (v & 0xcd5) | 0x2;
    }

    pub fn cpuid(&mut self) {
        match self.r[EAX] {
            0 => {
                self.r[EAX] = 1;
                self.r[EBX] = 0x756e_6547;
                self.r[EDX] = 0x4965_6e69;
                self.r[ECX] = 0x6c65_746e;
            }
            1 => {
                self.r[EAX] = 0x0000_0623;
                self.r[EBX] = 0x0000_0800;
                self.r[ECX] = 0;
                self.r[EDX] = 0x0780_8011;
            }
            _ => {
                self.r[EAX] = 0;
                self.r[EBX] = 0;
                self.r[ECX] = 0;
                self.r[EDX] = 0;
            }
        }
    }

    // ---- stack -------------------------------------------------------------

    #[inline(always)]
    pub fn push32(&mut self, m: &mut Mem, v: u32) {
        self.r[ESP] = self.r[ESP].wrapping_sub(4);
        m.w32(self.r[ESP], v);
    }

    #[inline(always)]
    pub fn pop32(&mut self, m: &Mem) -> u32 {
        let v = m.r32(self.r[ESP]);
        self.r[ESP] = self.r[ESP].wrapping_add(4);
        v
    }

    /// `ret n`, for a translated `ret` and for a host import returning.
    #[inline(always)]
    pub fn ret(&mut self, m: &Mem, n: u32) {
        let t = self.pop32(m);
        self.r[ESP] = self.r[ESP].wrapping_add(n);
        self.ret_to = t;
    }

    // ---- string instructions -----------------------------------------------
    //
    // `rep` is "any repeat prefix" for movs/stos/lods, which ignore the
    // difference; scas/cmps take the two prefixes separately.

    #[inline(always)]
    fn step(&self, sz: usize) -> u32 {
        if self.eflags & DF != 0 {
            (sz as u32).wrapping_neg()
        } else {
            sz as u32
        }
    }

    pub fn movs(&mut self, m: &mut Mem, sz: usize, rep: bool) {
        let mut cnt = if rep { self.r[ECX] } else { 1 };
        while cnt != 0 {
            let v = m.rsz(self.r[ESI], sz);
            m.wsz(self.r[EDI], sz, v);
            let d = self.step(sz);
            self.r[ESI] = self.r[ESI].wrapping_add(d);
            self.r[EDI] = self.r[EDI].wrapping_add(d);
            cnt -= 1;
            if !rep {
                break;
            }
            self.r[ECX] = self.r[ECX].wrapping_sub(1);
        }
    }

    pub fn stos(&mut self, m: &mut Mem, sz: usize, rep: bool) {
        let mut cnt = if rep { self.r[ECX] } else { 1 };
        let val = self.getreg(EAX, sz);
        while cnt != 0 {
            m.wsz(self.r[EDI], sz, val);
            self.r[EDI] = self.r[EDI].wrapping_add(self.step(sz));
            cnt -= 1;
            if !rep {
                break;
            }
            self.r[ECX] = self.r[ECX].wrapping_sub(1);
        }
    }

    pub fn lods(&mut self, m: &Mem, sz: usize, rep: bool) {
        let mut cnt = if rep { self.r[ECX] } else { 1 };
        while cnt != 0 {
            let v = m.rsz(self.r[ESI], sz);
            self.setreg(EAX, sz, v);
            self.r[ESI] = self.r[ESI].wrapping_add(self.step(sz));
            cnt -= 1;
            if !rep {
                break;
            }
            self.r[ECX] = self.r[ECX].wrapping_sub(1);
        }
    }

    pub fn scas(&mut self, m: &Mem, sz: usize, rep: bool, repne: bool) {
        let any = rep || repne;
        let mut cnt = if any { self.r[ECX] } else { 1 };
        while cnt != 0 {
            let a = self.getreg(EAX, sz);
            let b = m.rsz(self.r[EDI], sz);
            self.sub(a, b, sz);
            self.r[EDI] = self.r[EDI].wrapping_add(self.step(sz));
            cnt -= 1;
            if !any {
                break;
            }
            self.r[ECX] = self.r[ECX].wrapping_sub(1);
            let zf = self.eflags & ZF != 0;
            if (rep && !zf) || (repne && zf) {
                break;
            }
        }
    }

    pub fn cmps(&mut self, m: &Mem, sz: usize, rep: bool, repne: bool) {
        let any = rep || repne;
        let mut cnt = if any { self.r[ECX] } else { 1 };
        while cnt != 0 {
            let a = m.rsz(self.r[ESI], sz);
            let b = m.rsz(self.r[EDI], sz);
            self.sub(a, b, sz);
            let d = self.step(sz);
            self.r[ESI] = self.r[ESI].wrapping_add(d);
            self.r[EDI] = self.r[EDI].wrapping_add(d);
            cnt -= 1;
            if !any {
                break;
            }
            self.r[ECX] = self.r[ECX].wrapping_sub(1);
            let zf = self.eflags & ZF != 0;
            if (rep && !zf) || (repne && zf) {
                break;
            }
        }
    }
}

/// Guest VAs of the host thunks: import `k` (the generated `IMPORTS[k]`) and
/// host callbacks after them sit at `THUNK_BASE + 16 * k`, as in the oracle.
pub const THUNK_BASE: u32 = 0x7100_0000;
pub const THUNK_END: u32 = 0x7110_0000;

/// System imports and host callbacks. The guest stack is exactly what the
/// callee would see: return address at `[esp]`, arguments above it. The host
/// leaves the result in EAX (or ST0) and returns with [`Cpu::ret`].
pub trait Host {
    fn import(&mut self, k: u32, c: &mut Cpu, m: &mut Mem);
}

pub struct NoHost;

impl Host for NoHost {
    fn import(&mut self, k: u32, _c: &mut Cpu, _m: &mut Mem) {
        panic!("translated code called host thunk {k}, but there is no host");
    }
}

#[cfg(feature = "cover")]
static RING: std::sync::Mutex<([u32; 64], usize)> = std::sync::Mutex::new(([0; 64], 0));

/// Record a block entry. Only with `--features cover`.
#[cfg(feature = "cover")]
pub fn hit(eip: u32) {
    let mut r = RING.lock().unwrap();
    let n = r.1;
    r.0[n % 64] = eip;
    r.1 = n + 1;
}

/// The last blocks entered, oldest first.
pub fn recent() -> Vec<u32> {
    #[cfg(feature = "cover")]
    {
        let r = RING.lock().unwrap();
        let n = r.1;
        let take = n.min(64);
        return (0..take).map(|k| r.0[(n - take + k) % 64]).collect();
    }
    #[cfg(not(feature = "cover"))]
    Vec::new()
}

pub(crate) fn where_from() -> String {
    let r = recent();
    if r.is_empty() {
        return String::from("\n  (rebuild with `--features cover` to see where from)");
    }
    let mut s = String::from("\n  last blocks entered, oldest first:");
    for chunk in r.chunks(8) {
        s.push_str("\n   ");
        for a in chunk {
            s.push_str(&format!(" {a:08x}"));
        }
    }
    s
}
