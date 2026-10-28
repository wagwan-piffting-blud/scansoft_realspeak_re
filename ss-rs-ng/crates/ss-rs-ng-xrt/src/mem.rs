//! Guest memory, in two shapes chosen by the host's pointer width. This is
//! loqng-xrt's `mem.rs`, changed for x86 guests: accesses may be unaligned,
//! so the page-table shape takes a slow path when one straddles a page.
//!
//! **64-bit host:** one 4 GB reservation; a guest access is `base + a`.
//! Reserved is not committed, so an address outside every mapped region
//! faults instead of reading another region.
//!
//! **32-bit host:** a page table of host pointers, one extra load per
//! access. Byte-identical to the window; only slower.

use std::cell::Cell;

#[allow(dead_code)]
const PAGE: u32 = 4096;

#[cfg(all(target_pointer_width = "64", target_vendor = "apple"))]
const COMMIT: u32 = 16384;
#[cfg(all(target_pointer_width = "64", not(target_vendor = "apple")))]
const COMMIT: u32 = PAGE;

// ===========================================================================
// 64-bit: one flat window
// ===========================================================================

#[cfg(target_pointer_width = "64")]
mod imp {
    use super::{Cell, COMMIT};

    const SPACE: usize = 1usize << 32;

    pub struct Mem {
        base: *mut u8,
        regions: Vec<(u32, u32)>,
        last: Cell<usize>,
    }

    impl Drop for Mem {
        fn drop(&mut self) {
            unsafe { sys::release(self.base, SPACE) };
        }
    }

    impl Mem {
        pub fn new() -> Self {
            let base = unsafe { sys::reserve(SPACE) };
            assert!(
                !base.is_null(),
                "could not reserve 4 GB of address space for the guest"
            );
            Mem {
                base,
                regions: Vec::new(),
                last: Cell::new(0),
            }
        }

        pub fn zeroed(&mut self, base: u32, len: u32) {
            self.commit(base, len as u64);
            self.regions.push((base, len));
        }

        pub fn map(&mut self, base: u32, data: Vec<u8>) {
            self.commit(base, data.len() as u64);
            unsafe {
                std::ptr::copy_nonoverlapping(
                    data.as_ptr(),
                    self.base.add(base as usize),
                    data.len(),
                );
            }
            self.regions.push((base, data.len() as u32));
        }

        fn commit(&mut self, base: u32, len: u64) {
            let end = base as u64 + len;
            for &(b, n) in &self.regions {
                assert!(
                    end <= b as u64 || base as u64 >= b as u64 + n as u64,
                    "region 0x{base:08x}+{len} overlaps 0x{b:08x}+{n}"
                );
            }
            let first = base & !(COMMIT - 1);
            let last = ((end as u32).wrapping_add(COMMIT - 1)) & !(COMMIT - 1);
            let span = if last == 0 {
                SPACE - first as usize
            } else {
                (last - first) as usize
            };
            unsafe {
                let at = self.base.add(first as usize);
                assert!(
                    sys::commit(at, span),
                    "could not commit {span} bytes at guest 0x{first:08x}"
                );
            }
        }

        /// The window is 4 GB and `a` a `u32`, so `base + a` is always inside
        /// the reservation. An access of `n` bytes at the very top of the
        /// space would run past it; nothing maps the top page.
        #[inline(always)]
        pub(super) fn at(&self, a: u32, _n: u32) -> *mut u8 {
            unsafe { self.base.add(a as usize) }
        }

        pub(super) fn extents(&self) -> (&[(u32, u32)], &Cell<usize>) {
            (&self.regions, &self.last)
        }
    }

    #[cfg(windows)]
    mod sys {
        const MEM_COMMIT: u32 = 0x1000;
        const MEM_RESERVE: u32 = 0x2000;
        const MEM_RELEASE: u32 = 0x8000;
        const PAGE_NOACCESS: u32 = 0x01;
        const PAGE_READWRITE: u32 = 0x04;

        extern "system" {
            fn VirtualAlloc(at: *mut u8, size: usize, kind: u32, prot: u32) -> *mut u8;
            fn VirtualFree(at: *mut u8, size: usize, kind: u32) -> i32;
        }

        pub unsafe fn reserve(size: usize) -> *mut u8 {
            VirtualAlloc(std::ptr::null_mut(), size, MEM_RESERVE, PAGE_NOACCESS)
        }

        pub unsafe fn commit(at: *mut u8, size: usize) -> bool {
            !VirtualAlloc(at, size, MEM_COMMIT, PAGE_READWRITE).is_null()
        }

        pub unsafe fn release(at: *mut u8, _size: usize) {
            VirtualFree(at, 0, MEM_RELEASE);
        }
    }

    #[cfg(unix)]
    mod sys {
        const PROT_NONE: i32 = 0;
        const PROT_READ: i32 = 1;
        const PROT_WRITE: i32 = 2;
        const MAP_PRIVATE: i32 = 2;
        #[cfg(target_vendor = "apple")]
        const MAP_ANONYMOUS: i32 = 0x1000;
        #[cfg(target_vendor = "apple")]
        const MAP_NORESERVE: i32 = 0x40;
        #[cfg(not(target_vendor = "apple"))]
        const MAP_ANONYMOUS: i32 = 0x20;
        #[cfg(not(target_vendor = "apple"))]
        const MAP_NORESERVE: i32 = 0x4000;

        extern "C" {
            fn mmap(at: *mut u8, len: usize, prot: i32, flags: i32, fd: i32, off: i64) -> *mut u8;
            fn mprotect(at: *mut u8, len: usize, prot: i32) -> i32;
            fn munmap(at: *mut u8, len: usize) -> i32;
        }

        pub unsafe fn reserve(size: usize) -> *mut u8 {
            let p = mmap(
                std::ptr::null_mut(),
                size,
                PROT_NONE,
                MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE,
                -1,
                0,
            );
            if p as isize == -1 {
                std::ptr::null_mut()
            } else {
                p
            }
        }

        pub unsafe fn commit(at: *mut u8, size: usize) -> bool {
            mprotect(at, size, PROT_READ | PROT_WRITE) == 0
        }

        pub unsafe fn release(at: *mut u8, size: usize) {
            munmap(at, size);
        }
    }
}

// ===========================================================================
// 32-bit: a page table of host pointers
// ===========================================================================

#[cfg(not(target_pointer_width = "64"))]
mod imp {
    use super::{Cell, PAGE};

    const PAGE_BITS: u32 = 12;
    const PAGES: usize = 1 << (32 - PAGE_BITS);

    struct Region {
        base: u32,
        len: u32,
        data: Vec<u8>,
    }

    pub struct Mem {
        regions: Vec<Region>,
        /// Where guest page `a >> PAGE_BITS` lives on the host, or null if
        /// the page is not wholly inside one region.
        page: Vec<*mut u8>,
        extent: Vec<(u32, u32)>,
        last: Cell<usize>,
    }

    impl Mem {
        pub fn new() -> Self {
            Mem {
                regions: Vec::new(),
                page: vec![std::ptr::null_mut(); PAGES],
                extent: Vec::new(),
                last: Cell::new(0),
            }
        }

        pub fn zeroed(&mut self, base: u32, len: u32) {
            self.map(base, vec![0; len as usize]);
        }

        pub fn map(&mut self, base: u32, mut data: Vec<u8>) {
            let end = base as u64 + data.len() as u64;
            for r in &self.regions {
                assert!(
                    end <= r.base as u64 || base as u64 >= r.base as u64 + r.len as u64,
                    "region 0x{base:08x}+{} overlaps 0x{:08x}+{}",
                    data.len(),
                    r.base,
                    r.len
                );
            }
            let host = data.as_mut_ptr();
            let step = PAGE as u64;
            let mut at = (base as u64 + step - 1) & !(step - 1);
            let stop = end & !(step - 1);
            while at < stop {
                self.page[(at >> PAGE_BITS) as usize] =
                    unsafe { host.add((at - base as u64) as usize) };
                at += step;
            }
            let len = data.len() as u32;
            self.extent.push((base, len));
            self.regions.push(Region { base, len, data });
        }

        /// A non-null entry proves the page is mapped. An `n`-byte access
        /// that would leave the page, or one in a ragged region end, goes to
        /// `edge`, which finds the region and proves all `n` bytes lie in it.
        #[inline(always)]
        pub(super) fn at(&self, a: u32, n: u32) -> *mut u8 {
            let p = unsafe { *self.page.get_unchecked((a >> PAGE_BITS) as usize) };
            if p.is_null() || (a & (PAGE - 1)) > PAGE - n {
                return self.edge(a, n);
            }
            unsafe { p.add((a & (PAGE - 1)) as usize) }
        }

        #[inline(never)]
        #[cold]
        fn edge(&self, a: u32, n: u32) -> *mut u8 {
            for (k, r) in self.regions.iter().enumerate() {
                let off = a.wrapping_sub(r.base) as u64;
                if a >= r.base && off + n as u64 <= r.len as u64 {
                    self.last.set(k);
                    return unsafe { r.data.as_ptr().add(off as usize) as *mut u8 };
                }
            }
            panic!(
                "translated code touched unmapped memory at 0x{a:08x}+{n}{}",
                super::super::where_from()
            );
        }

        pub(super) fn extents(&self) -> (&[(u32, u32)], &Cell<usize>) {
            (&self.extent, &self.last)
        }
    }
}

pub use imp::Mem;

// ===========================================================================
// The accessors, which are the same either way
// ===========================================================================

impl Mem {
    pub fn with_image(image: &[(u32, &[u8])]) -> Self {
        let mut m = Mem::new();
        for (base, bytes) in image {
            m.map(*base, bytes.to_vec());
        }
        m
    }

    /// Whether `n` bytes at `a` are inside one mapped region.
    pub fn mapped(&self, a: u32, n: u32) -> bool {
        let (regions, last) = self.extents();
        let hit = |&(b, len): &(u32, u32)| a >= b && (a - b) as u64 + n as u64 <= len as u64;
        if regions.get(last.get()).map_or(false, hit) {
            return true;
        }
        match regions.iter().position(hit) {
            Some(k) => {
                last.set(k);
                true
            }
            None => false,
        }
    }

    #[inline(always)]
    pub fn r8(&self, a: u32) -> u8 {
        debug_assert!(self.mapped(a, 1), "read8 from unmapped 0x{a:08x}");
        unsafe { *self.at(a, 1) }
    }

    #[inline(always)]
    pub fn r16(&self, a: u32) -> u16 {
        debug_assert!(self.mapped(a, 2), "read16 from unmapped 0x{a:08x}");
        unsafe { u16::from_le((self.at(a, 2) as *const u16).read_unaligned()) }
    }

    #[inline(always)]
    pub fn r32(&self, a: u32) -> u32 {
        debug_assert!(self.mapped(a, 4), "read32 from unmapped 0x{a:08x}");
        unsafe { u32::from_le((self.at(a, 4) as *const u32).read_unaligned()) }
    }

    #[inline(always)]
    pub fn r64(&self, a: u32) -> u64 {
        debug_assert!(self.mapped(a, 8), "read64 from unmapped 0x{a:08x}");
        unsafe { u64::from_le((self.at(a, 8) as *const u64).read_unaligned()) }
    }

    #[inline(always)]
    pub fn w8(&mut self, a: u32, v: u8) {
        debug_assert!(self.mapped(a, 1), "write8 to unmapped 0x{a:08x}");
        unsafe { *self.at(a, 1) = v };
    }

    #[inline(always)]
    pub fn w16(&mut self, a: u32, v: u16) {
        debug_assert!(self.mapped(a, 2), "write16 to unmapped 0x{a:08x}");
        unsafe { (self.at(a, 2) as *mut u16).write_unaligned(v.to_le()) };
    }

    #[inline(always)]
    pub fn w32(&mut self, a: u32, v: u32) {
        debug_assert!(self.mapped(a, 4), "write32 to unmapped 0x{a:08x}");
        unsafe { (self.at(a, 4) as *mut u32).write_unaligned(v.to_le()) };
    }

    #[inline(always)]
    pub fn w64(&mut self, a: u32, v: u64) {
        debug_assert!(self.mapped(a, 8), "write64 to unmapped 0x{a:08x}");
        unsafe { (self.at(a, 8) as *mut u64).write_unaligned(v.to_le()) };
    }

    /// A read at operand size 1, 2 or 4, zero-extended.
    #[inline(always)]
    pub fn rsz(&self, a: u32, sz: usize) -> u32 {
        match sz {
            1 => self.r8(a) as u32,
            2 => self.r16(a) as u32,
            _ => self.r32(a),
        }
    }

    #[inline(always)]
    pub fn wsz(&mut self, a: u32, sz: usize, v: u32) {
        match sz {
            1 => self.w8(a, v as u8),
            2 => self.w16(a, v as u16),
            _ => self.w32(a, v),
        }
    }

    pub fn read(&self, a: u32, n: usize) -> Vec<u8> {
        assert!(
            self.mapped(a, n as u32),
            "reading {n} bytes from unmapped 0x{a:08x}{}",
            super::where_from()
        );
        if n == 0 {
            return Vec::new();
        }
        unsafe { std::slice::from_raw_parts(self.at_run(a, n as u32), n).to_vec() }
    }

    pub fn write(&mut self, a: u32, bytes: &[u8]) {
        assert!(
            self.mapped(a, bytes.len() as u32),
            "writing {} bytes to unmapped 0x{a:08x}{}",
            bytes.len(),
            super::where_from()
        );
        if bytes.is_empty() {
            return;
        }
        unsafe {
            std::ptr::copy_nonoverlapping(bytes.as_ptr(), self.at_run(a, bytes.len() as u32), bytes.len());
        }
    }

    /// A host pointer to `n` bytes that `mapped` has proved lie in one
    /// region. On the page-table shape `at(a, 1)` lands in that region's
    /// single buffer, so the run continues in it past any page boundary.
    #[inline(always)]
    fn at_run(&self, a: u32, _n: u32) -> *mut u8 {
        self.at(a, 1)
    }
}

impl Default for Mem {
    fn default() -> Self {
        Mem::new()
    }
}

#[cfg(test)]
mod tests {
    use super::Mem;

    #[test]
    fn unaligned_and_straddling() {
        let mut m = Mem::new();
        m.zeroed(0x1000_0000, 0x3000);
        for (k, a) in [0x1000_0ffdu32, 0x1000_0fff, 0x1000_1ffb, 0x1000_0001].iter().enumerate() {
            let v = 0x0102_0304_0506_0708u64.wrapping_mul(k as u64 + 3);
            m.w64(*a, v);
            assert_eq!(m.r64(*a), v);
            assert_eq!(m.r32(*a), v as u32);
            assert_eq!(m.r16(*a + 1), (v >> 8) as u16);
            for i in 0..8 {
                assert_eq!(m.r8(*a + i), (v >> (8 * i)) as u8);
            }
        }
        let bytes: Vec<u8> = (0..0x1800u32).map(|i| (i * 7) as u8).collect();
        m.write(0x1000_0800, &bytes);
        assert_eq!(m.read(0x1000_0800, bytes.len()), bytes);
    }

    #[test]
    fn ragged_region_ends() {
        let mut m = Mem::new();
        m.map(0x2000_0ff0, (0..0x30u8).collect());
        assert_eq!(m.r32(0x2000_0ffe), u32::from_le_bytes([14, 15, 16, 17]));
        m.w16(0x2000_0fff, 0xbeef);
        assert_eq!(m.r8(0x2000_0fff), 0xef);
        assert_eq!(m.r8(0x2000_1000), 0xbe);
        assert!(!m.mapped(0x2000_101e, 4));
        assert!(m.mapped(0x2000_101c, 4));
    }
}
