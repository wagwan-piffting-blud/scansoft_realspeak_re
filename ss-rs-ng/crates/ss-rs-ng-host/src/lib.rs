//! The host the translated engine runs on: guest memory laid out as the
//! oracle lays it out (`oracle/emu/emu.h`), the vendor DLLs mapped in as data,
//! the system imports, and the `rssoloapi` call sequence of
//! `oracle/emu/rs_oracle.c`. No vendor code runs except as translated Rust.

pub mod fmt;
pub mod heap;
pub mod pe;
pub mod sha256;
pub mod shims;
pub mod vfs;

use heap::Heap;
use ss_rs_ng_eng::Pack;
use ss_rs_ng_xrt::{Cpu, Host, Mem, EAX, ESP, THUNK_BASE};

use vfs::{Backend, FindEntry, VFile, Vfs, VIRTUAL_ROOT};

pub const STACK_TOP: u32 = 0xC080_0000;
pub const STACK_SIZE: u32 = 0x0070_0000;
pub const STACK_ESP0: u32 = STACK_TOP - 0x0020_0000;
pub const AUX_BASE: u32 = 0x6000_0000;
pub const TEB_BASE: u32 = 0x7ffd_e000;
pub const PEB_BASE: u32 = 0x7ffd_f000;
pub const MAP_ARENA: u32 = 0x6200_0000;
pub const MAP_ARENA_SIZE: u32 = 0x0d00_0000;
pub const MODULE_BASE0: u32 = 0x1000_0000;
pub const RET_SENTINEL: u32 = 0xdead_beef;
pub const OUTBUF_BYTES: u32 = 8192;
const THUNK_SPAN: u32 = 1024 * 16;
const HBASE: u32 = 0x00a0_0000;
const NHANDLES: usize = 512;

pub enum Handle {
    Free,
    File(VFile, String),
    Sink,
    Map(String),
    Find(Vec<FindEntry>),
}

pub enum Stream {
    File(VFile),
    Sink,
}

pub struct View {
    pub path: String,
    pub off: u32,
    pub size: u32,
    pub va: u32,
}

/// Everything the oracle's host keeps outside guest memory.
pub struct Guest {
    pub pack: &'static Pack,
    pub heap: Heap,
    pub vfs: Vfs,
    loaded: Vec<bool>,
    shims: Vec<(shims::Shim, u32)>,
    handles: Vec<Handle>,
    pub views: Vec<View>,
    pub map_next: u32,
    pub streams: Vec<Option<Stream>>,
    pub stream_va: Vec<u32>,
    pub lasterr: u32,
    pub var_pctype: u32,
    var_mb_cur_max: u32,
    var_iob: u32,
    pub ctime_buf: u32,
    pub pcm: Vec<u8>,
    pub buf_va: u32,
    pub msgs: Vec<u32>,
}

impl Host for Guest {
    fn import(&mut self, k: u32, c: &mut Cpu, m: &mut Mem) {
        let (f, argb) = if (k as usize) < self.shims.len() {
            self.shims[k as usize]
        } else if k as usize == self.shims.len() {
            (shims::out_cb as shims::Shim, 0)
        } else {
            panic!("host thunk {k} was never registered");
        };
        f(self, c, m);
        c.ret(m, argb);
    }
}

impl Guest {
    fn new(pack: &'static Pack, backend: Backend, heap: Heap) -> Guest {
        let shims = pack.imports.iter().map(|(_, n)| shims::lookup(n)).collect();
        let mut handles = Vec::with_capacity(NHANDLES);
        handles.resize_with(NHANDLES, || Handle::Free);
        Guest {
            pack,
            heap,
            vfs: Vfs::new(backend),
            loaded: vec![false; pack.modules.len()],
            shims,
            handles,
            views: Vec::new(),
            map_next: 0,
            streams: (0..64).map(|_| None).collect(),
            stream_va: vec![0; 64],
            lasterr: 0,
            var_pctype: 0,
            var_mb_cur_max: 0,
            var_iob: 0,
            ctime_buf: 0,
            pcm: Vec::new(),
            buf_va: 0,
            msgs: vec![0; 0x200],
        }
    }

    pub fn h_new(&mut self, h: Handle) -> u32 {
        for i in 1..NHANDLES {
            if matches!(self.handles[i], Handle::Free) {
                self.handles[i] = h;
                return HBASE + 4 * i as u32;
            }
        }
        0
    }

    fn slot(h: u32) -> Option<usize> {
        if h < HBASE || h >= HBASE + 4 * NHANDLES as u32 || h & 3 != 0 {
            None
        } else {
            Some(((h - HBASE) / 4) as usize)
        }
    }

    pub fn h_get(&self, h: u32) -> Option<&Handle> {
        Self::slot(h).map(|i| &self.handles[i]).filter(|x| !matches!(x, Handle::Free))
    }

    pub fn h_get_mut(&mut self, h: u32) -> Option<&mut Handle> {
        Self::slot(h).map(|i| &mut self.handles[i]).filter(|x| !matches!(x, Handle::Free))
    }

    pub fn h_close(&mut self, h: u32) {
        if let Some(i) = Self::slot(h) {
            self.handles[i] = Handle::Free;
        }
    }

    pub fn stream_of(&self, va: u32) -> Option<usize> {
        (0..self.streams.len()).find(|&i| self.stream_va[i] == va && self.streams[i].is_some())
    }

    /// `call_nested_args`: a call into the guest from the host, with the CPU
    /// saved around it, as the oracle makes every API call and DllMain.
    pub fn call_nested_args(&mut self, c: &mut Cpu, m: &mut Mem, f: u32, args: &[u32]) -> u32 {
        let save = c.clone();
        if c.r[ESP] == 0 {
            c.r[ESP] = STACK_ESP0;
        }
        c.r[ESP] = c.r[ESP].wrapping_sub(64);
        for &a in args.iter().rev() {
            c.push32(m, a);
        }
        c.push32(m, RET_SENTINEL);
        (self.pack.enter)(c, m, self, f);
        if c.ret_to != RET_SENTINEL {
            panic!("guest call 0x{f:08x} returned to 0x{:08x}", c.ret_to);
        }
        let eax = c.r[EAX];
        *c = save;
        eax
    }

    /// `call_nested` (the `_initterm` form): no argument area, no arguments.
    pub fn call_nested(&mut self, c: &mut Cpu, m: &mut Mem, f: u32) {
        let save = c.clone();
        c.push32(m, RET_SENTINEL);
        (self.pack.enter)(c, m, self, f);
        if c.ret_to != RET_SENTINEL {
            panic!("initterm call 0x{f:08x} returned to 0x{:08x}", c.ret_to);
        }
        *c = save;
    }

    /// `mod_load`: map a module by its file name, load what it imports,
    /// bind its IAT, run its DllMain. Returns its index in the pack.
    pub fn mod_load(&mut self, c: &mut Cpu, m: &mut Mem, name: &str) -> Option<usize> {
        let base = name.rsplit(['\\', '/']).next().unwrap_or(name).to_ascii_lowercase();
        let stem = base.strip_suffix(".dll").unwrap_or(&base);
        let k = self.pack.modules.iter().position(|x| x.name == stem)?;
        if self.loaded[k] {
            return Some(k);
        }
        let md = &self.pack.modules[k];
        let guest_path = format!("{VIRTUAL_ROOT}\\{}", md.file.replace('/', "\\"));
        let file = match self.vfs.read_range(&guest_path, 0, None) {
            Some(f) => f,
            None => {
                eprintln!("[modules] cannot read {}", md.file);
                return None;
            }
        };
        let sum = sha256::hex(&file);
        if sum != md.sha256 {
            panic!(
                "{} is not the file this build was translated from (sha256 {sum}, want {})",
                md.file, md.sha256
            );
        }
        self.loaded[k] = true;
        let img = pe::map(m, &file, md.base).unwrap_or_else(|e| panic!("{}: {e}", md.file));
        for &(_, v) in md.iat {
            if let Some(dep) = self.pack.modules.iter().position(|x| v >= x.base && v < x.base + x.size) {
                if !self.loaded[dep] {
                    let f = self.pack.modules[dep].file;
                    let dep_name = f.rsplit('/').next().unwrap();
                    self.mod_load(c, m, dep_name)?;
                }
            }
        }
        for &(slot, v) in md.iat {
            let mut val = v;
            if (THUNK_BASE..THUNK_BASE + THUNK_SPAN).contains(&v) {
                match self.pack.imports[((v - THUNK_BASE) / 16) as usize].1 {
                    "_pctype" => val = self.var_pctype,
                    "__mb_cur_max" => val = self.var_mb_cur_max,
                    "_iob" => val = self.var_iob,
                    _ => {}
                }
            }
            m.w32(slot, val);
        }
        if img.entry_rva != 0 {
            let ok = self.call_nested_args(c, m, md.base + img.entry_rva, &[md.base, 1, 0]);
            if ok == 0 {
                eprintln!("[modules] DllMain({}) returned FALSE", md.name);
            }
        }
        Some(k)
    }

    fn gstrdup(&mut self, m: &mut Mem, s: &[u8]) -> u32 {
        let va = self.heap.alloc(m, s.len() as u32 + 1, true);
        let mut b = s.to_vec();
        b.push(0);
        m.write(va, &b);
        va
    }
}

/// The C locale `_ctype` table and the data imports, as `build_data_vars`.
fn build_data_vars(g: &mut Guest, m: &mut Mem) {
    let tab = g.heap.alloc(m, 2 * 257 + 16, true);
    for ch in 0..256u32 {
        let mut f: u16 = 0;
        if ch < 0x80 {
            let b = ch as u8;
            if b.is_ascii_uppercase() {
                f |= 0x101;
            }
            if b.is_ascii_lowercase() {
                f |= 0x102;
            }
            if b.is_ascii_digit() {
                f |= 0x4;
            }
            if b == b' ' || (9..=13).contains(&b) {
                f |= 0x8;
            }
            if b.is_ascii_punctuation() {
                f |= 0x10;
            }
            if b < 0x20 || b == 0x7f {
                f |= 0x20;
            }
            if b == b' ' {
                f |= 0x40;
            }
            if b.is_ascii_hexdigit() {
                f |= 0x80;
            }
        }
        if ch == 9 {
            f |= 0x40;
        }
        m.w16(tab + 2 + 2 * ch, f);
    }
    g.var_pctype = g.heap.alloc(m, 4, true);
    m.w32(g.var_pctype, tab + 2);
    g.var_mb_cur_max = g.heap.alloc(m, 4, true);
    m.w32(g.var_mb_cur_max, 1);
    g.var_iob = g.heap.alloc(m, 0x60, true);
}

/// Parameters for one rendering, as `rs_oracle.exe`'s command line.
pub struct Request<'a> {
    pub voice: &'a str,
    pub text: &'a [u8],
    pub product: &'a str,
    pub khz: u32,
    pub extra: &'a [(u32, u16)],
}

pub struct Output {
    pub pcm: Vec<u8>,
    pub rate: u32,
    pub msgs: Vec<(u32, u32)>,
}

/// A running engine: one `rssoloapi` instance, opened as `rs_oracle.exe`
/// opens it, then any number of utterances. Deep guest recursion is Rust
/// recursion, so open and use it on a thread with a large stack
/// ([`ENGINE_STACK`]).
pub struct Engine {
    m: Mem,
    c: Cpu,
    g: Guest,
    h: (u32, u32),
    set_text: u32,
    process: u32,
    pub rate: u32,
}

pub const ENGINE_STACK: usize = 512 << 20;

impl Engine {
    pub fn open(pack: &'static Pack, backend: Backend, req: &Request) -> Result<Engine, String> {
        let mut m = Mem::new();
        let mut c = Cpu::default();
        // win32_init
        let heap = Heap::init(&mut m);
        let mut g = Guest::new(pack, backend, heap);
        m.zeroed(AUX_BASE, 0x1000);
        // mod_env_init
        m.zeroed(STACK_TOP - STACK_SIZE, STACK_SIZE);
        m.zeroed(THUNK_BASE, THUNK_SPAN);
        m.zeroed(TEB_BASE, 0x1000);
        m.zeroed(PEB_BASE, 0x1000);
        m.w32(TEB_BASE, 0xffff_ffff);
        m.w32(TEB_BASE + 0x04, STACK_TOP);
        m.w32(TEB_BASE + 0x08, STACK_TOP - STACK_SIZE);
        m.w32(TEB_BASE + 0x18, TEB_BASE);
        m.w32(TEB_BASE + 0x20, 0x1000);
        m.w32(TEB_BASE + 0x24, 0x2000);
        m.w32(TEB_BASE + 0x30, PEB_BASE);
        m.w32(PEB_BASE + 0x08, MODULE_BASE0);
        c.fs_base = TEB_BASE;
        c.r[ESP] = STACK_ESP0;
        build_data_vars(&mut g, &mut m);

        let api = format!("{VIRTUAL_ROOT}\\components\\common\\rssoloapi.dll");
        let k = g.mod_load(&mut c, &mut m, &api).ok_or("cannot load rssoloapi.dll")?;
        let exports = pack.modules[k].exports;
        let export = |n: &str| exports.iter().find(|e| e.0 == n).map(|e| e.1).ok_or(format!("no export {n}"));

        let hcls = g.heap.alloc(&mut m, 8, true);
        let hinst = g.heap.alloc(&mut m, 8, true);
        let sp = g.gstrdup(&mut m, VIRTUAL_ROOT.as_bytes());
        let r = g.call_nested_args(&mut c, &mut m, export("ssft_ttsInitialize")?, &[sp, hcls]);
        if r != 0 {
            return Err(format!("ssft_ttsInitialize -> {r:08x}"));
        }
        let prod = g.gstrdup(&mut m, req.product.as_bytes());
        let (c0, c1) = (m.r32(hcls), m.r32(hcls + 4));
        let r = g.call_nested_args(&mut c, &mut m, export("ssft_ttsOpen")?, &[c0, c1, prod, hinst, 0]);
        if r != 0 {
            return Err(format!("ssft_ttsOpen -> {r:08x}"));
        }
        let (h0, h1) = (m.r32(hinst), m.r32(hinst + 4));

        let params = g.heap.alloc(&mut m, 16 * 0x84, true);
        m.w32(params, 0x40);
        m.write(params + 4, b"American English\0");
        m.w32(params + 0x84, 0x80);
        let mut v = req.voice.as_bytes().to_vec();
        v.push(0);
        m.write(params + 0x84 + 4, &v);
        m.w32(params + 2 * 0x84, 0x01);
        m.w16(params + 2 * 0x84 + 4, req.khz as u16);
        let mut np = 3u32;
        for &(id, val) in req.extra.iter().take(13) {
            m.w32(params + np * 0x84, id);
            m.w16(params + np * 0x84 + 4, val);
            np += 1;
        }
        let r = g.call_nested_args(&mut c, &mut m, export("ssft_ttsSetParamList")?, &[h0, h1, params, np]);
        if r != 0 {
            return Err(format!("ssft_ttsSetParamList -> {r:08x}"));
        }

        g.buf_va = g.heap.alloc(&mut m, OUTBUF_BYTES, true);
        let dev = g.heap.alloc(&mut m, 8, true);
        m.w32(dev, 0);
        m.w32(dev + 4, THUNK_BASE + 16 * pack.imports.len() as u32);
        let r = g.call_nested_args(&mut c, &mut m, export("ssft_ttsSetOutDevice")?, &[h0, h1, dev]);
        if r != 0 {
            return Err(format!("ssft_ttsSetOutDevice -> {r:08x}"));
        }
        let rate = match req.khz {
            22 => 22050,
            11 => 11025,
            k => k * 1000,
        };
        Ok(Engine {
            set_text: export("ssft_ttsSetText")?,
            process: export("ssft_ttsProcess")?,
            m,
            c,
            g,
            h: (h0, h1),
            rate,
        })
    }

    /// One utterance: `ssft_ttsSetText`, then `ssft_ttsProcess`, which is
    /// synchronous. Returns its 16-bit mono PCM.
    pub fn say(&mut self, text: &[u8]) -> Result<Vec<u8>, String> {
        let (m, c, g) = (&mut self.m, &mut self.c, &mut self.g);
        let trec = g.heap.alloc(m, 12, true);
        let tva = g.heap.alloc(m, text.len() as u32 + 1, true);
        let mut t = text.to_vec();
        t.push(0);
        m.write(tva, &t);
        m.w32(trec, 0);
        m.w32(trec + 4, text.len() as u32);
        m.w32(trec + 8, tva);
        g.pcm.clear();
        let r = g.call_nested_args(c, m, self.set_text, &[self.h.0, self.h.1, trec]);
        if r != 0 {
            return Err(format!("ssft_ttsSetText -> {r:08x}"));
        }
        let r = g.call_nested_args(c, m, self.process, &[self.h.0, self.h.1, 0]);
        if r != 0 {
            return Err(format!("ssft_ttsProcess -> {r:08x}"));
        }
        g.heap.free(m, tva);
        g.heap.free(m, trec);
        Ok(std::mem::take(&mut g.pcm))
    }

    /// Every file the engine has opened or searched for, relative to the
    /// speech directory: `open <path>` and `find <pattern>`.
    pub fn file_log(&self) -> Vec<String> {
        self.g.vfs.log.borrow().clone()
    }

    pub fn msgs(&self) -> Vec<(u32, u32)> {
        self.g.msgs.iter().enumerate().filter(|x| *x.1 != 0).map(|(k, n)| (k as u32, *n)).collect()
    }
}

/// One request from a fresh engine, exactly as one `rs_oracle.exe` run.
pub fn render(pack: &'static Pack, backend: Backend, req: &Request) -> Result<Output, String> {
    let mut e = Engine::open(pack, backend, req)?;
    let pcm = e.say(req.text)?;
    Ok(Output { pcm, rate: e.rate, msgs: e.msgs() })
}

pub fn wav(pcm: &[u8], rate: u32) -> Vec<u8> {
    let mut w = Vec::with_capacity(44 + pcm.len());
    w.extend_from_slice(b"RIFF");
    w.extend_from_slice(&(36 + pcm.len() as u32).to_le_bytes());
    w.extend_from_slice(b"WAVEfmt ");
    w.extend_from_slice(&16u32.to_le_bytes());
    w.extend_from_slice(&1u16.to_le_bytes());
    w.extend_from_slice(&1u16.to_le_bytes());
    w.extend_from_slice(&rate.to_le_bytes());
    w.extend_from_slice(&(rate * 2).to_le_bytes());
    w.extend_from_slice(&2u16.to_le_bytes());
    w.extend_from_slice(&16u16.to_le_bytes());
    w.extend_from_slice(b"data");
    w.extend_from_slice(&(pcm.len() as u32).to_le_bytes());
    w.extend_from_slice(pcm);
    w
}
