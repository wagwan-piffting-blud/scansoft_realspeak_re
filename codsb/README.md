# codsb_dump — ScanSoft / RealSpeak `codsb` ACELP decoder

A clean-room C reimplementation of the audio decoder in `synth_155mrf22.dll`
(ScanSoft NextUp 2004 and RealSpeak Solo v4 2006, the same DLL in both). It reads a
voice's `vf_<voice>_full_155mrf22_270_06.dat`, unpacks the ACELP bitstream, and
writes PCM.

Status (2026-10-23):
- **Works:** it produces clean, intelligible 22,050 Hz speech. It decoded both
  full Tom corpora (4.07 h and 4.98 h).
- **Not bit-exact.** Every known departure from the engine is listed below with
  its fix location.

The format and codec are documented in full in
`%USERPROFILE%\Documents\ssrs_re\README_TECHNICAL.md` §2–§8. This file covers
the tool.

---

## Build

```powershell
cd $env:USERPROFILE\Documents\ssrs_re\codsb
.\build.bat
```

- MSVC x64, `/W4 /WX /O2 /MT`; zero warnings is the bar.
- `build.bat` finds VS 2022 Community, VS 18, or 2019 BuildTools, in that order.
- Output: `build\codsb_dump.exe`.

## Usage

```
codsb_dump <file.dat> [--order 15|16|17] [--start K] [--count M]
                      [--csv out.csv] [--params] [--wav out.wav] [--gain G]
```

| option | effect |
|---|---|
| (none) | header report, plus which of the three modes tile the body exactly |
| `--wav out.wav` | decode `--count` frames (default 3000) from `--start` to mono 16-bit WAV, then print RMS, zero-crossing rate and clip % |
| `--params` | decode pitch lags and pulse positions over the span; print lag min/max/mean and the sf0/sf2 lag-coherence check |
| `--csv out.csv` | write every unpacked field of the span, one row per frame |
| `--order N` | choose the variant: 15/16/17 = mode 1/2/3. Default 17, which is right for every shipped voice |
| `--gain G` | scale the WAV output |

⚠ `--start`, `--count` and `--csv` also switch on the per-frame field dump to
stdout (`want_dump` in `main.c`). For large spans, pass `--csv` or send stdout to
`$null`, or you get a million lines on the console.

Examples (PowerShell):

```powershell
$tom04 = "$env:USERPROFILE\Documents\ssrs_re\ScanSoft\speech\components\data\vf_tom_full_155mrf22_270_06.dat"
$tom06 = "$env:USERPROFILE\Documents\ssrs_re\RealSpeak\speech\components\data\vf_tom_full_155mrf22_270_06.dat"

# header + mode fit
.\build\codsb_dump.exe $tom04

# whole 2004 corpus to WAV (1,010,009 frames, 646 MB)
.\build\codsb_dump.exe $tom04 --wav C:\tmp\nomorekillmyvibe\codsb_corpus\nextup_tom_full.wav --count 1010009 > $null

# lag statistics over the whole 2006 corpus
.\build\codsb_dump.exe $tom06 --params --count 1234792 | Select-String 'subframes|lag\(sf2'
```

Frames are written end to end at 320 samples each with **no per-unit resets**,
so a sample index in these WAVs is a linear image of the `codsb` body. That is
what lets `ss_rs` cross-correlate unit positions against the audio.

---

## Files

| file | contents | engine source |
|---|---|---|
| `codsb.h` / `codsb.c` | `SCANSOFT` header, body geometry, the three bit-allocation rows, LSB-first unpack | `FUN_10005cb0`, `DAT_10012034`, `FUN_1000ec90` / `FUN_1000ed30` |
| `acelp.h` / `acelp.c` | 5- and 4-pulse algebraic codebooks, pitch-lag decode, multi-stage LSF VQ | `FUN_1000fd30`, `FUN_10010140`, `FUN_10010550`, `FUN_1000f9a0` |
| `decode.h` / `decode.c` | whole-frame synthesis: LSF stabilise, interpolate, LSF→LSP→LPC, bandwidth expansion, adaptive + fixed excitation, MA gain prediction, 1/A(z) | `FUN_1000e190` and callees |
| `tables.h` / `tables.c` | cos[8192], MA[4], log[1024], exp[2048], pitch gain[256], LSF interp[4], fixed gain[64], extracted verbatim. **Generated, do not edit** | `..\tools\codsb_tables.py` |
| `main.c` | CLI, WAV writer, the `--params` sanity checks | — |
| `build.bat` | MSVC build | — |

Supporting probes in `..\tools\`:
- `codsb_bitalloc.py`, `codsb_frame_size.py`, `codsb_sections.py`, `codsb_unpack.py`:
  derivation of the layout
- `codsb_hook_addr.py`, `codsb_hook_args.py`: Frida, live engine
- `codsb_unit_map.py`, `codsb_unit_marker.py`: unit → frame mapping
- `codsb_verify_audio.py`, `acelp_ceiling.py`: audio checks

`codsb.c` cites a `RESUME-ARCH.md` for the derivation. That file does not
exist. `ssrs_re\README_TECHNICAL.md` replaces it.

---

## What the tool gets right

- **Container.** It reads `toc_len` at +0x7c. The body starts there and is
  frames only: NextUp 49,490,441 B = 1,010,009 × 49, RS4 1,234,792 × 49.
- **Bit allocation.** All three rows, LSB-first within each byte and each field,
  exactly as the engine unpacks them.
- **LSF codebook.** Located in the codec header at TOC+72: 5 stages × 256 × 16 int16.
  The engine's own size check confirms the layout to the byte.
- **Excitation.** Pitch lag, adaptive codebook, pulse tracks and pulse amplitude
  (±0x2000) all match the engine.
- **Gains.** Pitch-gain table, and the fixed-gain predictor with its four
  shift bands and history offsets.
- **Interpolation and synthesis.** LSF interpolation weights (0.25 / 0.5 / 0.75 /
  current), the cosine-table LSF→LSP mapping, γ = 0x7EF9 bandwidth expansion, and
  the stage-2/3 gain scales (0xAAAA/65536 and 1/2).
- **Layout check.** Pitch lags in both Tom corpora span exactly 54..397. 397 is
  the engine's excitation-history length, and a misaligned unpack would range up
  to 565. This is the strongest layout check available. The `--params`
  "COHERENT" verdict is stricter than it should be (0.35 × null); the measured
  ratios are 0.40 and 0.43, both well below chance.

## Where it departs from the engine

From the Ghidra pass of 2026-10-23. Ranked by expected audibility; the same
list with full engine detail is in `ssrs_re\README_TECHNICAL.md` §8.

**D1 + D2 A/B** (`ssrs_re\tools\codsb_ab_d1d2.py`; frames 200,000..203,000,
43.5 s per voice; the previous build is kept as
`build\codsb_dump_pre_d1d2.exe`):

| voice | subframes with lag < 80 | DC old → new | energy < 40 Hz old → new | RMS old → new | old/new difference, lag < 80 frames / others |
|---|---:|---:|---:|---:|---:|
| SS Tom | 9.0% | −32.0 → 7.2 | −26.4 → −31.4 dB | 6737 → 6662 | −13.1 / −15.4 dB |
| SS Kyoko | 34.5% | 13.7 → 0.1 | −27.4 → −42.6 dB | 2125 → 2164 | −12.0 / −20.3 dB |
| RS Samantha | 6.2% | −4.8 → 0.1 | −31.4 → −38.8 dB | 5901 → 5866 | −13.5 / −16.6 dB |

- **D2:** removes the DC offset and 5–15 dB of sub-40 Hz energy.
- **D1:** the change concentrates in short-lag frames, and Kyoko is affected most.
- No new clipping (≤ 0.01%).
- Listening pairs, 14.5 s each: `C:\tmp\codsb_ab\{kyoko,tom04}_{old,new}.wav`.

| # | engine | here | fix location |
|---|---|---|---|
| D1 | **pitch sharpening**: when `lag < 80`, every fixed-codebook stage gets `code[n] += code[n−lag]·g_prev` (Q14; `g_prev` = previous subframe's pitch gain, init 0.2) | ✔ **FIXED 2026-10-23**, integer-exact: `pitch_sharpen()`, `codsb_dec.pg_prev` | — |
| D2 | **DC-blocking high-pass** on output, `y = x − x₁ + 0.98999·y₁` (`FUN_1000f310`, 0x7EB8) | ✔ **FIXED 2026-10-23**, integer-exact: `dc_block()`, `codsb_dec.hp_x1/hp_y1` | — |
| D3 | gain-predictor history init `0xE400` ×4 | 0 | `decode.c` `codsb_dec_init` |
| D4 | LSF stabiliser mode 0 (every shipped voice): ≤ 2 bubble passes, **no** spacing, no clamp | full sort + 40-unit gap + top clamp | `decode.c` `lsf_stabilise` |
| D5 | previous-LSF init uniform, `(k+1)·0x6488/17` | primed from the first frame | `decode.c` `codsb_dec_frame`, `!d->primed` branch |
| D6 | no lag clamp | clamps to [20, base] | harmless, data is always 54..397 |
| D7 | cold decoder reset + 40-sample delay + 6 lookback frames **per unit** (`FUN_100060f0`) | linear decode | `main.c`; correct for a corpus dump, needed only for per-unit extraction |
| D8 | fixed point throughout | double | by design |
| D9 | mode read from codec header `u16[1]` (= 3 in every voice) | hard-coded `LAYOUTS[2]` | `codsb.c` `codsb_open`; also fix `main.c`'s header comment, which says the mode is not stored |

Naming: what `codsb.h` calls "LPC order 15/16/17" is the engine's **variant id**
(state+0x04). The LPC order is always 16. Mode 2's nominal rate is 20.4 kbps,
not 20.1.
