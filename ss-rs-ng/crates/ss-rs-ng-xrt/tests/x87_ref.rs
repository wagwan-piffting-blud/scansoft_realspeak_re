//! f2xm1, fyl2x and the FLD constants against correctly rounded references
//! (`tools/x87_ref.py`, mpmath at 400 bits).

use ss_rs_ng_xrt::Cpu;

fn hex(s: &str) -> u64 {
    u64::from_str_radix(s, 16).unwrap()
}

#[test]
fn x87_transcendentals_match_reference() {
    let text = include_str!("x87_ref.txt");
    let (mut n, mut bad) = (0, Vec::new());
    for line in text.lines() {
        let f: Vec<&str> = line.split_whitespace().collect();
        let mut c = Cpu::default();
        let (got, want) = match f[0] {
            "const" => {
                assert!(c.x87_reg(0xD9, hex(f[1]) as u8));
                (c.st(0).to_bits(), hex(f[2]))
            }
            "f2xm1" => {
                c.fpush(f64::from_bits(hex(f[1])));
                assert!(c.x87_reg(0xD9, 0xF0));
                (c.st(0).to_bits(), hex(f[2]))
            }
            _ => {
                c.fpush(f64::from_bits(hex(f[1])));
                c.fpush(f64::from_bits(hex(f[2])));
                assert!(c.x87_reg(0xD9, 0xF1));
                (c.st(0).to_bits(), hex(f[3]))
            }
        };
        n += 1;
        if got != want {
            bad.push(format!("{line} -> {got:016x}"));
        }
    }
    assert!(n > 10000, "only {n} vectors");
    assert!(bad.is_empty(), "{} of {n} wrong:\n{}", bad.len(), bad[..bad.len().min(20)].join("\n"));
}
