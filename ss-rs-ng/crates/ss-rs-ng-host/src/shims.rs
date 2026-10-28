//! The 57 system imports the two packs use, each as the oracle implements
//! it (`ssrs_shims.c` first, then `win32_donor.c` / `spfy_extra_shims.c`),
//! with the same stdcall argument bytes. An import the oracle has no shim for
//! returns 0 and cleans nothing, as `s_unimpl` does.

use crate::fmt::{format_guest, gstr};
use crate::{Guest, Handle, Stream, View, MAP_ARENA, MAP_ARENA_SIZE};
use ss_rs_ng_xrt::{Cpu, Mem, EAX, EDX, ESP};
use std::io::{Seek, SeekFrom};

pub type Shim = fn(&mut Guest, &mut Cpu, &mut Mem);

#[inline]
fn arg(c: &Cpu, m: &Mem, i: u32) -> u32 {
    m.r32(c.r[ESP].wrapping_add(4 + 4 * i))
}

fn ret(c: &mut Cpu, v: u32) {
    c.r[EAX] = v;
}

fn gstring(m: &Mem, va: u32, n: usize) -> String {
    String::from_utf8_lossy(&gstr(m, va, n)).into_owned()
}

/// `(shim, stdcall argument bytes)` for an import name.
pub fn lookup(name: &str) -> (Shim, u32) {
    match name {
        "LoadLibraryA" => (k_load_library, 4),
        "FreeLibrary" => (ret1, 4),
        "GetProcAddress" => (k_get_proc_address, 8),
        "CreateFileA" => (k_create_file, 28),
        "GetFileSize" => (k_get_file_size, 8),
        "CreateFileMappingA" => (k_create_file_mapping, 24),
        "MapViewOfFile" => (k_map_view, 20),
        "UnmapViewOfFile" => (ret1, 4),
        "FindFirstFileA" => (k_find_first, 8),
        "FindNextFileA" => (k_find_next, 8),
        "FindClose" => (k_find_close, 4),
        "CloseHandle" => (k_close_handle, 4),
        "DisableThreadLibraryCalls" => (ret1, 4),
        "InitializeCriticalSection" | "DeleteCriticalSection" | "EnterCriticalSection"
        | "LeaveCriticalSection" => (nop, 4),
        "IsBadReadPtr" | "IsBadWritePtr" | "IsBadStringPtrA" => (ret0, 8),
        "IsBadCodePtr" => (ret0, 4),
        "fopen" => (c_fopen, 0),
        "fclose" => (c_fclose, 0),
        "fread" => (c_fread, 0),
        "fwrite" => (c_fwrite, 0),
        "fseek" => (c_fseek, 0),
        "ftell" => (c_ftell, 0),
        "fflush" => (ret0, 0),
        "_fstat" | "remove" | "rename" => (ret_m1, 0),
        "sprintf" => (c_sprintf, 0),
        "_ftol" => (c_ftol, 0),
        "_isctype" => (c_isctype, 0),
        "tolower" => (c_tolower, 0),
        "time" => (c_time, 0),
        "ctime" => (c_ctime, 0),
        "strncat" => (c_strncat, 0),
        "strpbrk" => (c_strpbrk, 0),
        "strrchr" => (c_strrchr, 0),
        "strtoul" => (c_strtoul, 0),
        "wcslen" => (c_wcslen, 0),
        "_initterm" => (c_initterm, 0),
        "malloc" => (c_malloc, 0),
        "calloc" => (c_calloc, 0),
        "realloc" => (c_realloc, 0),
        "free" => (c_free, 0),
        "memmove" => (c_memmove, 0),
        "strncmp" => (c_strncmp, 0),
        "strncpy" => (c_strncpy, 0),
        "strstr" => (c_strstr, 0),
        "strchr" => (c_strchr, 0),
        "atoi" | "atol" => (c_atoi, 0),
        "_adjust_fdiv" => (ret0, 0),
        _ => (ret0, 0),
    }
}

fn nop(_g: &mut Guest, _c: &mut Cpu, _m: &mut Mem) {}

fn ret0(_g: &mut Guest, c: &mut Cpu, _m: &mut Mem) {
    ret(c, 0);
}

fn ret1(_g: &mut Guest, c: &mut Cpu, _m: &mut Mem) {
    ret(c, 1);
}

fn ret_m1(_g: &mut Guest, c: &mut Cpu, _m: &mut Mem) {
    ret(c, 0xffff_ffff);
}

// ---- KERNEL32: modules -----------------------------------------------------

fn k_load_library(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let name = gstring(m, arg(c, m, 0), 300);
    match g.mod_load(c, m, &name) {
        Some(k) => ret(c, g.pack.modules[k].base),
        None => {
            g.lasterr = 126;
            ret(c, 0);
        }
    }
}

fn k_get_proc_address(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let h = arg(c, m, 0);
    let p = arg(c, m, 1);
    let mut r = 0;
    if let Some(md) = g.pack.modules.iter().find(|x| x.base == h) {
        if p < 0x10000 {
            r = md.ordinals.iter().find(|o| o.0 as u32 == p).map_or(0, |o| o.1);
        } else {
            let n = gstring(m, p, 128);
            r = md.exports.iter().find(|e| e.0 == n).map_or(0, |e| e.1);
        }
    }
    if r == 0 {
        g.lasterr = 127;
    }
    ret(c, r);
}

// ---- KERNEL32: files ---------------------------------------------------------

fn k_create_file(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let path = gstring(m, arg(c, m, 0), 300);
    let access = arg(c, m, 1);
    let disp = arg(c, m, 4);
    let writing = access & 0x4000_0000 != 0 || matches!(disp, 1 | 2 | 4 | 5);
    if writing {
        let h = g.h_new(Handle::Sink);
        ret(c, h);
        return;
    }
    match g.vfs.open(&path) {
        Some(f) => {
            let h = g.h_new(Handle::File(f, path));
            ret(c, h);
        }
        None => {
            g.lasterr = 2;
            ret(c, 0xffff_ffff);
        }
    }
}

fn k_get_file_size(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let phigh = arg(c, m, 1);
    let h = arg(c, m, 0);
    let sz = match g.h_get(h) {
        Some(Handle::File(f, _)) => Some(f.len()),
        _ => None,
    };
    match sz {
        Some(sz) => {
            if phigh != 0 {
                m.w32(phigh, (sz >> 32) as u32);
            }
            ret(c, sz as u32);
        }
        None => ret(c, 0xffff_ffff),
    }
}

fn k_create_file_mapping(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let h = arg(c, m, 0);
    let path = match g.h_get(h) {
        Some(Handle::File(_, p)) => p.clone(),
        _ => {
            ret(c, 0);
            return;
        }
    };
    let h = g.h_new(Handle::Map(path));
    ret(c, h);
}

fn k_map_view(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let h = arg(c, m, 0);
    let off = arg(c, m, 3);
    let mut size = arg(c, m, 4);
    let path = match g.h_get(h) {
        Some(Handle::Map(p)) => p.clone(),
        _ => {
            ret(c, 0);
            return;
        }
    };
    if g.map_next == 0 {
        g.map_next = MAP_ARENA;
    }
    if let Some(v) = g.views.iter().find(|v| v.off == off && v.size == size && v.path == path) {
        ret(c, v.va);
        return;
    }
    let data = match g.vfs.read_range(&path, off as u64, if size == 0 { None } else { Some(size as u64) }) {
        Some(d) => d,
        None => {
            ret(c, 0);
            return;
        }
    };
    if size == 0 {
        size = data.len() as u32;
    }
    let va = g.map_next;
    if va as u64 + size as u64 > (MAP_ARENA + MAP_ARENA_SIZE) as u64 || g.views.len() >= 256 {
        eprintln!("[ssrs] mapping arena full ({path} +{size})");
        ret(c, 0);
        return;
    }
    // Each view is its own region at the address the oracle's arena would
    // give it, so only what is mapped is committed.
    let span = (size + 0xfff) & !0xfff;
    m.zeroed(va, span.max(0x1000));
    m.write(va, &data);
    g.map_next = (va + size + 0xffff) & !0xffff;
    g.views.push(View { path, off, size, va });
    ret(c, va);
}

fn write_find(m: &mut Mem, dst: u32, e: &crate::vfs::FindEntry) {
    let mut b = [0u8; 320];
    let attr: u32 = if e.dir { 0x10 } else { 0x20 };
    b[0..4].copy_from_slice(&attr.to_le_bytes());
    for (k, t) in e.times.iter().enumerate() {
        b[4 + 8 * k..12 + 8 * k].copy_from_slice(&t.to_le_bytes());
    }
    b[28..32].copy_from_slice(&((e.size >> 32) as u32).to_le_bytes());
    b[32..36].copy_from_slice(&(e.size as u32).to_le_bytes());
    let n = e.name.as_bytes();
    let k = n.len().min(259);
    b[44..44 + k].copy_from_slice(&n[..k]);
    m.write(dst, &b);
}

fn k_find_first(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let pat = gstring(m, arg(c, m, 0), 300);
    let mut ents = g.vfs.find(&pat);
    if ents.is_empty() {
        g.lasterr = 2;
        ret(c, 0xffff_ffff);
        return;
    }
    let first = ents.remove(0);
    let dst = arg(c, m, 1);
    write_find(m, dst, &first);
    let h = g.h_new(Handle::Find(ents.into_iter().rev().collect()));
    ret(c, h);
}

fn k_find_next(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let h = arg(c, m, 0);
    let dst = arg(c, m, 1);
    let next = match g.h_get_mut(h) {
        Some(Handle::Find(rest)) => rest.pop(),
        _ => None,
    };
    match next {
        Some(e) => {
            write_find(m, dst, &e);
            ret(c, 1);
        }
        None => {
            g.lasterr = 18;
            ret(c, 0);
        }
    }
}

fn k_find_close(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let h = arg(c, m, 0);
    if matches!(g.h_get(h), Some(Handle::Find(_))) {
        g.h_close(h);
    }
    ret(c, 1);
}

fn k_close_handle(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let h = arg(c, m, 0);
    g.h_close(h);
    ret(c, 1);
}

// ---- MSVCRT: stdio -------------------------------------------------------------

fn c_fopen(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let path = gstring(m, arg(c, m, 0), 300);
    let mode = gstr(m, arg(c, m, 1), 16);
    let s = if mode.iter().any(|b| b"wa+".contains(b)) {
        Some(Stream::Sink)
    } else {
        g.vfs.open(&path).map(Stream::File)
    };
    let s = match s {
        Some(s) => s,
        None => {
            ret(c, 0);
            return;
        }
    };
    for i in 0..g.streams.len() {
        if g.streams[i].is_none() {
            g.streams[i] = Some(s);
            if g.stream_va[i] == 0 {
                g.stream_va[i] = g.heap.alloc(m, 32, true);
            }
            ret(c, g.stream_va[i]);
            return;
        }
    }
    ret(c, 0);
}

fn c_fclose(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    if let Some(i) = g.stream_of(arg(c, m, 0)) {
        g.streams[i] = None;
    }
    ret(c, 0);
}

fn c_fread(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let (buf, sz, n) = (arg(c, m, 0), arg(c, m, 1), arg(c, m, 2));
    let i = match g.stream_of(arg(c, m, 3)) {
        Some(i) if sz != 0 && n != 0 => i,
        _ => {
            ret(c, 0);
            return;
        }
    };
    let items = match g.streams[i].as_mut() {
        Some(Stream::File(f)) => f.read_into(m, buf, sz as usize, n as usize),
        _ => 0,
    };
    ret(c, items as u32);
}

fn c_fwrite(_g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let n = arg(c, m, 2);
    ret(c, n);
}

fn c_fseek(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let off = arg(c, m, 1) as i32 as i64;
    let whence = arg(c, m, 2);
    let r = match g.stream_of(arg(c, m, 0)).and_then(|i| g.streams[i].as_mut()) {
        Some(Stream::File(f)) => {
            let pos = match whence {
                0 if off >= 0 => Some(SeekFrom::Start(off as u64)),
                0 => None,
                1 => Some(SeekFrom::Current(off)),
                2 => Some(SeekFrom::End(off)),
                _ => None,
            };
            match pos.map(|p| f.seek(p)) {
                Some(Ok(_)) => 0,
                _ => 0xffff_ffff,
            }
        }
        Some(Stream::Sink) => 0,
        None => 0xffff_ffff,
    };
    ret(c, r);
}

fn c_ftell(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let r = match g.stream_of(arg(c, m, 0)).and_then(|i| g.streams[i].as_mut()) {
        Some(Stream::File(f)) => f.stream_position().map(|p| p as u32).unwrap_or(0xffff_ffff),
        Some(Stream::Sink) => 0,
        None => 0xffff_ffff,
    };
    ret(c, r);
}

// ---- MSVCRT: strings and misc ----------------------------------------------------

fn c_sprintf(_g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let (dst, fmt) = (arg(c, m, 0), arg(c, m, 1));
    let n = format_guest(m, dst, fmt, c.r[ESP].wrapping_add(12));
    ret(c, n);
}

fn c_ftol(_g: &mut Guest, c: &mut Cpu, _m: &mut Mem) {
    c.ftol();
}

fn c_isctype(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let ch = arg(c, m, 0) as i32;
    let mask = arg(c, m, 1);
    let tab = m.r32(g.var_pctype);
    let v = if (-1..=255).contains(&ch) {
        m.r16(tab.wrapping_add((2 * ch) as u32)) as u32 & mask
    } else {
        0
    };
    ret(c, v);
}

fn c_tolower(_g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let ch = arg(c, m, 0) as i32;
    ret(c, if (b'A' as i32..=b'Z' as i32).contains(&ch) { (ch + 32) as u32 } else { ch as u32 });
}

fn c_time(_g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let p = arg(c, m, 0);
    let t = 0x4469_7751;
    if p != 0 {
        m.w32(p, t);
    }
    ret(c, t);
}

fn c_ctime(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    if g.ctime_buf == 0 {
        g.ctime_buf = g.heap.alloc(m, 32, true);
    }
    m.write(g.ctime_buf, b"Tue May 16 06:38:41 2006\n\0");
    ret(c, g.ctime_buf);
}

fn c_strncat(_g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let (d, s, n) = (arg(c, m, 0), arg(c, m, 1), arg(c, m, 2));
    let mut e = d;
    while m.r8(e) != 0 {
        e += 1;
    }
    let mut i = 0;
    while i < n {
        let ch = m.r8(s + i);
        if ch == 0 {
            break;
        }
        m.w8(e + i, ch);
        i += 1;
    }
    m.w8(e + i, 0);
    ret(c, d);
}

fn c_strpbrk(_g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let mut s = arg(c, m, 0);
    let set = gstr(m, arg(c, m, 1), 256);
    loop {
        let ch = m.r8(s);
        if ch == 0 {
            ret(c, 0);
            return;
        }
        if set.contains(&ch) {
            ret(c, s);
            return;
        }
        s += 1;
    }
}

fn c_strrchr(_g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let mut s = arg(c, m, 0);
    let want = arg(c, m, 1) as u8;
    let mut r = 0;
    loop {
        let ch = m.r8(s);
        if ch == want {
            r = s;
        }
        if ch == 0 {
            break;
        }
        s += 1;
    }
    ret(c, r);
}

/// C `strtoul` on a 32-bit `unsigned long`.
fn strtoul(b: &[u8], base: u32) -> (u32, usize) {
    let mut i = 0;
    while i < b.len() && matches!(b[i], b' ' | b'\t' | b'\n' | 0x0b | 0x0c | b'\r') {
        i += 1;
    }
    let mut neg = false;
    if i < b.len() && (b[i] == b'+' || b[i] == b'-') {
        neg = b[i] == b'-';
        i += 1;
    }
    let mut base = base;
    let hex_prefix = i + 1 < b.len() && b[i] == b'0' && (b[i + 1] | 0x20) == b'x';
    if (base == 0 || base == 16) && hex_prefix && i + 2 < b.len() && (b[i + 2] as char).is_ascii_hexdigit() {
        base = 16;
        i += 2;
    } else if base == 0 {
        base = if i < b.len() && b[i] == b'0' { 8 } else { 10 };
    }
    if !(2..=36).contains(&base) {
        return (0, 0);
    }
    let start = i;
    let mut v: u64 = 0;
    let mut over = false;
    while i < b.len() {
        let d = match b[i] {
            x @ b'0'..=b'9' => (x - b'0') as u32,
            x @ b'a'..=b'z' => (x - b'a' + 10) as u32,
            x @ b'A'..=b'Z' => (x - b'A' + 10) as u32,
            _ => break,
        };
        if d >= base {
            break;
        }
        v = v * base as u64 + d as u64;
        if v > u32::MAX as u64 {
            over = true;
            v = u32::MAX as u64;
        }
        i += 1;
    }
    if i == start {
        return (0, 0);
    }
    let r = if over {
        u32::MAX
    } else if neg {
        (v as u32).wrapping_neg()
    } else {
        v as u32
    };
    (r, i)
}

fn c_strtoul(_g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let s = arg(c, m, 0);
    let buf = gstr(m, s, 128);
    let (v, end) = strtoul(&buf, arg(c, m, 2));
    let endp = arg(c, m, 1);
    if endp != 0 {
        m.w32(endp, s + end as u32);
    }
    ret(c, v);
}

fn c_wcslen(_g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let s = arg(c, m, 0);
    let mut n = 0;
    while m.r16(s + 2 * n) != 0 {
        n += 1;
    }
    ret(c, n);
}

fn c_initterm(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let (first, last) = (arg(c, m, 0), arg(c, m, 1));
    let mut p = first;
    while p + 4 <= last {
        let f = m.r32(p);
        if f != 0 {
            g.call_nested(c, m, f);
        }
        p += 4;
    }
}

fn c_malloc(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let n = arg(c, m, 0);
    let p = g.heap.alloc(m, n, false);
    ret(c, p);
}

fn c_calloc(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let n = arg(c, m, 0).wrapping_mul(arg(c, m, 1));
    let p = g.heap.alloc(m, n, true);
    ret(c, p);
}

fn c_realloc(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let (p, n) = (arg(c, m, 0), arg(c, m, 1));
    let r = g.heap.realloc(m, p, n);
    ret(c, r);
}

fn c_free(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let p = arg(c, m, 0);
    g.heap.free(m, p);
}

fn c_memmove(_g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let (d, s, n) = (arg(c, m, 0), arg(c, m, 1), arg(c, m, 2));
    if n != 0 && m.mapped(d, n) && m.mapped(s, n) {
        let tmp = m.read(s, n as usize);
        m.write(d, &tmp);
    }
    ret(c, d);
}

fn c_strncmp(_g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let (a, b, n) = (arg(c, m, 0), arg(c, m, 1), arg(c, m, 2) as i32);
    for i in 0..n.max(0) as u32 {
        let (x, y) = (m.r8(a + i), m.r8(b + i));
        if x != y {
            ret(c, (x as i32 - y as i32) as u32);
            return;
        }
        if x == 0 {
            break;
        }
    }
    ret(c, 0);
}

fn c_strncpy(_g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let (d, s, n) = (arg(c, m, 0), arg(c, m, 1), arg(c, m, 2) as i32);
    let mut i = 0i32;
    while i < n {
        let ch = m.r8(s + i as u32);
        m.w8(d + i as u32, ch);
        if ch == 0 {
            i += 1;
            while i < n {
                m.w8(d + i as u32, 0);
                i += 1;
            }
            break;
        }
        i += 1;
    }
    ret(c, d);
}

fn c_strstr(_g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let (h, n) = (arg(c, m, 0), arg(c, m, 1));
    if m.r8(n) == 0 {
        ret(c, h);
        return;
    }
    let mut i = 0;
    while m.r8(h + i) != 0 {
        let mut j = 0;
        while m.r8(n + j) != 0 && m.r8(h + i + j) == m.r8(n + j) {
            j += 1;
        }
        if m.r8(n + j) == 0 {
            ret(c, h + i);
            return;
        }
        i += 1;
    }
    ret(c, 0);
}

fn c_strchr(_g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let s = arg(c, m, 0);
    let want = (arg(c, m, 1) & 0xff) as u8;
    let mut i = 0;
    loop {
        let ch = m.r8(s + i);
        if ch == want {
            ret(c, s + i);
            return;
        }
        if ch == 0 {
            break;
        }
        i += 1;
    }
    ret(c, 0);
}

/// MSVCRT `atoi` over the oracle's 64-byte copy.
fn c_atoi(_g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let b = gstr(m, arg(c, m, 0), 64);
    let mut i = 0;
    while i < b.len() && matches!(b[i], b' ' | b'\t' | b'\n' | 0x0b | 0x0c | b'\r') {
        i += 1;
    }
    let mut neg = false;
    if i < b.len() && (b[i] == b'+' || b[i] == b'-') {
        neg = b[i] == b'-';
        i += 1;
    }
    let mut v: i32 = 0;
    while i < b.len() && b[i].is_ascii_digit() {
        v = v.wrapping_mul(10).wrapping_add((b[i] - b'0') as i32);
        i += 1;
    }
    ret(c, if neg { v.wrapping_neg() } else { v } as u32);
}

/// The output callback registered with `ssft_ttsSetOutDevice`:
/// `cb(hinst, magic, ctx, msg*, appdata)`, as `rs_oracle.c`'s `out_cb`.
pub fn out_cb(g: &mut Guest, c: &mut Cpu, m: &mut Mem) {
    let msg = arg(c, m, 3);
    let kind = m.r32(msg);
    let od = m.r32(msg + 8);
    if kind < 0x200 {
        g.msgs[kind as usize] += 1;
    }
    if kind == 0x10 && od != 0 && m.r32(od + 8) != 0 && m.r32(od + 4) != 0 {
        let (pcm, n) = (m.r32(od + 8), m.r32(od + 4));
        let bytes = m.read(pcm, n as usize);
        g.pcm.extend_from_slice(&bytes);
    } else if kind == 8 && od != 0 {
        m.w32(od + 4, crate::OUTBUF_BYTES);
        m.w32(od + 8, g.buf_va);
        m.w32(od + 12, 0);
        m.w32(od + 16, 0);
    }
    c.r[EAX] = 0;
    let _ = EDX;
}

#[cfg(test)]
mod tests {
    use super::strtoul;

    #[test]
    fn strtoul_c() {
        assert_eq!(strtoul(b"  42xyz", 10), (42, 4));
        assert_eq!(strtoul(b"0x1F", 0), (31, 4));
        assert_eq!(strtoul(b"017", 0), (15, 3));
        assert_eq!(strtoul(b"-1", 10), (0xffff_ffff, 2));
        assert_eq!(strtoul(b"99999999999", 10), (0xffff_ffff, 11));
        assert_eq!(strtoul(b"zz", 10), (0, 0));
    }
}
