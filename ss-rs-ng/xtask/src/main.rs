mod engcorpus;
mod opgate;

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let code = match args.first().map(|s| s.as_str()) {
        Some("opgate") => opgate::run(&args[1..]),
        Some("engcorpus") => engcorpus::run(&args[1..]),
        _ => {
            eprintln!("usage: cargo run -p xtask --release -- <command>");
            eprintln!("  opgate    [--n N] [--seed S] [--shards K] [--show K]");
            eprintln!("  engcorpus [--pack rs|ss] [--line K] [--jobs N] [--ref DIR]");
            2
        }
    };
    std::process::exit(code);
}
