# ScanSoft / RealSpeak Solo v4 DLL Analysis

Companion to `README.md` and `README_TECHNICAL.md`. Speechify's own DLL analysis
is `..\Speechify\reveng\DLL_ANALYSIS.md`, cited as
`spfy DLL §N`. The broker (`combrk.dll`) and the voice-font section directory
are closed out in `Speechify\reveng\ss_rs\README_TECHNICAL.md` §2–§3 and not
repeated here.

**Dated 2026-10-23.** Base 0x10000000 for every ScanSoft/RealSpeak DLL.

Ghidra programs (pass `program=` by path; the two voice fonts share a name):

| path | binary |
|---|---|
| `/ss_synth_155mrf22.dll` | `ScanSoft\speech\components\synthesizer\synth_155mrf22.dll` |
| `/ss_vf_tom_full.dll` | `ScanSoft\speech\components\voicefont\vf_tom_full.dll` |
| `/rs_vf_tom_full.dll` | `RealSpeak\speech\components\voicefont\vf_tom_full.dll` |
| `/spfy_SWIttsUSel.dll` | `..\Speechify\bin\SWIttsUSel.dll` (base 0x08e80000) |

---

## 1. Build-tooling forensics: what MADE ScanSoft / RealSpeak

Source: PE headers, Rich headers, CodeView records, version resources and
`.rdata` strings of all 129 binaries across the three packs
(`tools\pe_survey.py`, output `tools\pe_survey_2026-10-23.json`). The method is
the same as `spfy DLL` "Build-Tooling Forensics", so the two can be compared row by row.

### 1.1 Compiler and linker

**Every ScanSoft/RealSpeak module is MSVC 6.0**: linker 6.0, Rich compiler ids
8966 / 8797, plus 8034/8047/8569 in the SAPI and ActiveX modules. Speechify is
uniformly MSVC 7.1 (13.10.3077, linker 7.10). No module in either family uses the
other's toolset.

`ssftrssolo.ocx` (the ActiveX control, 2004-11-30, byte-identical in both packs)
has its own Rich profile (8047/8569) and static MFC. Its string overlap with
Speechify's `mfc71.dll` is MFC RTTI names and CRT messages, which every MFC
version shares. It is not evidence of a shared toolchain.

### 1.2 Build roots (CodeView PDB paths, RealSpeak 2006 builds only)

```
F:\common.a\win32.x86\rel\cdf_prd\<component>\...\<module>.pdb       audiofetch, audioout, combrk,
                                                                     comrsrc\lite, comsyssvc, dcteg,
                                                                     edct, xcoder\lite, xlit\1252
F:\ttssrc.a\win32.x86\rel\tts_predev_prd\<subsys>\...\<module>.pdb   g2p\{enu,spm}, pp\std\{enu,spm},
                                                                     vf\synth\{112mrf16,155mrf22,83swf11},
                                                                     vf\voices\<lang>\<voice>\full,
                                                                     domain_mngr
H:\ttssrc.a\win32.x86\rel\tts_predev_prd\{rs_sapi5_solo,ttseg}\      rs_sapi5_solo, ttsengine
H:\ttssrc.a\win32.x86\rel\embed\spapi\rssoloapi_prd\lhs_ansi\        rssoloapi
H:\ttssrc.a\win32.x86\rel\ttt_main\regex\cdf_prd\                    rettt
L:\ttssrc.a\win32.x86\rel\tts_predev_prd\{g2p\eng,vf\voices\eng\emily\full}
```

- **Two source trees**: `common.a` (the CDF framework) and `ttssrc.a` (the TTS
  product). Configurations are named `*_prd`.
- **Three drive letters** (F:, H:, L:) for the same `ttssrc.a` tree: either
  several build hosts or several mapped views. The `.a` suffix is unexplained.
- **The voice-font path encodes language, voice and variant**:
  `vf\voices\enu\tom\full`. The voice font is a per-voice build target, which
  matches `ss_rs §3`'s finding that the section directory is compiled into the DLL.
- **`lhs_ansi`** in the `rssoloapi` path: an L&H-era configuration name (INFERRED).
- The 2004 ScanSoft builds carry no PDB record at all.

### 1.3 Version control

**None visible.** No `$Id$`, `$Header$` or `$Name$` in any SS/RS binary.
Speechify has 150 `$Id$` rows (`spfy DLL §1.2`).

### 1.4 Component banners: the CDF registry

Each component carries a `#TTSSO_VER` banner of the form
`ScanSoft\nCDF <module> <version>\nCopyright <year>`. That gives a version
registry independent of the PE version resource:

| module | SS 2004 | RS 2006 | note |
|---|---|---|---|
| combrk | 1.03 (2002) | 1.03 | broker |
| comrsrc | 1.03.01 (2004) | same | also carries "ScanSoft Protection System for the Unified SDK." |
| ttsengine | 1.6 (2003) | 1.6 | |
| synth_155mrf22 / 112mrf16 / 83swf11 | 2.0 (2004) | 2.0 | |
| g2p_enu / stdpp_enu | 2.00 (2003) | 2.00 | |
| g2p_eng | — | 4.1 (2003-2005) | |
| empp_enu / jpj / kok | 2.0 / 1.1 / 1.01 (2003) | — | also carry an **L&H copyright** (§1.5) |
| `vf_tom_full` | **`vf_jennifer_full 1.00` (2003)** | **`vf_jennifer_full 1.00`** | template banner, never renamed |
| `vf_jill_full` | — | **`vf_jennifer_full 1.00`** | same template |
| vf_kyoko / narae | own name 1.00 | — | |
| vf_daniel / karen / lee / paulina | — | own name 4.0 | |
| vf_samantha | — | own name 4.01 (2006) | |
| rettt | — | `smspp 0.1` (2005) | regex text-transform preprocessor |

The Jennifer banner is at `0x100be010` in the SS Tom voice font.

### 1.5 Vendor marks

| string | where |
|---|---|
| `Copyright 1993-1997 / 1998 - 2000 / 2000  Lernout & Hauspie Speech Products (tm) N.V.` | SS `empp_jpj`, `empp_enu`, `empp_kok` |
| `CompanyName = Lernout & Hauspie Speech Produ…`, FileVersion 6,0,0,0 | SS `empp_kok.dll` version resource |
| `lh_ErrorGetString` route (bit 0x2000) | `combrk.dll` (`ss_rs §2`) |
| `L&H+ string.` | `comrsrc.dll`, `rssoloapi.dll` (both packs) |
| `L&H TTS ActiveX` | `ssftrssolo.ocx` |
| `L&H: %s SAPI5: %d` | RS `rs_sapi5_solo.dll` |

CompanyName runs "ScanSoft, Inc." → "Nuance Communications, Inc." from the
2006-02 builds onward. The 2004 voice fonts and `swisolo.dll` stay "ScanSoft, Inc.".

### 1.6 What is shared with Speechify, string by string

`tools\shared_strings.py` intersects every non-CRT printable string (≥ 8 chars,
ASCII and UTF-16) between SS∪RS and Speechify's `bin\`:

- 536 strings are shared. Almost all are noise: relocation-table byte runs, MFC 7.1
  RTTI names, CRT messages, SAPI5 interface names (`ISpTTSEngineSite Interface`,
  `ISpObjectToken InterfaceWW`), CJK code-page tables.
- **The only real overlap is in `swisolo.dll`**: `application/x-swi-dictionary`,
  `tts.audioformat.samplerate`, `tts.network.connecttimeout`,
  `hostname parameter set twice`, `text/plain;charset=wchar_t`. They are
  Speechify API-surface strings (§4).
- No Flite, Festival, WSOLA, `cst_*`, `SBlog`, `VXI` or SpeechWorks copyright
  string occurs in any SS/RS binary.

---

## 2. `synth_155mrf22.dll` — the `codsb` decoder

110,686 B, 281 functions, single export `synth_GetInterface` (ordinal 1).
Imports CDF only (`heap_*`, `paramc_*`, `critsec_*`, `safeh_*`, `brk_*`,
`osspi_*`, `InitRsrcFunction`). Behaviour is in `README_TECHNICAL.md` §2–§6.
This section is the address map.

### 2.1 Interfaces

| table | getter | contents |
|---|---|---|
| `0x100110c8` | `synth_GetInterface` (`0x10002b60`, `ver < 2`, else `0x81002001`) | slots 2–13; see below |
| `0x10011a20` | `FUN_10006740` (`ver < 2`, else `0x86306001`) | ACELP codec: +0x10 create `FUN_10005ee0`, +0x14 destroy `FUN_10006240`, +0x34 address `FUN_100060f0`, +0x38 decode `0x100062e0` |
| `0x10012188` | `FUN_1000ee70` (`ver < 2`, else `0x87002001`) | PCM pass-through codec (`FUN_1000ef80`) |

`synth_GetInterface` slots:

| slot | address | role |
|---:|---|---|
| 2, 3 | `0x10001820` | no function defined; ClassOpen/Close INFERRED by analogy with `vf_GetInterface` |
| 4 | `0x10001830` | no function defined; ObjOpen INFERRED |
| 5 | `FUN_100020b0` | **ObjClose**: closes three sub-objects (+0x48, +0x60, +0x78), frees buffers, drops the `waitfactor` / `markermode` listeners |
| 6 | `FUN_10002700` | **GetParam**: ids 3/7 forward to sub-object +0x5c (as 1/10), ids 6/8/0xb forward to +0x74 (as 5/0xb/6), id 4 = `FUN_10003010`, id 5 = the critsec-guarded u16 at +0x100 |
| 7 | `0x10002860` | no function defined |
| 8 | `FUN_10002ac0` | **SetParam / ResetParam**: id 4 → `waitfactor`, id 5 → `markermode` via `paramc_ParamSet`, others forwarded |
| 9 | `FUN_10002a70` | **ResetParams** |
| 10, 11 | `0x10002220`, `0x100022d0` | no function defined; ToPcm path INFERRED |
| 12 | `FUN_100011b0` | lazy open of the `.dat` (`FUN_10005950`) |
| 13 | `0x10001540` | no function defined |

The table is followed by floats 0.5, 0.2, 0.001 and a decreasing Q15 run
(0x7FDD, 0x7FC5, 0x7F94, 0x7F4A, …). Unidentified.

### 2.2 Data access

| function | role |
|---|---|
| `FUN_10005950` | open the `.dat` via `brk_DataOpen`, parse, create codec |
| `FUN_10005d50` | map the 0x90 header; copy the TOC (`toc_len − 0x90`) to the heap |
| `FUN_10005cb0` | header parse: coder @0x54 (32 B, trailing spaces → NUL), toc_len @0x7c, `atoi` of 3 bytes @0x80 → obj+0x54 |
| `FUN_10005ec0` | returns obj+0x54 (the +0x80 number) |
| `FUN_10005b60` | map one unit: codec +0x34, then `brk_DataMap(toc_len + off, len)` |
| `FUN_10005bf0` | unmap |
| `FUN_10005c30` | decode call through codec +0x38 |
| `FUN_10005ee0` | codec create: parses TOC `u16[0..2]`, sets up the addressing object (0x2ac) |
| `FUN_10006200` | handle check, class 99, size 0x2ac (error `0x86306008`) |
| `FUN_100060f0` | **unit addressing**: +40 delay, −6 lookback, decoder reset |
| `FUN_10006240` | destroy |
| `FUN_10006bf0` | 0x440-byte rate object: `ratewpm` / `raterelchg` / `pausestatus` listeners; default rate 0x32 |

### 2.3 Codec core (codec id `0x102102`, version `0xFA5`)

| function | role |
|---|---|
| `FUN_1000eb60` | descriptor query: mode → bytes, bits, bitrate, sizes |
| `FUN_1000df60` | create: validate the blob size identity, bind codebook, set variant, call init |
| `FUN_1000e070` | init the configuration and the state |
| `FUN_1000e150` | clear the dynamic state |
| `FUN_1000eaa0` | reset: clear, plus gp = 0xE400, g_prev = 0x0CCC, uniform prev LSF |
| `FUN_1000ea30` / `FUN_1000ea70` | handle check (class 0x10062, size 0x660) / release |
| `FUN_1000e190` | **one frame** |
| `FUN_1000ec90` / `FUN_1000ed30` | bit explode / field gather (LSB-first) |
| `FUN_1000f9a0` | LSF multi-stage VQ |
| `FUN_1000f730` / `FUN_1000f7c0` | LSF ordering (2 or 5 passes) / spacing (mode 3 only) |
| `FUN_10006860` | uniform LSF fill |
| `FUN_100067e0` | LSF interpolation (Q15 weight) |
| `FUN_1000f480` | LSF → cos (8192-entry table `0x10012244`) |
| `FUN_1000f4e0` | LSP → LPC (int32) |
| `FUN_1000f6d0` | bandwidth expansion (γ = 0x7EF9) |
| `FUN_1000f390` | 1/A(z), 32-bit state |
| `FUN_1000f310` | DC-blocking high-pass (0x7EB8) |
| `FUN_10010550` | pitch lag decode |
| `FUN_10010520` | adaptive-codebook copy |
| `FUN_1000fd30` / `FUN_10010140` | 5-pulse / 4-pulse algebraic codebook |
| `FUN_1000fbf0` | fixed gain (4 shift bands) |
| `FUN_1000fa60` / `FUN_1000fb10` | predicted gain from vector / analytic energy |
| `FUN_1000fbb0` | MA history update |
| `FUN_1000de90` / `FUN_1000dee0` | interpolated log / exp table lookups |
| `FUN_1000dd20` / `FUN_1000dd90` | saturating add / sub |
| `FUN_1000de40` / `FUN_1000ddc0` | Q-format 32×16 / 32×32 multiplies |
| `FUN_10006760` / `FUN_10006780` | copy dwords / halfwords |
| `FUN_100067b0` / `FUN_100067c0` | zero dwords / halfwords |
| `FUN_1000ed90` | Latin-1 lower-case mapping (unrelated utility) |

Data:

| address | contents |
|---|---|
| `0x1001202c` | LSF interpolation weights `{8192, 16384, 24576, 0}` |
| `0x10012034` | bit allocation, 3 rows × 0x70 |
| `0x10012244` | cos[8192] |
| `0x10016244` | MA[4] |
| `0x1001654c` | log[1024] |
| `0x10016d4c` | exp[2048] |
| `0x1001754c` | pitch gain[256], Q14 |
| `0x10017750` | fixed-gain correction[64] |

### 2.4 Error scheme

Module = `(code >> 20) & 0x7ff`. Every code here has bit 0x2000 set, which is
`combrk`'s route to `lh_ErrorGetString` (`ss_rs §2`).

| range | module | origin |
|---|---:|---|
| `0x810020xx` | 0x010 | synth interface layer |
| `0x862020xx` | 0x062 | ACELP codec core |
| `0x863060xx` | 0x063 | codec wrapper and addressing |
| `0x870020xx` | 0x070 | PCM codec |

Codes seen in the codec core:

| code | meaning |
|---|---|
| `…01` | bad flags / mode |
| `…06` | null argument |
| `…07` | mode bits out of range |
| `…08` | null handle |
| `…09` | short input / bad blob size |
| `…0a` | out of memory |
| `…100` | wrong codec id / version |

Speechify's `SWIttsRiffResult` and `SWItts` error catalog share nothing with this
scheme (`spfy DLL §9.5`).

---

## 3. Unit selection three ways: ScanSoft 2004 vs RealSpeak 2006 vs Speechify 3.0.5

Probes: `tools\func_match.py`, `tools\imm_scan.py`, `tools\find_dur_table.py`,
`tools\vf_iface.py`, `tools\verify_dur_table.py`. Read-only Ghidra session.

### 3.1 Headline

**No shared object code. Shared design, and one shared table.**

**The duration-continuity table at `DAT_100b75b0` in the ScanSoft 2004 voice
font is Speechify Tom's own table, `floor(10·x)`, 100 of 100 entries.**
CONFIRMED twice, independently:
- by the fork's scan
- by `tools\verify_dur_table.py`, which decrypts `Speechify\en-US\tom\tom.vin`
  (XOR 0xCE) and reads 100 f32 at file offset 34,264,578

```
Speechify tom.vin   6.789 6.043 5.418 4.895 4.109 3.348 2.570 1.748 0.824 0.000 0.218 1.302 2.154 2.879
ScanSoft 100b75b0      67    60    54    48    41    33    25    17     8     0     2    13    21    28
```

The fork's sweep found no copy elsewhere:
- absent from Speechify Jill, Paulina, Javier and Felix (it is in `aicraig.vin`,
  a Tom derivative). So it is voice-build output, not an engine constant.
- absent from every other DLL and `.dat` in both packs, including RealSpeak 2006 Tom.

**Same talent:** all three Toms are Tom Glynn (user, 2026-10-23). So the copied
table is a SpeechWorks build output for the same speaker, reused when ScanSoft
built his 22 kHz voice. It is not one voice's data grafted onto another's.

**Direction, INFERRED: Speechify → ScanSoft.** It is a data file in Speechify
and a compiled-in constant in a ScanSoft font built from the Jennifer template,
2004-07. Speechify's `usel_*.cpp` are dated 2003-04..2003-10, and SpeechWorks
was acquired Aug 2003.

### 3.2 Architecture side by side

| | ScanSoft 2004 | RealSpeak 2006 | Speechify 3.0.5 |
|---|---|---|---|
| arithmetic | integer, 1.0 ≙ 100,000 (INFERRED from the 6000 and 2500 constants) | integer, same scale | float32 |
| unit | half-phone, `2·n_phones − 1` slots (`FUN_10004610`) | half-phone (`FUN_10004bf0`) | half-phone (`SWIttsUSelUnitSelection` 0x08e819e0) |
| preselect | base-131 triphone key, 3-level backoff (`FUN_10015e50`) | same encoding (`FUN_10018e00`) | `prsl` cache + context key (0x08e89a70) |
| target cost | 2 phone-substitution matrices + 8 feature sub-costs (`FUN_100073a0`: `FUN_1000f7e0` matrix·w, `FUN_1000f9b0` w·Δ²·10/var, `FUN_1000fb70` w·flag·10, …) | 12 feature sub-costs (`FUN_1000a7b0` → `FUN_10012530..FUN_10012ae0`) | 5 CART-predicted prosody costs + 4-slot `ccos` context + quadratic dur/F0 + stress/unit bias (0x08e88de0) |
| join cost | precomputed row-displacement table G/H; miss → +10,000,000 (`FUN_10007f20` @0x10008022) | **runtime** 3-point over three 7-bit codes, 3 × 128×128 byte tables (`FUN_1000b230`) | precomputed `hash` (row-displacement) or runtime edge-frame kernel `FUN_08e8c440` |
| join fallback | duration-continuity table, gated (§3.3) | same mechanism, **retrained** table `DAT_10027900`, per-node weight | same, `0.6 · table[dl_cur + 50 − dl_prev]` |
| contiguity | ±3 ticks on `pos + len`, bit 31 vetoes (`FUN_10004900`) | identical test (head of `FUN_1000b230`) | `left == right − 1` uid adjacency |
| pruning | 40-bin histogram, 2500/bin, cut `0.8 − 0.005·cum`, beam best + 80,000 (`FUN_100073a0` @0x100079c2..0x10007a01) | **no histogram**: fixed beam best + 450,000, N-best cap (`FUN_1000a7b0`) | 40-bin histogram, 0.025/bin, cut `THRESH − SLOPE·cum`, SLOPE default 0.005 (0x08e88830) |
| search | Viterbi, branch-and-bound early exit (bound 4e9, `FUN_10004900` → `FUN_10007f20`) | same shape (`FUN_10004f10` → `FUN_1000b230`) | Viterbi, exhaustive pred loop + heapsort (0x08e8edd0 / 0x08e8b620) |
| node stride | 0x40 | 0x48 | 0x84+ |

### 3.3 Shared code? The honest test

**Binary level: none.** CONFIRMED by measurement, with one caveat. Every
function was compared by mnemonic 6-gram Jaccard similarity over call-target
entry points:

| pair | functions ≥ 30 instr | J ≥ 0.9 | J ≥ 0.5 | J ≥ 0.3 | best |
|---|---:|---:|---:|---:|---:|
| SS → RS (positive control) | 90 | 6 | 17 | 42 | 1.000 |
| SS → Speechify USel | 90 | 0 | 0 | 0 | 0.191 (CRT) |
| RS → Speechify USel | 87 | 0 | 0 | 0 | 0.213 (CRT) |

⚠ VC6 vs VC7.1, and integer vs float arithmetic, both depress this score. It
rules out shared object code, not shared source. The design-level evidence below
is the stronger instrument.

**Design level: the same.** CONFIRMED by decompilation, constant by constant.

The join-cost fallback (`FUN_10007f20` vs Speechify's hash-miss path 0x08e8b7f5..0x08e8b854):

| element | ScanSoft `FUN_10007f20` | Speechify `ViterbiWithJoinCache` |
|---|---|---|
| runs only on a cache miss of a non-contiguous pair | `!bVar3 && !bVar4` | hash-miss branch |
| gate 1: current unit's dl > 20 | `0x14 < node[+0x32]` | `[ecx+0x6c] > 0x14` |
| gate 2: predecessor's dl > 20 | `0x14 < node[+0x30]` | `[edx+0x7c] > 0x14` |
| gate 3: run counter < 15 | `node[+0x31] < 0xf` | `[edx+0x80] < 0xf` |
| index | `cur − prev + 0x32`, clamp 0..99 | `dl_cur + 50 − dl_prev` (count 100, offset −50) |
| scale | `byte · 6000` | `0.6 · f32` |
| table | `DAT_100b75b0` | Tom VIN, same values ×10 floored |

`6000 · floor(10x) ≈ 0.6 · x · 100,000`: that is where the 1.0 ≙ 100,000 scale comes from.

- **Join cache.** Same data structure: a row-displacement sparse matrix with a
  right-unit tag and `0xFFFFFFFF` sentinels in 8-byte `(tag, cost)` cells.
  - ScanSoft: `H[(left + G[right])·8]`, tag `== right`.
  - Speechify: `cell[rows[uid_right] + uid_left]`, tag `== uid_right` (0x08e8b7e6).
- **Pruner.** Same algorithm: a 40-bin histogram (cap 0x27) with a cut rule of
  the form `bin_edge > K − SLOPE·cum`.
  - ScanSoft: bin 2500 = 0.025, `(0xa0 − cum)·500 < edge` = `0.8 − 0.005·cum`.
  - Speechify: bin 0.025, `HALFPHONE_CAND_PRUNE_SLOPE` default **0.005**.
  - Only K differs: ScanSoft hard-codes 0.8, Speechify's Tom VCF sets 0.95.
- **RealSpeak 2006 keeps Speechify's 3-point join shape.** `FUN_1000b230` sums,
  per stream k = 0..2,
  `T_k[end(L)][end(R−1)] + T_k[start(L+1)][start(R)] + 2·T_k[end(L)][start(R)]`.
  That is Speechify `FUN_08e8d3a0`'s
  `kernel(end L, end R−1) + 2·kernel(end L, start R) + kernel(start L+1, start R)`,
  with the seam term doubled. Operand roles are INFERRED by analogy.
- **Voicing split: present but different.**
  - RealSpeak has 46-char per-phone strings `"uvuv…"` (voicing) and `"CVCC…"`
    (`0x1002fd7c` / `0x1002fd4c`).
  - It adds `w·0x3fc` when both phones are voiced and an edge dl < 21, plus a
    piecewise-linear F0 term (cap 1000).
  - Speechify instead picks V0/V1/V2 `(JCW, JCO)` by voicing (`FUN_08e8ed20`).

**Not shared:**
- arithmetic
- struct layouts
- the contiguity rule (position ±3 ticks vs uid adjacency)
- the target-cost model (feature-lane mismatch tables vs CART prosody trees + `ccos`)
- the preselect encoding (base-131 key vs `prsl`)
- logging (`FUN_10010360(log, mod, lvl, 0, "Entering vf_X")` vs SBlog/SWIttsLog)
- the error scheme (§2.4)

**ScanSoft vs RealSpeak: the same source tree, evolved.** 10 functions are
mnemonic-identical, and 42 of 90 non-trivial functions match at J ≥ 0.3:

| stage | SS | RS |
|---|---|---|
| Viterbi | `FUN_10004610` | `FUN_10004bf0` |
| context build | `FUN_10004820` | `FUN_10004e00` |
| DP step | `FUN_10004900` | `FUN_10004f10` |
| scorer | `FUN_100073a0` | `FUN_1000a7b0` |
| join | `FUN_10007f20` | `FUN_1000b230` |
| preselect | `FUN_10015e50` | `FUN_10018e00` |
| segment merge | `FUN_10005060` | `FUN_100059e0` |

What changed in 2006:
- the G/H precomputed table was dropped for the runtime join
- the histogram pruner was dropped for a fixed beam of 450,000
- target sub-costs went from 8 to 12
- the duration table was retrained (`DAT_10027900`)
- the `·6000` constant became a per-node weight

### 3.4 `vf_GetInterface`

`vf_GetInterface(ver, out)` returns the table for `ver < 2`, else `0x81002001`.

| | getter | table |
|---|---|---|
| SS | `0x10002410` | `0x10017068` |
| RS | `0x100028b0` | `0x100190a0` |

| slot | SS | RS | role (from the slot's log strings) |
|---:|---|---|---|
| 2, 3 | `0x100012b0` | `0x100012b0` | stub |
| 4 | `0x10001350` | `0x10001350` | **vf_ObjOpen** (`pros_ObjOpen failed`, `vf_ext/configure`, paramc coder/voice/freq) |
| 5 | `0x100012c0` | `0x100012c0` | **vf_ObjClose** |
| 7 | `0x10001ec0` | `0x10002360` | **vf_GetParam** (forwards to synth vtable +0x18) |
| 9 | `0x100020c0` | `0x10002560` | **vf_SetParam** |
| 10 | `0x10002310` | `0x100027b0` | **vf_ResetParam** |
| 11 | `0x10002280` | `0x10002720` | **vf_ResetParams** |
| 12 | `0x10001b70` | `0x10001b70` | **vf_GenPcm**: `pros_ToEpt` → `us_ToSeg` → `synth_ToPcm`, plus `vf_FlushMarkers`, `vf_CheckForEmptyMessage` |
| 13 | `0x10001e60` | `0x10002300` | **vf_Stop** (sets obj+0x4c) |
| 14, 15 | `0x10001a10`, `0x10001900` | same | unnamed, import stubs only (INFERRED: marker/event callbacks) |
| 19–25, 27 | `0x10002ba0…0x10002c80` | `0x10002e50…0x10002f40` | one-call thunks into one helper (SS `0x10014930`, RS `0x100178e0`) (INFERRED: per-parameter accessors) |
| 26 | `0x100103b0` | `0x10013330` | leaf |

- After slot 27: `{u16 5, u16 645 (SS) / 654 (RS), u32 23, ptrs…}`, then a
  second list of 26 pointers. Not decoded.
- Slots 2–5, 12, 14 and 15 are at **the same addresses in both packs**: the
  orchestration layer was carried over unchanged.

### 3.5 Corrections this triggers

- **`ss_rs §6f`**: record bytes +13/+14 are the unit's edge-duration values
  (node +0x32/+0x30 via `FUN_10004af0`), not F0 or energy. INFERRED from §3.3.
- **Node +0x31** is zeroed in `FUN_10004af0` and gated `< 15`. That matches
  Speechify's same-recording run counter. Its writer was not located.

---

## 4. `swisolo.dll` — the Speechify API on RealSpeak Solo

106,496 B, sha256[:16] `3631f7ddca576506`, the same file in both packs,
PE 2004-10-28, VC6, CompanyName "ScanSoft, Inc.", banner `RealSpeak Solo v4.0`.

**Exports, 49:**
- the full Speechify 3 C API (every export of Speechify's `SWItts.dll`):
  `SWIttsInit[Ex]`, `SWIttsTerm`, `SWIttsOpenPort[Ex]`, `SWIttsClosePort`,
  `SWIttsSpeak[Ex]`, `SWIttsStop`, `SWIttsPing`, `SWIttsGet/SetParameter`,
  `SWIttsResourceAllocate/Free`, the `SWIttsDictionary*` and
  `*DictionaryEntry` families, `SWIttsLog*`
- **plus `SWIttsPause` / `SWIttsResume`**, which Speechify 3.0.5 does not export
- plus the CDF logging API (`log_*`, `logemb_*`)

**Imports:** `comrsrc.dll` (29), `combrk.dll` (9), `KERNEL32`, `MSVCRT`. Nothing
from SpeechWorks.

**Strings:**
- Speechify parameter names (`tts.audioformat.samplerate`,
  `tts.network.connecttimeout`), MIME types (`application/x-swi-dictionary`,
  `text/plain;charset=wchar_t`), argument-parser messages
  (`hostname parameter set twice`), and `?com.speechworks.SWIttsClientLog`
- trace strings (`Entered SWIttsOpenPortEx: 0x%p, '%S', …`) in the CDF logging style

**Reading:** a ScanSoft-written emulation of the Speechify client API, so
Speechify integrations could run unchanged against RealSpeak Solo.
Speechify's `SWItts.dll` is a network client to `Speechify.exe`;
`swisolo.dll` reproduces the API surface in-process. Its `hostname` and
`hostport` messages show it even parses the client/server init string. It is
an API port, not a code port: no Speechify object code, toolchain or CVS keywords.

---

## 5. Open

- The unnamed `synth_GetInterface` slots and the codec decode entry `0x100062e0`.
  Each needs `create_function` before it will decompile.
- Where ScanSoft's 10,000,000 miss penalty and 50,000 penalties
  (`FUN_10007f20` @0x10007f99/0x10007fb8) map in Speechify's config.
  `MISSING_JOIN_COST` defaults to 1000.0, so not there.
- The 2006 runtime join's three 7-bit feature codes: what is quantised.
- Talent identity is answered (Tom Glynn, all three). Recording overlap is
  answered too: SS 2004 and RS 2006 both contain tom8's physical takes,
  re-coded (`README_TECHNICAL.md` §10). The shared duration table (§3.1) is
  therefore build output for the same source audio, not just the same speaker.
- Whether the front ends share anything. Speechify's is ETI-Eloquence
  (`spfy DLL §7`); SS/RS's is `g2p_*` / `stdpp_*` / `empp_*`. Not yet compared.

---

## 7. Engine round 2: prosody, synthesis, engine core (2026-10-23)

Ghidra programs: `/rs_vf_tom_full.dll`, `/rs_synth_155mrf22.dll`, `/rs_ttsengine.dll`,
`/rs_xcoder.dll`. Functions were created and renamed; **not saved**.

| area | detail |
|---|---|
| prosody | `notes\prosody_2006.md` |
| synthesis | `notes\synth_concat_2006.md` |
| engine core | `notes\ttsengine_xcoder_2006.md` |

### 7.1 One utterance, end to end (RealSpeak 2006)

```
app text --(callback)--> ttsengine (orchestrator only)
  xcoder        : input charset -> internal (UTF-8/16/UCS-4/ISO-8859/code pages via xlit/*);
                  also maps marker positions back to input offsets.  NOT audio.
  markup parser : only for SSML/XML input
  stdpp (PP)    : text preprocessing, slot 12; loops until 0x3002003 (end of input)
  g2p           : slot 13
  vf_*_full     : vf_GenPcm (slot 12, 0x10001b70)
     pros_ToEpt : symbolic prosody on 5 parallel tiers (phoneme/GR/POS/MORPH/INTON)
     us_ToSeg   : unit selection -> USIDS/USDURS/USRATES/USPM/... + UNIT/SUBUNIT list
     synth_ToPcm (synth vtable +0x28 -> 0x10002220)
        codsb decode per unit (4 excitation-only + 2 full warm-up frames)
        join by type (low nibble of the unit's flags byte), Hann-ish Q15 windows
        WSOLA rate change, then volume ramp
  --(PCM callback: codes 1, 0x20/0x40/0x80/0xa0, 2)--> app
```

### 7.2 Headline findings

1. **No pitch target anywhere.**
   - Prosody (654 rewrite rules + phrase-break and pause trees) is purely symbolic.
   - Durations and rates come from unit selection.
   - The synth never modifies pitch: no PSOLA.
   - `pitch` / `pitchrelchg` (range 1–100 / ±100, default 50) are stored by `ttsengine.dll`
     only. The strings occur in no other DLL of either pack (checked).
   - Pitch is a no-op, CONFIRMED by output. `ESC\pitch=10/50/90\` and SAPI `<pitch>` give PCM
     byte-identical to the baseline in both engines (`notes\pitch_control_test.md`).
   - Rate and volume do act, in the synth.
2. **Pauses** are inserted by a compiled 11-feature decision tree, with exactly four
   lengths: **101 / 121 / 138 / 160** (INFERRED: ms).
3. **Four join types** in `synth_ToPcm`:

   | type | join |
   |---:|---|
   | 0 | 5 ms fade-out, pause, 5 ms fade-in |
   | 1 | 5 ms crossfade aligned on pitch peaks |
   | 2 | SOLA, xcorr lag 0..10 ms + 10 ms crossfade |
   | 4 | 10 ms out / 2 ms in |

   Which type a unit gets is set by the voice font's unit-list writer (open).
4. **Rate** is WSOLA after concatenation: 10 ms hop, ±4 ms search, 0.5×–2.5×, bypassed at
   rate 50. The wpm table is seeded by voice header +0x80 = native wpm (Tom 173, INFERRED).
5. **xcoder is a text transcoder.** The engine outputs native linear PCM only
   (`typeofoutput` = 1).
6. **Dictionaries are not in `ttsengine`.** It passes the PP's lookup callback to the app;
   the edct/dcteg handling sits in the API DLLs (`rssoloapi`, `swisolo`, `rs_sapi5_solo`).

### 7.3 Resolved from earlier "Open" lists

- §3.4's undecoded record after slot 27, `{u16 5, u16 645/654, u32 23, ptrs…}`, is the
  **prosody rewrite-rule table header**: 5 tiers, 645 (SS) / 654 (RS) rules, highest rule
  variable index 23. It is not "23 rule sets": the program has 12 block slots, 8 used, and the
  SS 2004 VF has the same 8 blocks with 9 fewer rules (corrected in §8.4).
- §5 "unnamed `synth_GetInterface` slots and the codec decode entry": all mapped (README_TECHNICAL §11).
- The `MSG_DATA_TAG_PM_TTS` layer is the **phoneme** tier, not pitch marks.

### 7.4 Still open

- Which join type each unit gets: trace the unit-list writer in `us_ToSeg`.
- What rewrite-rule blocks 3 / 0xB / 4 do: decode the rule bytecode. The g2p notes have a
  rule disassembler for the same engine (`notes\g2p_enu_2006.md`).
- ~~Whether in-text markup can still change pitch~~: it cannot (§8.3).
- ~~The PP/G2P call signatures from their own side~~: done, §8.
- ScanSoft 2004's voice font: compare its 645-rule table to the 2006 one. Header level done
  (§8.4: same 8 blocks, 9 fewer rules in blocks 3 / 4 / 0xB); rule-by-rule diff open.

## 8. Front end: stdpp, empp, g2p (2026-10-23)

Ghidra programs: `/rs_stdpp_enu.dll`, `/rs_g2p_enu.dll`, `/ss_empp_enu.dll` (renamed), plus
`/ss_stdpp_enu.dll`, `/ss_g2p_enu.dll` for the 2004 diff. **Not saved.**

| module | notes |
|---|---|
| stdpp_enu 2006 | `notes\stdpp_enu_2006.md` |
| g2p_enu 2006 | `notes\g2p_enu_2006.md` |
| empp_enu 2004 | `notes\empp_enu_2004.md` |
| 2004 vs 2006 | `notes\fe_2004_vs_2006.md` |
| pitch/duration control (output test) | `notes\pitch_control_test.md` |

### 8.1 Who does what

```
stdpp (PP, +0x30 pp_Process 0x10001520)
    writes ONLY sections 6 (text), 0x12 (markers), 0x27 (string pool)      CONFIRMED
    flex scanner (1598-state DFA) + packed tables, all compiled in; no data file
    sentence split (210-entry abbreviation table @0x1000a300), readmode chunking,
    URL/e-mail detection (\x1eur / \x1ead regions), spell mode, cp1252->cp437,
    user dictionary via WORD_DCTEG, ESC\name=val\ and legacy ESC-letter tags -> marker records
    NO number/date/abbreviation expansion, NO POS
g2p (+0x34 g2p_TranscribeTts 0x10001e10)
    retypes 6 -> 8 and rewrites 8 in place (text -> phonemes)                 CONFIRMED
    creates/fills 7 GR (orthography copy), 9 POS, 10 MORPH, 0x10 (TN tags), 0xC CM
    all text normalisation (say-as table @0x10036310, 69 modes), lexicons, POS tagger,
    homographs, letter-to-sound: ONE rewrite-rule program, 4517 rules / 236 blocks
vf (pros_ToEpt) consumes 8/7/9/10/0x10 as its 5 tiers (section 7)
```

`empp_enu` (2004 only) is the **E-Mail Pre-Processor**, an alternative PP: it exports
`stdpp_GetInterface` and `empp_GetInterface` at the same address `0x10001e70`, with the same
14-slot table. It is registered by `rssolo_empp_enu.hdr` as `EMail` / `pp/email/enu` / priority
90 (stdpp is `Text` / priority 100). CONFIRMED. It is C++ (three chained flex lexers). It reads
mail headers, time zones, `Re:`, ~2,780 domain → organisation names and 157 smileys. It writes
6 / 0xC / 0x12 / 0x27, never POS. The 2006 pack has no EMPP and no `pp/email` hdr.

### 8.2 Headline findings

1. **G2P is the whole linguistic front end.** The PP only segments and tags.
   - **The engine:** the G2P rule engine is the prosody's five-tier rewrite machine, with
     the same tier layout and the same 0x5dc capacity. One L&H rule compiler serves both
     stages (INFERRED).
   - **Rule calls:** a rule can call one of 236 native routines (@`0x10036540`).
2. **The main lexicon is decoded.** It holds 34,813 entries (`C:\tmp\g2p_enu_lex.tsv`).
   - **Keys:** a Huffman-coded letter trie.
   - **Entries:** `PHON#POS#F3`, byte-pair-compressed and front-coded.
   - **Homographs:** 723 carry an `H<n>` class plus an alternate pronunciation
     (`read 'rid#H7#'rEd`). CONFIRMED (sampled)
   - **Small dictionaries:** 24 more (function words, symbols, acronyms, units, currency,
     months, states, roman numerals, affixes); the DLL's own code under Unicorn listed them.
3. **Letter-to-sound is hand-written context rules**, ~678 in 23 blocks, run after affix
   stripping. No tree and no n-gram; there are no x87/SSE instructions in 60,606.
4. **Phonemes are the internal L&H ASCII set**, not SAMPA: `$` = schwa, `J/Y/@` diphthongs,
   `R` flap, 0x91 = æ, `'` and `` ` `` for stress, `-` for syllables. Program 2 (107 rules)
   maps to L&H+ broad and narrow notation.
5. **Markup is thin in 2006.**
   - **SetParam:** `pp_SetParam` accepts 0x81 (markermode) and 0x87 (readmode) and discards
     both. The PP reads the `markermode`, `newreadmode` and `tnmode` paramc keys itself, and
     only markermode bit 2 matters (mask 0xfffb vs 0xfff9). CONFIRMED
   - **Pitch tags:** `pitch=` becomes a 0x10 marker record with subtype 0x80, and nothing
     downstream acts on it (output test, 8.3).
   - **Phonetic input:** `\prn=` is dropped.
6. **Phonetic input with explicit prosody exists in the chassis.** EMPP's spoken prompts are
   L&H phonetic strings carrying a per-phone duration and F0 targets in Hz, e.g.
   `m[67(2,87)]E[52]-s[121(112,118)]…` ("Message from"). This is the only F0 target found in
   either pack.
   - **g2p:** parses it (`0x1002cb10`).
   - **Voice font:** only reads `#[N]` pauses.
   - **Output test:** durations and F0 targets in `ESC/+…ESC/+` phonetic input leave the PCM
     byte-identical, while `#[800]` adds about 1 s (8.3).
7. **No Eloquence code or data.** The only strings shared with `SWIttsFe-en-US.dll` are PE
   boilerplate. There are no Delta, ECI, `salsa` or `maindict` markers, and 1–16 of 9k–43k
   32-byte code chunks are shared (CRT). CONFIRMED (`C:\tmp\fe_overlap.py`). EMPP also shares
   nothing with Speechify's `SWIEmail.dll`.
8. **Custom G2P:** `brk_InterfaceQuery("cg2p/enu/<name>", 1)` is called from SetParam, for up
   to 32 modules. In-text `domain=` markers (0x8003 / 0x8004) push and pop the active one.

### 8.3 Resolved

- 7.4 "PP/G2P call signatures": mapped (8.1 and the notes).
- Where POS comes from: G2P (lexicon POS, then context rule blocks 0x90–0x95).
- Where numbers and dates are expanded: G2P, not PP.
- What EMPP is: the e-mail PP, dropped in 2006.
- §7.3 "23 rule sets": this is a misread. Header +4 is the highest rule-variable index; see 8.4.
- **In-text pitch and duration control: none, in either engine.** CONFIRMED by output
  (`notes\pitch_control_test.md`). These give PCM byte-identical to the baseline:
  - `ESC\pitch=\` and SAPI `<pitch>`
  - per-phone `[dur(t,F0)]` targets in phonetic input

  Rate, volume and `#[N]` pauses do act. The only phonetic-input route is the legacy
  `ESC/+ … ESC/+` region, which the SAPI wrapper also uses for `<pron>` (template `\x1b/+##\x1b/+`
  at `rs_sapi5_solo.dll` file offset `0xc504`).

### 8.4 2004 vs 2006: same engine, data regenerated

| | ScanSoft 2004 | RealSpeak 2006 |
|---|---|---|
| g2p interface | `0x100c6048`, 18 slots, every function at its 2006 address −0x10 | `0x100d5048` |
| main lexicon | 34,689 entries | 34,813 (34,529 identical, 150 changed, 134 added, 10 removed) |
| g2p rule program 1 | 3,315 rules / 162 block slots (88 used) | 4,517 / 236 (146); 94% of the 2004 rules have a 2006 twin |
| say-as modes | 19 (`0x1002e2f0`) | 69; new blocks 0xbe–0xeb (696 rules) |
| g2p program 2 | 107 rules | 107 (106 byte-identical) |
| stdpp DFA | 986 states | 1598; same 210 abbreviations, same charmap |
| stdpp params | 0x81 / 0x87 honoured via SetParam | moved to paramc; SetParam is a no-op |
| VF prosody header | {5, 645, 23}, 8 blocks | {5, 654, 23}, same 8 blocks |

- **Lexicon codec:** same algorithm, different code bytes. 2004 uses end 5, prefix codes
  0x7b–0x8a and separator 0x92. The generic decoder `C:\tmp\g2p_lex2.py` handles both builds.
  CONFIRMED (2006 dump reproduced byte for byte)
- **Lexicon additions:** mostly tech words and brands (`TCP/IP`, `bluetooth`, `realspeak`) and
  British `-tre` spellings. 2006 also has hand-entry defects, such as `realspeak` with a stray
  byte 0xa1. The diff is `C:\tmp\g2p_lexdiff_2004_2006.tsv`.
- **Nothing voice-specific** in either front end. All of Tom's identity is in the VF.

### 8.5 Still open

- ~~Whether VF reads the 0x10 pitch subtype or the `[dur(t,F0)]` notation~~: it reads
  neither (8.3).
- G2P section 0xE: TranscribeTts attaches 0xE instead of 8 when 0xE exists. This is
  INFERRED to be a phonetic-input path.
- Two small dictionaries (`0x100311b0`, `0x10034880`) returned no hits for the keys tried.

---

## 6. Build forensics, part 2: what MADE ScanSoft 2004 / RealSpeak 2006 (2026-10-23)

Modelled on the Speechify write-up (artifact "Speechify Build Forensics"). The
evidence is the shipped files only: PE/COFF headers, CodeView records, Rich
headers, version resources, `.rdata` strings, `.hdr` text, and SCANSOFT data
headers.

Probes, all in `tools\`:
- `ssrs_forensics.py`, full dump at `C:\tmp\tom_overlap\forensics.txt`
- `build_clock.py`
- `scansoft_stamp_dates.py` (already in §10.9)

This extends `DLL_ANALYSIS.md` §1 and `README_TECHNICAL.md` §0/§1/§10.9 without
repeating them.

**Not available in SS/RS:**
- **CVS / `$Id$`:** none. The class is skipped.
- **An `ICRD`-style dated writer:** none. SCANSOFT headers carry no calendar
  date (§10.9).
- **The voice-build tool:** no RIFF-writer-style dead code names it.

### F1. What dates the Tom audio. No file records when it was RECORDED.

| Tom | dated artefact | value | source | tag |
|---|---|---|---|---|
| Speechify | voice container written | **2003-05-12** | `tom.vin` LIST/INFO `ICRD` (writer formats `localtime()` at emit) | CONFIRMED |
| Speechify | audio file | 2003-05-28 | `tom8.vdb` mtime | CONFIRMED |
| SS 2004 | unit DB / audio written | 2004-06-17 / 2004-06-20 | `us_tom_full.dat` / `vf_tom_full_155mrf22_270_06.dat` mtimes | CONFIRMED (preserved mtimes) |
| SS 2004 | voice font linked | 2004-07-22 18:23:40 UTC | `vf_tom_full.dll` PE stamp (no PDB record) | CONFIRMED |
| RS 2006 | unit DB / audio written | 2006-04-20 | data mtimes | CONFIRMED |
| RS 2006 | audio written by the **2006 header writer** (generation B, F4) | — | `+0x84` = 822349082, `+0x88` = `".00"`, shared with Paulina and Samantha | CONFIRMED |
| RS 2006 | voice font linked | 2006-05-16 06:55:13 UTC | PE stamp = NB10 signature, **age 1** (fresh, single link) | CONFIRMED |
| RS 2006 | build number | 4.0.2.**6136** = 2006, day 136 = 2006-05-16 | version resource (F2) | CONFIRMED |

- Both voice fonts carry the `CDF vf_jennifer_full 1.00 / Copyright 2003`
  banner. It is the template's date, not Tom's.
- The `.hdr` descriptions differ in house style: SS Tom says "Tom 22 **KHz**",
  RS Tom "Tom 22 **kHz**". "KHz" also appears in RS Emily, Jill and Isabel; the
  other eight say "kHz". Different hands wrote them.
- **INFERRED:** the latest possible recording date for the shared takes is May
  2003 (the Speechify container). The non-Speechify takes are bounded only by
  June 2004 (the SS data). Nothing in any file narrows that window.

### F2. The 4th version field is a build date, `YDDD`. CONFIRMED.

| | value |
|---|---|
| scheme | `4.0.2.6136` = 200**6**, day **136** = 2006-05-16 |
| matches PE stamp to the day | **22 RS modules** |
| off by one or more days | `ttsengine` 6180 = Jun 29, PE Jun 30 (+1 d); `rssoloapi` 6174 = Jun 23, PE Jun 30 (+7 d) |
| 2004 ScanSoft builds | `4.0.0.x` with no date field |
| `ssftrssolo.ocx` | FileVersion string `1.4.0.20041130`; fixed field `1.4.0.52650` = 20041130 & 0xFFFF |

Notable values: 6089 = audiofetch (Mar 30), 6090 Samantha (Mar 31), 6097 Emily
and g2p_eng (Apr 7), 6135 combrk and comrsrc (May 15), **6136** the main 2006
drop (May 16), 6153 Paulina and the Mexican Spanish modules (Jun 2), 6181 rettt
(Jun 30), 6216 rs_sapi5_solo (Aug 4).

The ttsengine and rssoloapi offsets mean the version number was stamped at
check-in or tag time, and the binary was relinked later. The NB10 ages agree:
4 and 7 relinks (F3).

### F3. CodeView NB10 records (RS 2006 only; the 2004 builds are stripped)

The signature is the PDB creation time; the age is the number of links into
that PDB.

| cluster | NB10 signature (UTC) | PE link (UTC) | age | modules |
|---|---|---|---:|---|
| main drop | 2006-05-15 15:34–15:47 | 2006-05-16 06:38–06:47 (+15 h) | 2 | audioout, comsyssvc, dcteg, edct, xcoder, xlit_1252, g2p_enu, stdpp_enu, synth_112/155/83 |
| main drop | 2006-05-15 15:34/15:35 | 2006-05-15 (+1 min) | 2 | combrk, comrsrc |
| fresh | 2006-05-16 06:55:13 | same | **1** | **vf_tom_full** |
| fresh | 2006-05-16 07:38:02 | same | 1 | domain_mngr |
| earlier | 2006-03-30 09:43 | 2006-03-31 (+31 h) | 3 | vf_samantha_full |
| earlier | 2006-03-30 09:50 | +43 min | 2 | audiofetch |
| earlier | 2006-04-07 16:00 / 16:25 | same | 1 | g2p_eng, vf_emily_full (drive **L:**) |
| later | 2006-06-02 11:34–11:41 | same | 1 | g2p_spm, stdpp_spm, vf_paulina_full |
| later | 2006-06-23 12:04 / 13:07 | 2006-06-30 | **7** / **4** | rssoloapi, ttsengine (drive **H:**) |
| later | 2006-06-29 07:01 | +30 h | 2 | rettt (H:) |
| later | 2006-08-04 16:46:51 | same | 1 | rs_sapi5_solo (H:) |

- **The 2006 Tom voice font was a one-shot link on the morning after the main
  common-code rebuild.** That fits a scheduled re-release of an existing voice
  rather than a voice under active development. Contrast Samantha (age 3, two
  days of relinks). INFERRED.
- **Three source drive letters** for `ttssrc.a`. F: holds the bulk of the
  products and all voices except Emily; L: holds Emily and g2p_eng; H: holds the
  SDK/API layer. These are separate build views or hosts.

### F4. Two generations of SCANSOFT data-header writer. CONFIRMED.

| gen | `+0x84` | `+0x88` | files |
|---|---|---|---|
| **A** | 265498 | zero | all SS 2004 (Tom, Kyoko, Narae); RS Daniel, Isabel, Jill, Karen, Lee |
| **B** | 822349082 | `2e 30 30` (".00") | RS **Tom**, Paulina, Samantha (both `useld` and `codsb`) |
| **B** | 839126298 | ".00" | RS Emily |

Header fields `ss_rs §1` did not decode:
- **codsb `+0x20`** (language field) carries the sample rate after the language
  code: `enu   22050`.
- **codsb `+0x74` / `+0x78`** = u32 **270** / u32 **6**: the `.hdr` `BITRATE` and
  `OVERHEADFRAMES`, written into the container.
- **RS Daniel and Lee `useld`** name a *different* coder: `+0x20` = `eng 11025` /
  `ena 11025`, variant `83swf11`, `+0x74/+0x78` = 165 / 4. Their unit databases
  came out of an **11 kHz `83swf11` build** and were shipped against 22 kHz
  audio. Lee's variant reads `2`, not `full`, and its version `1`.
- **Version fields vary:** `1.00` mostly; `1.0` (Karen); `1` (Narae codsb, Lee);
  **`3.00` (RS Jill codsb)**.
- **`encrypt` in the variant:** SS Narae; RS Jill, Samantha, **Tom** (`useld`
  only). SS Tom's `useld` has none.

So **RS Tom was re-emitted in full by the 2006 (gen B) tooling**, both `useld`
and `codsb`, not carried over from 2004. That agrees with the zero shared coded
frames (§7) and the new unit count.

### F5. Rich profiles: which modules share a recipe

- **Unchanged common modules are byte-for-byte the same build recipe in both
  packs:** audioout, comrsrc, comsyssvc, dcteg, xcoder, xlit_1252/2022, swisolo,
  ssftrssolo.ocx.
- **SS Tom 2004 and RS Karen (2004-10-28) share one voice-font profile.**
- **RS Tom, Emily and Samantha share one 2006 voice-font profile** (`vf` 2006 recipe).
- **RS Daniel and Jill** share a third.

So voice fonts were built from a small number of per-era templates, not
hand-built per voice. INFERRED.

### F6. Build-site clock: Central Europe, not Boston (`build_clock.py`)

Share of distinct PE link times that fall on a weekday, 08:00–20:00 local:

| | New York | **Brussels / Berlin** | Tokyo | Kolkata |
|---|---:|---:|---:|---:|
| Speechify 3.0.5 (SpeechWorks, Boston), calibration | **100%** | 25% | 0% | 0% |
| SS 2004 pack | 88% | 84% | 9% | 47% |
| **RS 2006 pack** | 42% | **100%** | 49% | 67% |

- **The 2006 builds were linked in a Central European working day.** UTC hours
  span 06–16, i.e. 08–18 CEST. That fits the L&H-heritage R&D site in Belgium
  (or Aachen), not SpeechWorks Boston. INFERRED.
- **2004 is ambiguous** between New York and Brussels.

### F7. L&H inheritance inside the code. CONFIRMED.

| file | evidence |
|---|---|
| `empp_enu.dll` @0x29320 | `EMPP (Eng USA) V4.02.00 Jan 14, 2000` / `(c) Copyright 1998 - 2000 Lernout & Hauspie Speech Products (tm) N.V.` |
| `empp_jpj.dll` @0x1610d | `EMPP (Eng USA) V1.00 May 5, 1997` / `(c) 1993-1997 L&H`: the **English** banner reused verbatim in the Japanese module |
| `empp_kok.dll` | version resource CompanyName = Lernout & Hauspie Speech Products, FileVersion 6.0.0.0 |
| `comrsrc.dll` | the shared error catalog of L&H's **`lhs` unified ASR+TTS SDK**: `LHASR API`, `casrOpen`/`casrImportContext`, `lhs_InitializeEx`, PLH protection files, "Contact ScanSoft for a new license", ASR user-word training errors. So this TTS ships the ASR SDK's resource DLL |
| `swisolo.dll` @0x11178 | default identity `RealSpeak Solo` `4.0.0` `SSFTSOLOSDK` `RealSpeak Solo v4.0` `speech` **`Jennifer`** `American English` `DRI40`: the Speechify-API shim defaults to L&H's US voice |

### F8. NextUp's OEM rebrand, and a local patch

| file | sha256[:16] | vs stock `rs_sapi5_solo.dll` |
|---|---|---|
| `rs_sapi5_solo.dll` | `a518ed0d10a8ca80` | stock |
| `rs_sapi5_solo_nextup.dll.orig` | `dd0a65decf3be539` | **6 bytes**: engine token `tts/eng.RealSpeakSolo` → `RealSpeakNxtU` (@0xe126), and GUID bytes `l`→`m` at 0xa1b0 / 0xff9c (a new CLSID). NextUp's OEM rebuild, so it can coexist with a stock install. INFERRED (vendor) |
| `rs_sapi5_solo_nextup.dll` | `f3c724582fb8309f` | `.orig` plus a new `.vgain` section (0x200 B), a call patched in at 0x45f8, and gain scaling `movzx; imul 0x4d; shr 7` (×77/128) at 0x5c32. **mtime 2026-09-21: made on this machine, not vendor** |

### F9. `ssftrssolo.ocx`

- **Identity:** byte-identical in both packs. PE 2004-11-30; FileVersion
  `1.4.0.20041130`; `Copyright (C) 2004, ScanSoft, Inc.`
- **ProgIDs:** `SsftRSSoloA.SsftRSSoloCtrl.1`, `SsftRSSoloA.SsftRSSoloPropPage.1`.
  Typelib (`MSFT`) at 0x44e88.
- **Build:** MFC, its own Rich profile (8047/8569).
- **Strings:** `PrivateBuild` / `SpecialBuild` keys are present but empty. No
  author or project strings beyond the product names.

### F10. `.hdr` registry (all values)

| field | values |
|---|---|
| `VERSION` | `SSFT_1.0` (schema), `4.0`, and **`3.5` for `xcoder`** in both packs: an older component version carried along |
| `CHARTYPE` | `ANSI` |
| `VOICEAGE` | `Adult` |
| `REDUCTIONTYPE` | `FULL` |
| `PRIORITY` | 5 / 90 / 100 |
| `COMMAND` | `%text` / `%email` |
| `ISOCODE` | includes `es-Mx` (mixed case) |
| `MANUFACTURER` | `ScanSoft` |
| per-voice tags | no build, author, date or tool fields |

### Dead ends (do not re-run)

- **The "wordy" ASCII runs in `useld` tails** (`nEkst#d`, `twElvn#P`,
  `sEntst#`) are the 16-byte unit records' phone lanes, which hold SAMPA
  characters as bytes (`ss_rs §4`). They are context strings, not a prompt list.
- **`codsb` ASCII runs** are codec payload.
- **No person, e-mail, machine name, voice-build tool name, studio, session or
  prompt-script reference** exists in any SS/RS file. Path-like hits other than
  the PDB paths are relocation and garbage bytes.
- **The only literal dates in any binary** are the L&H EMPP banners (1997, 2000).
