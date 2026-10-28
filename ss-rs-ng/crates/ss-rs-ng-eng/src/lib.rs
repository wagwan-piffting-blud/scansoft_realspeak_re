//! The two engines as translated Rust. Each pack is a separate module tree
//! at its own fixed bases; `tools/x86xlate.py translate --pack rs|ss`
//! regenerates them.

use ss_rs_ng_xrt::{Cpu, Host, Mem};

/// One vendor DLL as the translation expects to find it.
pub struct Module {
    pub name: &'static str,
    /// Relative to the pack's `speech` directory, as the oracle found it.
    pub file: &'static str,
    pub base: u32,
    pub size: u32,
    pub sha256: &'static str,
    pub entry: u32,
    pub exports: &'static [(&'static str, u32)],
    pub ordinals: &'static [(u16, u32)],
    /// `(IAT slot, value)`: a guest export VA, or `THUNK_BASE + 16 * k` for
    /// host import `k`.
    pub iat: &'static [(u32, u32)],
}

/// A translated pack: its modules, its host imports, and the way into its
/// code (an indirect transfer to any block, or to a host thunk).
pub struct Pack {
    pub name: &'static str,
    pub modules: &'static [Module],
    pub imports: &'static [(&'static str, &'static str)],
    pub enter: fn(&mut Cpu, &mut Mem, &mut dyn Host, u32),
}

#[cfg(feature = "rs")]
pub mod rs;
#[cfg(feature = "ss")]
pub mod ss;
