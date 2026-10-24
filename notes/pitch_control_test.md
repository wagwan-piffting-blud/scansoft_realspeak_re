# Pitch and duration control: output test (RS 2006 + SS 2004 Tom), 2026-10-23

Question (DLL_ANALYSIS §7.4 / §8.5): can in-text markup change pitch, and does the voice font
honour the L&H phonetic notation `ph[dur(t,F0)(t,F0)…]` that EMPP's prompts use?

**Answer: no, in either engine. Every pitch and duration control path is accepted and
silently dropped. Only rate, volume and `#[N]` pauses act.** CONFIRMED (byte-identical PCM).

## Method

- Installed SAPI5 voices "RealSpeak Tom" (2006) and the NextUp "ScanSoft Tom" (2004), driven
  from 32-bit PowerShell (`C:\tmp\pitchtest\render{,2,3,4}.ps1`), 22.05 kHz 16-bit mono.
- `C:\tmp\pitchtest\measure.py`: speech duration, F0 median/p10/p90 (parselmouth), RMS, and
  the SHA-1 of the PCM. `C:\tmp\pitchtest\asr.py` (faster-whisper medium.en) checks what was
  said.

## Results

### 1. Pitch markup: no effect

"This is a test of the pitch control in the engine."

| case | RS 2006 | SS 2004 |
|---|---|---|
| baseline | 2.221 s, F0 108.9, sha `77548c59b8` | 2.250 s, F0 109.4, sha `d612766cf2` |
| `ESC\pitch=10\` / `=50\` / `=90\` | **identical sha** | **identical sha** |
| SAPI `<pitch absmiddle="-10">` / `"+10"` | **identical sha** | **identical sha** |
| `ESC\rate=20\` (control) | 3.189 s | 3.412 s |
| `ESC\vol=20\` (control) | −38.1 dB (vs −14.6) | −32.5 dB (vs −20.4) |
| SAPI `<rate absspeed="-5">` (control) | 2.976 s | 3.190 s |

The escape is consumed rather than spoken (the output equals the baseline, so nothing was
read aloud). The stdpp record (type 0x10, subtype 0x80) and the ttsengine `pitch` param both
die before audio. This closes §7.2 item 1: "pitch is a no-op" is now CONFIRMED by output.

### 2. Phonetic input with duration/F0 targets: no effect

The only way into the phonetic path is the legacy `ESC/+ … ESC/+` region. The SAPI wrapper
uses the same one: template `\x1b/+##\x1b/+` at `rs_sapi5_solo.dll` file offset `0xc504`.
External symbols follow `sapi5_conv_enu.dat` (ax→`$`, ow→`o&U`, stress 1→`'`, syllable→`.`).
Raw `+…+`, `\x10…\x0f` and `ESC\/+\` in text are read aloud by the PP (ASR: "plus H dollar
sign…").

"Say ‹hello› now.":

| case | RS 2006 sha | SS 2004 sha |
|---|---|---|
| SAPI `<pron sym="h ax 1 l ow">hello</pron>` | `de0efd9384` | `175a1cdd22` |
| `ESC/+h$.'lo&UESC/+` | `de0efd9384` (same) | `175a1cdd22` (same) |
| + `[60]` / `[80]` / `[600]` durations | same | same |
| + `[600(0,80)(550,200)]` (rise) / `(0,200)(550,80)` (fall) | same | same |
| + `(0,60)` / `(0,180)` flat targets | same | same |
| + `#[800]` pause (control) | 1.885 s vs 0.836 s, **differs** | 1.674 s vs 0.814 s, **differs** |

ASR reads "Say hello now." for all of them.

### 3. Where the targets are lost (static)

- **g2p parses them.** `g2p_parse_phonetic_string` (`0x1002bae0`, RS) calls the 4-state
  tokenizer `0x1002cb10`. It recognises phone `[` dur `(` t `,` F0 `)` … `]`. The callbacks
  store each phone in a record:

  | field | meaning |
  |---|---|
  | +0 | phone (≤ 6 chars) |
  | +8 | duration kind (1 absolute, 2 `±` relative) |
  | +0xc | duration |
  | +0xe | target count (≤ 7) |
  | +0x10 | `{t, F0}` pairs, 4 bytes each |

  The function then re-serialises them into the phoneme tier as `[dur(t,F0)…]` text, with the
  duration scaled by a per-phone factor /100. CONFIRMED (decompile)
- **The voice font only parses `#[N]`.** The RS `vf_tom_full.dll` has exactly three `cmp …, '['`
  (`0x10001258`, `0x10005dc8`, `0x10018bd8`), each guarded by a preceding `#` test. The
  phoneme-tier reader `0x10005c80` atoi's `#[N]` into the pause array. SS 2004 has the same
  three (`0x1000125a`, `0x10005420`, `0x10015c28`). No `[`+`(`+`]` parsing cluster exists in
  any VF, synth, PP or ttsengine; the one cluster is the g2p tokenizer (RS `0x1002ce94`, SS
  `0x10024a10`). CONFIRMED (`C:\tmp\pitchtest\bracket_scan.py`, `vf_bracket.py`)
- INFERRED: the per-phone `[dur(t,F0)]` text is ignored or stripped when the voice font builds
  its segment list. Output parity proves the effect either way.

## Consequence

The `[dur(t,F0)]` notation is INFERRED to be the input format of an older L&H synthesiser
(the diphone-era engines took explicit F0 targets); nothing in these packs proves which. EMPP's prompts still carry it, but RealSpeak's
unit-selection voice fonts never use it. Melody and timing always come from the selected
recordings.
