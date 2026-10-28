//! `sprintf` for the guest: `ssrs_shims.c`'s `format_guest` (spec parsing,
//! buffer limits, argument walk), with the conversions done by a C printf
//! rather than the host's.

use ss_rs_ng_xrt::Mem;

#[derive(Default)]
struct Spec {
    left: bool,
    plus: bool,
    space: bool,
    alt: bool,
    zero: bool,
    width: usize,
    prec: Option<usize>,
}

fn parse(spec: &str) -> Spec {
    let b = spec.as_bytes();
    let mut s = Spec::default();
    let mut i = 1;
    while i < b.len() && b"-+ #0".contains(&b[i]) {
        match b[i] {
            b'-' => s.left = true,
            b'+' => s.plus = true,
            b' ' => s.space = true,
            b'#' => s.alt = true,
            _ => s.zero = true,
        }
        i += 1;
    }
    let mut w = 0i64;
    let mut neg = false;
    if i < b.len() && b[i] == b'-' {
        neg = true;
        i += 1;
    }
    while i < b.len() && b[i].is_ascii_digit() {
        w = w * 10 + (b[i] - b'0') as i64;
        i += 1;
    }
    if neg {
        s.left = true;
    }
    s.width = w as usize;
    if i < b.len() && b[i] == b'.' {
        i += 1;
        let mut p = 0i64;
        let mut pneg = false;
        if i < b.len() && b[i] == b'-' {
            pneg = true;
            i += 1;
        }
        while i < b.len() && b[i].is_ascii_digit() {
            p = p * 10 + (b[i] - b'0') as i64;
            i += 1;
        }
        s.prec = if pneg { None } else { Some(p as usize) };
    }
    s
}

fn pad(s: &Spec, sign: &str, body: String, zero_ok: bool) -> String {
    let len = sign.len() + body.len();
    if len >= s.width {
        return format!("{sign}{body}");
    }
    let fill = s.width - len;
    if s.left {
        format!("{sign}{body}{}", " ".repeat(fill))
    } else if s.zero && zero_ok {
        format!("{sign}{}{body}", "0".repeat(fill))
    } else {
        format!("{}{sign}{body}", " ".repeat(fill))
    }
}

fn int(s: &Spec, conv: u8, v: u64, neg: bool) -> String {
    let mut digits = match conv {
        b'x' => format!("{v:x}"),
        b'X' => format!("{v:X}"),
        b'o' => format!("{v:o}"),
        _ => format!("{v}"),
    };
    if let Some(p) = s.prec {
        if p == 0 && v == 0 {
            digits.clear();
        }
        while digits.len() < p {
            digits.insert(0, '0');
        }
    }
    if conv == b'o' && s.alt && !digits.starts_with('0') {
        digits.insert(0, '0');
    }
    let sign = if neg {
        "-"
    } else if matches!(conv, b'd' | b'i') && s.plus {
        "+"
    } else if matches!(conv, b'd' | b'i') && s.space {
        " "
    } else if s.alt && v != 0 && conv == b'x' {
        "0x"
    } else if s.alt && v != 0 && conv == b'X' {
        "0X"
    } else {
        ""
    };
    pad(s, sign, digits, s.prec.is_none())
}

/// `%e` digits: mantissa with `p` decimals and the exponent, C style.
fn exp_form(v: f64, p: usize, upper: bool) -> String {
    let r = format!("{:.*e}", p, v);
    let (mant, ex) = r.split_once('e').unwrap();
    let e: i32 = ex.parse().unwrap();
    let mut out = format!("{mant}{}{}{:02}", if upper { 'E' } else { 'e' }, if e < 0 { '-' } else { '+' }, e.abs());
    if upper {
        out = out.to_uppercase();
    }
    out
}

fn strip_zeros(s: String) -> String {
    if !s.contains('.') {
        return s;
    }
    let t = s.trim_end_matches('0');
    t.trim_end_matches('.').to_string()
}

fn float(s: &Spec, conv: u8, v: f64) -> String {
    let neg = v.is_sign_negative() && !v.is_nan();
    let a = v.abs();
    let sign = if neg {
        "-"
    } else if s.plus {
        "+"
    } else if s.space {
        " "
    } else {
        ""
    };
    if !a.is_finite() {
        let body = if a.is_nan() { "nan" } else { "inf" };
        let body = if conv.is_ascii_uppercase() { body.to_uppercase() } else { body.to_string() };
        return pad(s, sign, body, false);
    }
    let p = s.prec.unwrap_or(6);
    let body = match conv {
        b'f' => {
            let mut b = format!("{:.*}", p, a);
            if s.alt && p == 0 {
                b.push('.');
            }
            b
        }
        b'e' | b'E' => exp_form(a, p, conv == b'E'),
        _ => {
            let p = if p == 0 { 1 } else { p };
            let e = if a == 0.0 {
                0
            } else {
                let r = format!("{:.*e}", p - 1, a);
                r.split_once('e').unwrap().1.parse::<i32>().unwrap()
            };
            let b = if e < -4 || e >= p as i32 {
                let r = exp_form(a, p - 1, conv == b'G');
                if s.alt {
                    r
                } else {
                    let (m, x) = r.split_at(r.find(['e', 'E']).unwrap());
                    format!("{}{x}", strip_zeros(m.to_string()))
                }
            } else {
                let r = format!("{:.*}", (p as i32 - 1 - e).max(0) as usize, a);
                if s.alt {
                    r
                } else {
                    strip_zeros(r)
                }
            };
            b
        }
    };
    pad(s, sign, body, true)
}

/// Read a guest C string of at most `n - 1` bytes.
pub fn gstr(m: &Mem, va: u32, n: usize) -> Vec<u8> {
    let mut out = Vec::new();
    for i in 0..n.saturating_sub(1) {
        let c = m.r8(va + i as u32);
        if c == 0 {
            break;
        }
        out.push(c);
    }
    out
}

pub fn format_guest(m: &mut Mem, dst: u32, fmtva: u32, mut argp: u32) -> u32 {
    const OUT: usize = 4096;
    let fmt = gstr(m, fmtva, 1024);
    let mut out: Vec<u8> = Vec::new();
    let mut p = 0usize;
    while p < fmt.len() && out.len() < OUT - 1 {
        if fmt[p] != b'%' {
            out.push(fmt[p]);
            p += 1;
            continue;
        }
        let mut spec = String::from("%");
        p += 1;
        if p < fmt.len() && fmt[p] == b'%' {
            out.push(b'%');
            p += 1;
            continue;
        }
        while p < fmt.len() && b"-+ #0".contains(&fmt[p]) && spec.len() < 20 {
            spec.push(fmt[p] as char);
            p += 1;
        }
        if p < fmt.len() && fmt[p] == b'*' {
            spec.push_str(&(m.r32(argp) as i32).to_string());
            argp += 4;
            p += 1;
        } else {
            while p < fmt.len() && fmt[p].is_ascii_digit() && spec.len() < 24 {
                spec.push(fmt[p] as char);
                p += 1;
            }
        }
        if p < fmt.len() && fmt[p] == b'.' {
            spec.push('.');
            p += 1;
            if p < fmt.len() && fmt[p] == b'*' {
                spec.push_str(&(m.r32(argp) as i32).to_string());
                argp += 4;
                p += 1;
            } else {
                while p < fmt.len() && fmt[p].is_ascii_digit() && spec.len() < 28 {
                    spec.push(fmt[p] as char);
                    p += 1;
                }
            }
        }
        let mut is64 = false;
        if fmt[p..].starts_with(b"I64") {
            is64 = true;
            p += 3;
        } else {
            while p < fmt.len() && matches!(fmt[p], b'h' | b'l' | b'L') {
                p += 1;
            }
        }
        let conv = if p < fmt.len() {
            p += 1;
            fmt[p - 1]
        } else {
            0
        };
        let s = parse(&spec);
        let piece: Vec<u8> = match conv {
            b'd' | b'i' | b'u' | b'x' | b'X' | b'o' => {
                let signed = matches!(conv, b'd' | b'i');
                let (v, neg) = if is64 {
                    let v = m.r32(argp) as u64 | (m.r32(argp + 4) as u64) << 32;
                    argp += 8;
                    if signed && (v as i64) < 0 {
                        ((v as i64).unsigned_abs(), true)
                    } else {
                        (v, false)
                    }
                } else {
                    let v = m.r32(argp);
                    argp += 4;
                    if signed && (v as i32) < 0 {
                        ((v as i32).unsigned_abs() as u64, true)
                    } else {
                        (v as u64, false)
                    }
                };
                int(&s, conv, v, neg).into_bytes()
            }
            b'c' => {
                let c = (m.r32(argp) & 0xff) as u8;
                argp += 4;
                let mut b = pad(&s, "", String::from("\u{1}"), false).into_bytes();
                for x in b.iter_mut() {
                    if *x == 1 {
                        *x = c;
                    }
                }
                b
            }
            b's' => {
                let sv = m.r32(argp);
                argp += 4;
                let mut st = if sv != 0 { gstr(m, sv, 1024) } else { b"(null)".to_vec() };
                if let Some(pr) = s.prec {
                    st.truncate(pr);
                }
                let fill = s.width.saturating_sub(st.len());
                let mut b = Vec::new();
                if !s.left {
                    b.resize(fill, b' ');
                }
                b.extend_from_slice(&st);
                if s.left {
                    b.resize(b.len() + fill, b' ');
                }
                b
            }
            b'p' => {
                let v = m.r32(argp);
                argp += 4;
                format!("{v:08X}").into_bytes()
            }
            b'f' | b'e' | b'E' | b'g' | b'G' => {
                let v = f64::from_bits(m.r32(argp) as u64 | (m.r32(argp + 4) as u64) << 32);
                argp += 8;
                float(&s, conv, v).into_bytes()
            }
            b'n' => {
                argp += 4;
                Vec::new()
            }
            _ => Vec::new(),
        };
        out.extend_from_slice(&piece);
        if out.len() > OUT - 1 {
            out.truncate(OUT - 1);
        }
    }
    let n = out.len() as u32;
    out.push(0);
    m.write(dst, &out);
    n
}

#[cfg(test)]
mod tests {
    use super::{float, int, parse};

    #[test]
    fn c_conversions() {
        assert_eq!(int(&parse("%05"), b'd', 42, true), "-0042");
        assert_eq!(int(&parse("%-4"), b'x', 255, false), "ff  ");
        assert_eq!(int(&parse("%#"), b'x', 255, false), "0xff");
        assert_eq!(int(&parse("%.3"), b'u', 7, false), "007");
        assert_eq!(float(&parse("%"), b'f', 1.5), "1.500000");
        assert_eq!(float(&parse("%.2"), b'e', 12345.678), "1.23e+04");
        assert_eq!(float(&parse("%"), b'g', 0.0001), "0.0001");
        assert_eq!(float(&parse("%"), b'g', 1e-5), "1e-05");
        assert_eq!(float(&parse("%"), b'g', 123456789.0), "1.23457e+08");
        assert_eq!(float(&parse("%"), b'g', 100.0), "100");
    }
}
