//! The guest's view of the file system. The engine is told its speech
//! directory is [`VIRTUAL_ROOT`], whatever the host OS. Paths under it come
//! from one of two places:
//!
//! - **Disk**: the user's install, matched one component at a time ignoring
//!   case, so a Windows install copied to Linux or macOS works as it is.
//! - **Built in**: files compiled into the binary (`ss-rs-ng-voice`), keyed by
//!   their path relative to the speech directory, lower-cased.
//!
//! Every open and every directory search is recorded, which is how the list
//! of files a voice needs (`xlate/<pack>_files.txt`) is made.

use ss_rs_ng_xrt::Mem;
use std::borrow::Cow;
use std::cell::RefCell;
use std::io::{Cursor, Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

pub const VIRTUAL_ROOT: &str = "C:\\ssrsng\\speech";

/// `(path relative to the speech directory, lower-case, '/'-separated; bytes)`.
pub type Tree = &'static [(&'static str, &'static [u8])];

pub enum Backend {
    Disk(PathBuf),
    BuiltIn(Tree),
}

pub struct Vfs {
    backend: Backend,
    pub log: RefCell<Vec<String>>,
}

pub struct FindEntry {
    pub name: String,
    pub dir: bool,
    pub size: u64,
    /// Windows FILETIMEs: creation, last access, last write.
    pub times: [u64; 3],
}

pub enum VFile {
    Disk(std::fs::File),
    Mem(Cursor<&'static [u8]>),
}

impl VFile {
    pub fn len(&self) -> u64 {
        match self {
            VFile::Disk(f) => f.metadata().map(|m| m.len()).unwrap_or(0),
            VFile::Mem(c) => c.get_ref().len() as u64,
        }
    }

    /// `fread`: up to `n` items of `unit` bytes from the file position
    /// straight into guest memory at `dst`. Only whole items reach the
    /// guest, but a partial last item is still consumed. The items read.
    pub fn read_into(&mut self, m: &mut Mem, dst: u32, unit: usize, n: usize) -> usize {
        match self {
            VFile::Mem(c) => {
                let data: &'static [u8] = c.get_ref();
                let at = (c.position() as usize).min(data.len());
                let got = (unit * n).min(data.len() - at);
                let items = got / unit;
                prefetch(&data[at..at + items * unit]);
                m.write(dst, &data[at..at + items * unit]);
                c.set_position((at + got) as u64);
                items
            }
            VFile::Disk(f) => {
                // Chunks of whole items, each filled before it is written,
                // so only the last one can end mid-item.
                let want = unit * n;
                let chunk = ((1 << 20) / unit).max(1) * unit;
                let mut buf = vec![0u8; want.min(chunk)];
                let mut done = 0;
                while done < want {
                    let k = (want - done).min(buf.len());
                    let mut fill = 0;
                    while fill < k {
                        match f.read(&mut buf[fill..k]) {
                            Ok(0) | Err(_) => break,
                            Ok(r) => fill += r,
                        }
                    }
                    let whole = fill / unit * unit;
                    m.write(dst + done as u32, &buf[..whole]);
                    done += fill;
                    if fill < k {
                        break;
                    }
                }
                done / unit
            }
        }
    }
}

impl Read for VFile {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        match self {
            VFile::Disk(f) => f.read(buf),
            VFile::Mem(c) => c.read(buf),
        }
    }
}

impl Seek for VFile {
    fn seek(&mut self, pos: SeekFrom) -> std::io::Result<u64> {
        match self {
            VFile::Disk(f) => f.seek(pos),
            VFile::Mem(c) => c.seek(pos),
        }
    }
}

/// Ask the OS to read a built-in range in now, as a few large reads, before
/// it is copied. Copying a range that is not resident otherwise pages it in
/// one fault at a time; for the engine's 19-37 MB lexicon that is most of
/// a cold start.
pub fn prefetch(b: &[u8]) {
    if b.len() < (256 << 10) {
        return;
    }
    sys::prefetch(b.as_ptr(), b.len());
}

#[cfg(windows)]
mod sys {
    #[repr(C)]
    struct Range {
        at: *const u8,
        size: usize,
    }

    type Prefetch = unsafe extern "system" fn(isize, usize, *const Range, u32) -> i32;

    extern "system" {
        fn GetCurrentProcess() -> isize;
        fn GetModuleHandleA(name: *const u8) -> isize;
        fn GetProcAddress(module: isize, name: *const u8) -> Option<Prefetch>;
    }

    // Windows 8 and later; looked up so the binary still loads on 7.
    pub fn prefetch(at: *const u8, size: usize) {
        let r = Range { at, size };
        unsafe {
            let k32 = GetModuleHandleA(b"kernel32.dll\0".as_ptr());
            if let Some(f) = GetProcAddress(k32, b"PrefetchVirtualMemory\0".as_ptr()) {
                f(GetCurrentProcess(), 1, &r, 0);
            }
        }
    }
}

#[cfg(unix)]
mod sys {
    extern "C" {
        fn madvise(at: *mut u8, size: usize, advice: i32) -> i32;
    }

    const MADV_WILLNEED: i32 = 3;

    pub fn prefetch(at: *const u8, size: usize) {
        // madvise wants a page-aligned start; 64 KB is a multiple of every
        // page size in use.
        let lo = at as usize & !0xffff;
        unsafe {
            madvise(lo as *mut u8, size + (at as usize - lo), MADV_WILLNEED);
        }
    }
}

#[cfg(not(any(windows, unix)))]
mod sys {
    pub fn prefetch(_at: *const u8, _size: usize) {}
}

fn filetime(t: std::io::Result<std::time::SystemTime>) -> u64 {
    match t.ok().and_then(|t| t.duration_since(UNIX_EPOCH).ok()) {
        Some(d) => (d.as_secs() + 11_644_473_600) * 10_000_000 + (d.subsec_nanos() / 100) as u64,
        None => 0,
    }
}

/// Windows `*`/`?` matching, ignoring ASCII case.
fn wild(name: &[u8], pat: &[u8]) -> bool {
    match pat.first() {
        None => name.is_empty(),
        Some(b'*') => (0..=name.len()).any(|k| wild(&name[k..], &pat[1..])),
        Some(b'?') => !name.is_empty() && wild(&name[1..], &pat[1..]),
        Some(&c) => {
            !name.is_empty() && name[0].eq_ignore_ascii_case(&c) && wild(&name[1..], &pat[1..])
        }
    }
}

/// A guest path under the virtual root as `a/b/c`, lower-cased; None if it
/// is not under the root.
pub fn relative(guest: &str) -> Option<String> {
    let g = guest.replace('/', "\\");
    let root = VIRTUAL_ROOT.to_ascii_lowercase();
    let lower = g.to_ascii_lowercase();
    if !lower.starts_with(&root) {
        return None;
    }
    let mut parts: Vec<&str> = Vec::new();
    for comp in lower[root.len()..].split('\\') {
        match comp {
            "" | "." => {}
            ".." => {
                parts.pop();
            }
            c => parts.push(c),
        }
    }
    Some(parts.join("/"))
}

impl Vfs {
    pub fn new(backend: Backend) -> Vfs {
        Vfs {
            backend,
            log: RefCell::new(Vec::new()),
        }
    }

    fn note(&self, what: &str, guest: &str) {
        if let Some(r) = relative(guest) {
            self.log.borrow_mut().push(format!("{what} {r}"));
        }
    }

    /// The host path for a guest path on the disk backend. Paths outside
    /// the virtual root are taken as host paths.
    fn resolve(&self, real: &Path, guest: &str) -> PathBuf {
        let rel = match relative(guest) {
            Some(r) => r,
            None => return PathBuf::from(guest),
        };
        let mut p = real.to_path_buf();
        for comp in rel.split('/').filter(|c| !c.is_empty()) {
            let exact = p.join(comp);
            if exact.exists() {
                p = exact;
                continue;
            }
            let found = std::fs::read_dir(&p).ok().and_then(|rd| {
                rd.filter_map(|e| e.ok())
                    .find(|e| e.file_name().to_string_lossy().eq_ignore_ascii_case(comp))
                    .map(|e| e.path())
            });
            p = found.unwrap_or(exact);
        }
        p
    }

    pub fn open(&self, guest: &str) -> Option<VFile> {
        self.note("open", guest);
        match &self.backend {
            Backend::Disk(real) => std::fs::File::open(self.resolve(real, guest)).ok().map(VFile::Disk),
            Backend::BuiltIn(tree) => {
                let rel = relative(guest)?;
                tree.iter().find(|e| e.0 == rel).map(|e| VFile::Mem(Cursor::new(e.1)))
            }
        }
    }

    /// `size` bytes from `off`, or to the end when `size` is None.
    /// Built-in files are borrowed, not copied.
    pub fn read_range(&self, guest: &str, off: u64, size: Option<u64>) -> Option<Cow<'static, [u8]>> {
        let mut f = self.open(guest)?;
        let len = f.len();
        let lo = off.min(len);
        let hi = match size {
            Some(s) => (off + s).min(len),
            None => len,
        };
        if let VFile::Mem(c) = &f {
            let b = &c.get_ref()[lo as usize..hi as usize];
            prefetch(b);
            return Some(Cow::Borrowed(b));
        }
        f.seek(SeekFrom::Start(lo)).ok()?;
        let mut v = vec![0u8; (hi - lo) as usize];
        f.read_exact(&mut v).ok()?;
        Some(Cow::Owned(v))
    }

    pub fn is_builtin(&self) -> bool {
        matches!(self.backend, Backend::BuiltIn(_))
    }

    /// `FindFirstFileA` over a pattern: entries in NTFS order (upper-cased
    /// ordinal), with `.` and `..` first where the pattern matches them.
    pub fn find(&self, pattern: &str) -> Vec<FindEntry> {
        self.note("find", pattern);
        let g = pattern.replace('/', "\\");
        let (dir, pat) = match g.rfind('\\') {
            Some(k) => (&g[..k], &g[k + 1..]),
            None => ("", g.as_str()),
        };
        let mut out = Vec::new();
        let mut ents: Vec<FindEntry> = match &self.backend {
            Backend::Disk(real) => {
                let rd = match std::fs::read_dir(self.resolve(real, dir)) {
                    Ok(rd) => rd,
                    Err(_) => return out,
                };
                rd.filter_map(|e| e.ok())
                    .filter_map(|e| {
                        let name = e.file_name().to_string_lossy().into_owned();
                        if !wild(name.as_bytes(), pat.as_bytes()) {
                            return None;
                        }
                        let md = e.metadata().ok()?;
                        Some(FindEntry {
                            name,
                            dir: md.is_dir(),
                            size: if md.is_dir() { 0 } else { md.len() },
                            times: [filetime(md.created()), filetime(md.accessed()), filetime(md.modified())],
                        })
                    })
                    .collect()
            }
            Backend::BuiltIn(tree) => {
                let base = match relative(dir) {
                    Some(b) => b,
                    None => return out,
                };
                let prefix = if base.is_empty() { String::new() } else { format!("{base}/") };
                let mut names: Vec<(String, bool, u64)> = Vec::new();
                for (path, bytes) in tree.iter() {
                    let rest = match path.strip_prefix(&prefix) {
                        Some(r) => r,
                        None => continue,
                    };
                    let (name, dir) = match rest.split_once('/') {
                        Some((d, _)) => (d, true),
                        None => (rest, false),
                    };
                    if wild(name.as_bytes(), pat.as_bytes()) && !names.iter().any(|n| n.0 == name) {
                        names.push((name.to_string(), dir, if dir { 0 } else { bytes.len() as u64 }));
                    }
                }
                names
                    .into_iter()
                    .map(|(name, dir, size)| FindEntry { name, dir, size, times: [0; 3] })
                    .collect()
            }
        };
        if wild(b".", pat.as_bytes()) {
            for n in [".", ".."] {
                out.push(FindEntry {
                    name: n.into(),
                    dir: true,
                    size: 0,
                    times: [0; 3],
                });
            }
        }
        ents.sort_by(|a, b| a.name.to_ascii_uppercase().cmp(&b.name.to_ascii_uppercase()));
        out.extend(ents);
        out
    }
}

/// A built-in tree loaded at run time from a disk install: every `open`
/// line of a `xlate/<pack>_files.txt` list. What `ss-rs-ng-voice` bakes in at
/// build time, for testing the built-in backend without a rebuild.
pub fn tree_from_list(speech: &Path, list: &str) -> Result<Tree, String> {
    let disk = Vfs::new(Backend::Disk(speech.to_path_buf()));
    let mut out: Vec<(&'static str, &'static [u8])> = Vec::new();
    for rel in list.lines().filter_map(|l| l.strip_prefix("open ")) {
        let guest = format!("{VIRTUAL_ROOT}\\{}", rel.replace('/', "\\"));
        let bytes = disk.read_range(&guest, 0, None).ok_or(format!("{rel}: not in {}", speech.display()))?;
        out.push((Box::leak(rel.to_string().into_boxed_str()), Box::leak(bytes.into_owned().into_boxed_slice())));
    }
    Ok(Box::leak(out.into_boxed_slice()))
}

#[cfg(test)]
mod tests {
    use super::{relative, wild};

    #[test]
    fn wildcards() {
        assert!(wild(b"tts_enu.hdr", b"*.hdr"));
        assert!(wild(b"TTS_ENU.HDR", b"*.hdr"));
        assert!(!wild(b"tts_enu.dll", b"*.hdr"));
        assert!(wild(b"a.b", b"*.*"));
        assert!(wild(b"abc", b"a?c"));
    }

    #[test]
    fn relative_paths() {
        assert_eq!(relative("C:\\ssrsng\\speech\\Components\\common\\X.dll").unwrap(), "components/common/x.dll");
        assert_eq!(relative("c:/ssrsng/speech/a/../b").unwrap(), "b");
        assert!(relative("D:\\other").is_none());
    }
}
