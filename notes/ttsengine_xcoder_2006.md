# RealSpeak Solo v4 (2006): `ttsengine.dll` + `xcoder.dll`

**Dated 2026-10-23.** Ghidra programs `/rs_ttsengine.dll`
(`RealSpeak\speech\components\common\ttsengine.dll`) and
`/rs_xcoder.dll` (`...\components\common\xcoder.dll`). Base 0x10000000 for both. Nothing was
saved; the functions created and renamed (last section) exist only in the open Ghidra session.

Tags: **CONFIRMED** = seen in code or data. **INFERRED** = reasoning from structure, names
or L&H conventions.

Helper probes, in the scratchpad
`%TEMP%\claude\<session>\scratchpad\`:
- `immrefs.py`: imm32 references to an address in `.text`. Used in place of the xref tool group, which did not register in this session.
- `strgrep.py` and `exactstr.py`: string presence across `RealSpeak\speech\components`.

---

## Summary

- **The component is `ttseg`, not "ttsengine".** It has one export, `ttseg_GetInterface`
  (ordinal 1, `0x1000e5c0`), which returns a 24-slot table at `0x10013370`. ttseg is a pure
  orchestrator: it does no DSP and no linguistics. CONFIRMED
- **Per-sentence pipeline:** text → `xcoder` (charset) → [`mparser` markup] → **PP**
  (`stdpp_enu`, slot 12) → **G2P** (`g2p_enu`, slot 13) → **VF** (`vf_*_full`, slot 12
  `vf_GenPcm`) → PCM callback → app. The stages pass one shared typed **message object**
  (sections keyed by type id; type 0x12 holds 0x18-byte marker records). ttseg loops
  sentence by sentence until PP returns `0x3002003`. CONFIRMED
- **Parameters are strings in a `paramc` store** (obj+0xaf8). Components read them through
  `paramc` listeners. ttseg range-checks and stores pitch, rate and volume but applies none of
  them. No other RealSpeak component contains the string `"pitch"` or `"pitchrelchg"`; the
  synths listen on `rate` / `ratewpm` / `raterelchg` / `volume` / `volumerelchg`. String
  absence CONFIRMED; that pitch is therefore a no-op in this build is INFERRED.
- **`xcoder.dll` is a TEXT-encoding transcoder, not an audio one.** It converts input
  charsets (UTF-8, UTF-16 with BOM detection, UCS-4, ISO-8859-x, code pages) by routing
  through `xlit/<charset>` components, and maps marker text positions back to input offsets.
  No resampling, no µ-law/A-law, no filter. CONFIRMED
- **ttseg does not touch dictionaries.** It forwards PP's per-token "Dictionary Lookup"
  callback to an app-supplied callback. The edct/dcteg MIME types live in the API layer
  (`rssoloapi`, `rs_sapi5_solo`, `swisolo`) and in `dcteg.dll`. CONFIRMED (strings); routing INFERRED

---

## 1. Exports and interface

### 1.1 Exports

| dll | export | addr | notes |
|---|---|---|---|
| ttsengine.dll | `ttseg_GetInterface` (ord 1) | `0x1000e5c0` | `ver ∈ {0,3}` → `*out = 0x10013370`, else `0x81202001`. The test is `ver!=0 && (ver==2 || ver!=3)`. CONFIRMED |
| xcoder.dll | `xcoder_GetInterface` (ord 1) | `0x10001170` | `ver < 2` → `*out = 0x10003090`, else `0x89d3e001`. CONFIRMED |

Banners: `CDF ttsengine 1.6 / Copyright 2003` @`0x10014010`; `xcoder 1.00 / Copyright 2004`
@`0x10004010` (the `.hdr` says `VERSION 3.5`).

Imports (ttseg): `brk_*` from `combrk.dll` (InterfaceQuery/Release, ComponentTableQuery/Release,
TagQuery/Release, ObjOpen/Close), and from `comrsrc.dll` the `paramc_*` (incl.
`ParamSilentBackupThenSet`, `ParamSetTmpOverride`, `ParamResetAllToDefault`,
`ForceNotifyListeners`), `srvspi_SecEx*` (state machine), `objc_*` (named object registry),
`critsec_*`, `heap_*`, `safeh_*`, `osspi_*`, `InitRsrcFunction`. **No `brk_DataOpen`**: ttseg
never maps data itself. CONFIRMED

### 1.2 `ttseg` interface table @ `0x10013370`

The slot numbering follows `vf_GetInterface`: slot n sits at `+4n`, and slots 0 and 1 are 0.

| slot | +off | addr | name given | role |
|---:|---:|---|---|---|
| 2 | 0x08 | `0x10001ac0` | `ttseg_ClassOpen` | 0x20-B class object (magic 0xcdad); critsec; queries `tso/logging` iface → class+0x1c. CONFIRMED |
| 3 | 0x0c | `0x10001e30` | `ttseg_ClassClose` | "Some TTSEG objects not closed yet". CONFIRMED |
| 4 | 0x10 | `0x10001f20` | `ttseg_ObjOpen` | 0xb04-B instance (magic 0xcdac); see §2.1. CONFIRMED |
| 5 | 0x14 | `0x100050e0` | `ttseg_ObjClose` | srvspi state check ("TTSEG Object busy"), unloads parts. CONFIRMED |
| 6 | 0x18 | `0x10005b20` | `ttseg_GetParams` | list of `{u32 id, u16 val, ptr}` (12 B). count 0 or NULL → all 0x23 ids (2..0x24). One id = `ttseg_get_param_one` `0x10005270`. CONFIRMED |
| 7 | 0x1c | `0x10005cd0` | `ttseg_SetParams` | §3. CONFIRMED |
| 8 | 0x20 | `0x10007110` | `ttseg_ResetParams` | pitch=50, rate=50, volume=80, waitfactor=2, readmode=1. CONFIRMED |
| 9 | 0x24 | `0x10007530` | `ttseg_Speak` | thunk → `ttseg_SpeakFromUri(obj,h,0,NULL,nullhandle)`. Text arrives via the app input callback. CONFIRMED |
| 10 | 0x28 | `0x1000a040` | `ttseg_Break` | `srvspi_SecExToState(...,→4)`; the speak loop polls state==4 and aborts ("Speaking is interrupted"). CONFIRMED |
| 11 | 0x2c | `0x10009590` | `ttseg_Transcribe` | text → phonemes only: PP, then G2P slot 15 `TranscribeBroadLhp`; output via transcribe callback. CONFIRMED |
| 12 | 0x30 | `0x1000a180` | `ttseg_GetProductList` | "TTSENGINE" product tag. CONFIRMED (string) |
| 13 | 0x34 | `0x1000a3f0` | `ttseg_GetLanguageList` | `brk_ComponentTableQuery` + tags (`ISOCODE`, `lng/*`). CONFIRMED (strings) |
| 14 | 0x38 | `0x1000a750` | `ttseg_GetVoiceList` | tags `VOICEFONT`, `VOICEAGE`, `VOICETYPE`. CONFIRMED (strings) |
| 15 | 0x3c | `0x1000ae10` | `ttseg_GetDocumentList` | tags `COMMAND`, `MANUFACTURER`. CONFIRMED (strings) |
| 16 | 0x40 | `0x1000b2c0` | `ttseg_GetCustomG2PList` | `cg2p/*`. CONFIRMED (strings) |
| 17 | 0x44 | `0x1000bce0` | `ttseg_SpeakFromPosition` | "Out of range (%d) to jump". CONFIRMED (strings) |
| 18–20, 22 | 0x48–0x50, 0x58 | `0x100012f0` | `ttseg_stub_return_ok` | `return 0`. CONFIRMED |
| 21 | 0x54 | `0x1000b6a0` | `ttseg_GetSpeechDBList` | tags `REALSPEAKDATA`, `CODER`, `REDUCTIONTYPE`, `VOICEFREQUENCY`. CONFIRMED (strings) |
| 23 | 0x5c | `0x10007550` | `ttseg_SpeakFromUri` | `(obj,h,uri,mime,…)`; uri≠0 → `INET` object fetch. MIME: `default`, `text/xml`, `application/synthesis+ssml`, `text/plain[;charset=…]`, else `0x81202012`. CONFIRMED |

### 1.3 Instance object (0xb04 B): offsets used in the pipeline

| off | dword idx | content | tag |
|---|---|---|---|
| +0x00 | 0 | rsrc ctx (from `InitRsrcFunction`: +4 heap, +0xc broker, +0x10 log, +0x14 paramc, +0x18 objc registry) | CONFIRMED |
| +0x24 | 9 | app context passed to every app callback | CONFIRMED |
| +0x28 | 10 | **message object** for the current speak | CONFIRMED |
| +0x2c | 0xb | `tso/logging` session handle | CONFIRMED |
| +0x48/+0x4c | 0x12/0x13 | `ttseg_position_seek_cb` / `ttseg_transcribe_out_cb` | CONFIRMED |
| +0x60 / +0xc0 / +0x110 / +0x174 | 0x18/0x30/0x44/0x5d | component names: PP / G2P / VF / mparser | CONFIRMED |
| +0xa0, +0xa4..+0xb0, +0xb4 | 0x28, 0x29..0x2c, 0x2d | PP iface; PP callback block `{0, get_input_text, unget_input, dict_lookup}`; PP handle | CONFIRMED |
| +0x100, +0x104, +0x108 | 0x40, 0x41, 0x42 | G2P iface, G2P handle, G2P class handle (8 B) | CONFIRMED |
| +0x150, +0x154.., +0x168, +0x16c | 0x54, 0x55..0x59, 0x5a, 0x5b | VF iface; VF callback block `{pcm_out_cb, 0, log handle, log iface, paramc}`; VF handle; VF class handle | CONFIRMED |
| +0x364 | 0xd9 | mparser context (0x160 B) | CONFIRMED |
| +0x368, +0x36c | 0xda, 0xdb | xcoder iface, xcoder handle | CONFIRMED |
| +0x384..+0x390 | 0xe1..0xe4 | output type (=1) and a "sample coder" iface slot (always 0, §5.4) | CONFIRMED |
| +0x394 | 0xe5 | custom-G2P load/unload list, 32 × 0x30 B | CONFIRMED |
| +0x994..+0x9a4 | 0x265..0x269 | **app callbacks** copied from ObjOpen arg5: `[0]` input text, `[1]` dictionary lookup, `[2]` audio out, `[3]` transcription out, `[4]` ? | CONFIRMED (copy), roles CONFIRMED by use |
| +0xab8 | 0x2ae | cumulative PCM samples sent this speak | CONFIRMED |
| +0xaf8 / +0xafc | 0x2be / 0x2bf | paramc: **instance params** / **pending (component-reload) params** | CONFIRMED |

---

## 2. Pipeline

### 2.1 ObjOpen: what gets loaded (`ttseg_ObjOpen` `0x10001f20`)

```
ttseg_ObjOpen(cls, clsh, rsrc, heap, cb[5], appctx, params[], nparams, results[], out):
  obj = calloc(0xb04); obj.magic = 0xcdac
  ttseg_init_obj (0x10002a60): paramc_ObjOpen ×2 → +0xaf8, +0xafc
      ttseg_set_param_defaults (0x1000eeb0):        // strings, CONFIRMED @0x10016578..
          volume="80" rate="50" pitch="50" markermode="65529" typeofdoc="Text"
          readmode="2" typeofoutput="1" typeofmarkup="Standard" licensingmode="default"
  obj.cb[0..4] = cb[0..4]
  obj.pp_cb  = {0, ttseg_pp_get_input_text_cb, ttseg_pp_unget_input_cb,
                cb[1] ? ttseg_pp_dict_lookup_cb : NULL}
  obj.vf_cb  = {ttseg_vf_pcm_out_cb, ...}
  brk_InterfaceQuery(broker, "xcoder", 1, &cls, &obj.xcoder)               // 0x100021c3
  obj.xcoder->ObjOpen(rsrc, heap, "inputtypeofchar", "typeofchar", &obj.xh)  // +0x10
  register "TSO" logging object (objc); critsec; srvspi_SecExOpen(...,0xcdac,...)
  for p in params:   // ids → paramc_SetDefault on pending store +0xafc
      2 frequency ∈ {8,11,16,22}   3 language   6 voice   0xb typeofdoc
      0xd typeofchar enum   0x16 coder   0x17 reduction   0x18 typeofoutput (=1 only)
      0x1c inputtypeofchar string
  ttseg_open_service_component("audiofetch", "AUDIO_FETCHER")    // optional
  ttseg_open_service_component("domain_mngr","DOMAIN_MNGR")      // optional
  ttseg_open_service_component("ttt/re",     "RETTT")            // optional regex text transform
  if language/voice given: ttseg_open_parts(obj, ..., 2)
```

`ttseg_open_parts` (`0x10002e60`):
1. `ttseg_CheckValidity` (`0x1000f1f0`) resolves names from the pending params: the language
   to a PP and G2P name, the voice/frequency/coder/reduction to a VF name, the
   `typeofmarkup` to an mparser name. Tags used: `ISOCODE`, `CODER`, `BITRATE`,
   `OVERHEADFRAMES`, `encrypt`, `mparser/*`, `PRIORITY`, `lng/*`, `eng/*`. CONFIRMED (strings);
   resolution details INFERRED
2. `ttseg_unload_changed_parts` (`0x10003e40`) closes whichever of PP, G2P, mparser and VF
   changed. If the VF is unchanged it calls VF slot 15 (`+0x3c`) with the paramc handle
   instead: a live reconfigure. CONFIRMED (call); meaning INFERRED
3. `paramc_ParamSilentBackupThenSet(inst, pending)`
4. `ttseg_load_changed_parts` (`0x10003270`), in this order:
   - **mparser** `ttseg_load_mparser` `0x10003b00`. Skipped if `typeofmarkup=="Standard"`.
     ObjOpen at `+0x10`; its xcoder input is set to `UTF16_PlatformEndian`.
   - **PP** `ttseg_load_pp` `0x100038c0`: `brk_InterfaceQuery(name)`, then
     `PP->ObjOpen(rsrc, heap, &pp_cb, obj, &pph)` at `+0x10`. Then PP `+0x24` SetParam
     `{0x81, markermode}` if markermode was set.
   - **G2P** `ttseg_load_g2p` `0x10003980`: `G2P->ObjOpen(cls, rsrc, heap, &g2ph)`.
   - **domain** `FUN_1000c600`, if the domain manager is present.
   - **VF** `ttseg_load_vf` `0x10003a40`: `VF->ObjOpen(cls, rsrc, heap, &vf_cb, obj, &vfh)`.
     If the VF is unchanged, VF slot 14 (`+0x38`, `vfh`) instead.
   - **custom G2Ps** `FUN_10001050`.

   On failure the old names are restored and it reloads. CONFIRMED

### 2.2 One utterance: `ttseg_SpeakFromUri` (`0x10007550`)

```
ttseg_SpeakFromUri(obj, h, uri, mime, inet_h):
  require language loaded (FUN_10007500==1) else 0x81202002
  srvspi_SecExToState(→ speaking) else "TTSEG object is busy" 0x81202011
  reset counters (+0x5c text offset, +0x2b5.. PCM out state, +0xa6c sentence count)
  if uri: INET fetch; app input cb swapped for FUN_10004be0 (reads fetched buffer)
  if mime: paramc_ParamSetTmpOverride("typeofmarkup"/charset); ttseg_open_parts(...,1)
  msg_create(&obj.msg)                                 // 0x10011b00, 16-B header
  if mparser: FUN_100093b0/FUN_10009410 (prepare markup state)
  r = ttseg_pp_next_sentence(obj)                      // 0x100084a0, see below
  while r == 0:
      if state == 4 (Break): abort
      log "START/END LOGGING OF STANDARD PREPROCESSOR MODULE" (tso/logging +0x10, +0x1c)
      ttseg_apply_position_filter(obj)                 // 0x10008d90, SpeakFromPosition skip
      if msg has 0x10/0x20 on…off region: msg_clear_counts (FUN_100122d0)  // INFERRED: skip region
      r = G2P->[+0x34](g2ph, obj.msg)                  // @0x10007da3  "TranscribeTts"
      if r < 0: "TranscribeTts error"; abort
      log G2P section dump (tso/logging +0x14, level 5)
      r = VF->[+0x30](vfh, obj.msg)                    // @0x10007e80  vf_GenPcm
           // inside VF: pros_ToEpt → us_ToSeg → synth_ToPcm (DLL_ANALYSIS §3.4)
           // PCM leaves through obj.vf_cb[0] = ttseg_vf_pcm_out_cb
      if (r & 0x1fff) == 0x80b: "Empty Message is found" (not an error)
      msg_retype_section(obj.msg, 8, 6)                // leftover type-8 text becomes next input text
      r = ttseg_pp_next_sentence(obj)
         // 0x3002003 + mparser "change PP mode" → ttseg_open_parts(...,1) and retry
  ttseg_send_out_done(obj)                             // app audio cb msg 2
  on abort/error: PP->[+0x34](pph,…) and VF->[+0x34](vfh,…)  (flush/stop)
  restore params: ParamRemoveAll(pending); SilentCopy; ResetAllToDefault; open_parts(…,2);
                  ForceNotifyListeners
```

`ttseg_pp_next_sentence` (`0x100084a0`) and `ttseg_pp_process_fetch_sections` (`0x10008730`):

```
msg_clear_all_sections(msg)
PP->[+0x30](pph, msg)                    // PP Process: pulls text through pp_cb.get_input_text
markers = msg[0x12]; require markers[0].type == 1    // sentence header record
if obj.flag_a94: FUN_1000e5a0(markers, n)
text = msg[6]; extra = msg[0x27]          // string pool for marker string args
ttseg_scan_lang_voice_switch (0x10008840):
   markers[0].byte+0x14 == 2   → language switch, name = text   → ttseg_switch_language_pp
   record type 0x8002           → voice switch, name = pool[+0x14] → ttseg_switch_voice
      (same voice → VF +0x2c; else pending voice/frequency → ttseg_open_parts(…,1))
   remove the 0x8002 record; text offset +0x5c += consumed
```

Text input (`ttseg_pp_get_input_text_cb` `0x1000c900` → `ttseg_read_input_text` `0x1000cbc0`):
- unget buffer, then SpeakFromPosition replay buffer, then
- **no markup**: `xcoder->[+0x2c] ReadConvert(xh, app_input_cb, appctx, &len, buf)`, then
  `FUN_1000d450` (RETTT regex transform, INFERRED);
- **markup**: `mprs_Process` (`FUN_1000ebc0`). `0x309` = markup changed a param; 3 = end of input;
  "Illegal characters found in 4SML input!" CONFIRMED (strings, flow)
- End of input is signalled by `0x3002003`. CONFIRMED

### 2.3 The message object (shared between PP, G2P, VF)

Header, 16 B (`msg_create`): `{heap, owner, u8 nsect, sect**}`. Each section, 16 B
(`msg_alloc_section` `0x100120c0`): `{void* data, u16 used, u16 ?, u32 type, u16 capacity}`.
Byte sections are initialised to 0x20 (space), except type 0xc, which is zeroed. CONFIRMED

Element size by type (`msg_section_elem_size` `0x10011f90`). CONFIRMED:

| elem | types |
|---|---|
| 1 B | 1–0x10 (all, incl. 0xc), 0x14, 0x15, 0x16, 0x19, 0x1d, 0x1f, 0x21–0x24, 0x27, 0x2a |
| 0xffff (unknown type) | everything else |
| 2 B | 0x11, 0x17, 0x1a, 0x1b, 0x1e, 0x25, 0x26, 0x28 |
| 4 B | 0x1c, 0x20, 0x30 |
| 0x18 B | **0x12** (markers / events) |

Roles of the known types:
- 6: sentence text. CONFIRMED (read as `char*`)
- 8 → 6: carry-over text. CONFIRMED (retype)
- 0xe → 6: carry-over after Transcribe. CONFIRMED (retype)
- 0x12: markers. CONFIRMED
- 0x27: marker string pool. CONFIRMED (`0x8002` +0x14 offset)
- 0x17: mparser section, capacity 2000. CONFIRMED (`msg_add_section(...,0x17,2000)`)

The byte tiers are character-parallel annotation layers in L&H style (INFERRED). This is the
"EPT-ish" stream: PP fills text and markers, G2P adds the phonetic tiers, and the VF consumes
the whole thing (`pros_ToEpt`).

Marker record (type 0x12, 0x18 B):

| off | field | evidence |
|---|---|---|
| +0x00 | type (bit value) | CONFIRMED |
| +0x04 | source text position | xcoder remaps it; +`obj+0x5c` offset. CONFIRMED |
| +0x08 | source text length | xcoder remaps it. CONFIRMED |
| +0x0c | PCM sample position | `ttseg_markers_add_pcm_offset` adds `obj+0xab8`. CONFIRMED |
| +0x10 | ? | |
| +0x14 | value: u16 subtype + u16 arg, or a string-pool offset / bookmark id | CONFIRMED (uses) |

---

## 3. Parameters

All values go through `ttseg_SetParams` (`0x10005cd0`) as `{u32 id, u16 val | char* str}`.
They are stored as decimal **strings** in paramc: the instance store `+0xaf8` for runtime
params, the pending store `+0xafc` for params that force a component reload. A reload-class
id first moves the srvspi state to "busy". CONFIRMED

| id | name (paramc key) | range (SetParams) | default (ObjOpen / Reset) | store | consumer |
|---:|---|---|---|---|---|
| 2 | `frequency` | {8, 11, 16, 22} (kHz) | from .hdr | pending → reload | VF/synth (string in both). CONFIRMED |
| 3 | `language` | string | — | pending → reload | PP/G2P selection. CONFIRMED |
| 4 | **`pitch`** | 1..100 | "50" / 50 | instance | **no listener found** (§3.1) |
| 5 | `rate` | 1..100 | "50" / 50 | instance (+ sets +0x2bc = 0x457) | synth_* (`rate` string). CONFIRMED |
| 6 | `voice` | string | — | pending → reload | VF. CONFIRMED |
| 7 | `volume` | 0..100 | "80" / 80 | instance | synth_* (`volume`). CONFIRMED |
| 8 | `waitfactor` | 0..9 | — / 2 | instance | synth_* (listener, DLL_ANALYSIS §2.1). CONFIRMED |
| 9 | `markermode` | u16 bitmask | "65529" = 0xFFF9 | instance + u16 at obj+0x2ac → PP SetParam `{0x81, val}` | PP (`stdpp_*` has the string), synth. CONFIRMED |
| 10 | `readmode` | 1..4 | "2" / 1 | instance + PP SetParam `{0x87, val}` | PP. CONFIRMED |
| 0xb | `typeofdoc` | string | "Text" | pending → reload | PP domain. CONFIRMED |
| 0xc | `typeofmarkup` | string | "Standard" | pending → reload | mparser. CONFIRMED |
| 0xd | `inputtypeofchar` | enum 0..6 → `Standard`, `UTF-8`, `UTF16_PlatformEndian`, `UCS-4`, `ISO-8859-1`, `ISO-8859-2`, `ISO-8859-5` | — | instance | xcoder. CONFIRMED |
| 0xe | size-of-jumpback | −1 or ≥0 | — | obj+0x2e4 | SpeakFromPosition. CONFIRMED |
| 0xf | **`pitchrelchg`** | −100..+100 | — | instance | **no listener found** |
| 0x10 | `raterelchg` | −100..+100 | — | instance | synth_*. CONFIRMED |
| 0x11 | `ratewpm` | 1..1000 | — | instance | synth_*. CONFIRMED |
| 0x12 | `volumerelchg` | −100..+100 | — | instance | synth_*. CONFIRMED |
| 0x13 / 0x14 | load / unload custom G2P | string, max 32 | — | obj+0x394 list | G2P. CONFIRMED |
| 0x16 | `coder` | string | — | pending → reload | VF/synth. CONFIRMED |
| 0x17 | `reduction` | string | — | pending → reload | VF. CONFIRMED |
| 0x18 | `typeofoutput` | **only 1** (`0x10002c50`) | "1" | pending | ttseg. CONFIRMED |
| 0x19, 0x1a, 0x1b | (Get only) | → "" / 0 | | | CONFIRMED |
| 0x1c | `inputtypeofchar` (raw string) | string | | instance | xcoder. CONFIRMED |
| 0x1e / 0x1f | load / unload RETTT ruleset | ptr | | RETTT object | `ttt/re`. CONFIRMED |

Out-of-range values return `0x8120200f`. If nothing else succeeded, SetParams returns at the
first bad value. CONFIRMED

### 3.1 Where pitch is applied

- **ttseg applies nothing.** It range-checks, converts to a string and stores. The only
  forwarding it does itself is markermode and readmode to the PP, via PP `+0x24`. CONFIRMED
- **String census** (`exactstr.py`, NUL-delimited exact match over every component DLL):
  - `pitch` and `pitchrelchg` occur **only in `ttsengine.dll`**.
  - The three synths contain `rate`, `ratewpm`, `raterelchg`, `volume`, `volumerelchg`,
    `waitfactor`, `markermode`, `frequency`, `voice` and `coder`.
  - The voice fonts contain only `frequency`, `voice` and `coder`.

  CONFIRMED
- **Conclusion, INFERRED:**
  - No component subscribes to the pitch parameters. In the 2006 Solo build the API pitch
    and pitch-relative-change are accepted and stored, then ignored.
  - F0 is decided entirely inside the voice font (`pros_*`) from linguistic context.
  - Pitch control by markup (if the PP emits pitch records into the message) is a separate
    path and was not traced.
  - **Rate and volume are applied in the synth** (`synth_155mrf22` `FUN_10006bf0` rate object,
    DLL_ANALYSIS §2.2), not in the voice font.

---

## 4. Dictionaries

- **ttseg has no dictionary code.** It contains no `edct` / `dcteg` / MIME strings and never
  calls `brk_DataOpen`. CONFIRMED
- **Hook:** the PP callback block slot 3 is `ttseg_pp_dict_lookup_cb` (`0x10004f30`). It is
  installed only when the app passed a non-NULL `cb[1]` in ObjOpen.
  - It logs `"Dictionary Lookup : %s"` at level 5.
  - It calls `cb[1](appctx, a2, a3, a4)` and returns the app's result.
  - With no app callback it returns `0x81202000`, which means "not found".

  CONFIRMED
- **When:** PP calls it during `PP->Process` (slot 12, inside `ttseg_pp_next_sentence`), that
  is, at text-normalisation time, before G2P. INFERRED (it is in the PP callback block; the
  per-token granularity is INFERRED)
- **Who answers:** the API layers. `rssoloapi.dll` and `rs_sapi5_solo.dll` carry `dcteg` and
  `application/edct-bin-dictionary`; `swisolo.dll` carries `dcteg`, `netdcteg`,
  `application/edct-text-dictionary` and `application/x-swi-dictionary`. `dcteg.dll`
  registers three MIME types: `application/edct-bin-dictionary`,
  `application/edct-text-dictionary` and `application/cdct-bin-dictionary`, plus `edctspi`.
  `edct.dll` is the dictionary engine; its error texts live in `comrsrc.dll` ("Illegal text
  dictionary format", "userword version" mismatch, `edct_DctWriteStream`). CONFIRMED (strings);
  that the API callback queries dcteg/edct is INFERRED
- **Custom G2P** (ids 0x13/0x14, `cg2p/*`) is a separate mechanism: whole G2P rule
  components loaded next to the main G2P (`FUN_10001050`). CONFIRMED (strings, list storage)

---

## 5. `xcoder.dll`: character-set transcoder

### 5.1 What it is

It is **text-encoding conversion with position tracking**. It contains no audio code: no
tables, no filters, no sample-rate constants (`xcoder.dll` is 63 functions, 32 KB). It
imports only `brk_*`, `paramc_*`, `heap_*`, `safeh_*` and `tolower`. CONFIRMED

Strings @`0x10004040..`: `UTF-16`, `LE`, `UCS-`, `Standard`, `xlit/`, `xlit/*`,
`UCS_PlatformEndian`, `UTF16_PlatformEndian`. CONFIRMED

ttseg uses it in two places:
- **input text**: app charset → engine charset, via `ReadConvert`
- **marker text positions**: engine offsets → app offsets, via `MapMarkerPositions` in the
  PCM callback

### 5.2 Interface table @ `0x10003090`

| slot | +off | addr | name given | role |
|---:|---:|---|---|---|
| 2 | 0x08 | `0x10001200` | `xcoder_ClassOpen` | class handle magic 0x353. CONFIRMED |
| 3 | 0x0c | `0x10002070` | `xcoder_ClassClose` | `return 0`. CONFIRMED |
| 4 | 0x10 | `0x100012c0` | `xcoder_ObjOpen(rsrc,heap,inParamName,outParamName,&h)` | 0x1c8-B object (magic 0x354). Reads both encodings from paramc (missing input → sets "Standard"; missing output → sets a 1-char default) and adds **paramc listeners** on both names (`0x100015e0`, `0x10001650`), so a `SetParams(inputtypeofchar)` reaches xcoder automatically. CONFIRMED |
| 5 | 0x14 | `0x100016c0` | `xcoder_ObjClose` | removes listeners. CONFIRMED |
| 6 | 0x18 | `0x100017a0` | `xcoder_Reset` | frees the 0x400 input buffer and the position-map list. CONFIRMED |
| 7 | 0x1c | `0x10002af0` | `xcoder_SetInputEncoding(h,name)` | ≤ 0x7f chars; on change, drop xlit and mark dirty (0x8810200e). CONFIRMED |
| 8 | 0x20 | `0x10001880` | `xcoder_GetInputEncoding(h,buf,len)` | CONFIRMED |
| 9 | 0x24 | `0x10002bf0` | `xcoder_SetOutputEncoding(h,name)` | CONFIRMED |
| 10 | 0x28 | `0x10001db0` | `xcoder_SetEncodings(h,in,out)` | both, then route. CONFIRMED |
| 11 | 0x2c | `0x10001a50` | `xcoder_ReadConvert(h,readfn,ctx,&len,out)` | pull-model conversion; see 5.3. CONFIRMED |
| 12 | 0x30 | `0x10001e80` | `xcoder_MapMarkerPositions(h,&markers,&n)` | see 5.3. CONFIRMED |
| 13 | 0x34 | `0x10001cc0` | `xcoder_ConvertBuffer(h,in,inlen,out,outoff,&outlen,map)` | push-model conversion. CONFIRMED |

### 5.3 Algorithm

**Routing** (`xcoder_select_xlit_route` `0x10002160`). `cmp` = `FUN_10002d50` (case-insensitive
compare, INFERRED). The conversion is delegated to an `xlit` component (`xlit_1250`, `1251`,
`1252`, `2022`, `936`, `949`, `950` in `components\xlit\`), interface version 4. CONFIRMED

| in | out | route | xlit iface calls |
|---|---|---|---|
| in == out, or either is `Standard` | — | **identity**, flag +0x1a8 = 1 | none (ReadConvert just calls `readfn`) |
| `UTF16_PlatformEndian` | `UCS_PlatformEndian` | first `xlit/*` in the component table, mode 3 | `+0x1c` (UTF-16 → UCS-4) |
| `UTF16_PlatformEndian` | X | `xlit/X`, mode 4 | `+0x1c` then `+0x10` (UTF-16 → UCS-4 → X) |
| `UCS_P…` (5-char prefix) | X | `xlit/X`, mode 1 | `+0x10` (UCS-4 → X) |
| X | `UCS_PlatformEndian` | `xlit/X`, mode 2 | `+0x14` (X → UCS-4) |
| anything else | | error `0x88102007` | |

The xlit slot roles (`+0x10` from-UCS, `+0x14` to-UCS, `+0x1c` UTF-16 → UCS) are INFERRED
from the routing table.

**UTF-16 BOM** (`xcoder_detect_utf16_bom` `0x10001190`): when the input is named `UTF-16`,
`FF FE` gives order 2 (LE) and `FE FF` gives order 1 (BE). A change of BOM forces a re-route.
CONFIRMED

**ReadConvert:**
- `xcoder_fill_input_buffer` (`0x10001900`) compacts and refills a **0x400-byte** input
  buffer through `readfn(ctx, &n, buf)`. A read status of `…03` means EOF.
- `xcoder_convert_core` (`0x100027e0`) converts into the caller's buffer.
- If a map is requested, every output unit gets a u32 source offset (`FUN_100026b0`). That is
  stored in a linked list of 0x18-B chunk nodes `{u32* map, outlen, inlen, base_src_off,
  base_out_off, next}` at obj+0x1c0.
- End of input is `0x3002003`.

CONFIRMED

**MapMarkerPositions:**
- Applies to marker types 1, 2, 8, 0x10, 0x20, 0x40, 0x100 and 0x200.
- It rewrites `+4` (pos) and `+8` (len) from engine (converted) offsets to source offsets
  using the chunk maps (`FUN_10001e20`).
- On a type-1 record it frees chunk nodes that lie wholly before the record's position.
- On identity routing it does nothing.

CONFIRMED

**Not present:** resampling, sample-format conversion, companding. There is no audio
transcoder in the ttseg path at all. The ttseg "sample coder" slot (obj+0x390, called at
`+0x38` in `ttseg_vf_pcm_out_cb`) can never be filled, because `ttseg_set_output_type`
accepts only type 1 and nulls the slot. Output is the synth's native linear PCM at the voice
rate (22050 Hz for `155mrf22`). CONFIRMED (code); the 22050 figure is from the
`.hdr`/`codsb` header (`enu 22050`, DLL_ANALYSIS F4).

### 5.4 Constants

- handle magics: 0x353 (class), 0x354 (object, 0x1c8 B)
- input buffer 0x400
- name limit 0x80
- error module `0x881` (`0x8810200x`)
- the GetInterface error is `0x89d3e001`

CONFIRMED

---

## 6. Markup and events

**Audio and event callback.** `ttseg_vf_pcm_out_cb` (`0x10004c60`) is the VF's output
callback. It calls `cb[2](appctx, msg, &pcm, &nsamples, &markers, &nmarkers)` (CONFIRMED):

| msg | when |
|---|---|
| 1 | `pcm==NULL && markers==NULL`: buffer request ("Send TTSEG_OUT_BUFREQ message"). The app returns a buffer; ttseg keeps it at +0xad4 |
| 0x20 | first PCM of a sentence (flag +0xadc set by the seek filter at sentence start) |
| 0x40 | PCM continuation |
| 0x80 | last chunk (VF passes status 3) |
| 0xa0 | first and last together |
| 2 | `TTS_OUT_DONE` (`ttseg_send_out_done` `0x10001a00`, after the loop) |

The 0x20/0x40/0x80 values are CONFIRMED. Reading them as begin/continue/end is INFERRED.

Before the call:
1. `ttseg_markers_add_pcm_offset` makes each marker's `+0xc` absolute by adding obj+0xab8,
   for types 1, 2, 4, 8 and 0x200. obj+0xab8 then grows by `nsamples`.
2. `xcoder->MapMarkerPositions` maps `+4/+8` back to input-text offsets. Its failure is
   logged as "Get Correct Marker Position Error!".

Transcription mode uses `ttseg_transcribe_out_cb` (`0x10004f80`) with the same message codes
into `cb[3]`. It logs `"Phoneme : %s"`, and done = 2 via `ttseg_send_transcribe_done`.
CONFIRMED

**Marker types:** 1, 2, 4, 8, 0x10, 0x20, 0x40, 0x100, 0x200 and 0x8002. CONFIRMED values.

| value | INFERRED meaning | reasoning |
|---|---|---|
| 1 | sentence | the PP's first record is always type 1, and xcoder prunes its maps on it |
| 2 | word | |
| 4 | phoneme | not text-mapped by xcoder |
| 8 | bookmark | the `+0x14` id is matched by SpeakFromPosition |
| 0x10 | sub-type 0x20 on/off | brackets a region `FUN_100122d0` empties (skip / "audio" region?) |
| 0x200 | paragraph or phrase | counted by SpeakFromPosition mode 2 |
| 0x8002 | internal voice switch | removed before the VF sees it |

**Default `markermode`:** 65529 = 0xFFF9, so bits 0x2 and 0x4 (word, phoneme) are off by
default. INFERRED (from the bit layout)

**Markup:**
- `typeofmarkup` other than `Standard` loads an **mparser** component (`mparser/*`). It runs
  `mprs_Process` on the input. Its xcoder input is set to UTF-16.
- MIME `application/synthesis+ssml` and `text/xml` select markup through
  `paramc_ParamSetTmpOverride`.
- The mparser can change the PP mode mid-speak (status 3 or 1 at mparser+0x15c), which makes
  ttseg reopen the parts.
- Language and voice switches arrive as in-band records (§2.2).

CONFIRMED

**Speak-from-position / seek** (`ttseg_position_seek_cb` `0x10004700`, mode at obj+0xa7c):
- jump by sentence count (+0xa84)
- jump to the n-th 0x200 record (+0xa8c)
- jump to the type-8 record whose `+0x14` equals the target id (+0xa80)

Records before the target are dropped by `ttseg_apply_position_filter` before G2P runs.
CONFIRMED (code); unit names INFERRED

---

## 7. Open questions

- The exact argument lists of PP slot 12 (`+0x30`) and G2P slots 13/15 (`+0x34` / `+0x3c`)
  beyond `(handle, msg)`, and VF slots 11 (`+0x2c`), 14 (`+0x38`) and 15 (`+0x3c`). These need
  `stdpp_enu` / `g2p_enu` / `rs_vf_tom_full` decompiled from the callee side.
- Is pitch really dead? Check `rs_vf_tom_full` and `stdpp_enu` for runtime-built names or a
  `paramc_ParamGet` on a key that is not a literal. Also check whether the PP emits pitch
  records from in-text markup (`\pit=`-style) that `pros_*` honours.
- The signature of the dictionary-lookup callback (`a2..a4`) and how `rssoloapi` implements
  it against dcteg/edct.
- The meaning of the byte-tier section types 1–0x2a (which one is phonemes, stress, syllable
  and so on). Dump a live message after G2P with the `tso/logging` object enabled: G2P dumps
  sections at level 5.
- `FUN_1000d450` (the post-xcoder text hook; RETTT is assumed) and `FUN_10001050` (custom-G2P
  application).
- App callback `cb[4]` (obj+0x9a4): unused in the paths traced.
- `ttseg_GetInterface` accepts only versions 0 and 3; the redundant `ver==2` test suggests
  the condition was edited. Which version does `rssoloapi` request?

---

## 8. Functions created and renamed (unsaved Ghidra session)

**`/rs_ttsengine.dll`, created** (the interface slots and callbacks were undefined):
`0x10001ac0`, `0x10001f20`, `0x100050e0`, `0x10005b20`, `0x10005cd0`, `0x10007110`,
`0x10007530`, `0x1000a040`, `0x10009590`, `0x1000a3f0`, `0x1000a750`, `0x1000ae10`,
`0x1000b2c0`, `0x1000bce0`, `0x1000b6a0`, `0x10004700`, `0x1000c900`, `0x10004bb0`.

**`/rs_ttsengine.dll`, renamed:**

| addr | name |
|---|---|
| 0x10001ac0 | ttseg_ClassOpen |
| 0x10001e30 | ttseg_ClassClose |
| 0x10001f20 | ttseg_ObjOpen |
| 0x100050e0 | ttseg_ObjClose |
| 0x10005b20 | ttseg_GetParams |
| 0x10005270 | ttseg_get_param_one |
| 0x10005cd0 | ttseg_SetParams |
| 0x10007110 | ttseg_ResetParams |
| 0x10007530 | ttseg_Speak |
| 0x10007550 | ttseg_SpeakFromUri |
| 0x1000a040 | ttseg_Break |
| 0x10009590 | ttseg_Transcribe |
| 0x1000a180 | ttseg_GetProductList |
| 0x1000a3f0 | ttseg_GetLanguageList |
| 0x1000a750 | ttseg_GetVoiceList |
| 0x1000ae10 | ttseg_GetDocumentList |
| 0x1000b2c0 | ttseg_GetCustomG2PList |
| 0x1000b6a0 | ttseg_GetSpeechDBList |
| 0x1000bce0 | ttseg_SpeakFromPosition |
| 0x100012f0 | ttseg_stub_return_ok |
| 0x10002e60 | ttseg_open_parts |
| 0x10003270 | ttseg_load_changed_parts |
| 0x10003e40 | ttseg_unload_changed_parts |
| 0x100038c0 | ttseg_load_pp |
| 0x10003980 | ttseg_load_g2p |
| 0x10003a40 | ttseg_load_vf |
| 0x10003b00 | ttseg_load_mparser |
| 0x10002d00 | ttseg_open_service_component |
| 0x1000eeb0 | ttseg_set_param_defaults |
| 0x10007000 | ttseg_forward_marker_read_mode_to_pp |
| 0x100084a0 | ttseg_pp_next_sentence |
| 0x10008730 | ttseg_pp_process_fetch_sections |
| 0x10008840 | ttseg_scan_lang_voice_switch |
| 0x100089e0 | ttseg_switch_language_pp |
| 0x10008bf0 | ttseg_switch_voice |
| 0x10008d90 | ttseg_apply_position_filter |
| 0x10004c60 | ttseg_vf_pcm_out_cb |
| 0x10004f30 | ttseg_pp_dict_lookup_cb |
| 0x10004f80 | ttseg_transcribe_out_cb |
| 0x10004700 | ttseg_position_seek_cb |
| 0x1000c900 | ttseg_pp_get_input_text_cb |
| 0x1000cbc0 | ttseg_read_input_text |
| 0x100048c0 | ttseg_pp_unget_input_cb |
| 0x10004ed0 | ttseg_markers_add_pcm_offset |
| 0x10001a00 | ttseg_send_out_done |
| 0x10001a60 | ttseg_send_transcribe_done |
| 0x10002c50 | ttseg_set_output_type |
| 0x10003dc0 | ttseg_release_sample_coder |
| 0x10011b00 | msg_create |
| 0x10011c80 | msg_get_section |
| 0x10011d00 | msg_retype_section |
| 0x10011dc0 | msg_add_section |
| 0x100120c0 | msg_alloc_section |
| 0x10011e50 | msg_resize_section |
| 0x10011f20 | msg_find_section |
| 0x10011f90 | msg_section_elem_size |
| 0x100123d0 | msg_clear_all_sections |

**`/rs_xcoder.dll`, created:** `0x10001200`, `0x100012c0`, `0x10001880`, `0x10001a50`.

**`/rs_xcoder.dll`, renamed:**

| addr | name |
|---|---|
| 0x10001200 | xcoder_ClassOpen |
| 0x10002070 | xcoder_ClassClose |
| 0x100012c0 | xcoder_ObjOpen |
| 0x100016c0 | xcoder_ObjClose |
| 0x100017a0 | xcoder_Reset |
| 0x10002af0 | xcoder_SetInputEncoding |
| 0x10001880 | xcoder_GetInputEncoding |
| 0x10002bf0 | xcoder_SetOutputEncoding |
| 0x10001db0 | xcoder_SetEncodings |
| 0x10001a50 | xcoder_ReadConvert |
| 0x10001e80 | xcoder_MapMarkerPositions |
| 0x10001cc0 | xcoder_ConvertBuffer |
| 0x10002160 | xcoder_select_xlit_route |
| 0x100027e0 | xcoder_convert_core |
| 0x10001900 | xcoder_fill_input_buffer |
| 0x10001190 | xcoder_detect_utf16_bom |
