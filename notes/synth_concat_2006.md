# `synth_155mrf22.dll` (RealSpeak Solo v4, 2006): concatenation and signal path

Program: Ghidra `/rs_synth_155mrf22.dll`
(`RealSpeak\speech\components\synthesizer\synth_155mrf22.dll`). Not saved.

**Addresses are not shifted.** `README_TECHNICAL.md` §0 already records that the
"ScanSoft" `synth_155mrf22.dll` is byte-identical to the RealSpeak one
(sha256 `d12c7c0097daba3b…`, 4.0.2.6136, 2006-05-16). Every address in
`DLL_ANALYSIS.md` §2 is valid here as-is. CONFIRMED: the interface table at
`0x100110c8` has the same contents.

Labels: **C** = CONFIRMED (seen in code or data), **I** = INFERRED.

---

## Summary

- **The voice font sends no prosody.** No F0 or energy target reaches the synth, and pitch is never changed (no PSOLA) (C).
  - `synth_ToPcm` gets a unit list. Each unit carries a database position, a duration, a pause, marker anchors, and a join-flags byte.
  - Positions and durations are in **0.1 ms ticks**. At 22050 Hz that is ×2.205 samples per tick (C).
- **Middle samples are untouched.** A unit's audio between joins is copied straight from the ACELP decoder to the output (C).
- **Only a few boundary samples are processed.** The join type is chosen per unit by the low nibble of the flags byte. There are four types (C):
  - 0: 5 ms fade-out, optional pause, 5 ms fade-in, with no overlap
  - 1: crossfade aligned on pitch peaks, 5 ms
  - 2: SOLA crossfade aligned by cross-correlation, 10 ms
  - 4: 10 ms fade-out, then 2 ms fade-in
- **The Q15 table after the interface is a family of four fade-out tapers**, one per sample rate. Each is ≈10 ms long, i.e. 10 ms + 1 sample. At 22050 Hz it has 221 entries (C).
  - Shape: `T[n] ≈ 32736·½(1+cos(π(n+½)/L))`, ±1 LSB.
  - Each table is exactly complementary: `T[n]+T[L−1−n] = 32736` (C).
- **Speaking rate is changed after concatenation, by WSOLA on the PCM** (C).
  - Synthesis hop 10 ms, Hann crossfade over 10 ms, search window ±4 ms with a 3-level coarse-to-fine cross-correlation.
  - Analysis hop = `L·(100+pct)/100`, with pct from −50 to +150, i.e. 0.5× to 2.5× speed.
  - The voice header's 3-digit `+0x80` field (Tom = 173) is the **base wpm at rate 50** (flow C, meaning I).
- **Output chain after the joins:** WSOLA rate stage → volume stage (Q15 gain table with 30 ms log/exp ramps, saturating) → audio-insertion stage (`AUDIO_FETCHER`) → host (C).
  - There is no post-filter, de-emphasis or resampler.
  - The codec's DC-block is the only filter.
  - The rate is set by the `frequency` param, with tables for 8000, 11025, 16000 and 22050 Hz.

---

## 1. `synth_GetInterface` table (`0x100110c8`, returned for `ver < 2`)

| slot | off | address | name given | role |
|---:|---:|---|---|---|
| 0, 1 | +0x00, +0x04 | 0 | — | null (C) |
| 2, 3 | +0x08, +0x0c | `0x10001820` | `synth_class_noop` | `return 0`. ClassOpen/ClassClose stubs (C code; I roles) |
| 4 | +0x10 | `0x10001830` | `synth_obj_open` | ObjOpen. 0x108-byte object; reads `frequency`, `markermode` (default 0x1F9), `waitfactor` (default 2); builds the work struct (0xA8 B) and buffers; opens the voice data; builds the stage chain (§5) (C) |
| 5 | +0x14 | `0x100020b0` | `synth_obj_close` | ObjClose (C, prior doc) |
| 6 | +0x18 | `0x10002700` | `synth_get_param` | GetParam (C, prior doc) |
| 7 | +0x1c | `0x10002860` | `synth_set_param` | SetParam by id (C), table below |
| 8 | +0x20 | `0x10002ac0` | `synth_reset_param` | ResetParam(id): 3/7 → volume stage reset; 4 → `waitfactor`="2"; 5 → `markermode`; 6/8/0xb → rate stage reset (C) |
| 9 | +0x24 | `0x10002a70` | `synth_reset_params` | resets volume (1), rate (5), `waitfactor`, `markermode` (C) |
| 10 | +0x28 | `0x10002220` | `synth_to_pcm` | **ToPcm**: unit list → PCM (§2) (C) |
| 11 | +0x2c | `0x100022d0` | `synth_process_events` | event list with no units. Type 1 + byte 0x80 → ResetParams; type 0x80 → `waitfactor`; type 0x20 → pause of `round(ms·fs/1000 + 0.5)` zero samples (`FADD [0x10011100]` = 0.5); output goes through the rate stage (C). "Pauses/bookmarks only" (I) |
| 12 | +0x30 | `0x100011b0` | `synth_open_voice_data` | lazy `.dat` open (C, prior doc) |
| 13 | +0x34 | `0x10001540` | `synth_check_voice_compat` | compares `reduction`, `coder`, `bitrate`, `overheadframe` of the current vs the new voice param set. If any differ, it closes the data (`FUN_10005ae0`) (C) |

Codec vtable `0x10011a20` +0x38 = `0x100062e0` (`codec_decode_frames`, created). See §6.1.

`synth_set_param` id map (C). The target stage receives its own id.

| id | target |
|---:|---|
| 3 | volume stage, id 1 (`volume`) |
| 4 | `waitfactor` (0..9) |
| 5 | `markermode` |
| 6 | rate stage, id 5 |
| 7 | volume stage, id 10 (`volume`) |
| 8 | rate stage, id 0xb |
| 0xb | rate stage, id 6 |
| 0xd | volume stage, id 0xd (`volumerelchg`) |
| 0xe | rate stage, id 0xe |

Data right after the table (C):

| address | value | used by |
|---|---|---|
| `0x10011100` | 0.5f | rounding of pause samples (`0x10002416`) |
| `0x10011104` | 0.2f | `set_waitfactor`: tail silence = `fs·w·0.2` |
| `0x10011108` | 0.001f | samples per ms (`calc_samples_per_ms`, the volume stage, the audio-insertion stage) |
| `0x1001110c…0x10011a0b` | 4 taper tables | §4 |
| `0x10011a0c` | {81, 113, 161, 221} | the taper lengths |

---

## 2. `synth_to_pcm` (`0x10002220`)

### 2.1 Input (C)

Input is a typed-stream container. `FUN_10006b00(h, id, &ptr, &count)` reads it.

| stream id | contents |
|---:|---|
| 0x12 | event/marker list, 24-byte records |
| 0x2c | sub-record array, 12-byte records = marker anchors |
| 0x2b | **unit list**, 24-byte records |

Unit record (C, field use read in `tp_convert_unit_times` `0x10002da0` and `unit_begin` `0x10004880`):

| off | type | meaning |
|---:|---|---|
| +0x00 | u32 | database position, **0.1 ms ticks** → samples (`ticks100us_to_samples`) |
| +0x04 | u32 | duration, 0.1 ms ticks → samples. Raised to the sum of its sub-record durations if that is larger |
| +0x08 | ptr | sub-records of this unit |
| +0x0c | u32 | written by the synth: lead/marker offset |
| +0x10 | u32 | pause **before** the unit, in ms → samples (`ms_to_samples`) |
| +0x14 | i16 | sub-record count |
| +0x16 | u8 | **join flags**. Low nibble = left-edge join type; high nibble = right-edge tail extension (§2.3) |

Sub-record (C):

| off | meaning |
|---:|---|
| +0 | absolute output sample position (filled by `subrec_relayout`) |
| +4 | duration, 0.1 ms ticks → samples |
| +8 | i16 index into the event list |
| +10 | u8 number of events anchored here |

For the last sub-record of the last unit, `+0` holds the trailing pause in ms, plus a flag in bit 0x20000 (C).

Tick and ms conversions use `mul_q31_round(x, c, 31)` = `round(x·c/2³¹)` (C):

| fs | per 0.1 ms tick | per ms |
|---|---:|---:|
| 22050 | 2.205 | 22.05 |
| 11025 | 1.1025 | 11.025 |
| 16000 | **1.603636** | **16.036** |
| 8000 | **0.801818** | **8.1818** |

The 16 kHz and 8 kHz constants are not exact: 0.2% to 2% off. They look derived from 22050 (×8/11, ×4/11). They are bugs at those rates only (C values, I cause).

### 2.2 Work-struct constants per rate (`join_ws_init` `0x100033e0`, `join_ws_set_rate_consts` `0x100032a0`) (C)

`N = round_to_mult4(10 ms)`. The values at 22050 Hz:

| field | symbol | value | meaning |
|---|---|---:|---|
| W[0] | N | 220 | 10 ms |
| W[1] | H | 110 | N/2 |
| W[2] | 2N | 440 | |
| W[3] | 3N | 660 | buffer capacity |
| W[4] | dec | 4 | SOLA decimation (2 at 8 kHz / 11 kHz) |
| W[0x1f] | Pmax | **298** | 13.5 ms, type-1 tail extension and head length |
| W[0x20] | | 149 | Pmax/2, peak search range |
| W[0x22] | | 260 | not referenced on the paths read |
| W[0x25] | | N | type-4 fade-out length |
| W[0x26] | | **44** | 2 ms, type-4 fade-in length |
| W[0x27] | | 5 | type-4 taper step |
| W[0x28] | | **8** | peak-picker moving-sum width |

Values at the other rates:

| fs | N | Pmax | W[0x22] | W[0x26] | W[0x28] |
|---|---:|---:|---:|---:|---:|
| 8000 | 80 | 108 | 94 | 16 | 2 |
| 11025 | 112 | 149 | 130 | 22 | 4 |
| 16000 | 160 | 216 | 188 | 32 | 6 |

Buffers:

| buffer | what | type |
|---|---|---|
| **A** (W+0x2c) | previous unit's tail | int32[3N] |
| **B** (W+0x34) | next unit's head | int32[3N] |
| **P** (W+0x38) | push-back queue, emitted before any further decoder output | int32[5N] |

Output is int16 in `obj+0x8c`. **P → int16 takes the low 16 bits, with no saturation** (`pending_drain` `0x10003910`) (C). Overflow cannot happen, because each crossfade's weights sum to 32736/32768 (§4).

### 2.3 Algorithm

Call chain (C): `synth_to_pcm` → `tp_run_unit_list` (`0x100034d0`) → `tp_reset_state`, `tp_convert_unit_times`, `concat_units` (`0x10004aa0`).

Pseudocode (C unless marked):

```
# tp_convert_unit_times
for u in units:
    u.pos  = ticks(u.pos);  u.dur = ticks(u.dur);  u.pause = ms(u.pause)
    u.dur  = max(u.dur, sum(ticks(s.dur) for s in u.sub))
repeat 4x: tp_merge_zero_dur_units()   # interior unit with dur==0 removed:
                                       #   prev.subcount += it.subcount, prev.flags hi := 0x40,
                                       #   next.flags lo := 4   (& 0xF4 | 4)
tail_pause = ms(last.sub[-1].field0 & 0xFFFF);  tail_enable = bit16 if bit17 set

# concat_units
unit_begin(0); unit0_lead_pause(); unit_emit_body(0); unit_read_tail()
for i in 1..n-1:
    unit_begin(i)                                  # maps [pos-lead, pos-lead+end) via codec addressing
    switch u[i].flags & 0x0F:
        0: join_fade_out_in(i)                     # 0x100056e0
        2: join_sola_xfade(i)                      # 0x100053d0
        1: join_epoch_xfade(i)                     # 0x10004d90
        4: join_fade10_in2(i)                      # 0x100051a0
        (test order 2, 1, 4; other non-zero values: no join call)
    unit_emit_body(i); unit_read_tail()
emit(A[0 : core_end-pos])                          # last unit: no fade-out
emit_silence(tail_pause + waitfactor*0.2*fs)       # if tail_enable

# unit_begin(i)  (0x10004880)
lead = {0: min(pos, H), 2: min(pos, N), 1: 0, 4: 0}[lo]
core_end = lead + dur
end = core_end + {hi 0: H, 0x20: 2N, 0x10: Pmax, 0x40: 0}[hi]
map(pos - lead, end);  rpos = 0

# unit_emit_body(i)  (0x10004950): stream straight from decoder, no processing
n = core_end - rpos - {hi 0/0x20: H, 0x10: W[0x28]/2 (=4), 0x40: N}
emit(n); rpos += n

# unit_read_tail()  (0x10004a00)
A = decode(min(end - rpos, 3N)); zero-pad A to 3N
```

The four joins. Unit i−1's tail is in A, starting at `core_end(i−1) − X`, where X = the body stop in `unit_emit_body`. B is unit i's head. `T` is the taper (§4).

```
# type 0  join_fade_out_in   (prev hi 0 → A = last H of core + H extension)
B = decode(H)
A[k] = A[k]*T[2k] >> 15,       k = 0..H-1          # taper_fade_out_step2, 5 ms
emit(A[0:H])                                        # prev ends exactly at its core_end
emit_silence(u[i].pause)
B[k] = B[k]*T[N-2k] >> 15,     k = 0..H-1          # taper_fade_in_step2, 5 ms
emit(B[0:H])                                        # = the H samples BEFORE u[i].pos
rpos = H                                            # no overlap anywhere

# type 2  join_sola_xfade    (lead = N; pairs with prev hi 0x20, I)
B = decode(min(end, 3N))
k* = argmax_{k=0,dec,..,N}  Σ_{j=0,dec,..<2N} (A[j]*B[j+k]) >> 3     # sola_find_lag
A[j] = (T[N-j]*B[k*+j] >> 15) + (T[j]*A[j] >> 15),  j = 0..N-1        # taper_xfade_full, 10 ms
emit(A[0:H]) as unit i-1;  emit(A[H:N]) as unit i
pushback(B[N+k* : B.n]);   rpos = N + k*

# type 1  join_epoch_xfade   (lead = 0; prev hi 0x10 → A starts 4 samples before prev core_end)
B = decode(min(end, Pmax))  (0 if ≤ 2*W[0x28]+1)
S_X(j) = Σ_{m=j-4}^{j+3} X[m]                                         # moving_sum8, signed
pa = argmax_{j∈[4,149)} S_A(j)                                       # init −2^29
lo = max(pa-4, 4);  pb = argmax_{j∈[lo, lo+145) ∩ [.., B.n-4)} S_B(j)   # init 0
a = 4;  b = 4 + pb - pa;  b = min(b, B.n - 150)                       # epoch_align_peaks
A[a+j] = (T[N-2j]*B[b+j] >> 15) + (T[2j]*A[a+j] >> 15),  j = 0..H-1   # taper_xfade_step2, 5 ms
emit(A[0 : a+H/2]) as unit i-1;  emit(A[a+H/2 : a+H]) as unit i
pushback(B[H+b : B.n]);   rpos = H + b
# the crossfade starts exactly at prev's nominal end; unit i starts b samples into its span

# type 4  join_fade10_in2    (after a merged zero-length unit; prev hi 0x40 → A = last N of core)
B = decode(W[0x26]=44)
A[k] = A[k]*T[k] >> 15,        k = 0..N-1          # taper_fade_out_step1, 10 ms
emit(A)
B[k] = B[k]*T[N-5k] >> 15,     k = 0..43           # taper_fade_in_stepn, 2 ms
emit(B);  rpos = 44
```

All four join types are followed by the same `unit_emit_body` and `unit_read_tail` calls (C).

Every join's emit calls also move the event anchors (`emit_samples_markers` `0x10003c50`, `subrec_relayout` `0x100046c0`). A marker's output sample position is its unit's output position plus its sub-record offset (C).

**Which join type each unit gets is decided in the voice font, not here (I).** The flags byte arrives filled in. The only setter inside the synth is `tp_merge_zero_dur_units`, which writes hi 0x40 and lo 4 (C).

The natural pairings follow from buffer coverage (I):

| next unit's join type | prev's tail extension | why |
|---|---|---|
| 0 | 0 | |
| 2 | 0x20 | 2N extension fills the 2N correlation window; with hi 0 A has only N real samples |
| 1 | 0x10 | |
| 4 | 0x40 | |

**Duration and pitch (C):** no sample is repeated, dropped or resampled per unit. Unit duration is only the window `[pos−lead, pos+dur+ext)`. There is no F0 field in the input.

---

## 3. Speaking rate (`rate_*`, stage object 0x440 B, vtable `0x10011a68`)

### 3.1 Parameters (C)

| param | range | effect |
|---|---|---|
| `rate` | 1..100, default "50" (`DAT_100180c8`) | index into the wpm table |
| `raterelchg` | percent | new rate = `rate + rate·relchg/100`, must stay in 1..100 |
| `ratewpm` | (wpm[0], wpm[100]] | nearest rate index by binary search (`rate_from_wpm` `0x100073f0`) |
| `pausestatus` | "0" or other | "0" applies changes now (`rate_set`); otherwise they are queued in R+0x284 |

Inline markers can also change the rate inside `rate_run` (`0x10008250`). They are event type 0x10 with sub-type:

| sub-type | value |
|---|---|
| 4 | ASCII digit `c`: rate = `c·10 − 480`, so '0'..'9' → 0..90 |
| 0x100 | the rate itself |
| 0x800 | a wpm value |

Event type 0x20 (pause) temporarily forces rate 50 (C).

wpm table (`rate_build_wpm_table` `0x10007720`). `base` = R+0x294 = the voice header's `+0x80` number. `synth_obj_open` passes it as stream param 6 via `FUN_10005ec0`, with 200 as the placeholder before that call (C):

```
wpm[0]   = base/2
wpm[k]   = base/2 + k·(base - base/2)/50          k = 1..49
wpm[50]  = base
wpm[50+k]= base + k·(2.5·base - base)/50          k = 1..49
wpm[100] = 2.5·base
```

Tom (`+0x80` = 173): 86 wpm at rate 0, 173 wpm at rate 50, 432 wpm at rate 100 (I: the field means native wpm).

Percent change, `rate_to_pct` (`0x10007510`) (C):

| rate | pct |
|---|---|
| < 50 | rate − 50 |
| 50..100 | 3·rate − 150 |
| > 100 | 150 |

So pct runs from −50 to +150. `speed = 100 + pct`. This agrees with the wpm table: `wpm(rate) = base·speed/100`.

### 3.2 WSOLA (`wsola_*`, object 0x104 B from `wsola_create` `0x10009760`) (C)

| symbol | 22050 Hz value | where |
|---|---:|---|
| frame `L` | 10 ms = 220 | `wsola_set_frame_ms(10)` |
| tolerance `Δ` | 4 ms = 88 | `wsola_set_tolerance_ms(4)` |
| analysis hop `Sa` | `L·speed/100` | `wsola_set_speed`, re-run when pct changes |
| synthesis hop | `L` | |
| input buffer | `3L + 2Δ + Δ` = 924 | |

- **Bypass:** when pct == 0 the stage copies input to output unchanged (state 4).
- **Window** (`wsola_build_hann` `0x10009360`, 2L entries, Q16):
  - `w[i] = (65536 − cos_q16(π·i/L)) / 2`, clamped to 0xFFFF.
  - `cos_q16` (`0x1000a8b0`) is a polynomial on the reduced argument: `1 − 0.49669·x² + 0.03552·x⁴` (coefficients 0x7F27, 0x918).
- **Overlap-add** (state 5, `wsola_process` `0x1000a0b0`):
  - `out[i] = sat16( w[i]·cur[i] + w[L+i]·prev_cont[i] ) >> 16`, for i = 0..L−1.
  - The two weights sum to 1, so this is a complementary raised-cosine crossfade over 10 ms.
- **Segment search** (`wsola_find_offset` `0x1000a020`):
  - The two ping-pong buffers are each decimated twice by an 8-tap half-band FIR. Coefficients `{−1461, 2736, −6009, 20531, 20531, −6009, 2736, −1461}` at `0x10011b58`, sum 0.964. Code: `halfband_decimate2` `0x1000b0d0`.
  - The match criterion is the maximum **unnormalised** cross-correlation with the natural continuation `prev[pos_prev + L …]`, accumulated in 64 bits (`add64_carry`).

  | level | rate | lags | correlation length |
  |---|---|---|---|
  | coarse (`0x10009ed0`) | 1/4 | 45 lags covering 0..±Δ | 110 |
  | mid (`0x10009d80`) | 1/2 | ±3 | 220 |
  | fine (`0x10009c40`) | full | ±3 | 440 = 2L |

  The result is an offset within ±88 samples.
- **Pitch is preserved**, because this is time-domain TSM. Markers ride along as an 8-byte `{int32 sample, u8 tag}` record per sample, through a 127-entry tag ring that re-times them.

---

## 4. The taper table (`0x1001110c`, chosen by `join_select_taper` `0x100045f0`)

Four contiguous int32 tables. `L = N + 1`, which makes each ≈10 ms. Dumped from the file with `C:\tmp\synth_taper_dump.py` and `C:\tmp\synth_taper_fit*.py` (C):

| fs | address | L | T[0] | T[(L−1)/2] | T[L−1] |
|---|---|---:|---:|---:|---:|
| 8000 | `0x1001110c` | 81 | 32733 (0x7FDD) | 16368 | 3 |
| 16000 | `0x10011250` | 161 | 32736 | 16368 | 0 |
| 11025 | `0x100114d4` | 113 | 32735 | 16368 | 1 |
| 22050 | `0x10011698` | 221 | 32736 | 16368 | 0 |

The descriptor at W+0x30 is `{L, L, ptr}`.

Shape (C, from the dump):

- **Exact complement:** `T[n] + T[L−1−n] = 32736` (0x7FE0) for every n, in all four tables.
- **Formula:** `T[n] = 32736 · ½·(1 + cos(π·(n + ½)/L))`, within ±1 LSB. This is a half-sample-offset raised cosine (Hann half), i.e. `32736·cos²(π(n+½)/2L)`.
  - Largest residual: 0.90 / 0.98 / 0.97 / 0.99 LSB.
  - The table sits slightly above the curve in the first half and slightly below it in the second (mean +0.29..0.38 / −0.29..0.38 LSB). That is what you get if the second half was rounded and the first half filled as `32736 − mirror`, but no simple floor, ceil or round rule reproduces it bit-exactly.
  - **Ship the dumped tables verbatim**, not the formula.
- **Amplitude:** 32736 = 0.99902 in Q15. The crossfades therefore lose 0.0085 dB, and their sums can never overflow 16 bits.

22050 Hz table, first and last 8 values:

```
32736 32733 32726 32716 32703 32686 32667 32644 …  20 10 3 0     (T[110] = 16368)
```

How the tables are read (C):

| user | indexing | length | effect |
|---|---|---|---|
| `taper_xfade_full` | T[j], T[N−j] | N | 10 ms crossfade (type 2) |
| `taper_xfade_step2` | T[2j], T[N−2j] | N/2 | 5 ms crossfade (type 1) |
| `taper_fade_out_step2` / `taper_fade_in_step2` | step 2 | N/2 | 5 ms fades (type 0) |
| `taper_fade_out_step1` | step 1 | N | 10 ms fade-out (type 4) |
| `taper_fade_in_stepn` | step 5 | N/5 | 2 ms fade-in (type 4) |

The WSOLA stage does not use these tables; it builds its own Q16 Hann (§3.2).

---

## 5. Everything else on the path after decode

Chain built in `synth_obj_open`. Each stage's process slot is vtable +0x30 (C):

```
synth core (§2) ──► rate/WSOLA  (vtable 0x10011a68, process 0x10007e20)
                ──► volume      (vtable 0x10011d90, process 0x1000be70)
                ──► audio-ins   (vtable 0x10011df0, process 0x1000cb70, "SYNTH_CODED")
                ──► synth_output_sink 0x10001d90 ── filter_markers_by_mode(markermode) ──► host callback
```

- **Codec output (C).**
  - The codec's own DC-blocking high-pass (`FUN_1000f310`, pole 0x7EB8) is the only filter anywhere on the path.
  - There is no post-filter, no de-emphasis, no AGC, no dither and no resampler.
- **Volume (C).**
  - Params: `volume`, 0..100, default 80; `volumerelchg`.
  - Gain table: `volume_to_gain` reads 101 × u16 Q15 at `0x10011cc0`. Applied as `sat(x·g >> 15)` to ±32767.
  - Gain is ≈0.3 dB per step, with exact anchors:

    | volume | gain | level |
    |---:|---:|---|
    | 0 | 0 | mute |
    | 1 | 2048 | −24.1 dB |
    | 20 | 4096 | −18.1 dB |
    | 40 | 8192 | −12.0 dB |
    | 60 | 16384 | −6.0 dB |
    | 80 | 32767 | 0 dB, **bypass** |
    | 100 | 65534 | +6.0 dB |

  - Gain changes ramp over `int((fs+500)·0.001 · 30)` samples (676 at 22050 Hz, 30 ms). The ramp shape is chosen by direction:

    | direction | ramp |
    |---|---|
    | rising | `32767·(e^{(n−k+1)/(n+1)} − 1)/(e − 1)` |
    | falling | `32767·log10(9·(n−k+1)/(n+1) + 1)` |

    Code: `volume_build_ramps` `0x1000bc10`. Constants at `0x10011dc8`: 32767.0f, 1.0, 9.0, 30.0f, 500.0f.
  - Inline markers can set the volume: type 0x10, sub-type 1 (value·10) or 0x40 (direct).
- **Audio insertion (C).**
  - Event type 8 with a negative value pulls audio from the `AUDIO_FETCHER` object (`audioins_run` `0x1000cf20` → `FUN_1000d740`) and splices it into the stream.
  - Otherwise the stage is a pass-through.
- **Sample rate (C).**
  - `frequency` param: "8" / "11" / "16" / "22" → 8000 / 11025 / 16000 / 22050 Hz (`parse_frequency` `0x10001ea0`).
  - The ACELP codec itself is fixed at 22050 (state +0x14), so a 22 kHz voice needs `frequency=22` (I).
- **Silence (C).**
  - Per-unit leading pause: `u.pause` ms.
  - Pause events: `round(ms·fs/1000 + 0.5)`.
  - End of utterance: `tail_pause + waitfactor·0.2·fs`, with waitfactor 0..9, default 2 (= 400 ms).

### 5.1 New codec finding: excitation-only warm-up (C)

`codec_decode_frames` (`0x100062e0`, codec +0x38) chooses the frame flag from `skip`, the number of samples still to discard:

| condition | flags | frame type |
|---|---:|---|
| `skip ≥ 3·320` | **1** | excitation-only (uniform LSF, no synthesis filter, output discarded) |
| `320 ≤ skip < 960` | 0 | full decode, output discarded |
| `skip < 320` | 0 | full decode, output kept after the remaining skip |

With 6 lookback frames and the 40-sample delay, `skip` = 1920 + (s mod 320). So every unit decodes **4 excitation-only frames, then 2 full warm-up frames**, then its first output frame.

This corrects `README_TECHNICAL.md` §5 ("No shipped path was seen setting it"). It also matters for `codsb_dump` departure D7: a bit-exact unit extractor must use flag 1 on the first 4 lookback frames.

---

## 6. Open questions

1. **Which join type the voice font picks.**
   - `vf_tom_full.dll` fills unit `+0x16`. Its rule (context class? voiced/unvoiced? contiguity?) decides whether type 0 is common or rare. Today that is unknown.
   - Next step: trace the writer of the 0x2b unit stream in `/rs_vf_tom_full.dll`.
   - It is also unconfirmed whether the low and high nibbles are always set as the pairs in §2.3.
2. **The exact rounding rule that generated the taper tables** (±1 LSB unresolved). It does not matter if the tables are copied verbatim.
3. **`W[0x22]`** (260 / 188 / 130 / 94) is set but not referenced on the paths read. Possibly dead.
4. **Event list layout** beyond the fields used here:
   - known: +0 type, +0xc sample position, +0x14 value, +0x16 sub-value
   - not decoded: the `markermode` bit meanings (default 0x1F9), and `FUN_1000f170` / `FUN_1000f0b0`, the event filters with masks 0x30/0x904 and 0x41.
5. **The `+0x80` field = "native wpm"** is inferred from how it is used. A measurement would confirm it: Tom at rate 50 should come out near 173 wpm.
6. **The 8 kHz and 16 kHz tick/ms constants** are probably wrong. That is irrelevant to the 22 kHz voices.

---

## 7. Functions created and renamed in `/rs_synth_155mrf22.dll`

Created; each also renamed, as shown:

| address | name |
|---|---|
| `0x10001540` | `synth_check_voice_compat` |
| `0x10001820` | `synth_class_noop` |
| `0x10001830` | `synth_obj_open` |
| `0x10002220` | `synth_to_pcm` |
| `0x100022d0` | `synth_process_events` |
| `0x10002860` | `synth_set_param` |
| `0x100062e0` | `codec_decode_frames` |
| `0x10006f80` | `rate_param_validate` |
| `0x100070d0` | `rate_param_changed` |
| `0x10001d90` | `synth_output_sink` |

Created and left with `FUN_` names (vtable slots not analysed):

- `0x10007a10`, `0x10007e00`, `0x10007b50` (rate vtable)
- `0x1000be70`, renamed `volume_process`
- `0x1000ba40` (volume vtable)
- `0x1000cb50`, `0x1000ca20` (audio-insertion vtable)
- `0x10005ee0` (codec create; the prior doc named it, but no function was defined)
- `0x1000edd0`, `0x1000ee90` (PCM codec vtable)

Renamed (existing `FUN_` names):

- **Interface:** `synth_obj_close`, `synth_get_param`, `synth_reset_param`, `synth_reset_params`, `synth_open_voice_data`
- **Unit-list driver:** `tp_run_unit_list`, `tp_reset_state`, `tp_fetch_input_streams`, `tp_convert_unit_times`, `tp_merge_zero_dur_units`
- **Conversions and helpers:** `ticks100us_to_samples`, `ms_to_samples`, `mul_q31_round`, `round_to_mult4`, `calc_samples_per_ms`, `parse_frequency`, `set_waitfactor`, `handle_waitfactor_marker`
- **Join engine:**
  - setup: `join_ws_init`, `join_ws_set_rate_consts`, `join_select_taper`, `concat_units`
  - per unit: `unit_begin`, `unit0_lead_pause`, `unit_emit_body`, `unit_read_tail`
  - the four joins: `join_fade_out_in`, `join_sola_xfade`, `join_epoch_xfade`, `join_fade10_in2`
  - alignment: `sola_find_lag`, `epoch_align_peaks`, `moving_sum8`
  - tapers: `taper_fade_out_step2`, `taper_fade_in_step2`, `taper_xfade_full`, `taper_xfade_step2`, `taper_fade_out_step1`, `taper_fade_in_stepn`, `zero_i32`
- **Buffering and output:** `decode_into_buf`, `pending_drain`, `pending_load`, `emit_samples_markers`, `emit_samples`, `emit_to_outbuf`, `emit_silence`, `flush_outbuf`, `output_state_step`, `subrec_relayout`, `subrec_find_marker`, `data_map_unit`, `data_decode`, `filter_markers_by_mode`
- **Rate stage:** `rate_open`, `rate_process`, `rate_run`, `rate_build_wpm_table`, `rate_set`, `rate_to_pct`, `rate_from_wpm`
- **WSOLA:** `wsola_create`, `wsola_set_frame_ms`, `wsola_set_tolerance_ms`, `wsola_set_speed`, `wsola_build_hann`, `wsola_rebuild_hann`, `wsola_process`, `wsola_find_offset`, `wsola_xcorr_coarse`, `wsola_xcorr_mid`, `wsola_xcorr_fine`, `wsola_decimate_bufs`, `halfband_decimate2`, `cos_q16`, `add64_carry`
- **Volume stage:** `volume_open`, `volume_apply`, `volume_set`, `volume_to_gain`, `volume_build_ramps`, `volume_ramp_lookup`
- **Audio insertion:** `audioins_open`, `audioins_process`, `audioins_run`

Scratch scripts (not project files):

- `C:\tmp\synth_taper_dump.py`, `C:\tmp\synth_taper_fit.py`, `C:\tmp\synth_taper_fit2.py`, `C:\tmp\synth_taper_fit3.py`: taper dump and fit
- `C:\tmp\synth_consts.py`: conversion factors and the volume table
