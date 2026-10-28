//! `xtask opgate`: the M2 gate. Random machine states, one instruction each,
//! through the oracle's own `cpu.c` (`oracle/opstep`) and through the
//! ss-rs-ng-xrt helpers the translator will call. Every register, flag, x87
//! slot and data byte must match.

use ss_rs_ng_xrt::{Cpu, Mem, EAX, ECX, EDI, EDX, ESI, ESP};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

const DATA: u32 = 0x2000_0000;
const CASE: usize = 392;

/// Where xrt follows the hardware and not the oracle, on purpose. In each
/// case the oracle's value comes from mingw's libm or cpu.c's decimal
/// literals; `tests/x87_ref.rs` checks xrt against correctly rounded values,
/// and `ss-rs-ng/notes/x87_tables.md` shows the engine's output is the same
/// either way.
const NATIVE: [(&str, &str); 8] = [
    ("freg D9 E9", "fldl2t: exact constant, cpu.c literal is short"),
    ("freg D9 EA", "fldl2e: exact constant"),
    ("freg D9 EB", "fldpi: exact constant"),
    ("freg D9 EC", "fldlg2: exact constant"),
    ("freg D9 ED", "fldln2: exact constant"),
    ("freg D9 F0", "f2xm1: correctly rounded, oracle uses pow(2,x)-1"),
    ("freg D9 F1", "fyl2x: correctly rounded, oracle uses log(x)/log(2)"),
    ("freg D9 FA", "fsqrt: IEEE, mingw's sqrt double-rounds (f64::MAX)"),
];

/// Host libm in both, and in no vendor DLL.
const LIBM: [&str; 4] = ["freg D9 F2", "freg D9 F3", "freg D9 FE", "freg D9 FF"];

#[derive(Clone, PartialEq)]
struct Case {
    code: [u8; 16],
    r: [u32; 8],
    eflags: u32,
    top: u32,
    cw: u16,
    sw: u16,
    faulted: u32,
    st: [u64; 8],
    data: [u8; 256],
}

impl Case {
    fn to_bytes(&self, out: &mut Vec<u8>) {
        out.extend_from_slice(&self.code);
        for v in self.r {
            out.extend_from_slice(&v.to_le_bytes());
        }
        out.extend_from_slice(&self.eflags.to_le_bytes());
        out.extend_from_slice(&self.top.to_le_bytes());
        out.extend_from_slice(&self.cw.to_le_bytes());
        out.extend_from_slice(&self.sw.to_le_bytes());
        out.extend_from_slice(&self.faulted.to_le_bytes());
        out.extend_from_slice(&0u32.to_le_bytes());
        out.extend_from_slice(&0u32.to_le_bytes());
        for v in self.st {
            out.extend_from_slice(&v.to_le_bytes());
        }
        out.extend_from_slice(&self.data);
    }

    fn from_bytes(b: &[u8]) -> Case {
        let u32_at = |o: usize| u32::from_le_bytes(b[o..o + 4].try_into().unwrap());
        let u16_at = |o: usize| u16::from_le_bytes(b[o..o + 2].try_into().unwrap());
        let mut c = Case {
            code: b[0..16].try_into().unwrap(),
            r: [0; 8],
            eflags: u32_at(48),
            top: u32_at(52),
            cw: u16_at(56),
            sw: u16_at(58),
            faulted: u32_at(60),
            st: [0; 8],
            data: b[136..392].try_into().unwrap(),
        };
        for k in 0..8 {
            c.r[k] = u32_at(16 + 4 * k);
            c.st[k] = u64::from_le_bytes(b[72 + 8 * k..80 + 8 * k].try_into().unwrap());
        }
        c
    }
}

struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        z ^ (z >> 31)
    }

    fn u32(&mut self) -> u32 {
        (self.next() >> 32) as u32
    }

    fn below(&mut self, n: u32) -> u32 {
        (self.next() % n as u64) as u32
    }

    fn pick<T: Copy>(&mut self, xs: &[T]) -> T {
        xs[self.below(xs.len() as u32) as usize]
    }

    fn bit(&mut self) -> bool {
        self.next() & 1 != 0
    }
}

const EDGE32: [u32; 16] = [
    0, 1, 2, 0x7f, 0x80, 0xff, 0x100, 0x7fff, 0x8000, 0xffff, 0x10000, 0x7fff_ffff, 0x8000_0000,
    0xffff_ffff, 0xffff_fffe, 0x8000_0001,
];
const EDGE8: [u32; 6] = [0, 1, 0x7f, 0x80, 0xff, 0xfe];
const EDGE16: [u32; 6] = [0, 1, 0x7fff, 0x8000, 0xffff, 0xfffe];

fn rv(r: &mut Rng) -> u32 {
    match r.below(20) {
        0..=4 => r.pick(&EDGE32),
        5..=7 => (r.u32() & 0xffff_ff00) | r.pick(&EDGE8),
        8..=9 => (r.u32() & 0xffff_0000) | r.pick(&EDGE16),
        10..=11 => r.below(64),
        _ => r.u32(),
    }
}

const FSPECIAL: [f64; 36] = [
    0.0,
    -0.0,
    1.0,
    -1.0,
    0.5,
    -0.5,
    1.5,
    2.5,
    -2.5,
    3.5,
    f64::INFINITY,
    f64::NEG_INFINITY,
    f64::NAN,
    f64::MIN_POSITIVE,
    5e-324,
    f64::MAX,
    -f64::MAX,
    32767.5,
    32768.0,
    -32768.5,
    -32769.0,
    65535.0,
    2147483647.5,
    2147483648.0,
    -2147483648.5,
    -2147483649.0,
    4294967296.0,
    9223372036854775807.0,
    9.3e18,
    -9.3e18,
    1.8e19,
    1.9e19,
    1e300,
    1e-300,
    0.25,
    -0.75,
];

fn fv(r: &mut Rng) -> f64 {
    match r.below(10) {
        0..=1 => {
            if r.below(20) == 0 {
                f64::from_bits(0xfff8_0000_0000_0000)
            } else {
                r.pick(&FSPECIAL)
            }
        }
        2..=3 => {
            if r.bit() {
                r.u32() as i32 as f64
            } else {
                (r.below(200) as i32 - 100) as f64
            }
        }
        4..=5 => (r.u32() as i32 >> r.below(31)) as f64 + 0.5,
        6..=7 => (r.u32() as f64 / 4294967296.0 - 0.5) * 2000.0,
        _ => {
            let e = 1023 + r.below(161) as u64 - 80;
            f64::from_bits((r.next() & 0x800f_ffff_ffff_ffff) | (e << 52))
        }
    }
}

#[derive(Clone, Copy, Debug)]
enum Op {
    Alu { op: u32, sz: usize, form: u8, reg: usize, rm: usize, imm: u32, opc: u8 },
    IncDec { dec: bool, sz: usize, rm: usize, short: bool },
    Unary { sel: u32, sz: usize, rm: usize, imm: u32 },
    Imul { form: u8, sz: usize, reg: usize, rm: usize, imm: u32 },
    Test { sz: usize, reg: usize, rm: usize },
    Shift { form: u8, sel: u32, sz: usize, rm: usize, imm: u8 },
    Shxd { left: bool, cl: bool, sz: usize, reg: usize, rm: usize, imm: u8 },
    BtReg { sel: u32, sz: usize, reg: usize, rm: usize, imm: Option<u8> },
    BtMem { sel: u32, sz: usize, reg: usize, imm: Option<u8> },
    Bsx { rev: bool, sz: usize, reg: usize, rm: usize },
    Setcc { cc: u32, rm: usize },
    Cmov { cc: u32, sz: usize, reg: usize, rm: usize },
    Movx { sx: bool, word: bool, sz: usize, reg: usize, rm: usize },
    Cbw { sz: usize },
    Cwd { sz: usize },
    Flag { opc: u8 },
    Xchg { sz: usize, reg: usize, rm: usize },
    XchgEax { sz: usize, r: usize },
    Xadd { sz: usize, reg: usize, rm: usize },
    Cmpxchg { sz: usize, reg: usize, rm: usize },
    Bswap { r: usize },
    Push { r: usize },
    Pop { r: usize },
    PushImm { wide: bool, imm: u32 },
    Str { opc: u8, sz: usize, rep: u8 },
    FMem { opc: u8, reg: u8, off: u32 },
    FReg { opc: u8, modrm: u8 },
}

fn modrm(reg: usize, rm: usize) -> u8 {
    0xC0 | ((reg as u8) << 3) | rm as u8
}

fn abs(reg: u8, a: u32, out: &mut Vec<u8>) {
    out.push((reg << 3) | 5);
    out.extend_from_slice(&a.to_le_bytes());
}

fn imm_sz(imm: u32, sz: usize, out: &mut Vec<u8>) {
    match sz {
        1 => out.push(imm as u8),
        2 => out.extend_from_slice(&(imm as u16).to_le_bytes()),
        _ => out.extend_from_slice(&imm.to_le_bytes()),
    }
}

fn group(op: &Op) -> String {
    match *op {
        Op::Alu { op, sz, form, opc, .. } => {
            let f = ["rm,r", "r,rm", "grp", "acc"][form as usize];
            if form == 2 {
                format!("alu{op} {f}{opc:02X} sz{sz}")
            } else {
                format!("alu{op} {f} sz{sz}")
            }
        }
        Op::IncDec { dec, sz, short, .. } => {
            format!("{} {} sz{sz}", if dec { "dec" } else { "inc" }, if short { "short" } else { "grp" })
        }
        Op::Unary { sel, sz, .. } => format!("F6/F7 /{sel} sz{sz}"),
        Op::Imul { form, sz, .. } => format!("imul {form:02X} sz{sz}"),
        Op::Test { sz, .. } => format!("test sz{sz}"),
        Op::Shift { form, sel, sz, .. } => format!("shift {form:02X} /{sel} sz{sz}"),
        Op::Shxd { left, cl, sz, .. } => {
            format!("{} {} sz{sz}", if left { "shld" } else { "shrd" }, if cl { "cl" } else { "imm" })
        }
        Op::BtReg { sel, sz, imm, .. } => format!("bt{sel} reg{} sz{sz}", if imm.is_some() { " imm" } else { "" }),
        Op::BtMem { sel, sz, imm, .. } => format!("bt{sel} mem{} sz{sz}", if imm.is_some() { " imm" } else { "" }),
        Op::Bsx { rev, sz, .. } => format!("{} sz{sz}", if rev { "bsr" } else { "bsf" }),
        Op::Setcc { .. } => "setcc".into(),
        Op::Cmov { sz, .. } => format!("cmov sz{sz}"),
        Op::Movx { sx, word, sz, .. } => format!("mov{}x{} sz{sz}", if sx { 's' } else { 'z' }, if word { 16 } else { 8 }),
        Op::Cbw { sz } => format!("cbw sz{sz}"),
        Op::Cwd { sz } => format!("cwd sz{sz}"),
        Op::Flag { opc } => format!("flag {opc:02X}"),
        Op::Xchg { sz, .. } => format!("xchg sz{sz}"),
        Op::XchgEax { sz, .. } => format!("xchg eax sz{sz}"),
        Op::Xadd { sz, .. } => format!("xadd sz{sz}"),
        Op::Cmpxchg { sz, .. } => format!("cmpxchg sz{sz}"),
        Op::Bswap { .. } => "bswap".into(),
        Op::Push { .. } => "push r".into(),
        Op::Pop { .. } => "pop r".into(),
        Op::PushImm { wide, .. } => format!("push imm{}", if wide { 32 } else { 8 }),
        Op::Str { opc, sz, rep } => format!("str {opc:02X} sz{sz} rep{rep:02X}"),
        Op::FMem { opc, reg, .. } => format!("fmem {opc:02X} /{reg}"),
        Op::FReg { opc, modrm } => {
            let reg = (modrm >> 3) & 7;
            if opc == 0xD9 && reg >= 4 {
                format!("freg D9 {modrm:02X}")
            } else {
                format!("freg {opc:02X} /{reg}")
            }
        }
    }
}

fn templates() -> Vec<Box<dyn Fn(&mut Rng) -> Op + Sync>> {
    let mut t: Vec<Box<dyn Fn(&mut Rng) -> Op + Sync>> = Vec::new();
    let szs = [1usize, 2, 4];
    for op in 0..8u32 {
        for sz in szs {
            for form in 0..4u8 {
                let opcs: &[u8] = match (form, sz) {
                    (2, 1) => &[0x80],
                    (2, _) => &[0x81, 0x83],
                    _ => &[0],
                };
                for &opc in opcs {
                    t.push(Box::new(move |r: &mut Rng| Op::Alu {
                        op,
                        sz,
                        form,
                        reg: r.below(8) as usize,
                        rm: r.below(8) as usize,
                        imm: rv(r),
                        opc,
                    }));
                }
            }
        }
    }
    for sz in szs {
        for dec in [false, true] {
            t.push(Box::new(move |r: &mut Rng| Op::IncDec { dec, sz, rm: r.below(8) as usize, short: false }));
            if sz != 1 {
                t.push(Box::new(move |r: &mut Rng| Op::IncDec { dec, sz, rm: r.below(8) as usize, short: true }));
            }
        }
        for sel in [0u32, 2, 3, 4, 5, 6, 7] {
            t.push(Box::new(move |r: &mut Rng| Op::Unary { sel, sz, rm: r.below(8) as usize, imm: rv(r) }));
        }
        t.push(Box::new(move |r: &mut Rng| Op::Test { sz, reg: r.below(8) as usize, rm: r.below(8) as usize }));
        for form in [0xC0u8, 0xD0, 0xD2] {
            for sel in 0..8u32 {
                t.push(Box::new(move |r: &mut Rng| Op::Shift {
                    form,
                    sel,
                    sz,
                    rm: r.below(8) as usize,
                    imm: r.below(64) as u8,
                }));
            }
        }
        t.push(Box::new(move |r: &mut Rng| Op::Xchg { sz, reg: r.below(8) as usize, rm: r.below(8) as usize }));
        t.push(Box::new(move |r: &mut Rng| Op::Xadd { sz, reg: r.below(8) as usize, rm: r.below(8) as usize }));
        t.push(Box::new(move |r: &mut Rng| Op::Cmpxchg { sz, reg: r.below(8) as usize, rm: r.below(8) as usize }));
        for opc in [0xA4u8, 0xAA, 0xAC, 0xAE, 0xA6] {
            for rep in [0u8, 0xF3, 0xF2] {
                t.push(Box::new(move |_r: &mut Rng| Op::Str { opc, sz, rep }));
            }
        }
    }
    for sz in [2usize, 4] {
        for form in [0x69u8, 0x6B, 0xAF] {
            t.push(Box::new(move |r: &mut Rng| Op::Imul {
                form,
                sz,
                reg: r.below(8) as usize,
                rm: r.below(8) as usize,
                imm: rv(r),
            }));
        }
        for left in [false, true] {
            for cl in [false, true] {
                t.push(Box::new(move |r: &mut Rng| Op::Shxd {
                    left,
                    cl,
                    sz,
                    reg: r.below(8) as usize,
                    rm: r.below(8) as usize,
                    imm: r.below(64) as u8,
                }));
            }
        }
        for sel in 4..8u32 {
            t.push(Box::new(move |r: &mut Rng| Op::BtReg {
                sel,
                sz,
                reg: r.below(8) as usize,
                rm: r.below(8) as usize,
                imm: None,
            }));
            t.push(Box::new(move |r: &mut Rng| Op::BtReg {
                sel,
                sz,
                reg: 0,
                rm: r.below(8) as usize,
                imm: Some(r.u32() as u8),
            }));
            t.push(Box::new(move |r: &mut Rng| Op::BtMem { sel, sz, reg: r.below(8) as usize, imm: None }));
            t.push(Box::new(move |r: &mut Rng| Op::BtMem { sel, sz, reg: 0, imm: Some(r.u32() as u8) }));
        }
        for rev in [false, true] {
            t.push(Box::new(move |r: &mut Rng| Op::Bsx { rev, sz, reg: r.below(8) as usize, rm: r.below(8) as usize }));
        }
        t.push(Box::new(move |r: &mut Rng| Op::Cmov {
            cc: r.below(16),
            sz,
            reg: r.below(8) as usize,
            rm: r.below(8) as usize,
        }));
        for sx in [false, true] {
            for word in [false, true] {
                t.push(Box::new(move |r: &mut Rng| Op::Movx {
                    sx,
                    word,
                    sz,
                    reg: r.below(8) as usize,
                    rm: r.below(8) as usize,
                }));
            }
        }
        t.push(Box::new(move |_r: &mut Rng| Op::Cbw { sz }));
        t.push(Box::new(move |_r: &mut Rng| Op::Cwd { sz }));
        t.push(Box::new(move |r: &mut Rng| Op::XchgEax { sz, r: 1 + r.below(7) as usize }));
    }
    t.push(Box::new(|r: &mut Rng| Op::Setcc { cc: r.below(16), rm: r.below(8) as usize }));
    for opc in [0x9Eu8, 0x9F, 0xF5, 0xF8, 0xF9, 0xFC, 0xFD, 0x9C, 0x9D] {
        t.push(Box::new(move |_r: &mut Rng| Op::Flag { opc }));
    }
    t.push(Box::new(|r: &mut Rng| Op::Bswap { r: r.below(8) as usize }));
    t.push(Box::new(|r: &mut Rng| Op::Push { r: r.below(8) as usize }));
    t.push(Box::new(|r: &mut Rng| Op::Pop { r: r.below(8) as usize }));
    t.push(Box::new(|r: &mut Rng| Op::PushImm { wide: true, imm: rv(r) }));
    t.push(Box::new(|r: &mut Rng| Op::PushImm { wide: false, imm: rv(r) }));
    for opc in 0xD8..=0xDFu8 {
        for reg in 0..8u8 {
            t.push(Box::new(move |r: &mut Rng| Op::FMem { opc, reg, off: r.below(240) }));
            if opc == 0xD9 && reg >= 4 {
                for low in 0..8u8 {
                    let m = 0xC0 | (reg << 3) | low;
                    t.push(Box::new(move |_r: &mut Rng| Op::FReg { opc, modrm: m }));
                }
            } else {
                t.push(Box::new(move |r: &mut Rng| Op::FReg { opc, modrm: 0xC0 | (reg << 3) | r.below(8) as u8 }));
            }
        }
    }
    t
}

fn put_f32(d: &mut [u8; 256], off: usize, v: u32) {
    d[off..off + 4].copy_from_slice(&v.to_le_bytes());
}

fn m80_of(v: f64) -> [u8; 10] {
    let bits = v.to_bits();
    let sign = (bits >> 63) as u16;
    let mut out = [0u8; 10];
    if v == 0.0 {
        out[9] = (sign << 7) as u8;
        return out;
    }
    let (mant, exp) = if v.is_finite() {
        let ex = ((bits >> 52) & 0x7ff) as i32;
        let frac = bits & 0x000f_ffff_ffff_ffff;
        if ex == 0 {
            let lz = frac.leading_zeros() as i32;
            (frac << lz, -1022 - (lz - 11) + 16383)
        } else {
            (((frac | (1 << 52)) << 11), ex - 1023 + 16383)
        }
    } else {
        (0x8000_0000_0000_0000u64 | ((bits & 0x000f_ffff_ffff_ffff) << 11), 0x7fff)
    };
    out[..8].copy_from_slice(&mant.to_le_bytes());
    let se = ((exp as u16) & 0x7fff) | (sign << 15);
    out[8..].copy_from_slice(&se.to_le_bytes());
    out
}

/// Build the case for `op` on top of a random base state.
fn setup(op: &Op, r: &mut Rng) -> Case {
    let mut c = Case {
        code: [0x90; 16],
        r: [0; 8],
        eflags: 0x202 | (r.u32() & 0xcd5),
        top: r.below(8),
        cw: 0x027f | ((r.below(4) as u16) << 10),
        sw: r.u32() as u16,
        faulted: 0,
        st: [0; 8],
        data: [0; 256],
    };
    for k in 0..8 {
        c.r[k] = rv(r);
        c.st[k] = fv(r).to_bits();
    }
    for b in c.data.iter_mut() {
        *b = r.u32() as u8;
    }
    let mut code: Vec<u8> = Vec::new();
    let pfx = |sz: usize, code: &mut Vec<u8>| {
        if sz == 2 {
            code.push(0x66);
        }
    };
    match *op {
        Op::Alu { op, sz, form, reg, rm, imm, opc } => {
            pfx(sz, &mut code);
            let base = (op as u8) << 3;
            let w = (sz != 1) as u8;
            match form {
                0 => code.extend([base + w, modrm(reg, rm)]),
                1 => code.extend([base + 2 + w, modrm(reg, rm)]),
                2 => {
                    code.extend([opc, modrm(op as usize, rm)]);
                    if opc == 0x81 {
                        imm_sz(imm, sz, &mut code);
                    } else {
                        code.push(imm as u8);
                    }
                }
                _ => {
                    code.push(base + 4 + w);
                    imm_sz(imm, sz, &mut code);
                }
            }
        }
        Op::IncDec { dec, sz, rm, short } => {
            pfx(sz, &mut code);
            if short {
                code.push(if dec { 0x48 } else { 0x40 } + rm as u8);
            } else {
                code.extend([if sz == 1 { 0xFE } else { 0xFF }, modrm(dec as usize, rm)]);
            }
        }
        Op::Unary { sel, sz, rm, imm } => {
            pfx(sz, &mut code);
            code.extend([if sz == 1 { 0xF6 } else { 0xF7 }, modrm(sel as usize, rm)]);
            if sel == 0 {
                imm_sz(imm, sz, &mut code);
            }
            // INT_MIN / -1 in the widened C division crashes the host.
            if sel == 7 && sz == 4 && c.r[EDX] == 0x8000_0000 && c.r[EAX] == 0 && c.r[rm] == 0xffff_ffff {
                c.r[EAX] = 1;
            }
            if sel == 7
                && sz == 2
                && c.r[EDX] & 0xffff == 0x8000
                && c.r[EAX] & 0xffff == 0
                && c.r[rm] & 0xffff == 0xffff
            {
                c.r[EAX] |= 1;
            }
        }
        Op::Imul { form, sz, reg, rm, imm } => {
            pfx(sz, &mut code);
            match form {
                0x69 => {
                    code.extend([0x69, modrm(reg, rm)]);
                    imm_sz(imm, sz, &mut code);
                }
                0x6B => code.extend([0x6B, modrm(reg, rm), imm as u8]),
                _ => code.extend([0x0F, 0xAF, modrm(reg, rm)]),
            }
        }
        Op::Test { sz, reg, rm } => {
            pfx(sz, &mut code);
            code.extend([if sz == 1 { 0x84 } else { 0x85 }, modrm(reg, rm)]);
        }
        Op::Shift { form, sel, sz, rm, imm } => {
            pfx(sz, &mut code);
            let w = (sz != 1) as u8;
            code.extend([form + w, modrm(sel as usize, rm)]);
            if form == 0xC0 {
                code.push(imm);
            }
            if form == 0xD2 {
                c.r[ECX] = (c.r[ECX] & !0xff) | imm as u32;
            }
        }
        Op::Shxd { left, cl, sz, reg, rm, imm } => {
            pfx(sz, &mut code);
            let o = if left { 0xA4 } else { 0xAC } + cl as u8;
            code.extend([0x0F, o, modrm(reg, rm)]);
            if !cl {
                code.push(imm);
            } else {
                c.r[ECX] = (c.r[ECX] & !0xff) | imm as u32;
            }
        }
        Op::BtReg { sel, sz, reg, rm, imm } => {
            pfx(sz, &mut code);
            match imm {
                Some(i) => code.extend([0x0F, 0xBA, modrm(sel as usize, rm), i]),
                None => code.extend([0x0F, [0xA3, 0xAB, 0xB3, 0xBB][sel as usize - 4], modrm(reg, rm)]),
            }
        }
        Op::BtMem { sel, sz, reg, imm } => {
            pfx(sz, &mut code);
            match imm {
                Some(i) => {
                    code.extend([0x0F, 0xBA]);
                    abs(sel as u8, DATA + 120, &mut code);
                    code.push(i);
                }
                None => {
                    code.extend([0x0F, [0xA3, 0xAB, 0xB3, 0xBB][sel as usize - 4]]);
                    abs(reg as u8, DATA + 128, &mut code);
                    let off = (r.below(2048) as i32 - 1024) as u32;
                    c.r[reg] = if sz == 2 { (r.u32() & 0xffff_0000) | (off & 0xffff) } else { off };
                }
            }
        }
        Op::Bsx { rev, sz, reg, rm } => {
            pfx(sz, &mut code);
            code.extend([0x0F, if rev { 0xBD } else { 0xBC }, modrm(reg, rm)]);
        }
        Op::Setcc { cc, rm } => code.extend([0x0F, 0x90 + cc as u8, modrm(0, rm)]),
        Op::Cmov { cc, sz, reg, rm } => {
            pfx(sz, &mut code);
            code.extend([0x0F, 0x40 + cc as u8, modrm(reg, rm)]);
        }
        Op::Movx { sx, word, sz, reg, rm } => {
            pfx(sz, &mut code);
            code.extend([0x0F, 0xB6 + (sx as u8) * 8 + word as u8, modrm(reg, rm)]);
        }
        Op::Cbw { sz } => {
            pfx(sz, &mut code);
            code.push(0x98);
        }
        Op::Cwd { sz } => {
            pfx(sz, &mut code);
            code.push(0x99);
        }
        Op::Flag { opc } => {
            code.push(opc);
            c.r[ESP] = DATA + 64 + r.below(128);
        }
        Op::Xchg { sz, reg, rm } => {
            pfx(sz, &mut code);
            code.extend([if sz == 1 { 0x86 } else { 0x87 }, modrm(reg, rm)]);
        }
        Op::XchgEax { sz, r: reg } => {
            pfx(sz, &mut code);
            code.push(0x90 + reg as u8);
        }
        Op::Xadd { sz, reg, rm } => {
            pfx(sz, &mut code);
            code.extend([0x0F, if sz == 1 { 0xC0 } else { 0xC1 }, modrm(reg, rm)]);
        }
        Op::Cmpxchg { sz, reg, rm } => {
            pfx(sz, &mut code);
            code.extend([0x0F, if sz == 1 { 0xB0 } else { 0xB1 }, modrm(reg, rm)]);
            if r.bit() {
                let v = c.r[rm];
                c.r[EAX] = v;
            }
        }
        Op::Bswap { r: reg } => code.extend([0x0F, 0xC8 + reg as u8]),
        Op::Push { r: reg } => {
            code.push(0x50 + reg as u8);
            c.r[ESP] = DATA + 64 + r.below(128);
        }
        Op::Pop { r: reg } => {
            code.push(0x58 + reg as u8);
            c.r[ESP] = DATA + 64 + r.below(128);
        }
        Op::PushImm { wide, imm } => {
            if wide {
                code.push(0x68);
                code.extend_from_slice(&imm.to_le_bytes());
            } else {
                code.extend([0x6A, imm as u8]);
            }
            c.r[ESP] = DATA + 64 + r.below(128);
        }
        Op::Str { opc, sz, rep } => {
            if rep != 0 {
                code.push(rep);
            }
            pfx(sz, &mut code);
            code.push(opc + (sz != 1) as u8);
            c.r[ESI] = DATA + 64 + r.below(128);
            c.r[EDI] = DATA + 64 + r.below(128);
            c.r[ECX] = if r.below(8) == 0 { 0 } else { r.below(9) };
            for b in c.data.iter_mut() {
                *b = r.below(3) as u8;
            }
            c.r[EAX] = (c.r[EAX] & 0xffff_ff00) | r.below(3);
            if r.bit() {
                c.r[EAX] = (c.r[EAX] & 0xffff_0000) | 0x0101 * r.below(3);
            }
        }
        Op::FMem { opc, reg, off } => {
            code.push(opc);
            abs(reg, DATA + off, &mut code);
            let o = off as usize;
            match (opc, reg) {
                (0xD9, 0) | (0xD8, _) => {
                    let v = if r.below(10) == 0 { r.u32() } else { (fv(r) as f32).to_bits() };
                    put_f32(&mut c.data, o, v);
                }
                (0xDD, 0) | (0xDC, _) => c.data[o..o + 8].copy_from_slice(&fv(r).to_bits().to_le_bytes()),
                (0xDB, 0) | (0xDA, _) => put_f32(&mut c.data, o, rv(r)),
                (0xDF, 0) => c.data[o..o + 2].copy_from_slice(&(rv(r) as u16).to_le_bytes()),
                (0xDF, 5) => c.data[o..o + 8].copy_from_slice(&(fv(r) as i64 as u64 ^ (r.below(2) as u64)).to_le_bytes()),
                (0xDB, 5) => {
                    let m = match r.below(5) {
                        0 => {
                            let mut m = [0u8; 10];
                            for b in m.iter_mut() {
                                *b = r.u32() as u8;
                            }
                            m
                        }
                        1 => {
                            let mut m = m80_of(fv(r));
                            let e = (r.below(0x7fff) as u16) | (m[9] as u16 & 0x80) << 8;
                            m[8..].copy_from_slice(&e.to_le_bytes());
                            m
                        }
                        _ => m80_of(fv(r)),
                    };
                    c.data[o..o + 10].copy_from_slice(&m);
                }
                (0xDF, 4) => {
                    for k in 0..9 {
                        let lo = if r.below(20) == 0 { r.below(16) } else { r.below(10) };
                        let hi = r.below(10);
                        c.data[o + k] = (lo | (hi << 4)) as u8;
                    }
                    c.data[o + 9] = if r.bit() { 0x80 } else { 0 };
                }
                (0xD9, 5) => {
                    let v = 0x027f | ((r.below(4) as u16) << 10) | (r.u32() as u16 & 0xf000);
                    c.data[o..o + 2].copy_from_slice(&v.to_le_bytes());
                }
                _ => {}
            }
        }
        Op::FReg { opc, modrm } => code.extend([opc, modrm]),
    }
    c.code[..code.len()].copy_from_slice(&code);
    c
}

/// What the translator will emit for `op`, run on the xrt helpers.
/// Returns true where the oracle traps.
fn eval(op: &Op, c: &mut Cpu, m: &mut Mem) -> bool {
    match *op {
        Op::Alu { op, sz, form, reg, rm, imm, opc } => match form {
            0 => {
                let (a, b) = (c.getreg(rm, sz), c.getreg(reg, sz));
                let v = c.alu(op, a, b, sz);
                if op != 7 {
                    c.setreg(rm, sz, v);
                }
            }
            1 => {
                let (a, b) = (c.getreg(reg, sz), c.getreg(rm, sz));
                let v = c.alu(op, a, b, sz);
                if op != 7 {
                    c.setreg(reg, sz, v);
                }
            }
            2 => {
                let a = c.getreg(rm, sz);
                let b = match opc {
                    0x80 => imm & 0xff,
                    0x83 => imm as u8 as i8 as i32 as u32,
                    _ => imm & ss_rs_ng_xrt::SZMASK[sz],
                };
                let v = c.alu(op, a, b, sz);
                if op != 7 {
                    c.setreg(rm, sz, v);
                }
            }
            _ => {
                let a = c.getreg(EAX, sz);
                let v = c.alu(op, a, imm & ss_rs_ng_xrt::SZMASK[sz], sz);
                if op != 7 {
                    c.setreg(EAX, sz, v);
                }
            }
        },
        Op::IncDec { dec, sz, rm, .. } => {
            let a = c.getreg(rm, sz);
            let v = if dec { c.dec(a, sz) } else { c.inc(a, sz) };
            c.setreg(rm, sz, v);
        }
        Op::Unary { sel, sz, rm, imm } => {
            let a = c.getreg(rm, sz);
            match sel {
                0 => {
                    c.logic(a & imm, sz);
                }
                2 => c.setreg(rm, sz, !a),
                3 => {
                    let v = c.neg(a, sz);
                    c.setreg(rm, sz, v);
                }
                4 => c.mul1(a, sz),
                5 => c.imul1(a, sz),
                6 => return !c.div1(a, sz),
                _ => return !c.idiv1(a, sz),
            }
        }
        Op::Imul { form, sz, reg, rm, imm } => {
            let (a, b) = match form {
                0x69 => (c.getreg(rm, sz), if sz == 2 { imm as u16 as i16 as i32 as u32 } else { imm }),
                0x6B => (c.getreg(rm, sz), imm as u8 as i8 as i32 as u32),
                _ => (c.getreg(reg, sz), c.getreg(rm, sz)),
            };
            let v = c.imul(a, b);
            c.setreg(reg, sz, v);
        }
        Op::Test { sz, reg, rm } => {
            let v = c.getreg(rm, sz) & c.getreg(reg, sz);
            c.logic(v, sz);
        }
        Op::Shift { form, sel, sz, rm, imm } => {
            let v = c.getreg(rm, sz);
            let cnt = match form {
                0xC0 => imm as u32,
                0xD0 => 1,
                _ => c.r[ECX] & 0xff,
            };
            let res = c.shift(sel, v, cnt, sz);
            c.setreg(rm, sz, res);
        }
        Op::Shxd { left, cl, sz, reg, rm, imm } => {
            let cnt = if cl { c.r[ECX] & 0xff } else { imm as u32 };
            let (dst, src) = (c.getreg(rm, sz), c.getreg(reg, sz));
            let v = if left { c.shld(dst, src, cnt, sz) } else { c.shrd(dst, src, cnt, sz) };
            c.setreg(rm, sz, v);
        }
        Op::BtReg { sel, sz, reg, rm, imm } => {
            let bit = match imm {
                Some(i) => i as u32,
                None => c.getreg(reg, sz),
            };
            let v = c.getreg(rm, sz);
            let nv = c.bt(sel, v, bit, sz);
            if sel != 4 {
                c.setreg(rm, sz, nv);
            }
        }
        Op::BtMem { sel, sz, reg, imm } => match imm {
            Some(i) => {
                let a = DATA + 120;
                let v = m.rsz(a, sz);
                let nv = c.bt(sel, v, i as u32, sz);
                if sel != 4 {
                    m.wsz(a, sz, nv);
                }
            }
            None => {
                let off = c.getreg(reg, sz);
                c.bt_mem(m, sel, DATA + 128, off, sz);
            }
        },
        Op::Bsx { rev, sz, reg, rm } => {
            let v = c.getreg(rm, sz);
            let r = if rev { c.bsr(v) } else { c.bsf(v) };
            if let Some(i) = r {
                c.setreg(reg, sz, i);
            }
        }
        Op::Setcc { cc, rm } => {
            let v = c.cond(cc) as u32;
            c.setreg(rm, 1, v);
        }
        Op::Cmov { cc, sz, reg, rm } => {
            let v = c.getreg(rm, sz);
            if c.cond(cc) {
                c.setreg(reg, sz, v);
            }
        }
        Op::Movx { sx, word, sz, reg, rm } => {
            let v = if word { c.getreg(rm, 2) } else { c.getreg(rm, 1) };
            let v = match (sx, word) {
                (true, false) => v as u8 as i8 as i32 as u32,
                (true, true) => v as u16 as i16 as i32 as u32,
                _ => v,
            };
            c.setreg(reg, sz, v);
        }
        Op::Cbw { sz } => c.cbw(sz),
        Op::Cwd { sz } => c.cwd(sz),
        Op::Flag { opc } => match opc {
            0x9E => c.sahf(),
            0x9F => c.lahf(),
            0xF5 => {
                let cf = c.flag(ss_rs_ng_xrt::CF);
                c.setf(ss_rs_ng_xrt::CF, !cf);
            }
            0xF8 => c.setf(ss_rs_ng_xrt::CF, false),
            0xF9 => c.setf(ss_rs_ng_xrt::CF, true),
            0xFC => c.setf(ss_rs_ng_xrt::DF, false),
            0xFD => c.setf(ss_rs_ng_xrt::DF, true),
            0x9C => {
                let f = c.eflags;
                c.push32(m, f);
            }
            _ => {
                let v = c.pop32(m);
                c.popf_value(v);
            }
        },
        Op::Xchg { sz, reg, rm } => {
            let (a, b) = (c.getreg(rm, sz), c.getreg(reg, sz));
            c.setreg(rm, sz, b);
            c.setreg(reg, sz, a);
        }
        Op::XchgEax { r: reg, .. } => c.r.swap(EAX, reg),
        Op::Xadd { sz, reg, rm } => {
            let (a, b) = (c.getreg(rm, sz), c.getreg(reg, sz));
            let s = c.add(a, b, sz);
            c.setreg(reg, sz, a);
            c.setreg(rm, sz, s);
        }
        Op::Cmpxchg { sz, reg, rm } => {
            let (a, acc) = (c.getreg(rm, sz), c.getreg(EAX, sz));
            c.sub(acc, a, sz);
            if acc == a {
                let v = c.getreg(reg, sz);
                c.setreg(rm, sz, v);
            } else {
                c.setreg(EAX, sz, a);
            }
        }
        Op::Bswap { r: reg } => c.r[reg] = c.r[reg].swap_bytes(),
        Op::Push { r: reg } => {
            let v = c.r[reg];
            c.push32(m, v);
        }
        Op::Pop { r: reg } => {
            let v = c.pop32(m);
            c.r[reg] = v;
        }
        Op::PushImm { wide, imm } => {
            let v = if wide { imm } else { imm as u8 as i8 as i32 as u32 };
            c.push32(m, v);
        }
        Op::Str { opc, sz, rep } => {
            let (f3, f2) = (rep == 0xF3, rep == 0xF2);
            match opc {
                0xA4 => c.movs(m, sz, f3 || f2),
                0xAA => c.stos(m, sz, f3 || f2),
                0xAC => c.lods(m, sz, f3 || f2),
                0xAE => c.scas(m, sz, f3, f2),
                _ => c.cmps(m, sz, f3, f2),
            }
        }
        Op::FMem { opc, reg, off } => return !c.x87_mem(m, opc, reg, DATA + off),
        Op::FReg { opc, modrm } => return !c.x87_reg(opc, modrm),
    }
    false
}

fn run_rust(op: &Op, input: &Case, m: &mut Mem) -> Case {
    let mut c = Cpu {
        r: input.r,
        eflags: input.eflags,
        top: input.top & 7,
        cw: input.cw,
        sw: input.sw,
        ..Cpu::default()
    };
    for k in 0..8 {
        c.st[k] = f64::from_bits(input.st[k]);
    }
    m.write(DATA, &input.data);
    let faulted = eval(op, &mut c, m);
    let mut out = input.clone();
    out.r = c.r;
    out.eflags = c.eflags;
    out.top = c.top & 7;
    out.cw = c.cw;
    out.sw = c.sw;
    out.faulted = faulted as u32;
    for k in 0..8 {
        out.st[k] = c.st[k].to_bits();
    }
    out.data.copy_from_slice(&m.read(DATA, 256));
    out
}

fn diff(input: &Case, ours: &Case, theirs: &Case) -> String {
    let mut s = String::new();
    let hex: Vec<String> = input.code.iter().map(|b| format!("{b:02x}")).collect();
    s.push_str(&format!("      code {}\n", hex.join(" ")));
    let names = ["eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi"];
    for k in 0..8 {
        if ours.r[k] != theirs.r[k] {
            s.push_str(&format!(
                "      {}: in {:08x}  xrt {:08x}  cpu.c {:08x}\n",
                names[k], input.r[k], ours.r[k], theirs.r[k]
            ));
        }
    }
    if ours.eflags != theirs.eflags {
        s.push_str(&format!(
            "      eflags: in {:04x}  xrt {:04x}  cpu.c {:04x}\n",
            input.eflags, ours.eflags, theirs.eflags
        ));
    }
    if ours.top != theirs.top || ours.cw != theirs.cw || ours.sw != theirs.sw {
        s.push_str(&format!(
            "      top/cw/sw: in {}/{:04x}/{:04x}  xrt {}/{:04x}/{:04x}  cpu.c {}/{:04x}/{:04x}\n",
            input.top, input.cw, input.sw, ours.top, ours.cw, ours.sw, theirs.top, theirs.cw, theirs.sw
        ));
    }
    for k in 0..8 {
        if ours.st[k] != theirs.st[k] {
            s.push_str(&format!(
                "      st[{k}] (top {}): in {:e}  xrt {:e} ({:016x})  cpu.c {:e} ({:016x})\n",
                input.top,
                f64::from_bits(input.st[k]),
                f64::from_bits(ours.st[k]),
                ours.st[k],
                f64::from_bits(theirs.st[k]),
                theirs.st[k]
            ));
        }
    }
    for k in 0..256 {
        if ours.data[k] != theirs.data[k] {
            let lo = k & !7;
            let row = |d: &[u8; 256]| {
                d[lo..lo + 16.min(256 - lo)].iter().map(|b| format!("{b:02x}")).collect::<Vec<_>>().join("")
            };
            s.push_str(&format!(
                "      data+{lo:#x}: in {}  xrt {}  cpu.c {}\n",
                row(&input.data),
                row(&ours.data),
                row(&theirs.data)
            ));
            break;
        }
    }
    if ours.faulted != theirs.faulted {
        s.push_str(&format!("      faulted: xrt {}  cpu.c {}\n", ours.faulted, theirs.faulted));
    }
    s
}

/// A mismatch only in which NaN came out (sign or payload), everything else
/// equal. x87 code that produces a NaN is on a broken path either way.
fn nan_only(ours: &Case, theirs: &Case) -> bool {
    let mut o = ours.clone();
    for k in 0..8 {
        let (a, b) = (f64::from_bits(ours.st[k]), f64::from_bits(theirs.st[k]));
        if a.is_nan() && b.is_nan() {
            o.st[k] = theirs.st[k];
        }
    }
    o == *theirs
}

#[derive(Default)]
struct Stat {
    n: u64,
    bad: u64,
    nan: u64,
    faults: u64,
    shown: Vec<String>,
}

fn shard(k: usize, n: usize, seed: u64, opstep: &Path, work: &Path, show: usize) -> BTreeMap<String, Stat> {
    let tpl = templates();
    let mut r = Rng(seed ^ (k as u64).wrapping_mul(0xd1b5_4a32_d192_ed03));
    let mut ops = Vec::with_capacity(n);
    let mut cases = Vec::with_capacity(n);
    let mut bytes = Vec::with_capacity(n * CASE);
    for i in 0..n {
        let t = &tpl[(i + k * 7919) % tpl.len()];
        let op = t(&mut r);
        let c = setup(&op, &mut r);
        c.to_bytes(&mut bytes);
        ops.push(op);
        cases.push(c);
    }
    let inp = work.join(format!("shard{k:02}.in"));
    let outp = work.join(format!("shard{k:02}.out"));
    std::fs::write(&inp, &bytes).expect("write cases");
    let st = Command::new(opstep)
        .arg(&inp)
        .arg(&outp)
        .stderr(Stdio::null())
        .status()
        .expect("run opstep");
    assert!(st.success(), "opstep failed on shard {k}");
    let res = std::fs::read(&outp).expect("read results");
    assert_eq!(res.len(), bytes.len(), "opstep returned a short file for shard {k}");
    let mut m = Mem::new();
    m.zeroed(DATA, 0x1000);
    let mut stats: BTreeMap<String, Stat> = BTreeMap::new();
    for i in 0..n {
        let theirs = Case::from_bytes(&res[i * CASE..(i + 1) * CASE]);
        let ours = run_rust(&ops[i], &cases[i], &mut m);
        let g = stats.entry(group(&ops[i])).or_default();
        g.n += 1;
        g.faults += theirs.faulted as u64;
        if ours != theirs {
            if nan_only(&ours, &theirs) {
                g.nan += 1;
                continue;
            }
            g.bad += 1;
            if g.shown.len() < show {
                g.shown.push(diff(&cases[i], &ours, &theirs));
            }
        }
    }
    let _ = std::fs::remove_file(&inp);
    let _ = std::fs::remove_file(&outp);
    stats
}

pub fn run(args: &[String]) -> i32 {
    let mut n: usize = 2_000_000;
    let mut seed: u64 = 0x5352_4e47_4d32;
    let mut shards = std::thread::available_parallelism().map_or(8, |p| p.get());
    let mut show = 2usize;
    let mut i = 0;
    while i < args.len() {
        let v = args.get(i + 1).cloned().unwrap_or_default();
        match args[i].as_str() {
            "--n" => n = v.parse().expect("--n"),
            "--seed" => seed = v.parse().expect("--seed"),
            "--shards" => shards = v.parse().expect("--shards"),
            "--show" => show = v.parse().expect("--show"),
            a => {
                eprintln!("opgate: unknown argument {a}");
                return 2;
            }
        }
        i += 2;
    }
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf();
    let opstep = root.join("oracle").join("opstep").join("build").join("opstep.exe");
    if !opstep.exists() {
        eprintln!("opgate: {} missing; run oracle\\opstep\\build.bat", opstep.display());
        return 2;
    }
    let work = std::env::temp_dir().join("ssrsng_opgate");
    std::fs::create_dir_all(&work).expect("work dir");
    let per = n.div_ceil(shards);
    let t0 = std::time::Instant::now();
    let results: Vec<BTreeMap<String, Stat>> = std::thread::scope(|s| {
        let hs: Vec<_> = (0..shards)
            .map(|k| {
                let (opstep, work) = (&opstep, &work);
                s.spawn(move || shard(k, per, seed, opstep, work, show))
            })
            .collect();
        hs.into_iter().map(|h| h.join().expect("shard panicked")).collect()
    });
    let mut all: BTreeMap<String, Stat> = BTreeMap::new();
    for r in results {
        for (g, s) in r {
            let a = all.entry(g).or_default();
            a.n += s.n;
            a.bad += s.bad;
            a.nan += s.nan;
            a.faults += s.faults;
            for x in s.shown {
                if a.shown.len() < show {
                    a.shown.push(x);
                }
            }
        }
    }
    let (mut total, mut bad, mut groups_bad) = (0u64, 0u64, 0usize);
    let (mut native, mut libm, mut nan) = (0u64, 0u64, 0u64);
    for (g, s) in &all {
        total += s.n;
        nan += s.nan;
        if s.bad == 0 {
            continue;
        }
        if let Some((_, why)) = NATIVE.iter().find(|(n, _)| n == g) {
            native += s.bad;
            println!("native  {g}: {}/{} differ from the oracle ({why})", s.bad, s.n);
            continue;
        }
        if LIBM.contains(&g.as_str()) {
            libm += s.bad;
            println!("libm    {g}: {}/{} differ (host libm, unused by the engine)", s.bad, s.n);
            continue;
        }
        bad += s.bad;
        groups_bad += 1;
        println!("MISMATCH {g}: {}/{} ({} oracle traps)", s.bad, s.n, s.faults);
        for x in &s.shown {
            print!("{x}");
        }
    }
    for (g, s) in &all {
        if s.nan != 0 {
            println!("nan     {g}: {}/{} differ only in NaN sign/payload", s.nan, s.n);
        }
    }
    println!(
        "opgate: {} groups, {} cases in {:.1} s: {} exact mismatches in {} groups \
         (documented: native {native}, libm {libm}, NaN-only {nan})",
        all.len(),
        total,
        t0.elapsed().as_secs_f64(),
        bad,
        groups_bad,
    );
    if bad == 0 {
        0
    } else {
        1
    }
}
