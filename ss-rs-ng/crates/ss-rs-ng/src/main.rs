//! `ss-rs-ng`: the ScanSoft 2004 and RealSpeak Solo v4 2006 engines as one
//! native binary. The vendor code is translated x86 -> Rust; no DLL is run.
//! Output is byte-identical to the original engine.
//!
//! ```text
//! ss-rs-ng --version realspeak "Hello there." hello.wav
//! ss-rs-ng "Hello there." -o hello.wav --speech "C:\Program Files\ScanSoft\RealSpeak Solo v4\speech"
//! ss-rs-ng --file script.txt out.wav
//! ss-rs-ng --serve < requests.tsv
//! ```

use ss_rs_ng_eng::Pack;
use ss_rs_ng_host::vfs::{Backend, Tree};
use ss_rs_ng_host::{sha256, wav, Engine, Request, ENGINE_STACK};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::ExitCode;

const USAGE: &str = "\
ss-rs-ng - ScanSoft 2004 / RealSpeak Solo v4 2006 Tom, natively

USAGE:
    ss-rs-ng [options] \"text\" [out.wav]
    ss-rs-ng [options] --file <path>|- [out.wav]
    ss-rs-ng [options] --serve

OPTIONS:
    -o, --out <path>          WAV output, also the last positional; `-` is
                              standard output                        [speech.wav]
    -f, --file <path>         Read the text from a file; `-` is standard input
        --speech <dir>        The install's `speech` directory (the one holding
                              `components`); not needed if the voice is built in
        --version <pack>      scansoft | realspeak. Otherwise the pack is told
                              from the voicefont DLL in --speech, or is the one
                              built in
        --volume <0-100>      Default: what the installed SAPI voice uses
                              (realspeak 100, scansoft 60)
        --speed <n>           Speaking rate, 100 = normal (the engine's \\rate=)
        --raw                 Headerless 16-bit mono PCM instead of a WAV
        --serve               One request per line on standard input:
                              `<out path><TAB><text>`, one status line per reply
    -q, --quiet               Only errors
    -V                        Program version and what is built in
    -h, --help                This

Text is UTF-8 (or, if it is not valid UTF-8, Latin-1) and is given to the
engine as Windows-1252. Engine control sequences pass through: ESC \\pause=500\\
and the like.
";

struct Args {
    text: Option<String>,
    file: Option<String>,
    out: String,
    speech: Option<PathBuf>,
    pack: Option<String>,
    volume: Option<u32>,
    speed: Option<u32>,
    raw: bool,
    serve: bool,
    quiet: bool,
}

fn main() -> ExitCode {
    let r = std::thread::Builder::new()
        .stack_size(ENGINE_STACK)
        .spawn(run)
        .map_err(|e| e.to_string())
        .and_then(|h| h.join().map_err(|_| "engine thread panicked".to_string()))
        .and_then(|r| r);
    match r {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("ss-rs-ng: {e}");
            ExitCode::FAILURE
        }
    }
}

fn parse(argv: &[String]) -> Result<Args, String> {
    let mut a = Args {
        text: None,
        file: None,
        out: "speech.wav".into(),
        speech: None,
        pack: None,
        volume: None,
        speed: None,
        raw: false,
        serve: false,
        quiet: false,
    };
    let mut out = None;
    let mut pos = Vec::new();
    let mut k = 0;
    while k < argv.len() {
        let arg = argv[k].as_str();
        let mut next = |what: &str| -> Result<String, String> {
            k += 1;
            argv.get(k).cloned().ok_or_else(|| format!("{what} needs a value"))
        };
        let num = |v: String, what: &str| v.parse::<u32>().map_err(|_| format!("{what} {v}: not a number"));
        match arg {
            "-o" | "--out" => out = Some(next("--out")?),
            "-f" | "--file" => a.file = Some(next("--file")?),
            "--speech" => a.speech = Some(PathBuf::from(next("--speech")?)),
            "--version" => a.pack = Some(next("--version")?.to_ascii_lowercase()),
            "--volume" => a.volume = Some(num(next("--volume")?, "--volume")?.min(100)),
            "--speed" => a.speed = Some(num(next("--speed")?, "--speed")?),
            "--raw" => a.raw = true,
            "--serve" => a.serve = true,
            "-q" | "--quiet" => a.quiet = true,
            other if other.starts_with('-') && other != "-" => {
                return Err(format!("unknown option `{other}` (try --help)"));
            }
            other => pos.push(other.to_string()),
        }
        k += 1;
    }
    // Positionals are `[text] [out]`; with --file or --serve there is no
    // text, so the only one is `[out]` (or nothing, for --serve).
    let mut pos = pos.into_iter();
    if a.file.is_none() && !a.serve {
        a.text = pos.next();
    }
    if let Some(p) = pos.next() {
        if a.serve {
            return Err(format!("`{p}`: --serve takes its text and paths from standard input"));
        }
        if out.is_some() {
            return Err(format!("`{p}`: the output is already given with --out"));
        }
        out = Some(p);
    }
    if let Some(p) = pos.next() {
        return Err(format!("`{p}`: too many arguments; quote the text if it has spaces (try --help)"));
    }
    if let Some(o) = out {
        a.out = o;
    }
    Ok(a)
}

fn pack_named(name: &str) -> Result<(&'static Pack, Tree), String> {
    match name {
        "realspeak" | "rs" => Ok((&ss_rs_ng_eng::rs::PACK, ss_rs_ng_voice::RS)),
        "scansoft" | "ss" => Ok((&ss_rs_ng_eng::ss::PACK, ss_rs_ng_voice::SS)),
        _ => Err(format!("--version {name}: scansoft or realspeak")),
    }
}

/// The pack an install is, from its voicefont DLL: each translated pack
/// knows the SHA-256 of the `vf_tom_full.dll` it was made from.
fn detect(speech: &Path) -> Result<&'static Pack, String> {
    let rel = "components/voicefont/vf_tom_full.dll";
    let mut p = speech.to_path_buf();
    for comp in rel.split('/') {
        let exact = p.join(comp);
        p = if exact.exists() {
            exact
        } else {
            std::fs::read_dir(&p)
                .ok()
                .and_then(|rd| {
                    rd.filter_map(|e| e.ok())
                        .find(|e| e.file_name().to_string_lossy().eq_ignore_ascii_case(comp))
                        .map(|e| e.path())
                })
                .unwrap_or(exact)
        };
    }
    let bytes = std::fs::read(&p).map_err(|e| format!("{}: {e} (is --speech the `speech` directory?)", p.display()))?;
    let sum = sha256::hex(&bytes);
    for pack in [&ss_rs_ng_eng::rs::PACK, &ss_rs_ng_eng::ss::PACK] {
        if pack.modules.iter().any(|m| m.name == "vf_tom_full" && m.sha256 == sum) {
            return Ok(pack);
        }
    }
    Err(format!("{}: unknown voicefont (sha256 {sum}); only ScanSoft 2004 and RealSpeak 2006 Tom are translated", p.display()))
}

fn backend(a: &Args) -> Result<(&'static Pack, Backend, &'static str), String> {
    if let Some(dir) = &a.speech {
        let pack = match &a.pack {
            Some(n) => pack_named(n)?.0,
            None => detect(dir)?,
        };
        return Ok((pack, Backend::Disk(dir.clone()), "voice files from --speech"));
    }
    let name = match &a.pack {
        Some(n) => n.clone(),
        None if !ss_rs_ng_voice::RS.is_empty() => "realspeak".into(),
        None if !ss_rs_ng_voice::SS.is_empty() => "scansoft".into(),
        None => return Err("this build carries no voice; pass --speech <install>\\speech".into()),
    };
    let (pack, tree) = pack_named(&name)?;
    if tree.is_empty() {
        return Err(format!("this build does not carry {name}; pass --speech <install>\\speech"));
    }
    Ok((pack, Backend::BuiltIn(tree), "built-in voice files"))
}

/// UTF-8 to Windows-1252; text that is not UTF-8 is taken as Latin-1.
/// A character 1252 cannot hold becomes `?`.
fn cp1252(raw: &[u8]) -> Vec<u8> {
    const HIGH: [u16; 32] = [
        0x20AC, 0, 0x201A, 0x0192, 0x201E, 0x2026, 0x2020, 0x2021, 0x02C6, 0x2030, 0x0160, 0x2039, 0x0152, 0, 0x017D, 0,
        0, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2013, 0x2014, 0x02DC, 0x2122, 0x0161, 0x203A, 0x0153, 0, 0x017E, 0x0178,
    ];
    let s = match std::str::from_utf8(raw) {
        Ok(s) => s,
        Err(_) => return raw.to_vec(),
    };
    s.chars()
        .map(|ch| {
            let u = ch as u32;
            if u < 0x80 || (0xA0..0x100).contains(&u) {
                u as u8
            } else {
                HIGH.iter().position(|&h| h as u32 == u && h != 0).map_or(b'?', |k| 0x80 + k as u8)
            }
        })
        .collect()
}

fn prefix(a: &Args, pack: &Pack) -> Vec<u8> {
    let vol = a.volume.unwrap_or(if pack.name == "ss" { 60 } else { 100 });
    let mut p = format!("\x1b\\vol={vol}\\").into_bytes();
    if let Some(s) = a.speed {
        p.extend_from_slice(format!("\x1b\\rate={s}\\").as_bytes());
    }
    p
}

fn write_out(path: &str, bytes: &[u8]) -> Result<(), String> {
    if path == "-" {
        let mut o = std::io::stdout().lock();
        o.write_all(bytes).and_then(|_| o.flush()).map_err(|e| format!("standard output: {e}"))
    } else {
        std::fs::write(path, bytes).map_err(|e| format!("{path}: {e}"))
    }
}

fn read_text(a: &Args) -> Result<Vec<u8>, String> {
    let raw = match a.file.as_deref() {
        Some("-") => {
            let mut v = Vec::new();
            std::io::stdin().read_to_end(&mut v).map_err(|e| format!("standard input: {e}"))?;
            v
        }
        Some(p) => std::fs::read(p).map_err(|e| format!("{p}: {e}"))?,
        None => a.text.clone().unwrap_or_default().into_bytes(),
    };
    Ok(cp1252(&raw).trim_ascii().to_vec())
}

fn request() -> Request<'static> {
    Request {
        voice: "Tom",
        text: b"",
        product: "RealSpeak Solo v4.0",
        khz: 22,
        extra: &[],
    }
}

fn run() -> Result<(), String> {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    if argv.iter().any(|a| a == "-h" || a == "--help") || argv.is_empty() {
        print!("{USAGE}");
        return Ok(());
    }
    if argv.iter().any(|a| a == "-V") {
        println!("ss-rs-ng {}", env!("CARGO_PKG_VERSION"));
        for (name, pack, tree) in [
            ("realspeak", &ss_rs_ng_eng::rs::PACK, ss_rs_ng_voice::RS),
            ("scansoft", &ss_rs_ng_eng::ss::PACK, ss_rs_ng_voice::SS),
        ] {
            let built = if tree.is_empty() {
                "voice not built in".to_string()
            } else {
                format!("voice built in: {} files, {:.1} MB", tree.len(), ss_rs_ng_voice::bytes(tree) as f64 / 1048576.0)
            };
            println!("{name:9}: {} modules translated from x86; {built}", pack.modules.len());
        }
        return Ok(());
    }
    let a = parse(&argv)?;
    let (pack, be, from) = backend(&a)?;
    let pre = prefix(&a, pack);

    if a.serve {
        return serve(pack, be, from, &a, &pre);
    }
    let text = read_text(&a)?;
    if text.is_empty() {
        return Err("no text to speak (try --help)".into());
    }
    let t0 = std::time::Instant::now();
    let mut eng = Engine::open(pack, be, &request())?;
    let load = t0.elapsed().as_secs_f64();
    let t1 = std::time::Instant::now();
    let pcm = eng.say(&[pre.as_slice(), text.as_slice()].concat())?;
    let spoke = t1.elapsed().as_secs_f64();
    if pcm.is_empty() {
        return Err("the engine produced no audio".into());
    }
    let bytes = if a.raw { pcm.clone() } else { wav(&pcm, eng.rate) };
    write_out(&a.out, &bytes)?;
    if !a.quiet {
        let secs = pcm.len() as f64 / 2.0 / eng.rate as f64;
        eprintln!(
            "{}: {} characters -> {secs:.2} s of audio in {spoke:.2} s ({:.0}x real time); engine ready in {load:.2} s ({from})",
            if pack.name == "ss" { "ScanSoft 2004 Tom" } else { "RealSpeak 2006 Tom" },
            text.len(),
            secs / spoke.max(1e-9)
        );
    }
    Ok(())
}

/// Keep one engine open and answer one request per line:
/// `<out path><TAB><text>` in, `ok <path> <samples> <seconds>` or
/// `error <message>` out, flushed per line.
fn serve(pack: &'static Pack, be: Backend, from: &str, a: &Args, pre: &[u8]) -> Result<(), String> {
    let t0 = std::time::Instant::now();
    let mut eng = Engine::open(pack, be, &request())?;
    if !a.quiet {
        eprintln!("ss-rs-ng ready in {:.2} s ({}, {from})", t0.elapsed().as_secs_f64(), pack.name);
    }
    let mut input = Vec::new();
    std::io::stdin().read_to_end(&mut input).map_err(|e| format!("standard input: {e}"))?;
    let mut out = std::io::stdout().lock();
    for line in input.split(|&b| b == b'\n') {
        let line = line.strip_suffix(b"\r").unwrap_or(line);
        if line.iter().all(|b| b.is_ascii_whitespace()) {
            continue;
        }
        let tab = match line.iter().position(|&b| b == b'\t') {
            Some(t) => t,
            None => {
                writeln!(out, "error no tab in request").ok();
                out.flush().ok();
                continue;
            }
        };
        let path = String::from_utf8_lossy(&line[..tab]).trim().to_string();
        let text = cp1252(&line[tab + 1..]);
        let t = std::time::Instant::now();
        let reply = eng.say(&[pre, text.as_slice()].concat()).and_then(|pcm| {
            if pcm.is_empty() {
                return Err("no audio".to_string());
            }
            let bytes = if a.raw { pcm.clone() } else { wav(&pcm, eng.rate) };
            write_out(&path, &bytes)?;
            Ok(pcm.len() / 2)
        });
        match reply {
            Ok(n) => writeln!(out, "ok {path} {n} {:.3}", t.elapsed().as_secs_f64()).ok(),
            Err(e) => writeln!(out, "error {e}").ok(),
        };
        out.flush().ok();
    }
    Ok(())
}
