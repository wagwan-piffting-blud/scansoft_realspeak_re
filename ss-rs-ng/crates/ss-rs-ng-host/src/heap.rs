//! The guest heap: `win32_donor.c`'s first-fit allocator over in-guest
//! `[size][free]` headers, with its forward merging, verbatim. The engine's
//! output does not depend on addresses (native and the oracle agree with
//! wholly different heaps), but the same allocator keeps traces comparable.

use ss_rs_ng_xrt::Mem;

pub const HEAP_BASE: u32 = 0x3000_0000;
pub const HEAP_SIZE: u32 = 0x0800_0000;
const HEAP_END: u32 = HEAP_BASE + HEAP_SIZE;

/// `lo` is a block header with only allocated blocks before it, so a scan
/// from it finds what the donor's scan from the base finds.
pub struct Heap {
    lo: u32,
}

fn zero(m: &mut Mem, a: u32, n: u32) {
    const CHUNK: usize = 1 << 16;
    let z = [0u8; CHUNK];
    let mut done = 0u32;
    while done < n {
        let k = (n - done).min(CHUNK as u32);
        m.write(a + done, &z[..k as usize]);
        done += k;
    }
}

impl Heap {
    pub fn init(m: &mut Mem) -> Heap {
        m.zeroed(HEAP_BASE, HEAP_SIZE);
        m.w32(HEAP_BASE, HEAP_SIZE - 8);
        m.w32(HEAP_BASE + 4, 1);
        Heap { lo: HEAP_BASE }
    }

    pub fn alloc(&mut self, m: &mut Mem, n: u32, zeroed: bool) -> u32 {
        let mut n = n.wrapping_add(7) & !7;
        if n == 0 {
            n = 8;
        }
        if self.lo < HEAP_BASE || self.lo >= HEAP_END {
            self.lo = HEAP_BASE;
        }
        let mut b = self.lo;
        while b < HEAP_END {
            let mut sz = m.r32(b);
            let fr = m.r32(b + 4);
            if fr != 0 {
                let mut nb = b + 8 + sz;
                while nb < HEAP_END && m.r32(nb + 4) != 0 {
                    sz += 8 + m.r32(nb);
                    nb = b + 8 + sz;
                }
                m.w32(b, sz);
            }
            if fr != 0 && sz >= n {
                if sz >= n + 16 {
                    let nb = b + 8 + n;
                    m.w32(nb, sz - n - 8);
                    m.w32(nb + 4, 1);
                    m.w32(b, n);
                }
                m.w32(b + 4, 0);
                if zeroed {
                    let len = (m.r32(b) + 3) & !3;
                    zero(m, b + 8, len);
                }
                return b + 8;
            }
            if fr == 0 && b == self.lo {
                self.lo = b + 8 + sz;
            }
            b += 8 + sz;
        }
        eprintln!("** heap OOM requesting {n}");
        0
    }

    pub fn free(&mut self, m: &mut Mem, p: u32) {
        if p == 0 {
            return;
        }
        let b = p - 8;
        m.w32(b + 4, 1);
        if b < self.lo {
            self.lo = b;
        }
        loop {
            let sz = m.r32(b);
            let nb = b + 8 + sz;
            if nb >= HEAP_END {
                break;
            }
            if m.r32(nb + 4) != 0 {
                let v = sz + 8 + m.r32(nb);
                m.w32(b, v);
            } else {
                break;
            }
        }
    }

    pub fn realloc(&mut self, m: &mut Mem, p: u32, n: u32) -> u32 {
        if p == 0 {
            return self.alloc(m, n, false);
        }
        let oldsz = m.r32(p - 8);
        let need = n.wrapping_add(7) & !7;
        if need > oldsz {
            let b = p - 8;
            let mut sz = oldsz;
            let mut nb = b + 8 + sz;
            while nb < HEAP_END && m.r32(nb + 4) != 0 && sz < need {
                sz += 8 + m.r32(nb);
                nb = b + 8 + sz;
            }
            if sz >= need {
                if sz >= need + 16 {
                    let tb = b + 8 + need;
                    m.w32(tb, sz - need - 8);
                    m.w32(tb + 4, 1);
                    sz = need;
                }
                m.w32(b, sz);
                if self.lo > b && self.lo < b + 8 + sz {
                    self.lo = b;
                }
                return p;
            }
        }
        let np = self.alloc(m, n, false);
        if np == 0 {
            return 0;
        }
        let c = oldsz.min(n);
        let tmp = m.read(p, c as usize);
        m.write(np, &tmp);
        self.free(m, p);
        np
    }

    pub fn size_of(&self, m: &Mem, p: u32) -> u32 {
        if p == 0 {
            0
        } else {
            m.r32(p - 8)
        }
    }
}
