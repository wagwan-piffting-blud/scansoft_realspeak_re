//! Mapping a vendor DLL into guest memory as data, as `modules.c`'s
//! `map_image` does: headers, sections, base relocations to the translated
//! base, and the new ImageBase written back. Nothing in the file is run.

use ss_rs_ng_xrt::Mem;

pub struct Image {
    pub size: u32,
    pub entry_rva: u32,
}

fn f16(b: &[u8], o: usize) -> u32 {
    b[o] as u32 | (b[o + 1] as u32) << 8
}

fn f32(b: &[u8], o: usize) -> u32 {
    f16(b, o) | f16(b, o + 2) << 16
}

pub fn map(m: &mut Mem, file: &[u8], base: u32) -> Result<Image, String> {
    if file.len() < 0x40 || f16(file, 0) != 0x5A4D {
        return Err("not an MZ file".into());
    }
    let lfanew = f32(file, 0x3c) as usize;
    if f32(file, lfanew) != 0x0000_4550 {
        return Err("no PE header".into());
    }
    let coff = lfanew + 4;
    let nsec = f16(file, coff + 2) as usize;
    let optsz = f16(file, coff + 16) as usize;
    let opt = coff + 20;
    if f16(file, opt) != 0x10b {
        return Err("not PE32".into());
    }
    let pref = f32(file, opt + 28);
    let size = f32(file, opt + 56);
    let entry_rva = f32(file, opt + 16);
    let reloc_rva = f32(file, opt + 96 + 5 * 8);
    let reloc_sz = f32(file, opt + 96 + 5 * 8 + 4);
    let span = (size + 0xfff) & !0xfff;
    m.zeroed(base, span);
    let hdr = (f32(file, opt + 60) as usize).min(file.len());
    m.write(base, &file[..hdr]);
    let sectab = opt + optsz;
    for i in 0..nsec {
        let s = sectab + i * 40;
        let vsize = f32(file, s + 8);
        let vaddr = f32(file, s + 12);
        let rawsz = f32(file, s + 16);
        let rawptr = f32(file, s + 20);
        let mut n = rawsz.min(vsize);
        if vsize == 0 {
            n = rawsz;
        }
        if (rawptr as u64 + n as u64) <= file.len() as u64 && vaddr as u64 + n as u64 <= size as u64 {
            m.write(base + vaddr, &file[rawptr as usize..(rawptr + n) as usize]);
        }
    }
    let delta = base.wrapping_sub(pref);
    if delta != 0 && reloc_rva != 0 && reloc_sz != 0 {
        let mut p = reloc_rva;
        let end = reloc_rva + reloc_sz;
        while p < end {
            let page = m.r32(base + p);
            let blk = m.r32(base + p + 4);
            if blk < 8 {
                break;
            }
            for k in 0..(blk - 8) / 2 {
                let e = m.r16(base + p + 8 + k * 2);
                if e >> 12 == 3 {
                    let a = base + page + (e & 0xfff) as u32;
                    let v = m.r32(a).wrapping_add(delta);
                    m.w32(a, v);
                }
            }
            p += blk;
        }
    }
    m.w32(base + lfanew as u32 + 52, base);
    Ok(Image { size, entry_rva })
}
