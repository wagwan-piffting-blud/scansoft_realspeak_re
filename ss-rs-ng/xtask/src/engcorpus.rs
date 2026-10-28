//! `xtask engcorpus`: the M4 gate. Every corpus line through the translated
//! engine, compared byte for byte with the real engine's PCM, as
//! `oracle/corpus_gate.py` left it (`<ref>/<pack>_tom_NN_native.wav`).

use ss_rs_ng_eng::Pack;
use ss_rs_ng_host::vfs::Backend;
use ss_rs_ng_host::{wav, Engine, Output, Request};
use std::collections::BTreeSet;
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;

pub fn run(args: &[String]) -> i32 {
    let mut pack = "rs".to_string();
    let mut only: Option<usize> = None;
    let mut jobs = std::thread::available_parallelism().map_or(8, |p| p.get());
    let mut reff = std::env::temp_dir().join("ssrsng_gate");
    if !reff.exists() {
        reff = PathBuf::from(r"C:\tmp\ssrsng_gate");
    }
    let mut corpus_name = "corpus_en.txt".to_string();
    let mut files_out: Option<PathBuf> = None;
    let mut mem_list: Option<PathBuf> = None;
    let mut i = 0;
    while i < args.len() {
        let v = args.get(i + 1).cloned().unwrap_or_default();
        match args[i].as_str() {
            "--pack" => pack = v,
            "--line" => only = Some(v.parse().expect("--line")),
            "--jobs" => jobs = v.parse().expect("--jobs"),
            "--ref" => reff = PathBuf::from(v),
            "--corpus" => corpus_name = v,
            "--files" => files_out = Some(PathBuf::from(v)),
            "--mem" => mem_list = Some(PathBuf::from(v)),
            a => {
                eprintln!("engcorpus: unknown argument {a}");
                return 2;
            }
        }
        i += 2;
    }
    let (p, folder, refname): (&'static Pack, &str, &str) = match pack.as_str() {
        "rs" => (&ss_rs_ng_eng::rs::PACK, "RealSpeak", "realspeak"),
        "ss" => (&ss_rs_ng_eng::ss::PACK, "ScanSoft", "scansoft"),
        _ => {
            eprintln!("engcorpus: --pack rs|ss");
            return 2;
        }
    };
    let ng = PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf();
    let speech = ng.parent().unwrap().join(folder).join("speech");
    let corpus = std::fs::read_to_string(ng.join("oracle").join(&corpus_name)).expect("corpus");
    let lines: Vec<String> = corpus.lines().map(|l| l.trim().to_string()).filter(|l| !l.is_empty()).collect();
    let out_dir = std::env::temp_dir().join("ssrsng_engcorpus");
    std::fs::create_dir_all(&out_dir).expect("out dir");
    let todo: Vec<usize> = match only {
        Some(k) => vec![k],
        None => (0..lines.len()).collect(),
    };
    let tree = match &mem_list {
        Some(l) => {
            let list = std::fs::read_to_string(l).expect("--mem list");
            match ss_rs_ng_host::vfs::tree_from_list(&speech, &list) {
                Ok(t) => {
                    println!("built-in backend: {} files from {}", t.len(), l.display());
                    Some(t)
                }
                Err(e) => {
                    eprintln!("engcorpus: {e}");
                    return 2;
                }
            }
        }
        None => None,
    };
    let next = AtomicUsize::new(0);
    let results = Mutex::new(Vec::new());
    let files: Mutex<BTreeSet<String>> = Mutex::new(BTreeSet::new());
    let t0 = std::time::Instant::now();
    std::thread::scope(|s| {
        for _ in 0..jobs.min(todo.len()) {
            std::thread::Builder::new()
                .stack_size(512 << 20)
                .spawn_scoped(s, || loop {
                    let n = next.fetch_add(1, Ordering::SeqCst);
                    if n >= todo.len() {
                        break;
                    }
                    let k = todo[n];
                    let text = format!("\x1b\\vol=100\\{}", lines[k]);
                    let t = std::time::Instant::now();
                    let req = Request {
                        voice: "Tom",
                        text: text.as_bytes(),
                        product: "RealSpeak Solo v4.0",
                        khz: 22,
                        extra: &[],
                    };
                    let r = Engine::open(p, match tree { Some(t) => Backend::BuiltIn(t), None => Backend::Disk(speech.clone()) }, &req).and_then(|mut e| {
                        let pcm = e.say(req.text)?;
                        files.lock().unwrap().extend(e.file_log());
                        Ok(Output { pcm, rate: e.rate, msgs: e.msgs() })
                    });
                    let dt = t.elapsed().as_secs_f64();
                    results.lock().unwrap().push((k, r, dt));
                })
                .expect("spawn");
        }
    });
    let mut results = results.into_inner().unwrap();
    results.sort_by_key(|r| r.0);
    let mut ok = 0;
    for (k, r, dt) in &results {
        let refp = reff.join(format!("{refname}_tom_{k:02}_native.wav"));
        let want = std::fs::read(&refp).map(|b| b[44.min(b.len())..].to_vec()).unwrap_or_default();
        match r {
            Ok(o) => {
                std::fs::write(out_dir.join(format!("{pack}_{k:02}.wav")), wav(&o.pcm, o.rate)).ok();
                let audio = o.pcm.len() as f64 / 2.0 / o.rate as f64;
                if o.pcm == want {
                    ok += 1;
                    println!("OK   {k:2} {audio:6.2} s audio in {dt:5.2} s ({:5.1}x real time)", audio / dt);
                } else {
                    let first = o.pcm.iter().zip(want.iter()).position(|(a, b)| a != b);
                    println!(
                        "DIFF {k:2} {} vs {} bytes, first difference at byte {:?} ({dt:.2} s)",
                        o.pcm.len(),
                        want.len(),
                        first
                    );
                }
            }
            Err(e) => println!("FAIL {k:2} {e}"),
        }
    }
    if let Some(path) = files_out {
        let set = files.into_inner().unwrap();
        let mut text = String::from("# Every file the engine opened or searched for, relative to `speech`.\n");
        text.push_str("# Generated by `xtask engcorpus --files`.\n");
        for l in &set {
            text.push_str(l);
            text.push('\n');
        }
        std::fs::write(&path, text).expect("write --files");
        println!("{} file accesses -> {}", set.len(), path.display());
    }
    println!(
        "engcorpus {pack}: {ok}/{} byte-identical to the real engine, {:.1} s wall",
        results.len(),
        t0.elapsed().as_secs_f64()
    );
    if ok == results.len() {
        0
    } else {
        1
    }
}
