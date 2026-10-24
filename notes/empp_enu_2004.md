# ScanSoft RealSpeak Solo v4 (2004): `empp_enu.dll`, the E-Mail pre-processor

**Dated 2026-10-23.** Ghidra program `/ss_empp_enu.dll`
(`ScanSoft\speech\components\pp\empp_enu.dll`), base
0x10000000. Nothing was saved. The functions created and renamed (§11) exist only in the open
Ghidra session.

Tags: **CONFIRMED** = seen in code or data. **INFERRED** = reasoning from structure, names
or L&H conventions.

Scratch probes, all in `C:\tmp\`:
- `empp_pescan.py`: PE headers, Rich, version info, imports and exports for every pp/g2p DLL in both packs, plus an `empp` string census over both trees.
- `empp_strcmp.py`: shared strings between EMPP and stdpp, g2p, ttseg, Speechify `SWIEmail.dll` and `SWIttsFe-en-US.dll`.
- `empp_probe.py`: counts of feature words across the 2004 and 2006 pp and g2p DLLs.
- `empp_ppslot.py`: compares the PP interface tables of stdpp 2004, stdpp 2006, empp enu, jpj and kok.
- `empp_dump.py`: dumps strings, pointers or hex for a VA range.
- `empp_digram.py`: decodes the smiley lexicon.
- `empp_digram2.py`: decodes the domain gazetteer. Its full output is `C:\tmp\empp_abbr.txt`.
- `empp_swicheck.py`: checks Speechify `bin\` for EMPP content.

---

## Summary

- **EMPP = E-Mail Pre-Processor.** It is not morphology, not a POS tagger and not an
  "expert mode". It is a drop-in replacement for `stdpp_enu`:
  - It exports **`stdpp_GetInterface` and `empp_GetInterface` at the same address**
    `0x10001e70`.
  - It returns the same 14-slot PP table as stdpp.
  - It is registered by `rssolov4\enu\rssolo_empp_enu.hdr` as a PP whose
    `NAME = EMail`, `BROKERSTRING = pp/email/enu`, `DESCRIPTION = E-Mail Text Processing` and
    `PRIORITY = 90`. stdpp has `Text`, `pp/text/enu` and priority 100.

  ttseg chooses one of the two through the `typeofdoc` param. CONFIRMED (hdr, exports, table);
  the selection path is INFERRED.
- **Nothing imports it.** No binary in either pack references `empp`; only the three
  `rssolo_empp_*.hdr` files do. It imports only `comrsrc` (`heap_*`, `objc_*`, `paramc_ParamSet`,
  `InitRsrcFunction`) and MSVCRT. It has no `combrk` import. CONFIRMED
- **Message output is text only:**
  - layer **6** (text),
  - layer **0xC** (a byte layer parallel to the text),
  - **0x12** markers,
  - the **0x27** string pool.

  It writes **no POS (9), MORPH (10), GR (7) or PM (8)**. The normalised text it writes carries
  L&H in-band control bytes, and G2P interprets them. CONFIRMED. The 2006 stdpp writes only 6,
  0x12 and 0x27; layer 0xC is EMPP-only. CONFIRMED (2006 decompile), INFERRED for 2004 stdpp.
- **Internals:** a C++ pull pipeline of five filter stages:
  1. an input reader;
  2. **`DemuxEscFlexLexer`**, which splits out escape sequences;
  3. **`EmTagCtxFlexLexer`**, which tags the e-mail structure (headers, fields, forwarded and
     included messages, citations);
  4. **`LexEmppFlexLexer`** plus an address reader, which renders the speakable text;
  5. an output stage that writes the message.

  All three lexers are flex C++ (`%option yyclass`). The address reader runs a compiled
  rewrite-rule program, a Huffman-coded domain gazetteer and a digram-compressed smiley
  lexicon. CONFIRMED
- **Embedded data:**
  - ~118 RFC-822 / Usenet / Lotus Notes / X.400 header names, some of them in German, Spanish
    or Portuguese, each with a class;
  - ~40 time-zone expansions;
  - subject-prefix rules (`Re:` → "reply to", `FW:` → "(Forwarded)", `CFP`, `FAQ`);
  - URL and e-mail-address reading rules;
  - a **~2,780-entry domain → organisation gazetteer** (`yale.edu` → "Yale University",
    310 country and US-state TLDs);
  - **~140 smiley descriptions** (the Sanderson list);
  - **hand-tuned phonetic prompts with explicit durations and F0 targets** for "Message from",
    "Date", "Subject", "No subject given", the forwarded/included message brackets, and 17
    interjections ("ha-ha", "oops", "boo-hoo"...).

  CONFIRMED
- **2006 replaced it with nothing.** The 2006 pack ships only `pp/text/*` hdrs, and 2006
  stdpp/g2p contain none of the header, smiley, gazetteer or prompt data. The generic
  URL/e-mail-address reading table (`mail to`, `'tEl-nEt`, ` in area `, symbol names) already
  lived in **g2p_enu in both 2004 and 2006**, so inline addresses still read the same. The
  e-mail *document mode* was dropped. ttseg 2006 still carries the `EMail` doc-type plumbing
  (`EMail_win936` and `EMail_win950` @`0x10014048`/`0x10014064` in `/rs_ttsengine.dll`).
  CONFIRMED (strings); "nothing replaced it" is INFERRED from absence.
- **No ETI-Eloquence lineage:**
  - no Delta, ECI or `LFILE` strings;
  - no shared strings with `SWIttsFe-en-US.dll`;
  - no shared strings with Speechify's own e-mail pre-processor `SWIEmail.dll` (SpeechWorks,
    `dmeyer` 2003, `eLex.cpp` / `eTag.cpp`).

  It is L&H code, banner `EMPP (Eng USA) V4.02.00 Jan 14, 2000`, rebuilt by ScanSoft
  2004-07-22. CONFIRMED

---

## 1. Identity, loader, interface

### 1.1 Exports and imports

| export | ord | addr | notes |
|---|---|---|---|
| `empp_GetInterface` | 1 | `0x10001e70` | `ver < 2` → `*out = 0x100292d0`, else `0x81102001`. CONFIRMED |
| `stdpp_GetInterface` | 2 | `0x10001e70` | same body, an alias. CONFIRMED |

The same alias pair exists in `empp_jpj.dll` (`0x10001fa0`) and `empp_kok.dll` (`0x10001f90`).
CONFIRMED (pefile)

Imports:
- `comrsrc.dll`: `heap_Alloc`, `heap_Calloc`, `heap_Realloc`, `heap_Free`, `objc_GetObject`,
  `objc_ReleaseObject`, `paramc_ParamSet`, `InitRsrcFunction`;
- `KERNEL32`: `DisableThreadLibraryCalls` only;
- MSVCRT: string and ctype functions, `sscanf`, `sprintf`, `_ftol`, `_purecall`.

It has **no `brk_*`**, so it loads no other component. The jpj and kok EMPPs do import
`brk_InterfaceQuery`/`Release`. CONFIRMED

### 1.2 Who loads it

`ScanSoft\speech\rssolov4\enu\rssolo_empp_enu.hdr`:

```
COMPTYPE PP | NAME EMail | VERSION 4.0 | BROKERSTRING pp/email/enu | ENGINE eng/realspeaksolo
DESCRIPTION E-Mail Text Processing | PRIORITY 90 | COMPONENT components\pp\empp_enu.dll
GETINTERFACE empp_GetInterface
```

The sibling `rssolo_stdpp_enu.hdr` is `NAME Text`, `pp/text/enu`, `PRIORITY 100`. CONFIRMED

The selection mechanism:
- `ttsengine.dll` (both years) carries `typeofdoc`, `pp/*`, `NAME` and `EMail`.
- `rssoloapi.dll` (2004) maps `EMail`/`email` and `Text`/`text`, and has the string
  "Unknown pre-processor".
- ttseg's `ttseg_CheckTypeOfDoc` (2006 string @`0x10016698`) resolves `typeofdoc` to a PP by
  hdr `NAME`, and `ttseg_load_pp` (ttsengine_xcoder_2006.md §2.1) queries the broker string.

INFERRED. EMPP is called only by ttseg, through PP slot 12, exactly like stdpp. It is not
called by stdpp or g2p, neither of which imports or names it. CONFIRMED (absence)

### 1.3 PP interface table @ `0x100292d0` (identical shape to stdpp)

14 slots; slots 0–3, 7 and 8 are NULL. Compared with stdpp 2004 @`0x1000c270` and stdpp 2006
@`0x1000c090` by `empp_ppslot.py`: same populated slots. CONFIRMED

| slot | +off | addr | name given | role |
|---:|---:|---|---|---|
| 4 | 0x10 | `0x10001170` | `empp_ObjOpen(rsrc, heap, pp_cb, appctx, &h)` | 0x18-B handle; validates `pp_cb[0]==0`, `[1]`, `[2]` ≠ 0 (`0x10002100`); builds core (`0x10002280`); **`paramc_ParamSet("typeofchar","windows-1252")`**; logs "Entering/Exiting empp_ObjOpen". CONFIRMED |
| 5 | 0x14 | `0x10001360` | `empp_ObjClose` | CONFIRMED |
| 6 | 0x18 | `0x10001400` | `empp_GetParam(h,{id,u16,ptr})` | 0x81 markermode; 0x84 → "windows-1252"; 0x87 readmode (inverse map). CONFIRMED |
| 9 | 0x24 | `0x10001590` | `empp_SetParam` | §7. CONFIRMED |
| 10 | 0x28 | `0x100018a0` | `empp_ResetParam(h,id)` | 0x81 → `0xfffd` (`0x100292a0`), 0x87 → internal 2 = sentence (`0x1002929c`). CONFIRMED |
| 11 | 0x2c | `0x10001910` | `empp_ResetRc` | command "resetrc". CONFIRMED |
| 12 | 0x30 | `0x10001960` | `empp_GetMessage(h,msg)` = **Process** | §2. Logs "Entering/Exiting empp_GetMessage". CONFIRMED |
| 13 | 0x34 | `0x10001530` | `empp_Reset(h,all)` | "reset"/"resetall" (flush; ttseg calls `+0x34` on abort). CONFIRMED |

The ObjOpen argument order matches ttseg's `PP->ObjOpen(rsrc, heap, &pp_cb, obj, &pph)`.
CONFIRMED

Handle (0x18 B):
- `{core*, rsrc_ctx, cb_table=0x1005d188, cb_ctx[16] (0x40 B), 0x10, lon_name*}`.
- Each `cb_ctx[i]` is the same 12-B `{pp_cb*, appctx, rsrc_ctx}`.

CONFIRMED (`0x10002100`)

### 1.4 Resource callback table handed to the core @ `0x1005d188` (16 entries)

| idx | addr | name given | role |
|---:|---|---|---|
| 0 | `0x10001e90` | `empp_cb_read_input` | `pp_cb[1](appctx,&buf,len)` = ttseg `get_input_text`; `0x3002003` → −5 (EOF). CONFIRMED |
| 1–3 | `0x10001fd0` / `0x10002010` / `0x10001ff0` | `empp_cb_alloc` / `realloc` / `free` | heap. CONFIRMED |
| 4 | `0x10001f20` | `empp_cb_marker_alloc` | 0x1c-B marker node = 0x18-B msg record + `next`. CONFIRMED |
| 5 | `0x10001f50` | `empp_cb_marker_list_free` | frees the string arg for types 0x8001/2/3. CONFIRMED |
| 6 | `0x10002030` | `empp_cb_dict_lookup_dcteg` | `objc_GetObject(rsrc+0x18,"WORD_DCTEG")` → vtable `+0x34`. **The user dictionary is reached through the objc registry, not ttseg's `pp_cb[3]`.** CONFIRMED; stdpp 2004/2006 also contain `WORD_DCTEG`. |
| 14 | `0x10001f00` | `empp_cb_unget_input` | `pp_cb[2]` = ttseg `unget_input`. CONFIRMED |
| 7–13, 15 | 0 | | CONFIRMED |

`pp_cb[3]` (ttseg's dict-lookup callback) is referenced by none of these. INFERRED that EMPP
never uses it.

---

## 2. Message I/O (`empp_GetMessage` `0x10001960`)

```
types[6] = {6, 0xc, 0,0,0,0}            // @0x10001995 (count 6), @0x100019e7 (0xc)
cap = core_get_param(0x81)  (default 0x400, clamp 0x800)     // @0x100019e1..0x100019f7
for t in types (non-zero): msg_ensure(t, cap); msg_get(t) → {len, ptr}
msg_get(0x12) → used = 0
r = core_process(core, &bufs, &markers)          // 0x10002380 → 0x10002a00
   r == -5 → return 0x3002003 (end of input)   r == -9 → 0x8110200a
on success:
   sect[6].used   = len0
   sect[0xc].used = min(len0, len1)             // the 0xc layer is clamped to the text length
   empp_write_markers_to_msg(msg, markers, 1)   // 0x10001c50
   cb[5](markers)                               // free list
```

CONFIRMED

- **Layer 6:** normalised text with in-band control bytes (§6). CONFIRMED
- **Layer 0xC:** core output tier 1. `empp_core_pull_sentence` (`0x10002be0`, loop
  `0x10002e27..0x10002e9a`) copies tier 0 to buffer 0 and tiers 1..n-1 to buffers 1..n-1.
  CONFIRMED
  - The writers are inside the address reader. `empp_domain_gazetteer_lookup` (`0x10026750`)
    writes the key part (before `0xF6`) at `row0[pos]`, and the part after `0xF6` at
    `row0[pos+0x800]`. That second row of the 0x800-stride working buffer is tier 1.
    CONFIRMED (copy); that row 1 equals msg layer 0xC is INFERRED.
  - So 0xC carries **annotations aligned with the characters**, such as the organisation name
    for a matched domain. INFERRED
- **Markers (0x12):** each record is 0x18 B, copied verbatim from core nodes. For types
  **0x8001, 0x8002 and 0x8003**:
  - the string at `+0x14` is appended to the **0x27 pool**;
  - `+0x14` is replaced by the pool offset.

  This is byte-identical to the 2006 stdpp Process (`/rs_stdpp_enu.dll` `0x10001520`).
  CONFIRMED
- **Not written:** 7 GR, 8 PM, 9 POS, 0xA MORPH, 0x10 INTON. No other type id appears in
  GetMessage or the marker writer. CONFIRMED

---

## 3. Internal architecture

### 3.1 Core object (0x9c B, `empp_core_ctor` `0x100023f0`)

The stages are C++ objects on a common filter base (`FUN_1000e620`) with a 20-slot vtable:
- slot 0 = read (pull);
- `+0x0c` = init(upstream);
- `+0x18` / `+0x1c` = get/set param;
- `+0x24` / `+0x2c` = set/get buffer size;
- `+0x3c` = misc.

CONFIRMED (vtables below)

| core off | size | ctor | vtable | lexer inside | role |
|---|---|---|---|---|---|
| +0x64 | — | `FUN_1000eaf0` | `0x10039d28` | — | raw input reader over `cb[0]` / `cb[14]` |
| +0x80 | 0x4c | `empp_stage_input_ctor` `0x100045a0` | `0x10029460` | — | input stage, 0x4000 buffer |
| +0x84 | 0x94 | `empp_stage_demuxesc_ctor` `0x10003e70` | `0x10029414` | 0x1c4-B `DemuxEscFlexLexer`-derived (`0x10005700`, vt `0x10029580`, base vt `0x10039c9c`); **yylex `0x1000b440`** (9.2 KB) | demultiplex `\…\` escape sequences from text; `\spell=on\` / `\spell=off\`; numeric args (`strtoul`, "4294967295") |
| +0x88 | 0x94 | `empp_stage_emtagctx_ctor` `0x100038e0` | `0x100293c4` | 0x1ac-B `EmTagCtxFlexLexer`-derived (`0x10004830`, vt `0x100294e0`, base vt `0x100381ec`); **yylex `0x10006a40`** (15.9 KB) | e-mail structure tagger; emits ESC-prefixed tags (§4.1); header classifier `empp_classify_header_name` `0x1000b3b0` installed at lexer+0x130 |
| +0x8c | 0x4ac0 | `empp_stage_lexempp_ctor` `0x10013c20` | `0x10039f54` | at +0x8e0: core wrapper `FUN_10014870` holding a 0x344-B `LexEmppFlexLexer` (`0x10017cc0`, vt `0x10039fcc`); **yylex `0x1001a020`** (19.2 KB); at +0xd4: **address reader** (`empp_addr_reader_ctor` `0x10020be0`, 6 sub-parsers at +0x2ec..+0x764) | renders headers and body into speakable text: field prompts, forwarded/included brackets, smileys, addresses/URLs, user dictionary |
| +0x90 = +0x94 | 0xf0 | `empp_stage_output_ctor` `0x10011540` | `0x10039edc` | — | output: **read `0x10011610`** maps internal events to marker nodes and appends sentence-end controls (`0x10013000`, `0x10013320`) |

All of this is CONFIRMED from the constructors and vtables. The flex class names come from the
three stub `yylex` functions:
- `0x10006a30` → "EmTagCtxFlexLexer::yylex invoked but %option yyclass used" @`0x1005d244`;
- `0x1000b430` → `DemuxEscFlexLexer` @`0x1005dd30`;
- `0x1001a010` → `LexEmppFlexLexer` @`0x1005e28c`.

CONFIRMED

### 3.2 Flow

- `empp_core_link_stages` (`0x10002680`) inits the stages in the order
  input → DemuxEsc → EmTagCtx → LexEmpp → output. Each gets the previous stage as upstream
  (stack slots, `0x10002680`). INFERRED from stack-slot reuse; the order of the vtable `+0xc`
  calls is CONFIRMED.
- `empp_core_pull_sentence` (`0x10002be0`) calls output slot 0 in a loop:
  - −8 = need more;
  - −0xb = end of data;
  - `FUN_10011230(...)==2` = flush.

  The output stage pulls its upstream through `(*up->vt[0])(up_ctx,…)`, inside
  `empp_stage_output_read`. A pull model, CONFIRMED.
- The state machine at core+0 (`empp_core_process` `0x10002a00`): 2 = idle, 4 = running,
  6 = drain (returns −5), 10 = dead. This matches the stdpp 2006 Process state machine. CONFIRMED

### 3.3 Not present

- no HMM or statistical tagger;
- no morphology;
- no POS tag set;
- no lexicon of ordinary words (`hundred`, `January` are absent; g2p has them).

The only "lexicons" are the smiley list and the domain gazetteer (§4). CONFIRMED (string census,
`empp_probe.py`)

---

## 4. Embedded data

### 4.1 Internal tags: EmTagCtx → LexEmpp

They are ESC (0x1b)-prefixed and CONFIRMED (bytes and xrefs):

| tag | addr | emitted at |
|---|---|---|
| `\x1b[header]\n` / `\x1b[\header]\n` | `0x100294b0` / `0x100294bc` | `empp_emit_header_open` `0x10004f50` (5 refs), `empp_emit_header_close` `0x10005130` (11 refs) |
| `[cite id="…"]` … `[\cite]` | `0x100294c9`, `0x100294d8` | `FUN_10005536` (quoted `>` text; `"%s%s\"%s\n"` @`0x1005d230` in `FUN_100052a0`) |
| `[message]` / `[\message]` / `[\field]` | `0x10038175..0x10038191` | EmTagCtx yylex `0x10008e55` |
| `[message t=inc]` … `[\message t=inc]` | `0x1003819d` / `0x100381b1` | included message |
| `[message t=fwd]` … `[\message t=fwd]` | `0x100381c5` / `0x100381d9` | forwarded message |
| `\x1b[field id=f]`, `id=d`, `id=s`, `id=z` | `0x1005d2c4`, `0x1005d2a4`, `0x1005d294`, `0x1005d2b4` | jump table `0x1000a910`/`0x1000a924` @`0x10007704`, indexed by header class − 0x101 |

`Content-type:` (`0x1005d284`) is handled in EmTagCtx at `0x100090bd` (MIME part detection).
INFERRED

### 4.2 Header-name table @ `0x1005d2e0`

It is an array of `{char* name, u32 class}`, sorted, about 118 entries, NULL-terminated. It is
searched by `empp_classify_header_name` `0x1000b3b0`, a case-insensitive prefix match.
CONFIRMED

| class | → field | names (all) / samples |
|---|---|---|
| 0x101 | `f` From | `from:` `author:` `de:` `von:` |
| 0x102 | `d` Date | `date:` `data:` `enviado:` `gesendet:` |
| 0x103 | `s` Subject | `subject:` `subj:` `betreff:` `asunto:` `assunto:` |
| 0x104 | (none) | `to:` `para:` `sendto:` `original-to:` `apparently-to:` `*to:` |
| 0x105 | (none) | `cc:` `bcc:` `copyto:` `blindcopyto:` `original-cc:` `*cc:` `*bcc:` |
| 0x10c | `z` Sender | `sender:` |
| 0x10d | (none) | `newsgroups:` `xref:` |
| 0x109 | skipped | `received:` `message-id:` `mime-version:` `content-*:` `x400-*:` `nntp-posting-*:` `$updatedby:` `$revisions:` `$additionalheaders:` `$links:` `x-` `--:` `xdisclaimer:` `importancia:` `confidencialidad:` `prioridade:` … |

The class → field mapping comes from the jump table above. CONFIRMED. The reading is
INFERRED: only From, Sender, Date and Subject are spoken; To and Cc are dropped.

### 4.3 Spoken prompts with hand-set prosody

The string tables are `0x1005ddb4` (message brackets) and `0x1005ddd4` (field labels).
LexEmpp inserts them:
- `empp_insert_field_prompt` `0x10017150`: token 3/7 → From/Sender, 4 → Date, 5 → Subject,
  8 → empty subject;
- the code at `0x1001bf81` inserts the bracket prompts.

CONFIRMED

| addr | text pair | phonetic string (abridged) |
|---|---|---|
| `0x1005df08` | (Message from) | `#[50]"m[67(2,87)]E[52]-s[121(112,118)]I[41]d[85]Z[104] 'f[25]r[11]a[148]m[156(155,74)]#[10]` |
| `0x1005ded8` | (Date) | `#[50]"d[121(0,82)]J[220]t[119(119,123)]#[10]` |
| `0x1005de80` | (Subject) | `#[50]"s[140(0,108)]^[92(25,93)]b[52]-d[47]Z[36]E[96(21,95)]k[61]t[144(143,80)]#[10]` |
| `0x1005dde4` | (No subject given) | `#[50]n[70(0,103)]O[143(0,100)(119,112)] "s[144]^[63]…'g[32(8,103)]I[74(67,84)]-v[60]$[45(3,88)]n[158(153,75)]#[10]` |
| `0x1005e1c0` | "Forwarded message." `0x1005e1ac` | `\x10#[50]"f[109(0,80)]o[120]r[56]-w[42(26,112)]$[67]-d[47]I[63(54,111)]d[88] 'm[61]E[104]-s[92]I[89]d[118]Z[91(83,74)]#[10]` |
| `0x1005e114` | "End of forwarded message." | `\x10#[50]E[155(0,96)]n[119(57,117)]d[105] #[69]?[19]^[90]v[124] 'f[49]…` |
| `0x1005e040` | "Included message." | `\x10#[50]b[20(1,112)]i[67(54,97)]-"g[39]I[128]n[127(69,126)] #[96]?[24]I[70]n[54(0,96)]-'k[36]l[46]u[127]-d…` ("begin included message") |
| `0x1005df84` | "End of included messages." | `\x10#[50]?[18(0,94)]E[110]n[71(49,118)]d[73] #[35]?[12]^[31]v[61(15,91)(55,103)] I[62]n…` |

The format is CONFIRMED. The meanings are INFERRED:
- the symbols are L&H phonemes: `E` ɛ, `I` ɪ, `J` eɪ, `^` ʌ, `$` ə, `O`, `Z` dʒ, `?` glottal stop;
- `"` and `'` are stress marks, `-` is a syllable boundary, `#[n]` is an n-ms pause;
- `ph[dur(t,F0)(t,F0)…]` is a duration in ms plus F0 targets in Hz at ms offsets inside the phone.

The F0 values, 74–151, sit in a male range. INFERRED: the prompts were tuned on the US male
(Tom) voice.

Phonetic spans are wrapped `0x10 … 0x0f`. `empp_insert_field_prompt` writes `0x10`, the label,
`0x10` before the label's trailing `0x0f`, and wraps the field value in `0xAF … 0xAF`.
CONFIRMED (code); the semantics are INFERRED.

### 4.4 Smiley and interjection lexicon (digram-compressed)

- **Layout:** pair table `0x100483f6`. The strings run `0x100485f4..0x10048ef3` and are
  `0x05`-separated. A byte c expands recursively to `pair[2c], pair[2c+1]` until
  `pair[2c] == 0`; bytes ≥ 0xEE other than 0xF0 get +0x21. CONFIRMED (`empp_smiley_lookup`
  `0x10025620`)
- **Lookup:** keys are up to 8 chars, classified by `0x10048fd3`/`0x10048ef3`, indexed by
  length from `0x100490e0` (0x24 B per length). CONFIRMED
- **157 entries** (`empp_digram.py`):
  - 0–16 are prosody-scripted interjections: `h a - h a` (ha-ha) ×2, `i k` (eek),
    `u p s` (oops), `k I s i - k I s i`, `?O` (oh), hee-hee, ho-ho, `h J - h J` (hey-hey),
    boo-hoo ×2, hmm-hmm ×2, whoops, nya-nya, `j ^ k` (yuck), `w I N k` (wink);
  - 17–156 are descriptions: `Not_funny_smiley`, `User_is_drunk.`, `User_is_a_robot.`,
    `User_is_wearing_sunglasses.`, `User_is_the_Pope_or_holds_some_other_religious_office.`,
    `Mega-Smiley:_A_drunk,_devilish_chef_with_a_toupee_in_an_updraft,…`, `Hugs`, `Kisses`,
    `smiley_cyclops`…

  CONFIRMED
- The `smileydel` command toggles deleting smileys instead of reading them (`0x10015475`,
  lexer+0x340). CONFIRMED

### 4.5 Domain → organisation gazetteer (Huffman trie + digram text)

- **Lookup:** `empp_domain_gazetteer_lookup` `0x10026750` takes keys up to 0x1c chars. The trie
  is `empp_gazetteer_trie_find` `0x10026560`, with `empp_gazetteer_trie_step` `0x100262a0`:
  - a 27-letter first-letter index at `0x1005a040`, offsets at `0x1005a05c`, char map at
    `0x10056957`;
  - the bitstream at `0x10056f34` is decoded by `empp_huffman_decode_symbol` `0x10025e50`,
    which walks a tree at `0x10056a58`.

  CONFIRMED
- **Expansion text:** pair table `0x10049e76`, strings `0x1004a074..0x10056957`, front-coded:
  bytes 0x7B..0x8E = shared-prefix length, and `0xF6` = key|value separator. CONFIRMED
- **Content** (`C:\tmp\empp_abbr.txt`, 407 blocks, **~2,778 entries**):
  - 893 `.edu`, 96 `.gov`, 310 country or US-state TLDs (marked `0xAA`);
  - keys are in spoken form with `0x16` after each letter to be spelled.

  Samples:

  ```
  yale_dot_edu | yale_University          zircon_dot_com_dot_a\x16u\x16 | zircon
  w\x16y\x16_dot_u\x16s\x16 | Wyoming     z\x16w\x16 | Zimbabwe   (country)
  whitehouse_dot_gov | the_Whitehouse     afip_dot_mil | armed_Forces_Institute_of_Pathology
  ```

  CONFIRMED. The list is mid-1990s academic and ISP-heavy; it includes Australian `.com.au`
  ISPs and UK `.ac.uk`. INFERRED: an L&H Belgian/Australian-era compilation.

### 4.6 Compiled rewrite-rule program (address/URL/header text rules)

- **Interpreter:** `empp_rule_interpreter` `0x10024410`, 3.9 KB with 51 call sites, plus
  `FUN_10021ee0`, `FUN_10022ac0` and `FUN_10023dd0`.
- **Tables:** `0x1003e04a..0x10043d8d`, with literals around `0x10044000..0x1004a000`.
- **Handlers:** about 70 small action handlers in a table at `0x1003df38..0x1003e048`
  (functions `0x10020b20..0x10021640`).

CONFIRMED (xrefs). Right-context literals are stored reversed (`tod` = dot, `thgirypo` =
copyright, `sruoh` = hours, `notgnihsaW`). CONFIRMED

Representative literals, matched → output (CONFIRMED, `empp_dump.py str 0x100449f0 0x1004a200`):
- Subject prefixes: `Re:`/`RE:`/`re:` → `reply to`, `REQ:` → `request:`, `CFP` →
  `call for papers:`, `FAQ` → `frequently asked Q`, `FW:`/`Fw:`/`FWD:`/`(fwd)`/`<fwd>` →
  ` (Forwarded) `, `[Q]` → `question: `, `Q.`/`A.` → `Question:`/`Answer:`.
- Dates in headers: `Mon,` → `Monday,` … `Sun,`; ` Jan ` → `1/` … ` Dec ` → `12/` (re-rendered
  as numeric m/d for G2P); `hours`, `minutes`.
- Time zones (~40): `EST` → `Eastern ST`, `PDT` → `Pacific DT`, `GMT` → `Greenwich Mean T`,
  `CET` → `Common European T`, `JST`, `KST`, `HKT`, `IST`, `NST` → `Newfoundland ST`,
  `LMT` → `Local Mean T`, `Oz` → `Australia`; `ST`/`DT` → `Standard Time`/`Daylight Time`;
  `GMT+`/`GMT-` → `U.T.C. plus `/`U.T.C. minus `.
- Addresses and URLs:
  - `.` → ` dot `, `-` → ` dash `, `%` → ` in area `, `+` → ` plus `, `_` → ` underscore `,
    `!` → ` bang `, `~` → ` tilde `, `@` → ` at ` / ` from `;
  - `http`/`ftp`/`gopher`, `telnet` → phonetic `'tEl-nEt`, `url` → `u.r.l `, `mailto` → `mail to `,
    `//`, `:` → ` colon `;
  - `[SMTP:`, ` at Internet`, `.ini`/`.sys`/`.dos`, `Mc`/`Mac`;
  - consonant-cluster pronounceability rules (`|$|b|l|m|p|…`) that decide between spelling an
    address part and reading it.
- Symbol names: `$` ` dollar sign `, `&` ` ampersand `, `*` ` asterisk `, `<` ` smaller than `,
  `>` ` greater than `, `\` ` backslash `, `;` ` semi-colon `, `"` ` double quote `, `?`, `=`,
  `!`.
- Misc: `(c)` → `copyright`, `#` → ` number `, `b*tch`/`f*ck`/`F*CK` unmasked, `FTP'd` →
  `F-T-Peed`, `FTPin'` → `F-T-P-ing`, ` `` `/`''` → `"`, `D.C.` ↔ `Washington`, pauses
  `#[90]`/`#[150]`/`#[200]`.

### 4.7 Character handling

- Input is declared **Windows-1252**: `paramc typeofchar` in ObjOpen, GetParam 0x84
  (`0x1005d050`), and core param 0x83 → `Windows-1252` (`0x1002938c`). CONFIRMED
- `empp_map_highbyte_char` `0x10019fe0` maps bytes ≥ 0x80 through a table at `0x10039ff8`
  before dictionary queries. CONFIRMED
- `empp_dict_result_sanitize` `0x1001fe10`: `0x80` (€) → `"EUR"` (`PTR_1005e2cc` →
  `0x1005d04c`), `0xE1` → `ss`, `0xFF` → `0x80`, and control bytes outside 0x0f..0xaf → space.
  CONFIRMED. That 0xE1 = ß means an OEM-style internal code page is INFERRED.
- `empp_map_symbols_fallback` `0x1001fdd0` uses the class string `%~+-/\{}*_` @`0x1003de2b`.
  CONFIRMED

---

## 5. Text-normalisation coverage

| area | present? | where | tag |
|---|---|---|---|
| E-mail headers (classify, read From/Sender/Date/Subject, skip the rest) | yes | §4.2, §4.3 | CONFIRMED |
| Quoted text `>` (cite levels), forwarded and included message brackets | yes | §4.1, §4.3 | CONFIRMED (tags); levels INFERRED |
| Header dates and time zones | yes, rewritten to day names, m/d and zone names | §4.6 | CONFIRMED |
| Subject-line abbreviations | yes | §4.6 | CONFIRMED |
| E-mail addresses, URLs, domains | yes, rules + gazetteer + user dictionary | §4.5, §4.6, §6 | CONFIRMED |
| Smileys and emotive interjections | yes | §4.4 | CONFIRMED |
| Roman numerals | probably | `empp_roman_numeral_convert` `0x10028100` (`IVX`/`ivx` @`0x1005e4b0`, `atoi`, digit table) | INFERRED |
| Euro sign | yes, "EUR" | §4.7 | CONFIRMED |
| Cardinal/ordinal numbers, currency amounts, general dates, general abbreviations (Mr., Dr.) | **no**, left to G2P | no `hundred`, `thousand`, `January`, `Mr.` strings in EMPP; g2p_enu has them | CONFIRMED (absence) |

---

## 6. In-band control bytes in the layer-6 text

| bytes | producer | meaning | tag |
|---|---|---|---|
| `0x10 … 0x0f` | §4.3 prompts | phonetic-with-prosody span | INFERRED |
| `0xAF … 0xAF` | `empp_insert_field_prompt` `0x10017150` | header-field value span; markers removed after the address reader | CONFIRMED (bytes) |
| `0x18 … 0x19` | `empp_addr_dict_lookup` `0x10020aa0` | user-dictionary result | CONFIRMED |
| `0x1e na … 0x1f na` | `empp_addr_consult_email_userdict` `0x10020090` | dictionary hit for an e-mail address, inserted verbatim | CONFIRMED (bytes); "na" meaning unknown |
| `0x18 0x1e uc%lu 0x1f uc 0x19` | fmt @`0x1005e454` in `FUN_10020670` | numeric code span, "uc" = Unicode char? | INFERRED |
| `0x20 0x11 /`, `… /+`, `… /~` | `empp_output_append_end_controls` `0x10013000`, by output+0xdc ∈ {2,3,4} | sentence/terminator control, read mode dependent | CONFIRMED (bytes); meaning INFERRED |
| `0x11 [\addr]` | same, when output+0xe8 is set | end of address region | CONFIRMED (bytes) |
| `\x16` after a letter | gazetteer keys | spell this letter | INFERRED |

G2P consumes these. Both g2p_enu builds contain `\x1ena`, `#[90]`, `#[150]` and the same
symbol-name literals (`empp_probe.py`). CONFIRMED (strings)

User-dictionary logging: "Consulting Email user dictionary for address: %s" @`0x1005e380`;
"Consulted user dictionary for: %s; result(ANSI, incl. tagging): %s" @`0x1005e40c`.
CONFIRMED

---

## 7. Parameters and commands

`empp_SetParam` `0x10001590` takes `{u32 id, u16 val | char*}`. CONFIRMED

| id | effect | core param |
|---|---|---|
| 0x81 markermode | u16 | 0x80 (core+6, forwarded to output `+0x1c`) |
| 0x87 readmode | 1 → 2 sentence, 2 → 0 spell, 3 → 1 word, 4 → 3 terminator | 0x86 |
| 2 | stores a string at handle+0x14 | — |
| 3 / 4 | sends `"lon"` / `"loff"` with `%hu` or `*` (`0x1005d148`/`0x1005d14c`), plus the id-2 string when set | command |

The readmode names come from `empp_readmode_to_name` `0x10003770`: spell, word, sentence,
terminator. The 1..4 numbering matches RealSpeak `TTS_READMODE_{SENTENCE,CHAR,WORD,LINE}`.
INFERRED

Core param 0x81 is the per-section output capacity (default 0x400, max 0x800). 0xfa → 2 and
0xfb → 0x7f8 are read-only constants. CONFIRMED (`empp_core_get_param` `0x10003010`,
`empp_core_set_param` `0x10003220`)

Commands (`empp_core_command` `0x100033b0` → `empp_lexempp_command` `0x10014110` →
`empp_lexempp_toggle_option` `0x10015380`):

| argv | effect |
|---|---|
| `reset` / `resetall` / `resetrc` | flush / full reset / reset rc |
| `Ms <n>` | markermode |
| `set readmode <name>` / `get readmode` | readmode |
| `hdr` | toggle header reading (`+0x4ab0`, default 1) |
| `cache` | toggle |
| `markonly` | toggle (lexer+0x341) |
| `smileydel` | toggle |

CONFIRMED

`lon` and `loff` (argc 2 or 3) fall through every handler and return −3. SetParam ignores the
result, so ids 3 and 4 are **dead in enu**. CONFIRMED (path). INFERRED: they were shared with
the jpj and kok builds.

---

## 8. 2004 → 2006: what replaced EMPP

| | 2004 ScanSoft | 2006 RealSpeak |
|---|---|---|
| PP hdrs (enu) | `rssolo_stdpp_enu.hdr` (Text, 100), `rssolo_empp_enu.hdr` (EMail, 90) | `rssolo_stdpp_enu.hdr` only; no `pp/email/*` in any language |
| E-mail document mode | EMPP | **none** |
| URL / inline address reading | g2p_enu (and a duplicate in EMPP) | g2p_enu (same literals) |
| ttseg `typeofdoc` | `EMail` plumbing | still present: `EMail_win936`/`EMail_win950` @`0x10014048`/`0x10014064`, used in `FUN_10001300` @`0x100014db`; `ttseg_CheckTypeOfDoc` |
| PP output layers | stdpp: 6/0x12/0x27; EMPP: 6/**0xC**/0x12/0x27 | stdpp: 6/0x12/0x27 |

CONFIRMED (strings, hdrs, 2006 decompile). The verdict is INFERRED: 2006 dropped e-mail mode
and replaced it with nothing. `typeofdoc=EMail` would fail the PP lookup for enu, and the stdpp
2006 Process carries no e-mail logic. Header names, smileys, the gazetteer and the time-zone
strings are all absent from 2006 stdpp and g2p.

---

## 9. Build forensics

- **Versions:**
  - PE timestamp `0x41000423` = **2004-07-22 18:14:59 UTC**. stdpp_enu is 18:13:08 and g2p_enu
    18:17:26, the same build run.
  - VERSIONINFO: FileDescription `/tts_predev_prd/pp/em/enu - Release`, ProductName
    `CDF - EMPP Eng USA`, FileVersion 4.00, `ScanSoft, Inc.`, `Copyright © 2002-2004`.
  - `#TTSSO_VER\nScanSoft\nCDF empp_enu 2.0\nCopyright 2003` @`0x1005d010`.
  - Module/log name `EMPP_ENU` @`0x10029090`, version field `2.0` @`0x10029190`.
  - Banner @`0x10029308`: `EMPP (Eng USA) V4.02.00 Jan 14, 2000 (c) Copyright 1998 - 2000
    Lernout & Hauspie Speech Products (tm) N.V.`

  CONFIRMED
- **Siblings:**
  - `empp_jpj.dll` (2004-10-28) carries the banner **`EMPP (Eng USA) V1.00 May 5, 1997`**, a
    leftover English banner in the Japanese build.
  - `empp_kok.dll` (2005-01-27): `EMPP (Kor KOR) V3.00.00, 1 Mar 2000`, CompanyName
    `Lernout & Hauspie Speech Products`, OriginalFilename `kok_empp.dll`, "L&H EMPP DLL Kor KOR
    for TTS Predev target".

  CONFIRMED. EMPP therefore dates to at least 1997 at L&H. INFERRED
- **No debug directory or PDB** in any 2004 pp DLL. The 2006 stdpp has
  `F:\ttssrc.a\win32.x86\rel\tts_predev_prd\pp\std\enu\stdpp_enu.pdb`, the same
  `tts_predev_prd` tree as EMPP's FileDescription. CONFIRMED
- **Toolchain:**
  - linker 6.0;
  - Rich: `10.8797 x5`, `4.8797 x3`, `14.7299 x1`, `19.8034 x2`, `1.0 x34`, **`11.8966 x45`
    (C++)**, `10.8966 x8` (C), `6.1735 x1`, `4.8447 x3`;
  - stdpp_enu 2004 has `10.8966 x18` and no C++ objects.

  CONFIRMED. VC6 SP-era compiler, build 8966, with linker 8447. EMPP is mostly C++ (flex
  `yyclass` lexers, vtables) while stdpp is plain C with a C flex scanner (stdpp strings "fatal
  flex scanner internal error…"). INFERRED for the version identification.
- **Eloquence check:**
  - none of `delta`, `^left`, `LFILE`, `ECIoutput`, `Eloquen`, `salsa`, `Klatt`. One `ECI`
    3-byte hit at `0x10057449` sits inside the Huffman bitstream;
  - shared ≥8-char strings with `SWIttsFe-en-US.dll`: only CRT/kernel and relocation noise;
  - shared with `..\Speechify\bin\SWIEmail.dll`: CRT only.

  SWIEmail is SpeechWorks' independent e-mail pre-processor:
  `$Id: eLex.cpp/eTag.cpp/eProc.cpp/eAPI.cpp … 2003/07 dmeyer`, PDB
  `C:\Speechify_3.0.5\Build_5046\i386-win32\Speechify30\ttsEmail\src\build\i386-win32\release\SWIEmail.pdb`,
  `Email.dic`, `\!HEAD`/`\!BODY`/`\!ADDR`/`\!MIME` notify tokens. **No code or data shared with
  ETI or with Speechify.** CONFIRMED. The lexer/tagger split is parallel (`eLex`/`eTag` vs
  `LexEmpp`/`EmTagCtx`), but no strings are shared. INFERRED: independent designs.

---

## 10. Open

- The full flex rule sets. The DFA tables for the three yylex functions are
  `0x1003a178..0x1003cb88` (LexEmpp), `0x1003841c..0x10039668` (DemuxEsc) and
  `0x10029b64..0x10032354` (EmTagCtx). Decoding yy_accept / yy_ec / yy_nxt would recover the
  regexes. The action switch of `empp_lexempp_yylex` (19 KB) was not decompiled.
- Exact semantics of layer 0xC as G2P reads it. Check `g2p_enu` 2004 for a `msg_get(0xc)`.
- The smiley **keys** (the encoded key tables at `0x10048fd3`/`0x100490e0`) were not decoded;
  only the values were.
- The `0x1e na`/`0x1f na` and `uc` span semantics inside G2P.
- The rule interpreter `0x10024410` bytecode format (ops 0xF2, 0xF4, 0xF6, 0xFC, 0xFD, 0xFF).
- Whether `0x10028100` is Roman numerals or something else (only the strings were checked).
- Internal event ids in `empp_stage_output_read` (2, 5, 6, 0xb–0xd, 0x13–0x16, 0x19–0x1d, 0x1f,
  0x21–0x24) and their mapping to the 0x12 marker types 1/2/4/8/0x10/0x200.
- The jpj (brk-importing) and kok EMPPs: what they `brk_InterfaceQuery` (`pp/text` strings are
  present, so they probably chain to stdpp).

---

## 11. Functions created and renamed (unsaved Ghidra session, `/ss_empp_enu.dll`)

**Created by hand:** `0x10001530`, `0x10001590`, `0x100018a0`, `0x10001910`, `0x10001960`,
`0x10001e90`, `0x10001f00`, `0x10001f20`, `0x10001fd0`, `0x10001ff0`, `0x10002010`,
`0x10002030`, `0x1000b3b0`.

**Created by script:** a vtable scan created 141 functions. It disassembled every
`.rdata`/`.data` pointer into `.text` that has a neighbouring code pointer and no function yet.
This covers all stage, lexer and address-reader vtable slots, including the three yylex bodies.

**Renamed (75):**

| addr | name |
|---|---|
| 0x10001170 | empp_ObjOpen |
| 0x10001360 | empp_ObjClose |
| 0x10001400 | empp_GetParam |
| 0x10001590 | empp_SetParam |
| 0x100018a0 | empp_ResetParam |
| 0x10001910 | empp_ResetRc |
| 0x10001960 | empp_GetMessage |
| 0x10001530 | empp_Reset |
| 0x10001c50 | empp_write_markers_to_msg |
| 0x10001e90 | empp_cb_read_input |
| 0x10001fd0 | empp_cb_alloc |
| 0x10002010 | empp_cb_realloc |
| 0x10001ff0 | empp_cb_free |
| 0x10001f20 | empp_cb_marker_alloc |
| 0x10001f50 | empp_cb_marker_list_free |
| 0x10001f80 | empp_cb_marker_free |
| 0x10002030 | empp_cb_dict_lookup_dcteg |
| 0x10001f00 | empp_cb_unget_input |
| 0x10002100 | empp_build_rsrc_callbacks |
| 0x100021e0 | empp_free_rsrc_callbacks |
| 0x10002210 | empp_core_get_param_w |
| 0x10002250 | empp_core_set_param_w |
| 0x10002280 | empp_core_create |
| 0x10002350 | empp_core_destroy |
| 0x10002380 | empp_core_process_w |
| 0x100023b0 | empp_core_command_w |
| 0x100023f0 | empp_core_ctor |
| 0x10002680 | empp_core_link_stages |
| 0x10002a00 | empp_core_process |
| 0x10002be0 | empp_core_pull_sentence |
| 0x10002b70 | empp_core_flush_stages |
| 0x10003010 | empp_core_get_param |
| 0x10003220 | empp_core_set_param |
| 0x100033b0 | empp_core_command |
| 0x10003770 | empp_readmode_to_name |
| 0x100037b0 | empp_readmode_from_name |
| 0x100045a0 | empp_stage_input_ctor |
| 0x10003e70 | empp_stage_demuxesc_ctor |
| 0x100038e0 | empp_stage_emtagctx_ctor |
| 0x10013c20 | empp_stage_lexempp_ctor |
| 0x10011540 | empp_stage_output_ctor |
| 0x10011610 | empp_stage_output_read |
| 0x10013000 | empp_output_append_end_controls |
| 0x10013320 | empp_output_emit_sentence_marker |
| 0x10005700 | empp_demuxesc_lexer_ctor |
| 0x10004830 | empp_emtagctx_lexer_ctor |
| 0x10017cc0 | empp_lexempp_lexer_ctor |
| 0x1000b440 | empp_demuxesc_yylex |
| 0x10006a40 | empp_emtagctx_yylex |
| 0x1001a020 | empp_lexempp_yylex |
| 0x1000b430 | empp_demuxesc_yylex_stub |
| 0x10006a30 | empp_emtagctx_yylex_stub |
| 0x1001a010 | empp_lexempp_yylex_stub |
| 0x1000b3b0 | empp_classify_header_name |
| 0x10004f50 | empp_emit_header_open |
| 0x10005130 | empp_emit_header_close |
| 0x10017150 | empp_insert_field_prompt |
| 0x10014110 | empp_lexempp_command |
| 0x10015380 | empp_lexempp_toggle_option |
| 0x10020be0 | empp_addr_reader_ctor |
| 0x10020090 | empp_addr_consult_email_userdict |
| 0x10020380 | empp_addr_consult_userdict |
| 0x10020aa0 | empp_addr_dict_lookup |
| 0x1001fe10 | empp_dict_result_sanitize |
| 0x10019fe0 | empp_map_highbyte_char |
| 0x10019fb0 | empp_map_highbyte_buf |
| 0x1001fdd0 | empp_map_symbols_fallback |
| 0x10024410 | empp_rule_interpreter (INFERRED) |
| 0x10025620 | empp_smiley_lookup |
| 0x10026750 | empp_domain_gazetteer_lookup |
| 0x10026560 | empp_gazetteer_trie_find |
| 0x100262a0 | empp_gazetteer_trie_step |
| 0x10025e50 | empp_huffman_decode_symbol |
| 0x10028100 | empp_roman_numeral_convert (INFERRED) |
| 0x10027a30 | empp_log |

`empp_GetInterface` `0x10001e70` already had its name.
