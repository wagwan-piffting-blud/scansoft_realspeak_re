# RealSpeak Solo v4 (2006) prosody: `pros_*` inside `vf_tom_full.dll`

Ghidra program `/rs_vf_tom_full.dll` (`RealSpeak\speech\components\voicefont\vf_tom_full.dll`),
2026-10-23. Functions were re-created and renamed in this session; **the program is not saved**.
Every claim is CONFIRMED from code or data unless it is marked INFERRED.

## Summary

- **Prosody is compiled into each voice font.** No separate `pros` DLL exists; every
  `vf_*_full.dll` carries the error strings and the code. `vf_GenPcm` runs `pros_ToEpt`, then
  the `us_ToSeg` unit-selection state machine, then `synth_ToPcm`.
- **It is entirely symbolic.** It inserts phrase breaks and pauses and rewrites the five
  parallel symbol tiers. It produces no F0 contour and no duration targets. Unit selection
  writes the numeric layers (`USDURS`, `USRATES`, `USPM`).
  - INFERRED: this voice's pitch and timing come from the selected recordings, which is
    RealSpeak-style "prosody from the corpus".
  - Speechify 3.0.5 differs: it predicts F0 and durations with CART trees and uses them as
    selection targets.
- **Phrase breaks and pauses:** a hand-coded decision tree gives the break level (0–3); a
  compiled 11-feature decision tree decides pause insertion. The pause length is one of
  **101 / 121 / 138 / 160** (INFERRED: ms), chosen by punctuation class. Pauses are spliced
  into the phoneme tier as the token `#[NNN]`.
- **The rest is a multi-tier rewrite-rule engine.** 654 rules in 12 block slots (8 non-empty) over 5
  tiers; blocks 3 (198 rules), 0xB (130) and 4 (217) run in that order. (Corrected
  2026-10-23: header +4 = 23 is the highest rule-variable index, not a set count.
  `PROS_ApplyRewriteRuleMatch` `0x100177f0` clears `ctx+0x360[0..=+4]`. CONFIRMED;
  `notes\fe_2004_vs_2006.md` §3.)
- **This resolves an open item.** The "undecoded" record after `vf_GetInterface` slot 27,
  `{u16 5, u16 645 (SS) / 654 (RS), u32 23, ptrs…}` in DLL_ANALYSIS §3.4, is this rule
  table's header: 5 tiers, rule count, highest variable index 23.

## The message and its layers (tags)

`vf_GenPcm` reads and frees layers through `FUN_10012d60(msg, tag, &ptr, &n)` (get) and
`FUN_10012f40(msg, tag)` (free). Each data layer has a buffer pointer at +0 and a u16 count
at +4.

| tag | name | role |
|---:|---|---|
| 7 | `GR_TTS` | per-symbol tier, read by prosody (grapheme / ortho tier, INFERRED) |
| 8 | `PM_TTS` | **phoneme tier** (not pitch marks); prosody inserts `#[NNN]` pause tokens here |
| 9 | `POS_TTS` | part-of-speech tier |
| 10 | `MORPH_TTS` | morphology tier; prosody writes the break level `'0'+level` at word ends |
| 0xC | `CM_U8` | per-symbol byte tier kept in step with the others (obj+0x3dc) |
| 0x10 | `INTON_TTS` | intonation tier |
| 0x12 | `M_MRKREC` | marker records, 0x18 bytes each; type 0x20 = user pause, value at +0x14 |
| 0x19–0x1d | `USPM`, `USRATES`, `USDURS`, `USIDS`, `USPLOSIVES` | unit-selection outputs |
| 0x1f, 0x24 | `ADJACENCY_U8`, `USMARKERS_U8` | unit-selection outputs |
| 0x2b, 0x2c | `UNIT_UNIT`, `SUBUNIT_SUBUNIT` | unit list consumed by `synth_ToPcm`; freed last |

Tiers 8, 7, 9, 10 and 0x10 are **parallel arrays of one byte per symbol**, sharing one count.
Every insertion shifts all five, plus CM. Filler symbol `~`; word separator `' '`.

## `vf_GenPcm` (slot 12, `0x10001b70`)

```
if obj.reset_pending: synth->ResetParams(synth_obj)          # vtable +0x24
if message empty (FUN_10001170): flush markers, return
pros_ToEpt(obj.pros, msg)                                     # PROS_ToEpt 0x100029b0
free GR, POS, INTON, MORPH                                    # tags 7, 9, 0x10, 10
state = 1
loop:
    us_ToSeg(obj.us, msg, &state, &x)                         # US_ToSeg 0x10003860
    if state == 4:
        optional debug dump of USIDS
        free PM, USPM, USRATES, USDURS, USIDS, USPLOSIVES, CM, USMARKERS, ADJACENCY
    synth->ToPcm(synth_obj, msg)                              # vtable +0x28
    until state == 4 (then free M_MRKREC, SUBUNIT, UNIT)
```

## `pros_ToEpt` (`PROS_ToEpt`, `0x100029b0`)

1. `FUN_10002ad0`: map tiers 8/7/9/10/0x10 into `ctx->tiers[]` (+0xac..+0xbc), CM to
   +0x3dc, markers to +0x3e0/+0x3e4.
2. `FUN_10002e20` → `FUN_10002f60` (init: capacity **0x5dc = 1500** symbols; rule table
   `DAT_10019110`), then `FUN_10002fe0`, five stages in order:
   1. `PROS_PredictPhraseBreaksAndPauses` (`0x100133c0`)
   2. `PROS_RunRewriteRuleSet(ctx, 3, …)`
   3. `PROS_RunRewriteRuleSet(ctx, 0xB, …)`
   4. `PROS_RunRewriteRuleSet(ctx, 4, …)`
   5. `PROS_ExpandUserPauseMarkers` (`0x10018b00`)
3. `FUN_10002c60`: write the new symbol count back to all six tiers. A logger callback then
   dumps tags 8, 7, 9, 10 and 0x10.
4. Overflow past 1500 sets `ctx[0x32b]`, and the call returns `0x81002000`.

### Stage 1: phrase breaks and pauses (`0x100133c0`)

- **Word classes:** for each word (delimited by `' '` in the phoneme tier), the class comes
  from the POS tier through a 57-entry pattern table `DAT_10027964`. Each 3-byte entry is
  {POS char, next POS char or 0, class}; the default class is 0x12.
- **Punctuation strength:** per boundary, from `DAT_10027a14[symbol]`. When several marks
  meet, the strongest wins by priority `DAT_10027b14`. The default at the end is 2.
- **Context per boundary**, 11 bytes:
  - index in phrase and words remaining
  - punctuation before / at / after
  - word classes w−3 … w+3
- **Break level:** `PROS_ClassifyBreakLevel` (`0x100146a0`), a hand-coded tree on
  punctuation (byte 3) and the classes of the current and next word (bytes 8, 9). It gives
  0–3, forced to **3** at the last boundary.
- **Pause decision:** `PROS_DecidePauseByTree` (`0x10013e50`), a compiled decision tree
  testing feature bytes in the order **3, 7, 8, 9, 6, 4, 10, 5, 2, 0, 1**.
  - Node tables: `DAT_10027c14`, `…c38`, `…d54`, `…8358`, `…94a0`, `…ad90`, `…bcec`, `…c6d0`,
    `…d27c`, `…d7c0`, `…db84`, `…dea0`.
  - Node layout: `u16 n`, then n × {u16 value or 0xFFFF wildcard, u16 child}.
- **Pause length:** `PROS_GetPauseLength` (`0x10013e10`):
  - punctuation ∉ {0, 3, 8, 9, 10}: **160**, or **138** if punctuation == 1
  - otherwise: **121** if the next-feature byte > 1, else **101**
- **Splicing:** the length is written as decimal digits into the phoneme tier as
  `#[NNN]`, with the other tiers filled with `~`.

### Stages 2–4: the multi-tier rewrite-rule engine (`PROS_RunRewriteRuleSet`, `0x100178e0`)

**Rule table header (`DAT_10019110`):**

| offset | value |
|---|---|
| +0 | `u16 n_tiers = 5` |
| +2 | `u16 n_rules = 654` |
| +4 | `u16 max_var = 23` (highest rule-variable index; was misread as n_sets) |
| +8 / +0xC | `u16` rule-set start / end indices |
| +0x28 | rule bytecode offsets (int[]) |
| +0x2C / +0x30 | left / right context lengths (byte[]) |
| +0x38 / +0x3C | skip counts (byte[]) |
| +0x40 / +0x44 | first / last symbol-class prefilter (byte[]) |
| +0x48 | bytecode base |

**Rule-set ranges, 1-based:**

| set | rules | count |
|---|---|---:|
| 3 | 1–198 | 198 |
| 4 | 199–415 | 217 |
| 5 | 416–427 | — |
| 6 | 428–440 | — |
| 7 | 441–447 | — |
| 8 | 448–500 | — |
| 9 | 501–524 | — |
| 0xB | 525–654 | 130 |

**Dispatch:**
- A symbol histogram of the span is built first. A rule runs only if both its prefilter
  classes are present.
- The opcode (first bytecode byte, −100 if > 100) picks a search mode:
  - 1/2: forward/backward, all matches, anchored on a symbol
  - 3/4: forward/backward, first match
  - 5–8: unanchored scans
  - 9–16: scans with sub-rule groups (skip counts at +0x38/+0x3C)
  - **99: switch the active tier pair** (`ctx+0x348 + idx*4` → tiers)
- Each match calls `PROS_ApplyRewriteRuleMatch` (`0x100177f0`).

INFERRED from the order and the tiers they touch: set 3 accent/stress assignment, 0xB
intonation-pattern marking, 4 boundary-tone/cleanup. Decoding the bytecode would confirm
this; not done.

### Stage 5: user pauses (`0x10018b00`)

Markers of type 0x20 (user pause requests) fill the `#[]` placeholders with their decimal
value. The symbols are shifted across all tiers and the capacity is checked against 1500.

## Functions created / renamed (unsaved)

`vf_ObjOpen` 0x10001350, `vf_GenPcm` 0x10001b70, `PROS_ToEpt` 0x100029b0, `US_ToSeg`
0x10003860, `PROS_RunRewriteRuleSet` 0x100178e0, `PROS_ApplyRewriteRuleMatch` 0x100177f0,
`PROS_PredictPhraseBreaksAndPauses` 0x100133c0, `PROS_ClassifyBreakLevel` 0x100146a0,
`PROS_DecidePauseByTree` 0x10013e50, `PROS_GetPauseLength` 0x10013e10,
`PROS_ExpandUserPauseMarkers` 0x10018b00.

## Open

- Decode the rule bytecode (`+0x48`) and name what rule sets 3, 0xB and 4 do. Sets 5–9 are
  called from elsewhere (INFERRED: the slot 19–27 thunks).
- What `us_ToSeg` writes into `USDURS` / `USRATES` / `USPM`, and whether `synth_ToPcm` then
  modifies pitch or duration toward any target. This is the decisive "prosody from the
  corpus?" check; see `notes\synth_concat_2006.md`.
- ScanSoft 2004: the same structure is expected (645 rules). Compare the tables when
  `ScanSoft\…\vf_tom_full.dll` is open again.
