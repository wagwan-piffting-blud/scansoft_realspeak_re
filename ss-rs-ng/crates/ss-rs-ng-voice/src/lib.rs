//! The voice files, compiled in: [`RS`] and [`SS`], each empty unless the
//! build set `SSRSNG_BAKE` (see `build.rs`).

pub type Tree = &'static [(&'static str, &'static [u8])];

include!(concat!(env!("OUT_DIR"), "/voice.rs"));

pub fn bytes(t: Tree) -> usize {
    t.iter().map(|(_, b)| b.len()).sum()
}
