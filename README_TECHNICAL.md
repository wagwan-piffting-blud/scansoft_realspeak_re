# ScanSoft 2004 / RealSpeak Solo v4 2006 — technical living document

Binary-level companion to `README.md`. Per-DLL reverse engineering is in
`DLL_ANALYSIS.md`. The unit database (`useld`), preselect, position tiling and
precomputed join table are in the prior notes,
`..\Speechify\reveng\ss_rs\README_TECHNICAL.md`. They are
referenced as `ss_rs §N` and not repeated.

**Dated 2026-10-23 unless noted.** Addresses are Ghidra addresses, image base
0x10000000 for every ScanSoft/RealSpeak DLL. Ghidra programs:

- `/ss_synth_155mrf22.dll`
- `/ss_vf_tom_full.dll`
- `/rs_vf_tom_full.dll`
- `/spfy_SWIttsUSel.dll`, base 0x08e80000

The one Ghidra edit: `FUN_10005ee0` was created as a function. Nothing has been
renamed or saved.

---

## 0. Provenance

| file | size | sha256[:16] | PE stamp | FileVersion |
|---|---:|---|---|---|
| SS `synthesizer\synth_155mrf22.dll` | 110,686 | `d12c7c0097daba3b` | 2006-05-16 06:43:04 | 4.0.2.6136 |
| RS `synthesizer\synth_155mrf22.dll` | 110,686 | `d12c7c0097daba3b` | 2006-05-16 06:43:04 | 4.0.2.6136 |
| SS `synthesizer\synth_112mrf16.dll` | 106,496 | `57d0f54d7389b476` | 2004-10-28 | 4.00.02 |
| SS `synthesizer\synth_83swf11.dll` | 106,496 | `fbaf2f249c043827` | 2004-10-28 | 4.00.02 |
| SS `voicefont\vf_tom_full.dll` | 794,624 | `ef3805f9d91e1199` | 2004-07-22 | 4.00.00 |
| RS `voicefont\vf_tom_full.dll` | 204,896 | `4d2a38fc5d20bb64` | 2006-05-16 | 4.0.2.6136 |
| `common\swisolo.dll` (both packs) | 106,496 | `3631f7ddca576506` | 2004-10-28 | 4.00.02 |
| Speechify `SWIttsUSel.dll` | 135,168 | `7be4558b5eaf99ac` | 2005-02-15 | 3.0.5.5046 |

⚠ The ScanSoft `synth_155mrf22.dll` is the **2006 build**, alone among the
ScanSoft synth DLLs. Every codec fact below was read from that build. No 2004
`synth_155mrf22.dll` is available to check whether it differs.

RealSpeak DLLs are not 4 KB-aligned in size because they carry a 64–106 byte
overlay. It is an **NB10 CodeView record** (PDB 2.0 path, e.g.
`F:\ttssrc.a\win32.x86\rel\tts_predev_prd\vf\synth\155mrf22\synth_155mrf22.pdb`),
not a signature and not tampering. The 2004 builds are stripped of it.

Full PE survey (129 binaries, Rich header, PDB paths, version info, provenance
strings): `tools\pe_survey.py` → `tools\pe_survey_2026-10-23.json`.

---

## 1. SCANSOFT header: per-file values (corrects `ss_rs §1`)

Layout is in `ss_rs §1`. The two fields that `ss_rs` misread:

| file | +0x80 (3 digits) | +0x84 (u32) |
|---|---|---:|
| SS `vf_tom` / `us_tom` | 173 / 173 | 265498 |
| SS `vf_kyoko` / `us_kyoko` | 269 / 269 | 265498 |
| SS `vf_narae` / `us_narae` | 90 / 90 | 265498 |
| RS `vf_tom` / `us_tom` | **173** / **216** | 822349082 |
| RS `vf_jill` / `us_jill` | 156 / 145 | 265498 |
| RS `vf_samantha` / `us_samantha` | 175 / 175 | 822349082 |
| RS `vf_paulina` / `us_paulina` | 102 / 102 | 822349082 |
| RS `vf_emily` / `us_emily` | 165 / 165 | 839126298 |
| RS daniel / isabel / karen / lee | 167 / 149 / 139 / 172 (each matches its `us_`) | 265498 |

- **+0x84 is not a per-pack stamp.** `265498` spans both packs. It marks a
  voice-build batch and still pairs a voice's `useld` with its `codsb`.
- **+0x80 is read by the synth DLL.** `FUN_10005cb0` does `atoi` on the 3 bytes
  and stores the result at obj+0x54. `FUN_10005ec0` returns it to the caller.
  Meaning unknown.
  - RealSpeak Tom's `codsb` carries **173**, the same value as both ScanSoft Tom
    files. Its own `useld` carries 216.
  - Together with §2's shared codebook, that says RealSpeak Tom's audio container
    came out of the same codec build as the 2004 Tom's.

---

## 2. The `codsb` codec header (the "TOC"), fully decoded

`toc_len` = header +0x7c = **0xA0D8 in all 12 voice files**. The bytes from
0x90 to 0xA0D8 (41,032) are the codec header.

`FUN_10005d50` copies them to the heap, and `FUN_10005ee0` (codec create) parses them:

| TOC offset | type | value (all voices) | read by | meaning |
|---:|---|---|---|---|
| +0x00 | u16 | `0x0FA5` (4005) | `FUN_10005ee0` → `FUN_1000eb60` `param_2` | codec version. `eb60` rejects anything else |
| +0x02 | u16 | **3** | `FUN_10005ee0` (`& 3`) | **mode** (1/2/3, table in §3) |
| +0x04 | u16 | 6 | `FUN_10005ee0` → obj+0x08 | lookback frames = `.hdr` `OVERHEADFRAMES` |
| +0x06 | u16 | 50, or **47** for Daniel/Emily/Lee/Samantha | nothing examined | ⚠ unknown |
| +0x08 | blob | | `FUN_1000df60` `param_5`, size `toc_len-0x90-8` | VQ descriptor + codebook |

The blob (i32 words, `n` = number of LSF VQ stages):

| blob word | value | read by | meaning |
|---|---|---|---|
| `[0]` | 5 | → state+0x2c | `n`, LSF VQ stages |
| `[1..n]` | 256 ×5 | state+0x30 → | entries per stage |
| `[n+1..2n]` | 8 ×5 | state+0x34 → | bits per stage index (= the five 8-bit LSF fields) |
| `[2n+1]` | 3 | nothing examined | ⚠ unknown |
| `[2n+2]` | **0** | → state+0x28 | **LSF stabiliser mode** (§4, step 2) |
| `[2n+3..2n+5]` | `0x5400`, 60, `0x7EFA0000` | nothing examined | ⚠ unknown |
| `[2n+6..]` | int16 × 16 × Σdims | state+0x5ec → | **LSF codebook**, stage-major |

`FUN_1000df60` enforces `8n + 24 + 32·Σdims == blob size`. For n=5 that is
`40 + 24 + 32·1280 = 41,024 = 41,032 − 8`, **exact in all 12 files**. The
codebook starts at TOC+72, which is the `CODSB_TOC_HDR 72` the decoder
hard-coded earlier, now explained.

### The codebook is per voice

TOC sha256[:16] (`tools\codsb_toc_dump.py`):

```
SS tom      304f4a82afa6308e      RS tom      304f4a82afa6308e   <-- identical
SS kyoko    1fef8e09fa004d71      RS jill     f7f0de8aa69b463a
SS narae    3ca39e527f6db490      RS samantha d00963ce5b25f086
RS daniel   8e3b4635c9dbe716      RS emily    a3dfc044037459c4
RS isabel   34655afcd5aba6cc      RS karen    deb29ea8ae1e884d
RS lee      d4c91fa81bcd2c82      RS paulina  dd0a1973af5ac363
```

**11 distinct codebooks across 12 files.** This retracts `ss_rs §6h`'s reading
("identical across packs, so codec tables"). It is a trained, per-voice
codebook, and the two Toms happen to share one.

---

## 3. Codec descriptor and modes — `FUN_1000eb60`

`FUN_1000eb60(codec_id, version, mode, flags, kind, out)`. The codec id must be
**`0x102102`**. For `kind != 1` the version must be `0xFA5`, and `mode` uses bits 0–1 only.

| mode (`& 3`) | variant id (state+0x04) | bytes/frame | bits | stages | nominal bps | unpack fields |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 15 | 28 (0x1C) | 224 | 1 | 15,500 (0x3C8C) | 28 |
| 2, and 0 | 16 | 37 (0x25) | 296 | 2 | 20,400 (0x4FB0) | 36 |
| 3 | 17 | 49 (0x31) | 392 | 3 | 27,000 | 44 |

Common descriptor fields:

| field | value | meaning |
|---|---|---|
| out+0x08 | 0x28 (40) | codec delay in samples, used as obj+0x06 (§6) |
| out+0x10 | 0xFA5 | version |
| out+0x14 | 0x280 | 640 output bytes per frame (320 × int16) |
| out+0x1E | 0x660 | decoder state size |
| out+0x20 | 0x360 | scratch size |

The variant id is what `codsb.h` calls "order 15/16/17". **It is not the LPC
order.** Every LPC call in `FUN_1000e190` passes `0x10` (16). The id is
compared against thresholds in `FUN_10010550` (lag decode) and selects the
5-pulse vs 4-pulse first stage (`== 0x10` → 4-pulse).

Nominal bitrates are rounded: 392 bits per 320 samples at 22,050 Hz is
27,011 bps. `codsb.c`'s "20.1 kbps" for mode 2 should read 20.4 nominal
(296 bits → 20,396 bps).

### Bit allocation, `DAT_10012034 + (variant − 15) · 0x70`

Rows are 56 × u16. The driver unpacks **nfields + 3** entries (28/36/44). The
last three have width 0 and decode as 0 (`FUN_1000ed30` returns 0 for
`width < 1`). Active fields: 25 / 33 / 41, exactly the `W15/W16/W17` tables in
`codsb.c`. Re-read from Ghidra on 2026-10-23 and identical.

---

## 4. Decoder state (0x660 bytes, handle class 0x10062)

Created by `FUN_1000df60`, initialised by `FUN_1000e070`, reset by
`FUN_1000eaa0` (which keeps the codebook and configuration).

| off | type | init | meaning |
|---:|---|---|---|
| +0x004 | i32 | 15/16/17 | variant id |
| +0x00c | i32 | 28/37/49 | bytes per frame |
| +0x010 | i32 | 28/36/44 | unpack field count (incl. 3 zero-width pads) |
| +0x014 | i32 | 0x5622 | 22,050 Hz |
| +0x01c | i32 | 0x36 | 54, minimum pitch lag |
| +0x020 | i32 | **0x18D** | **397, excitation history length = maximum usable lag** |
| +0x024 | i32 | 1/2/3 | fixed-codebook stages |
| +0x028 | i32 | blob `[2n+2]` = 0 | LSF stabiliser mode |
| +0x02c | i32 | 5 | LSF VQ stages |
| +0x030 | i32* | | dims[] |
| +0x034 | i32* | | bits[] and the trailing unknown words |
| +0x03c | i16* | state+0x35a | current-frame excitation pointer |
| +0x040 | i16[397] | 0 | past excitation |
| +0x35a | i16[320] | 0 | current-frame excitation |
| +0x5da | i16[4] | **0xE400** ×4 | MA gain-predictor history (log domain, −7168) |
| +0x5e2 | i16 | 0 | fixed gain applied to the current stage |
| +0x5e4 | i16 | 0 | stage-1 fixed gain |
| +0x5e6 | i16 | 0 | current pitch gain, Q14 |
| +0x5e8 | i16 | **0x0CCC** | previous pitch gain = sharpening factor, Q14 (0.2) |
| +0x5ec | i16* | | LSF codebook |
| +0x5f0 | i16 | 0 | high-pass `x[n-1]` |
| +0x5f6 | i16 | 0 | high-pass `y[n-1]` |
| +0x5fc | i32[16] | 0 | synthesis-filter memory (32-bit) |
| +0x63c | i16[16] | uniform | previous-frame LSF. `FUN_10006860`: `(k+1)·0x6488/17` |
| +0x65c | u32 | 0 | frame counter |

Scratch (0x360 bytes, caller-owned):

| off | contents |
|---:|---|
| +0x000 | int16 code vector, reused as the int32 filter workspace `[16 history + 80 acc]` |
| +0x180 | int16 output subframe |
| +0x220 | int32 LPC |
| +0x260 | int32 unpacked fields `[44]` |
| +0x340 | int16 current LSF `[16]` |

---

## 5. The frame — `FUN_1000e190`

Signature (INFERRED names):

```
FUN_1000e190(h_lo, h_hi, flags, const u8 *bits, u16 *io_nbytes,
             i16 *scratch, i16 *out, u16 *out_nbytes, u32 *side, u16 *side_len)
```

Return codes:

| code | meaning |
|---|---|
| `0x86202001` | `flags & ~1` |
| `0x86202009` | `*io_nbytes < frame bytes` |
| `0x86202006` | null argument |

On success `*io_nbytes` = bytes consumed and `*out_nbytes` += 160 per subframe.
`flags & 1` = **excitation-only mode**: the LSFs are forced uniform and the
excitation is output with no synthesis filter.

**CORRECTED 2026-10-23** (`notes\synth_concat_2006.md`): this was previously written as
"no shipped path was seen setting it". The synth's unit warm-up DOES use it. Each unit's
6-frame lookback (§6) decodes **4 frames excitation-only, then 2 full frames**, before the
unit's own audio. `codsb_dump` D7 (no per-unit reset/warm-up) should mirror this when
it extracts units.

1. **Unpack** (`FUN_1000ec90` / `FUN_1000ed30`). Explode to bits, LSB-first per
   byte. Each field accumulates `bit[j] << j`.
2. **LSF.**
   - **VQ** (`FUN_1000f9a0`): `lsf[i] = (Σ_{k≥1} cb_k[idx_k][i]) >> 2 + cb_0[idx_0][i]`.
   - **Order** (`FUN_1000f730`): bubble sort with an early exit, capped at
     **5 passes if stab mode == 3, otherwise 2**.
   - **Spacing** (`FUN_1000f7c0`) runs only when stab mode == 3. The minimum gap
     depends on the LSF count: 16/18 → 0xA1 (161 = 69 Hz at 22,050 Hz),
     14 → 0xE9, 20 → 0x75, other → 0x142. It pushes neighbours apart by half
     the deficit, up to 10 iterations, and stops when every gap is ≥ 0.99·gap
     (`0x7EB8`).
   - ⚠ **Every shipped voice has stab mode 0**, so the engine applies at most
     two sort passes and no spacing at all.
3. **Per subframe `s` = 0..3** (80 samples):
   - **Pitch lag** (`FUN_10010550`, cross-subframe state reset to 0 each frame):
     - even subframes: `lag = idx9 + 54`
     - odd subframes: `lag = prev − 15 + idx5`
   - **Adaptive codebook** (`FUN_10010520`): forward in-place copy
     `exc[n] = exc[n − lag]`, so lags below 80 repeat within the subframe.
     `pg = PGAIN[idx8]` (`DAT_1001754c`, Q14).
     `exc[n] = sat((pg·exc[n]·2 + 0x4000) >> 15)`.
   - **Fixed codebook, stage 1:**
     - pulse count: 5-pulse (`FUN_1000fd30`); 4-pulse (`FUN_10010140`) for variant 16
     - if `lag < 80`: **pitch sharpening**,
       `code[n] += sat((code[n−lag]·g_prev·2 + 0x4000) >> 15)` for n = lag..79,
       with `g_prev` = state+0x5e8 (Q14).
       - gain from the full vector's energy (`FUN_1000fa60`)
       - `exc[n] += (g·code[n]·2 + 0x8000) >> 16` over all 80 samples
     - else: gain from the analytic energy of `npulse` unit pulses
       (`FUN_1000fb10`), added only at the pulse positions.
   - **Gain** (`FUN_1000fbf0`):
     - **Predicted gain:** log-energy plus the MA predictor
       (`DAT_10016244` = 22282, 19005, 11141, 6225 = G.729's
       0.68 / 0.58 / 0.34 / 0.19), through `LOG` (`0x1001654c`) and
       `EXP` (`0x10016d4c`).
     - **Correction:** `FGAIN[idx6]` (`DAT_10017750`).
     - **Shift bands:**

       | idx6 | rounding / shift | history offset |
       |---|---|---:|
       | < 59 | `+0x2000 >> 14` | 0 |
       | 59–60 | `>> 13` | 0x302 |
       | 61–62 | `>> 12` | 0x605 |
       | 63 | `>> 10` | 0xC0A |

     - **History update** (`FUN_1000fbb0`): `gp[0] = (log(corr) + offset)·4`,
       after shifting `gp[0..2]` → `gp[1..3]`.
   - **Stage 2** (stages ≥ 2): 4-pulse, fields k = 5, 6,
     `g2 = (g1·0xAAAA + 0x8000) >> 16` (≈ 2/3). Same sharpening rule.
   - **Stage 3** (stages == 3): fields 7, 8, `g3 = ((g1 + 1)·0x8000) >> 16` (≈ 1/2).
   - `g_prev ← pg`.
   - **Synthesis** (`flags & 1 == 0`):
     1. Interpolate the LSFs: `out = (prev·(0x7FFF−w) + cur·w)·2 >> 16`,
        w = `DAT_1001202c` = 8192 / 16384 / 24576 for s = 0..2. Subframe 3 uses
        the current LSFs unchanged.
     2. `FUN_1000f480` LSF → cosine (8192-entry table `DAT_10012244`, index `lsf·0x4000/0x6488 >> 1`).
     3. `FUN_1000f4e0` LSP → int32 LPC.
     4. `FUN_1000f6d0` bandwidth expansion `a_k ·= γ^k`, γ = 0x7EF9/32768 = 0.99197.
     5. `FUN_1000f390` 1/A(z): input `<< 14`, 32-bit state, coefficient products
        at shift 28, output rounded `>> 14` and saturated.
     6. **`FUN_1000f310` DC-blocking high-pass, `y = sat(sat(x − x₁) + (y₁·0x7EB8·2 + 0x8000) >> 16)`**,
        pole 0.98999.
4. **End of frame:**
   - prev LSF ← current
   - excitation history ← the last 397 samples (copied from state+0x2c0 to +0x40)
   - current-frame excitation zeroed
   - frame counter += 1

All tables are already extracted verbatim into `codsb\tables.c` by
`tools\codsb_tables.py` from the same addresses listed above.

---

## 6. Getting a unit's audio

**Module chain**, all in `synth_155mrf22.dll`:

1. `FUN_10005950` opens the `.dat` through `brk_DataOpen`.
2. `FUN_10005d50` maps 0x90 bytes and parses the header (`FUN_10005cb0`), then
   copies the TOC to the heap.
3. `FUN_10006740` hands out the codec vtable `0x10011a20`:

   | slot | function | role |
   |---|---|---|
   | +0x10 | `FUN_10005ee0` | create, parses the TOC |
   | +0x14 | `FUN_10006240` | destroy |
   | +0x34 | `FUN_100060f0` | address |
   | +0x38 | `0x100062e0` | decode, INFERRED from the call in `FUN_10005c30` |

   ⚠ The table's u16 at +0x46 is 50, the same as TOC `u16[3]`. Not explained.
4. `FUN_10005b60` calls `+0x34`, then `brk_DataMap(toc_len + off, len)`.

**Addressing object** (0x2ac bytes, handle class 99), filled by `FUN_10005ee0`:

| off | value | source |
|---:|---|---|
| +0x00 | 8 | |
| +0x02 | 49 | bytes per frame |
| +0x04 | 320 | samples per frame (640 >> 1) |
| +0x06 | **40** | codec delay, descriptor +0x08 |
| +0x08 | **6** | lookback, TOC `u16[2]` |
| +0x0a | | 320-sample decode buffer |
| +0x28c | | unit length |
| +0x290 | | samples to discard |
| +0x294, +0x298 | | decoder state / scratch heap buffers |
| +0x2a0 | | decoder handle |

**`FUN_100060f0(obj, pos, len)`:**

```
s        = pos + 40
f0       = max(0, s / 320 - 6)
byte_off = 49 * f0                            (relative to body start = toc_len)
nbytes   = 49 * ((s + len - 1) / 320 - f0 + 1)
skip     = s - 320 * f0                       (samples to discard before the unit)
FUN_1000eaa0(decoder)                         (decoder reset, every unit)
```

So **every unit is decoded from a cold decoder, starting 6 frames (87 ms) plus
the 40-sample delay before its position**. That is the mechanism behind
`ss_rs`'s measured −80 ms audio offset, now read from the code. The units of
`pos` at this interface must be samples, because frame size and skip share
them. The tick-to-sample conversion `ss_rs §6` describes happens upstream in
the voice font (INFERRED; not traced).

A second codec (`FUN_1000ee70` → vtable `0x10012188`, errors `0x870020xx`) is a
plain PCM copy (`FUN_1000ef80`: up to 0x2000 bytes, even length). INFERRED:
for uncompressed voice data. No shipped voice uses it.

**Rate and markers:**
- `synth_GetInterface` (table `0x100110c8`) exposes param handlers for
  `waitfactor` and `markermode` (`FUN_10002ac0`).
- The object built by `FUN_10006bf0` (0x440 bytes) listens on `ratewpm`,
  `raterelchg` and `pausestatus`. Speaking-rate modification therefore lives in
  the synth DLL, below the codec.
- Not decoded.

---

## 7. Measurements

| measurement | ScanSoft Tom 2004 | RealSpeak Tom 2006 | tool |
|---|---:|---:|---|
| frames | 1,010,009 | 1,234,792 | `codsb_dump` |
| pitch lag min / max / mean | **54 / 397** / 179.6 | **54 / 397** / 172.8 | `codsb_dump --params` |
| mean \|lag(sf2) − lag(sf0)\| (null 170.7) | 68.9 (2.48× below null) | 73.9 (2.31×) | same |
| distinct frames | 998,157 (98.83%) | 1,234,792 (100.00%) | `tools\codsb_frame_overlap.py` |
| frames shared with the other Tom | 7 | 7 | same |

- **The lag ceiling is exactly 397 in both corpora, over 9 M subframes.** The 9-bit
  field could express up to 565. The encoder was constrained to the 397-sample
  excitation history (state+0x020). This is a stronger layout check than the
  coherence ratio: a misaligned unpack would put lags across the whole 54..565
  range.
  - ⚠ `codsb_dump` prints "NOT COHERENT" for both, because its threshold is 0.35 × null.
    The ratios (0.40, 0.43) are well below chance. The verdict line is too strict,
    and the lag-ceiling result above is the one to trust.
- **No coded-frame reuse between the Toms.** Seven shared frames is chance level.
  This says the bitstreams are independent encodes. It does **not** say the
  recordings differ: re-encoding the same audio from a different decoder state
  gives different bits.
- **2004 has 11,852 duplicated frames, 2006 has none.** Unexplained. Likely
  digital-silence frames in 2004; not checked.

---

## 8. `codsb_dump` vs the engine: every known departure

Exact slots in `codsb\`. Ranked by expected audibility.

| # | engine (§5) | `codsb_dump` today | where to change |
|---|---|---|---|
| D1 | pitch sharpening of every fixed-codebook stage when `lag < 80`, factor = previous subframe's pitch gain (Q14, init 0.2) | ✔ **FIXED 2026-10-23**, integer-exact: `pitch_sharpen()`, `codsb_dec.pg_prev` | — |
| D2 | output DC-block `y = x − x₁ + 0.98999·y₁` (`FUN_1000f310`) | ✔ **FIXED 2026-10-23**, integer-exact: `dc_block()`, `codsb_dec.hp_x1/hp_y1` | — |
| D3 | gain-predictor history init `0xE400` ×4 | `memset` 0 | `decode.c`, `codsb_dec_init` |
| D4 | stab mode 0: ≤ 2 bubble passes, no spacing, no clamp | full sort + `LSF_MIN_GAP 40` + top clamp | `decode.c`, `lsf_stabilise` |
| D5 | prev LSF init uniform `(k+1)·0x6488/17` | primed from frame 0 | `decode.c`, `codsb_dec_frame` (`!d->primed` branch) |
| D6 | no lag clamp (data is always in 54..397) | clamps to [20, base] | `decode.c`; harmless, can stay |
| D7 | cold reset + 40-sample delay + 6 lookback **per unit** | linear decode, no resets | `main.c`; correct for a corpus dump, wrong for unit extraction |
| D8 | fixed-point throughout (32-bit synth state, Q14/Q15 rounding) | double | by design (`decode.c` header). Bit-exactness would need the Q-format transcription |
| D9 | mode read from TOC `u16[1]` | hard-coded order 17; `main.c` header says the mode is "NOT stored in the container" | `codsb.c`, `codsb_open`; `main.c` header comment |

A/B for D1 + D2: `tools\codsb_ab_d1d2.py`, results table in `codsb\README.md`.
- DC goes to ~0 and sub-40 Hz energy drops 5–15 dB.
- D1's change concentrates in short-lag frames (Kyoko: 34.5% of subframes).
- RMS is unchanged and there is no new clipping.
- Pre-fix binary kept as `build\codsb_dump_pre_d1d2.exe`.

Also stale: `codsb.c` cites `RESUME-ARCH.md` for derivations. No such file
exists anywhere under `Speechify\`. This document is now that reference.

---

## 9. Retractions and corrections

| claim | where | status |
|---|---|---|
| `codsb` TOC is shared codec tables | `ss_rs §6h` | ✘ per-voice codebook; shared only by the two Toms (§2) |
| header +0x84 is a per-pack build stamp | `ss_rs §1` | ✘ voice-build batch, spans packs (§1) |
| the LSF order is a runtime value not in the container | `codsb\main.c` header | ✘ TOC `u16[1]` (§2) |
| "order 15/16/17" = LPC order | `codsb\codsb.h` | ✘ variant id; LPC order is always 16 (§3) |
| mode 2 = 20.1 kbps | `codsb\codsb.c` | ✘ 20.4 nominal (§3) |
| `FUN_1000f310` is a postfilter | `codsb\decode.c` | ✘ DC-blocking high-pass (§5) |
| LSF minimum separation uses a fixed floor | `codsb\decode.c` | ✘ engine applies none for shipped data (§5 step 2) |
| record bytes +13/+14 are F0 or energy at unit edges | `ss_rs §6f` | ✘ edge-duration values for the join fallback, INFERRED (`DLL_ANALYSIS.md` §3) |

---

## 10. Shared RECORDINGS with Speechify `tom8.vdb` (measured 2026-10-23)

The question is take identity, not speaker identity: all three are Tom Glynn,
so "sounds the same" is a given. Only phase-coherent waveform agreement can
show a shared physical recording. The statistic is NCC at 8 kHz, maximised over
all 124 min of `tom8.vdb` and both polarities.

The search is `vdb_fast.VdbSearcher` (coarse ÷4 pass, top-64 candidates, then
an exact full-rate NCC ±128 samples on the GPU). Its self-test was run first:
three self-probes scored 1.0000 at the exact position.

⚠ `tom16.vdb` was **not** used. It is AudioSR output made from `tom8`, not a
vendor file.

### 10.1 Global search, W = 1600 (200 ms), n = 3000 per arm (`tools\tom_overlap.py`)

Haystack: `tom8.vdb`, μ-law → int16. Probes: 22,050 Hz corpus WAVs from
`codsb_dump`, polyphase-resampled 160/441, gated to the top 60% by RMS.

| arm | what it is | p50 | p99 | p99.9 | max | **> threshold** |
|---|---|---:|---:|---:|---:|---:|
| CEIL | tom8 windows through AMR-WB 23.85k (ACELP), score at their true position | 0.876 | 0.962 | 0.973 | 0.980 | **76.5%** (sensitivity) |
| **F-TAKE** | those probes' best hit in a **different** tom8 recording: same speaker, same codec, other take | 0.584 | 0.766 | **0.810** | 0.849 | 0.10% (by definition) |
| F-REV | SS stretches time-reversed | 0.488 | 0.700 | 0.800 | 0.843 | 0.10% |
| F-SPK | Kyoko blind windows | 0.453 | 0.694 | 0.758 | 0.780 | 0.00% |
| TEST | SS 2004 stretches from the `useld` map | 0.592 | 0.883 | 0.925 | 0.960 | **5.33%** |
| **B-SS** | SS 2004 blind windows | 0.606 | 0.933 | 0.958 | 0.972 | **14.83%** |
| **B-RS** | RS 2006 blind windows | 0.614 | 0.872 | 0.898 | 0.926 | **6.00%** |

- The threshold (0.8097) was fixed in advance as F-TAKE's p99.9.
- CEIL found its true position 91.4% of the time. AMR-WB is not ScanSoft's
  coder and our decoder is not bit-exact, so CEIL bounds the ceiling rather than
  reproducing it.
- **Hit distinctiveness.** For the top TEST hits, the best score in any *other*
  tom8 recording was 0.48–0.73, against 0.89–0.96 for the hit. Each hit has one
  unique location.
- **The stretch arm under-performs blind windows** because the stretch map is
  the wrong unit: §10.2 shows the 300-tick gaps are not cuts. TEST is kept for
  the record; B-SS is the measure.

### 10.2 Lock tracking (`tools\tom_overlap_runs.py`, `tom_overlap_breaks.py`)

For 200 blind hits per pack:
- slide a 100 ms window in 20 ms steps over ±1.5 s of the corpus
- search tom8 only ±25 ms around where slope 1 predicts
- use the same window **reversed** as the local null (p99: SS 0.585, RS 0.591)

LOCKED = beats the null and the lag stays within 2 ms of the hit's.

| | ScanSoft 2004 | RealSpeak 2006 |
|---|---:|---:|
| hits that lock at the hit point | 198 / 200 | 198 / 200 |
| **slope**, tom8 samples per corpus sample | **1.00000** (IQR 0.99985–1.00013) | **1.00000** (IQR 0.99976–1.00034) |
| contiguous locked run, p10 / p50 / p90 / max | 260 / **380** / 606 / 1000 ms | 240 / **320** / 500 / 860 ms |
| same-lag span with breaks allowed, p50 / p90 / max | 480 / 920 / 1980 ms | 420 / 860 / 1300 ms |
| spans reaching the ±1.5 s edge | 0 | 0 |
| run ends within 30 ms of a tom8 recording boundary | 6.1% | 6.6% |
| run ends within 30 ms of an SS 300-tick gap | 23.0% (chance ≈ 25%) | — |
| SS 300-tick gaps **inside** locked runs | **344** | — |

Reading it:
1. **These are lines, not points.** A chance match does not keep its lag for
   0.4 s at slope 1.00000 ± 0.0002. The SS/RS audio is the same recording, same
   speed, as tom8's.
2. **The stores are cut into pieces of about 0.4–0.5 s** (never ≥ 2 s). The cuts
   are not tom8's recording boundaries, and **not the 300-tick gaps**. Audio runs
   straight across 344 of those. This settles `ss_rs §6d`.
3. **Some long same-lag spans merge pieces around non-matching audio of the same
   duration.** Whole-span NCC of the exported pairs is 0.39–0.49 on the five
   longest SS spans versus 0.75–0.88 on the others. Exporter alignment was
   checked (±1 sample in 21/24 pairs), and voicing does not explain it. Not
   understood. Use the contiguous-run figures as the conservative ones.

### 10.3 Spread (`tools\tom_overlap_recs.py`)

| | hits | distinct tom8 recordings | prompt families (of 18) | top families |
|---|---:|---:|---:|---|
| SS 2004 | 200 | 193 | 14 | news 113, pn 18, weather 17, shortAdd 10, dip 9 |
| RS 2006 | 200 | 194 | 11 | news 120, pn 16, weather 12, dip 11, usEmAdd 9 |

The two packs' independent samples hit **10 recordings in common**
(`dip2_091`, `news11_054`, `news22_076`, …).

### 10.4 How much is shared (INFERRED, rough)

- **Corpus share, lower bound:** 14.8% / 0.765 ≈ **≥ 19%** of SS 2004 speech
  time, and 6.0% / 0.765 ≈ **≥ 8%** of RS 2006, is material also in tom8.
  These are floors: a 200 ms window that straddles one of the ~0.4 s pieces'
  cuts cannot hit.
- **Shared pool size:** if both packs draw uniformly from one shared pool of S
  tom8 recordings, 10 coincidences from 193 × 194 samples gives S ≈ 3,700
  (Poisson 10 ± 3 → ~2,900–5,300) of tom8's 8,139.

### 10.5 Outputs

| path | contents |
|---|---|
| `C:\tmp\tom_overlap\summary_W1600.json` | §10.1 |
| `C:\tmp\tom_overlap\runs_{ss,rs}_W1600.json` | per-hit lock traces |
| `C:\tmp\tom_overlap\hits_W1600\` | top TEST hits, mono pairs |
| `C:\tmp\tom_overlap\listen\{ss,rs}_NN.wav` | **stereo, L = tom8, R = SS/RS, sample-aligned**, longest locked spans with 150 ms context; index in `listen.json` |

### 10.6 Every direction: tom8 ↔ SS ↔ RS (`tools\tom_overlap_xpack.py`, 2026-10-23)

**Setup:**
- **Haystacks:** three, at 8 kHz. The SS and RS corpora were resampled whole,
  160/441, and cached in `C:\tmp\tom_overlap\cache\`.
- **Probes:** W = 1600 (200 ms), n = 2000 RMS-gated windows per source, both polarities.
- **Thresholds:** the p99.9 of all **time-reversed** probes against that same
  haystack: SS 0.8260, RS 0.8252. tom8 keeps F-TAKE's 0.8097.
- **Self-tests:** all three haystacks passed (self-probes 1.0000 at the exact position).

| probe → haystack | hit rate | reversed-null rate | p50 | p99 | max |
|---|---:|---:|---:|---:|---:|
| tom8 → SS | **23.25%** | 0.00% | 0.690 | 0.943 | 0.969 |
| tom8 → RS | **8.30%** | 0.05% | 0.670 | 0.880 | 0.911 |
| SS → tom8 | 14.75% | — | 0.607 | 0.930 | 0.967 |
| RS → tom8 | 4.90% | — | 0.614 | 0.855 | 0.901 |
| **SS → RS** | **36.50%** | 0.15% | 0.765 | 0.945 | 0.958 |
| **RS → SS** | **26.75%** | 0.20% | 0.716 | 0.935 | 0.965 |
| Kyoko → SS / RS | 0.00% / 0.00% | — | 0.49 / 0.52 | 0.72 / 0.75 | 0.80 / 0.82 |

Which stores each window is found in (n = 2000 each):

| probes from | in both others | first only | second only | neither |
|---|---:|---:|---:|---:|
| tom8 (others: SS, RS) | 118 | 347 (SS) | 48 (RS) | 1487 |
| SS (others: tom8, RS) | 244 | 51 (tom8) | **486 (RS)** | 1219 |
| RS (others: tom8, SS) | 67 | 31 (tom8) | **468 (SS)** | 1434 |

Lock confirmation (up to 100 hits per class; same slide test as §10.2):

| class | locked | run p50 | slope p50 (IQR) |
|---|---:|---:|---|
| tom8 → SS | 100/100 | 360 ms | 1.00000 (0.99997–1.00005) |
| tom8 → RS | 100/100 | 360 ms | 1.00000 (0.99966–1.00026) |
| SS → RS, also in tom8 | 99/100 | 460 ms | 1.00000 (0.99989–1.00011) |
| **SS → RS, NOT in tom8** | **100/100** | 400 ms | 1.00000 (0.99975–1.00009) |
| RS → SS, also in tom8 | 67/67 | 460 ms | 1.00000 (0.99987–1.00004) |
| **RS → SS, NOT in tom8** | **100/100** | 400 ms | 1.00000 (0.99994–1.00013) |

**Reading it:**
1. **SS 2004 and RS 2006 share takes directly, and most of what they share is
   not in Speechify.** Of the SS windows found in RS, 486 of 730 are absent from
   tom8. Of the RS windows found in SS, 468 of 535 are absent. Those
   non-Speechify hits lock exactly like the rest. So ScanSoft held a pool of Tom
   Glynn session audio larger than Speechify's 8 kHz subset, and built both its
   voices from it.
2. **RS's Speechify material is mostly also SS's.** 118 of the 166 tom8 windows
   found in RS (71%) are also in SS.
3. **Speechify ↔ SS is the larger link, ↔ RS the smaller.** 23% of tom8 windows
   are in SS and 8% in RS.
4. **No coded frames are shared** between SS and RS (§7), so the 2006 Tom is a
   **re-encode of the same masters**, not a copy of the 2004 bitstream. The
   shared LSF codebook (§2) says it went through the same codec build.

**Shared material, INFERRED.** Hours = hit rate × source duration, over
RMS-gated speech windows. These are uncorrected for sensitivity (≈0.77 at
these thresholds) and for windows that straddle a piece cut, so all are floors.

| pair | estimated from side A | estimated from side B |
|---|---:|---:|
| tom8 ∩ SS | 23.25% × 2.06 h = 0.48 h | 14.75% × 4.07 h = 0.60 h |
| tom8 ∩ RS | 8.30% × 2.06 h = 0.17 h | 4.90% × 4.98 h = 0.24 h |
| **SS ∩ RS** | 36.50% × 4.07 h = **1.49 h** | 26.75% × 4.98 h = **1.33 h** |

Each pair's two independent estimates agree within ~25%, which is a
consistency check on the method. Dividing by the 0.77 sensitivity gives:
- roughly **≥ 0.7 h of tom8 (≥ 30%) inside SS 2004**
- **≥ 0.25 h (≥ 11%) inside RS 2006**
- **≥ 1.8 h shared between SS 2004 and RS 2006**: about 45% of SS and 37% of RS

### 10.7 Room tone: same sessions? (`tools\tom_roomtone.py`) — INCONCLUSIVE, with a replicated lean

5000 windows per pack, classed as:
- **A**: also in tom8
- **B**: in the other ACELP pack only
- **C**: in neither

| | A | B | C |
|---|---:|---:|---:|
| SS 2004 | 737 | 1062 | 3201 |
| RS 2006 | 260 | 1152 | 3588 |

Features come from the 22,050 Hz audio:
- noise floor (band p10 − p90)
- long-term spectrum shape
- energy above 4 and 8 kHz vs 1–4 kHz
- 50/60 Hz line energy

Cross-validated logistic AUC:

| | null A\|A | A\|B | A\|C | B\|C | B − A: floor | B − A: > 8 kHz | B − A: 4–8 kHz |
|---|---:|---:|---:|---:|---:|---:|---:|
| SS 2004, all features | 0.482 | 0.639 | 0.804 | 0.735 | −1.84 dB | +2.27 dB | +1.40 dB |
| RS 2006, all features | 0.567 | 0.618 | 0.703 | 0.688 | −2.99 dB | +0.99 dB | +1.24 dB |

- **B is weakly separable from A.** The null is noisy (0.46–0.59 across feature
  groups) because RS has only 260 A windows.
- **B is much closer to A than C is.** In both packs B sits a little quieter in
  the noise floor and a little brighter above 4 kHz. Two independent encodes
  agree on the direction.
- That fits slightly different recording conditions for the non-Speechify
  material, but a content difference (news prompts vs other text) could produce
  the same shift. 200 ms ACELP windows cannot separate the two explanations.
- **Not a verdict.** Same sessions is neither shown nor excluded.

### 10.8 A real 16 kHz Speechify Tom from the 22 kHz packs? (`tools\tom16_coverage.py`)

**Target:** the AudioSR build `tom16.vdb` is the same RIFF with `fmt` = PCM 16-bit
16 kHz, the identical 8,139-entry `indx` with offsets ×4, and `data` = 2× the
samples (`tools\vdb_layout.py`). A real build is a drop-in replacement for its
`data` chunk.

**Coverage pilot, seed-and-extend over 60 random tom8 recordings (20 ms speech grid):**
- **Seed:** 200 ms windows at a 100 ms hop, global search, xpack thresholds.
- **Extend:** 100 ms windows at a 20 ms hop, ±25 ms local search, lag kept
  within ±2 ms. Local null p99: SS 0.6435, RS 0.6333.
- A first attempt with 100 ms windows searched globally reported 6.7%. That is
  wrong: its own null pushed the threshold to 0.92. Kept here as a warning.

| speech time covered | SS 2004 | RS 2006 | either | both |
|---|---:|---:|---:|---:|
| | **42.8%** | 15.8% | **46.7%** | 11.8% |

Per recording (either): p10 0%, p50 44%, p90 79%. ≥ 90% covered: 3% of
recordings; ≥ 50%: 47%; none: 12%. These are floors: a region whose seeds all
miss is never extended into.

**Is the uncovered half a detector blind spot?** No (`tools\tom16_blindspot.py`).

| tom8 speech frames | median RMS | voiced | loud + voiced |
|---|---:|---:|---:|
| covered | 9,769 | 66% | 41% |
| uncovered | 8,891 | 67% | 34% |

Coverage of **loud voiced** frames, the detector's best case and near ceiling
sensitivity, is only **51.4%**. Quiet voiced is 40.2% and unvoiced 47.4%. The
uncovered speech is ordinary speech. **About half of Speechify's tom8 is
genuinely not in SS/RS**, at least not as pieces long enough to seed (≥ 200 ms).

It is SpeechWorks audio by definition, since it is Speechify's own file.
ScanSoft simply did not keep it.

**Consequence:** a pure 22 kHz-sourced Tom is not possible, because about half
of the speech has no wideband source. The viable design is a **hybrid**:
- **0–4 kHz:** tom8's own band everywhere. That leaves timing, pitch marks and
  joins unchanged, and every unit sounds consistent in its body.
- **4–8 kHz:** the time-aligned SS/RS ACELP band where coverage exists, AudioSR's
  band from the existing `tom16.vdb` elsewhere, with short crossfades at coverage
  edges.

The full build needs:
- a complete coverage map (all 8,139 recordings)
- sub-sample alignment refinement at 22 kHz, for a clean crossover
- per-region gain matching
- an ear check for the real-vs-AudioSR seams

#### 10.8.1 Ten-recording hybrid demo (`tools\hybrid16_demo.py`, 2026-10-23)

**Pre-flight (`tools\hybrid16_probe.py`):**
- AudioSR `tom16.vdb` is sample-locked to tom8 ×2: lag 0, NCC 0.9985–0.9993 on 0–3.4 kHz.
- tom8's 3.5–4 kHz carries more energy than its 3–3.5 kHz, which is mu-law noise, not
  speech. So the crossover sits at **3.4 kHz**, not 4.

**Method, per recording, on tom8's own 16 kHz time axis:**
1. Seed-and-extend as in §10.8. Each 20 ms cell takes its best lock, and runs are
   cells sharing pack, polarity and offset (±2 ms).
2. Each run is re-aligned at 22.05 kHz to a fractional sample on 0.3–3.4 kHz
   (parabolic peak), FFT fractional shift, `resample_poly(320, 441)`.
3. Gain is matched on 1–3 kHz. Each run is high-passed with margins before cropping.
4. A cell keeps the real band only if its 0.3–3.4 kHz NCC vs tom8 is ≥ 0.70 (or it is
   silent). The mask is eroded 5 ms, then a 10 ms Hann crossfade.
5. Output = complementary linear-phase split (511 taps): LP(tom8 ×2) + HP(real) where
   masked, HP(AudioSR) scaled to the real band's level elsewhere.

| rec | real HB on speech | runs SS/RS | align NCC p50 | gain | AudioSR HB vs real |
|---|---:|---|---:|---:|---:|
| news7_030 | 84% | 7/1 | 0.950 | +8.6 dB | −1.2 dB |
| news5_038 | 71% | 4/0 | 0.953 | +9.2 dB | −0.8 dB |
| news09_060 | 58% | 8/5 | 0.940 | +8.2 dB | −1.1 dB |
| news09_021 | 66% | 5/2 | 0.939 | +8.5 dB | +0.7 dB |
| news10_053 | 63% | 6/0 | 0.945 | +8.3 dB | −0.6 dB |
| news6_018 | 69% | 4/1 | 0.949 | +8.7 dB | −0.6 dB |
| news10_091 | 69% | 6/0 | 0.967 | +7.6 dB | −1.0 dB |
| usCity_022 | 72% | 3/0 | 0.958 | +8.4 dB | +0.1 dB |
| news19_061 | 66% | 10/8 | 0.877 | +8.6 dB | −1.0 dB |
| letter_088 | 71% | 3/2 | 0.953 | +8.6 dB | +0.2 dB |

The packs sit a steady **≈ 8.5 dB** below tom8: one processing gain, not per-piece
normalisation. AudioSR's top band is at the right **level** (within ±1.2 dB).

**AudioSR's top band is an image of the bottom band** (`tools\hybrid16_mirror.py`).
Per 32 ms frame, the detrended log spectrum over 600–3400 Hz is correlated with the same
frame at 8000 − f (mirror) and at f + 4000 (shift):

| | mirror r p50 | share r > 0.5 | shift r p50 |
|---|---:|---:|---:|
| AudioSR `tom16.vdb` | **+0.69** | **70%** | +0.00 |
| real SS/RS band, same frames | −0.00 | 0% | −0.00 |

Formant tracks at 2 kHz reappear flipped at 6 kHz (visible in every PNG). That is the
signature of zero-stuffed upsampling that the model did not clean up, not of plausible
bandwidth extension. **The "AudioSR elsewhere" fallback therefore carries a mirror
artifact**, and the hybrid inherits it in the ~30–40% of speech without real coverage.

Outputs in `C:\tmp\hybrid16_demo\`:
- `<rec>_{A_tom8,B_audiosr,C_hybrid,D_realonly}.wav`, plus `<rec>.png`
  (tom8 / AudioSR / hybrid, green bar = real band)
- `ALL_*.wav` (the 10 concatenated) and `ALL_B_then_C.wav` (AudioSR then hybrid per recording)
- `report.json`

#### 10.8.2 Full map, Tom-trained BWE, demo v2 (2026-10-23)

User ear check of v1: "sounds okay, but I can definitely tell when it splices".

**Pipeline (all in `tools\`):**
1. `hybrid16_map.py`: every recording, 62,661 seeds/pack. Hits: SS 13,025, RS 4,874.
   - 4,709 of 8,139 recordings have runs: 52.8 of 122.6 min of cells.
   - Output: `C:\tmp\hybrid16\runs.json`.
2. `hybrid16_extract.py`: verified real band on **36.1% of all tom8 cells (44.6 min)**
   (SS 31.4%, RS 4.6%).
   - `hi_real.f16.npy` is aligned to the tom16 data layout; `cell_ok.u8.npy` holds 0/1/2 = none/SS/RS.
   - Per-recording gain: SS p50 +8.0 dB (p10–p90 +7.1…+9.3), RS +8.6 dB (+6.0…+12.4).
3. `hybrid16_bwe.py train`: a dilated Conv1d net (192 ch, 6 blocks, dropout 0.2) maps
   the 0–3.4 kHz log power to the real 3.4–8 kHz log power, on 37.2 min of verified frames.
   - Held out: every 20th recording plus the 10 demo recordings.
   - Early-stopped at val 0.504. The first, larger net overfit after 500 steps.
   - Fine structure: full-wave rectified tom8 low band, whitened per frame, then shaped
     by the predicted envelope.
4. `hybrid16_bwe.py eval`: held-out top-band log-spectral distance to the REAL band.

| | p25 | p50 | p75 |
|---|---:|---:|---:|
| Tom BWE | 7.87 dB | **8.60 dB** | 9.59 dB |
| AudioSR `tom16.vdb` | 12.65 dB | 14.56 dB | 16.73 dB |

   The BWE renders 4.1 dB quiet; the build applies the measured gain (`bwe_eval.json`).

5. `hybrid16_build.py demo`: the splice fixes are a single gain per pack per recording,
   real islands < 100 ms dropped, and 30 ms crossfades eroded inside verified audio.

| variant | mirror r p50 | share r > 0.5 |
|---|---:|---:|
| B AudioSR | +0.69 | 70% |
| C2 hybrid v2 | −0.00 | 0% |
| E BWE only | +0.00 | 0% |

Outputs are in `C:\tmp\hybrid16_demo2\`: `ALL_B_C2_E.wav` plays AudioSR → hybrid v2 →
BWE only for each recording, plus per-recording WAVs and PNGs. The full build is
`hybrid16_build.py full [--bwe-only]` → `C:\tmp\hybrid16\tom16_{hybrid,bwe}.vdb`.

#### 10.8.3 The "crunch" is codec noise in the real top band; demo v4 re-textures it (2026-10-23)

User ear checks:
- BWE v1 sounds "crunchy, very rough".
- The real band alone (`hybrid16_demo3\ALL_real_masked.wav`) is crunchy too, "in the SS half".

| test (`tools\`) | result |
|---|---|
| `hybrid16_rough.py`: 30–150 Hz AM roughness of the top band | real 0.740; BWE v1 (rectified excitation) 0.732, so v1 copied the real band's texture; pitch-modulated noise 0.30–0.37 |
| `hybrid16_packcmp.py`: SS vs RS on the SAME moments (16 s, 26 recordings) | roughness 0.576 vs 0.584; modulation spectra within ±1 dB; no codec frame-rate peak; SS +1 dB brighter |
| same: waveform NCC, SS vs RS top band | **0.635**. With independent codec noise of equal power, that is ≈ 36% noise energy (SNR ≈ 2.4 dB) **in both packs** |
| `hybrid16_joins.py`: top-band energy spikes at run edges | > +6 dB at 27% of SS edges vs 21% mid-run; RS 25% vs 18%. Small, and not pack-specific |

Reading:
- ScanSoft's encode is not worse than RealSpeak's.
- The ACELP coder spends almost nothing on 3.4–8 kHz, so the "real" band has the right
  envelope and timing but noisy fine structure.
- "The SS half" is the real-band half: ~87% of the verified band comes from SS.

**v4, re-texture** (`hybrid16_bwe.render2`, `hybrid16_build.py`):
- One pitch-modulated noise excitation (depth 0.3) runs through the whole recording.
- The envelope comes from the real band where verified, from the net elsewhere. Both are
  smoothed over 9 bins (~280 Hz) × 3 frames (30 ms).
- The envelopes crossfade in log space (30 ms). The fine structure never switches.
- Calibration on 234 held-out recordings (`hybrid16_build.py calibrate`): the predicted
  envelope's bias is −0.2 dB (per bin −0.6…+0.1); resynthesis gain is +2.7 dB.

Demo: `C:\tmp\hybrid16_demo4\ALL_B_F_G.wav` plays AudioSR → F re-texture → G smooth BWE
only, for each recording.

**User pick: G** ("F/G sound about the same; G is ever so slightly smoother").

**Built: `C:\tmp\hybrid16\tom16_bwe.vdb`** (`hybrid16_build.py full --bwe-only`, ~10 min).
Checks with `tools\hybrid16_verify.py`:
- **File:** 237,632,574 B. The header through `indx` (0x20960 B) is byte-identical to the
  AudioSR `tom16.vdb`.
- **Low band:** matches tom8 ×2 at NCC p50 0.99995 (p1 0.99958) over 200 random recordings.
- **Top band:** sits 18.7 dB below the low band (p10–p90 −24.9…−14.8). Mirror r is −0.00.
- **Clipping:** the first build hard-clipped 9,253 samples in 3,097 recordings
  (`tools\hybrid16_clip.py`). Mu-law tom8 peaks at 32,124, but its ×2 upsample rings to
  ~38k on transients; AudioSR's file has none. A look-ahead limiter (`hybrid16_build.limit`)
  fixes it: sliding minimum of the needed gain over ±4 ms, then a Hann over the same span.
  Output never exceeds the 32,000 ceiling; gain is 1 away from peaks. Rebuilt: peak 32,000,
  0 samples at full scale.

#### 10.8.4 v5: the real take itself, full band, AudioSR-filled → H8, DEPLOYED (2026-10-23)

User redirect after the BWE builds: "AudioSR sounds great; this, not so much".
- Use the SS/RS 22 kHz output itself, brought to 16 kHz as faithfully as possible.
- Fill the gaps from AudioSR and hide the seams.
- Add 16 kHz to spfy and re-test there, in default mode (vendor Tom has no pitch marks).

**Inputs:**
- **Corpora SSoT:** `ScanSoft\ss_tom_full.wav` and `RealSpeak\rs_tom_full.wav` (moved 2026-10-24 from the
  folder root into the git-ignored pack folders), the fresh `codsb_dump` with
  D1+D2.
  - They are sample-identical in layout to the Aug-8 copies (`tools\corpus_swap_check.py`:
    lag 0 at 40/40 probes, NCC 0.98–0.99), so `runs.json` stays valid.
  - The fresh SS decode is ~7 dB louder.
- **AudioSR original:** `Documents\Speechify\en-US\tom\audiosr_tom16.vdb`.

**`tools\hybrid16_v5.py`, per run:**
1. Fractional alignment at 22.05 kHz.
2. ONE resampling step: a Kaiser-windowed sinc (256 taps, fc 7.75 kHz, β 9) evaluated on the
   GPU directly at tom8's 16 kHz sample times.
3. Gain matched to AudioSR on 1–3 kHz, one gain per pack per recording.
4. 20 ms cells kept at 0.3–3.4 kHz NCC ≥ 0.80.
5. Per-run weights: islands < 100 ms dropped, 20 ms coherent crossfades.
6. The look-ahead limiter.

**Variants, by ear** (comparisons via spfy `--16k`; files in `C:\tmp\spfy16k_test\`):

| variant | top band (> 4 kHz) | user verdict | measured reason |
|---|---|---|---|
| H | real where covered, raw AudioSR elsewhere | no seams, but "the takes differ between arms" | voiced frames: AudioSR is 6–11 dB brighter at 4–7 kHz (mirror). A static EQ removes only 27% of the per-frame gap (`hybrid16_v5_eq.py`) |
| H3 | AudioSR EQ'd to the real take | best of H/H3/Hm, but Tom "switches" on sibilants | same-frame /s/: real +7.7 / +17.8 / +35.7 dB over the filler at 4.5–6 / 6–7 / 7–8 k (`hybrid16_switch.py`) |
| H5 | filler /s/ → Tom BWE noise | "arguably worse" | matched the WRONG target: the filler was pulled UP to the real take's full-band /s/ |
| H6 | real /s/ cut, keyed on tom8 sibilance | stripes remain | band-limited tom8 barely flags many /s/ |
| H7 | real arms capped at AudioSR's same-instant level > 4.5 kHz (`asr_ceiling`) | "much better"; deployed, then "fading in and out between Toms" | the top band still swaps source at every handover |
| **H8** | **pure AudioSR everywhere**; the real take only < 4 kHz, EQ'd onto AudioSR (`real2asr_{ss,rs}`); 511-tap complementary split | **"by far, wins"** | the top band never changes source; below 4 kHz the arms already agree within ±1–2 dB and are phase-aligned |

**Retracted along the way:**
- A different-frames version of the switch test that showed H5 overshooting by 5–8 dB.
  That was selection bias, 21 vs 201 frames.
- The `hybrid16_verify.py` mirror label "+0.69". That was a different aggregation; raw
  AudioSR scores +0.98 on the verify metric.

**Deployed** (`Documents\Speechify\en-US\tom\`):
- `tom16.vdb` is **H8** (sha256 3d981fa3…). `h8_tom16.vdb` is a spare.
- `h7_tom16.vdb`, `deess8_tom16.vdb`, `audiosr_tom16.vdb` and `noess_new_tom16.vdb` are kept.
- Rebuild: `python -I tools\hybrid16_v5.py full --eq h8` → `C:\tmp\hybrid16\tom16_v5_h8.vdb`,
  ~3 min. It needs `C:\tmp\hybrid16\{runs.json,tom8_f32.npy,v5_eq.json}`.
- Verify: `python -I tools\hybrid16_verify.py <vdb>`. Header and size identical; peak 32,000;
  0 samples at full scale.

**Lesson:** the user's sonic reference is pure AudioSR. The ScanSoft/RealSpeak takes earn
their place only below 4 kHz, where clean ACELP replaces tom8's mu-law.

### 10.9 What the Speechify VIN can say about the non-Speechify audio (2026-10-23)

**VIN metadata** (`tools\vin_ckls.py`):
- `ICOP` = `Copyright 2003 SpeechWorks International, Inc. All Rights Reserved.`
- `ICRD` = **2003-05-12**
- `vers` = `3.0.0.0alpha`
- `cnts` = 92 / 16 / 169,579
- `tom8.vdb` file date 2003-05-28. The Speechify Tom audio existed by May 2003,
  three months before the SpeechWorks acquisition.

**Pack file dates** (preserved mtimes, `tools\scansoft_stamp_dates.py`):

| | unit DB | audio | voice font PE |
|---|---|---|---|
| SS 2004 Tom | 2004-06-17 | 2004-06-20 | 2004-07-22 |
| RS 2006 Tom | 2006-04-20 | 2006-04-20 | 2006-05-16 |

Header **+0x84 is not a date** under the 1970 or 1980 epochs: `265498` decodes
to January 1980, and Emily's value would postdate her own file. The ~13 months
between May 2003 and June 2004 leave room for new sessions. The dates neither
show nor exclude them.

**Recording names are complete** (`tools\tom8_name_gaps.py`):
- All 82 `family<session>_<item>` sessions are gap-free: 8,138 of 8,139, with
  `weather4_038` the only hole. Most sessions run `_001..._100`.
- So **Speechify kept every numbered SpeechWorks prompt**. ScanSoft's
  non-Speechify audio (≈ 3+ h in SS 2004) is not "the prompts Speechify dropped".
  It must be unnumbered retakes, other material, or new sessions.
- Also: 21 recordings are in the VDB but never referenced by the VIN (one
  empty name, `email3_021..024`, `news1_009`, …), so Speechify shelved a little audio itself.

**ckls, the checklist as timed words** (`tools\vin_ckls.py`):
- The parse is exact: 394,375 / 394,375 B, and all 13,026 tokens agree with the
  unit table's filenames.
- `_WORD_`: 5,108 tokens, 1,075 unique, in 2,816 recordings; p50 176 ms, 22.8
  min of labelled speech (~18% of tom8). `_SYL_`: 7,918 tokens, 1,350 unique.

**Which checklist words ScanSoft kept** (`tools\ckls_coverage.py`). This uses
the coverage map over 400 checklist-bearing recordings (seed-and-extend as
§10.8): speech coverage SS 43.5%, RS 20.0%, either 49.0%, both 14.6%.

| 717 word tokens | fully kept (≥ 80%) | partial | fully dropped (≤ 20%) |
|---|---:|---:|---:|
| either pack | **48.4%** | 11.0% | **40.6%** |

- **Keeping is all-or-nothing per word.** Only 11% of words are split, which fits
  word-scale pieces.
- **Coverage edges sit only slightly nearer checklist word boundaries than random
  positions do:** median 180 vs 160 ms; 24% vs 20% within 40 ms. The checklist
  labels only some of each prompt's words, so this test is weak.
- **Which word it is explains 29% of the variance.** Every family is roughly half
  kept (news 55%, dip 60%, weather 45%, pn 34%).

**ScanSoft's own phone labels are readable** (`tools\ss_label_check.py`).
- **Method:** at 4,115 locked SS↔tom8 instants, the trusted tom8 phone
  (`phone_center` → `labl`, darpa) is compared with the SS unit label (+9, SAMPA)
  over a sweep of label offsets.
- **Peak:** −2370 samples @22k (**−107 ms**), MI 1.588 bits vs 0.760 ± 0.119 at
  far offsets. That refines `ss_rs`'s −80 ms; the peak is broad, −93 to −132 ms.
- **Empirical mapping**, top SAMPA per darpa phone:
  - `iy→i` 75%, `ng→N` 89%, `el→L` 77%, `ax→$` 69%, `z→z` 69%
  - `pau→#` 69%, `uw→u` 64%, `ey→J` 59%, `ow→O` 54%, `n→n` 48%
  - `ix→0x8b` 47%, `er→e` 44%, `t→t` 41%, `v→v` 41%, `ch→0x8b/C`, `dx→R` 34%
- **Many-to-one accuracy at a single instant is only 38.8%.** The labels mean
  what they say but are noisy point by point. Reading words out of SS-only audio
  would need tolerant (edit-distance) matching.

### 10.10 Retakes of Speechify-script words in the non-Speechify audio (2026-10-23)

**Label route: FAILED, kept as a negative** (`tools\ss_retake_test.py`). Fuzzy
SAMPA matching of CMUdict pronunciations in the SS label stream found **0/21**
known Speechify takes inside SS. At 39% per-instant accuracy, 5–8 phone words
never read cleanly. The ZIPF ≤ 3.3 cut also left only 6 targets. This is a
verdict on the instrument, not on the audio.

**Acoustic route: query-by-example** (`tools\qbe_retake_test.py`):
- **Method:** each checklist token's own tom8 audio is a template (12 MFCC,
  0–4 kHz, 10 ms, global CMN). It is matched by cosine against every SS window
  at time scales 0.85 / 1.0 / 1.15, on the GPU.
- **Exclusion:** the best SS window that is **not** the Speechify take itself
  (waveform NCC vs the token ≤ 0.6) is kept.
- **Bug fixed before the reported run:** chunked MFCC was dropping 2 frames at
  each 8 M-sample boundary, a frame↔sample drift of up to 140 ms.

| | result |
|---|---|
| **calibration** (tom8, 300 tokens of words recorded in ≥ 2 recordings): best match in another recording IS another checklist take of the same word | **157/300 = 52.3%**; score p50 0.822 when correct, 0.797 when not |
| reversed-template null, SS | p95 = 0.832 |
#### ⚠ First run RETRACTED: the same-take filter leaked

The first run excluded "the Speechify take itself" with a whole-word NCC ≤ 0.6.
It reported COMMON 50.7% and RARE 36.7% above the null, led by news names
(`minister's`, `israel's`, `belgrade`, `hague`, `barak`). It read that as
"outtakes/retakes of the SpeechWorks script".

**The user listened: `belgrade` was the SAME take**, not a retake. SS stores
audio in ~0.4–0.5 s pieces, so a word can straddle a cut and score low on
whole-word NCC while being the very same recording.

#### Re-run with `same_take()`: any 100 ms slice of the token locks at NCC > 0.75

113 same-take candidates were excluded, across 93 words (`much`, `minister`,
`value`, `six`, `policy`, …).

| class | above reversed-null p95 (0.832) | above tom8 true-retake p50 (0.822) |
|---|---:|---:|
| **COMMON** (zipf ≥ 5.0, 148 types) | **33.8%** | 38.5% |
| **RARE** (zipf ≤ 3.8, 30 types) | **16.7%** (5/30; null 5%) | 16.7% |

Strongest remaining RARE matches:
- spelled letters / URL parts: `ess` 0.879, `aitch` 0.870, `org` 0.851, `doubleyou` 0.819, `eff` 0.794
- numbers: `thirtys` 0.868, `seventy` 0.839
- other: `useed`, `fiery`, `cloudy`, `unionists`, `companys`, all ≤ 0.805

**Every era-specific news name dropped out.** All of them were Speechify's own
take.

**Reading:**
- The non-Speechify SS audio contains other takes of common words (expected
  from any English script) and of letter names and numbers. Any script with
  spelled addresses, email and numbers has those.
- It shows **no retakes of the news-specific Speechify script**. Where SS
  holds those words, it holds Speechify's own takes.
- So **this test does not support "outtakes of the SpeechWorks script"**. It
  is mildly against news-script retakes, and silent on whether the extra audio
  is a different script or later sessions.
- The session question stays **OPEN**, now with that lean.
- Caveats: 30 rare types; QbE can match look-alikes; RS 2006 not tested.

Listening pairs (re-run): `C:\tmp\tom_overlap\qbe_listen\<word>_{spfy,ss}.wav`.

### 10.11 Not done yet

- **RS 2006** through the same QbE test.
- More rare targets: relax to zipf ≤ 4.2, add `_SYL_` tokens.
- **The decisive session test, label version.** Read the SS-only audio as phone strings and ask
  whether it contains **retakes of checklist words that are specific to
  Speechify's script** (proper nouns, script-specific phrases), at a rate a
  different script would not produce. Calibrate the tolerant matcher on SS
  material locked to tom8, where the true word is known.

- **What the real cut points are**, and whether the stored pieces' order follows
  the unit table.
- Why some long same-lag spans contain a non-matching middle (§10.2, point 3).

---

## 11. Open

Answered 2026-10-23, by the user: all three Toms are the same talent, **Tom
Glynn** (Boston VO). See `README.md` "Answered". The measurements in §2 and §7
are consistent with one speaker and three separate voice builds.

- TOC `u16[3]` (50/47), blob `[2n+1]` = 3, blob `[2n+3..2n+5]`, and codec
  vtable +0x46 = 50.
- ~~What +0x80 (173 etc.) means.~~ It seeds the speaking-rate (wpm) table, so it is the
  voice's **native words per minute** (INFERRED from its use; Tom = 173).
  `notes\synth_concat_2006.md`.
- ~~The 0x7Fxx Q15 taper.~~ **RESOLVED.**
  - It is four join crossfade windows at `0x1001110c`, one per sample rate (81 / 113 / 161 /
    221 entries).
  - Shape: `32736·½(1+cos(π(n+½)/L))` within ±1 LSB, exactly complementary
    (T[n]+T[L−1−n] = 32736). Copy the values; no rounding rule reproduces them exactly.
  - Used only by the join functions, not by rate change. Spot-checked: 32733, 32709,
    32660, 32586…
- ~~Unnamed `synth_GetInterface` slots.~~ **RESOLVED** (the SS and RS synth DLLs are
  byte-identical, sha256 d12c7c00…):

  | slot | role |
  |---|---|
  | `0x10001820` | no-op class stubs |
  | `0x10001830` | ObjOpen (builds the stage chain) |
  | `0x10002860` | SetParam by id |
  | `0x10002220` | **ToPcm** |
  | `0x100022d0` | pause/marker-only input |
  | `0x10001540` | voice-compatibility check |
  | `0x100062e0` | codec decode |

### 11.1 Engine round 2 (2026-10-23): prosody, synthesis, engine core

Full write-ups:
- `notes\prosody_2006.md` (by hand)
- `notes\synth_concat_2006.md` and `notes\ttsengine_xcoder_2006.md` (subagents; load-bearing
  claims spot-checked)

The three DLL_ANALYSIS §7 tables summarise them. The thread that ties them together:
**nothing in the 2006 engine computes or applies a pitch target.**
- Prosody is symbolic: breaks, pauses, rewrite rules.
- Unit selection supplies durations and rates.
- The synth only concatenates, with 4 join types, then WSOLA for rate and a volume ramp.
  It never shifts pitch.
- The `pitch` parameter is stored by `ttsengine.dll` and read by no other component. Its
  name occurs in no voice font or synth DLL of either pack (checked).
