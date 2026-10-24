# RealSpeak Solo v4 (2006): `stdpp_enu.dll` (English standard text preprocessor)

**Dated 2026-10-23.** Ghidra program `/rs_stdpp_enu.dll`
(`RealSpeak\speech\components\pp\stdpp_enu.dll`), base 0x10000000.
Nothing was saved. The functions created and renamed (last section) exist only in the open Ghidra session.

Tags: **CONFIRMED** = seen in code or data. **INFERRED** = reasoning from structure, names
or L&H conventions.

Helper scripts in the scratchpad
`%TEMP%\claude\<session>\scratchpad\`:
- `flexdfa.py`: an offline emulator of the compiled flex DFA, reading the tables straight from the
  DLL with pefile. Modes: `info` (character classes), `examples` (shortest accepted string per rule
  and start condition), `tok`. Every "rule N matches X" claim below comes from this emulator.
  `flextest*.py` hold the probe strings.
- `pptables.py`: decodes the abbreviation list, the spell-out table and the character map.
- `unjson.py`: unpacks oversize decompiler output. `yylex.c` is the full decompile of `pp_yylex`.

---

## Summary

- **The PP is a flex scanner plus a message packer. It does not normalize text.** All of its
  behaviour is code and tables compiled into the DLL: a 1598-state flex DFA, an abbreviation
  table, a CP1252→CP437 character map and a spell-out table. It never calls `brk_DataOpen`, and
  it imports only `comrsrc` (`paramc_*`, `heap_*`, `objc_*`, `safeh_*`, `InitRsrcFunction`) and
  msvcrt. CONFIRMED (imports)
- **It does not expand numbers, dates, times, currency or abbreviations.** None of that code is
  here. What it does:
  - splits sentences (abbreviation-aware), and chunks them by readmode and by size
  - parses `ESC` escape tags into marker records and in-band control codes
  - tags URLs and e-mail addresses as regions
  - spells characters in `tn=spell` mode, using phonetic strings
  - maps CP1252 to CP437
  - runs the user-dictionary (`WORD_DCTEG`) substitution

  CONFIRMED. That number and abbreviation expansion live in `g2p_enu` is INFERRED.
- **What it writes:**
  - section **6**: text, with in-band L&H control bytes 0x11 / 0x12 / 0x1e / 0x1f
  - section **0x12**: 0x18-byte M_MRKREC records
  - section **0x27**: the string pool for marker types 0x8001..0x8003

  It writes **no POS, MORPH, GR or PM**. POS hints travel only in-band, as `\x11@<c>`.
  CONFIRMED (`pp_Process` `0x10001520`)
- **`SetParam` is a no-op.** Slot `+0x24` (`0x100014c0`) accepts ids 0x81 (markermode) and 0x87
  (readmode) and discards the value. The PP reads paramc directly instead: `markermode`
  (only bit 0x2 matters), `newreadmode` and `tnmode`. CONFIRMED
- **In-band pitch exists.** `ESC\pitch=N\` becomes a type-0x10 record with subtype 0x80 and arg N
  (1..100). Whether the VF honours it is not checked. CONFIRMED (PP side)

---

## 1. Export and interface

### 1.1 Export

`stdpp_GetInterface` (ord 1) is at `0x100022a0`. `ver < 2` → `*out = 0x1000c090`, else
`0x81102001`. CONFIRMED

Error module 0x811 (`0x8110200x`). The message helpers inside the PP use `0x81a020xx`.
CONFIRMED

### 1.2 Interface table @ `0x1000c090`

| slot | +off | addr | name given | signature / role | tag |
|---:|---:|---|---|---|---|
| 0–3 | 0x00–0x0c | 0 | — | no ClassOpen or ClassClose | CONFIRMED |
| 4 | 0x10 | `0x10001170` | `pp_ObjOpen` | `(rsrc, heap, cb*, appctx, &h)`; see §2 | CONFIRMED |
| 5 | 0x14 | `0x10001400` | `pp_ObjClose` | `(h)`; state 4 or 6 → reset; frees the lexer, buffers and h | CONFIRMED |
| 6 | 0x18 | `0x10001480` | `pp_GetParam` | `(h, {u32 id, u16 len, char* val})`. Only id **0x84** → `"windows-1252"`, else `0x81102001` | CONFIRMED |
| 7, 8 | 0x1c, 0x20 | 0 | — | | CONFIRMED |
| 9 | 0x24 | `0x100014c0` | `pp_SetParam` | `(h, {id,…})`: returns 0 for 0x81 / 0x87, else `0x81102001`. **The value is ignored.** | CONFIRMED |
| 10 | 0x28 | `0x100014e0` | `pp_ResetParam` | `(h, u32 id)`: the same 0x81 / 0x87 check, no effect | CONFIRMED (role name INFERRED) |
| 11 | 0x2c | `0x10001500` | `pp_ResetReadMode` | `(h)`: sets paramc `newreadmode="1"` (`pp_reset_newreadmode` `0x1000b3b0`) | CONFIRMED |
| 12 | 0x30 | `0x10001520` | `pp_Process` | `(h, msg)`; see §3 | CONFIRMED |
| 13 | 0x34 | `0x10002250` | `pp_Stop` | `(h, flag)`: state 4/6 → `pp_reset_state`, state = 2. With flag≠0 it also resets newreadmode. States 0 and 10 → `0x81102000` | CONFIRMED |

---

## 2. Objects

### 2.1 PP handle (0x40 B, `pp_ObjOpen` `0x10001170`)

```
    pp_ObjOpen(rsrc, heap, cb, appctx, &h):
        InitRsrcFunction(rsrc, heap, &rc)
        paramc default "newreadmode"="1" (if absent), "tnmode"="normal" (if absent)
        require cb && cb[0] <= 1 && cb[1] != NULL          // else 0x81102007
        paramc_ParamSet("typeofchar", "windows-1252")      // tells ttseg's xcoder what to emit
        h = heap_Alloc(0x40): state=2, cb copy at +0x20..+0x2c, appctx at +0x30
        h+0x14 = pp_lex_create (0x10008a60)                // 0x1b0-B lexer + 0x2050-B flex buffer
        h+0x18 = pp_paramobj_create (0x100022c0)           // {u32 region=0x10, rc}
        pp_reset_state(h)
```

| off | content | tag |
|---|---|---|
| +0x00 | state: 2 idle, 4 in utterance, 6 draining the last sentence | CONFIRMED |
| +0x04 / +0x08 | `char*` lexer output not yet sent (one lexer "sentence") / u16 read offset into it | CONFIRMED |
| +0x0c / +0x10 | internal node list `{head, tail}` belonging to +0x04 | CONFIRMED |
| +0x14 | lexer context (§5) | CONFIRMED |
| +0x18 | param helper `{u32 current region code (0x10 = none), rc}` | CONFIRMED |
| +0x1c | rsrc ctx (`+4` heap, `+0x14` paramc, `+0x18` objc registry) | CONFIRMED |
| +0x20..+0x2c | copy of ttseg's `pp_cb = {u32 mode, get_input_text, unget_input, dict_lookup}` | CONFIRMED |
| +0x30 | appctx (the ttseg obj) | CONFIRMED |
| +0x34..+0x3e | u16 running position deltas: +0x34 pad, +0x36 spell growth, +0x38 charmap, +0x3a in-band codes, +0x3c domain, +0x3e user dictionary | CONFIRMED (roles from use) |

`pp_cb[3]` (`dict_lookup`, ttseg's `ttseg_pp_dict_lookup_cb`) is **never read** in any function
decompiled here. The user dictionary goes through the objc `WORD_DCTEG` object instead (§8.4).
CONFIRMED for the functions read; that it is unused overall is INFERRED.

### 2.2 Internal node (0x1c B, `pp_node_new` `0x1000af40`)

`{u32 kind, u32 src_pos, u32 src_len, u32 dst_pos, u32 dst_len, u32 value|char*, node* next}`.
Kinds 2, 0xa, 0x10, 0x1c, 0x1e and 0x28 own a heap string at +0x14. Kind 1 holds a nested list
(input markers passed through, §5.3). CONFIRMED

---

## 3. `pp_Process` (`0x10001520`) end to end

```
    pp_Process(h, msg):
        state 6 → pp_reset_state, state=2, return 0x81102800
        state 2 → pp_reset_state, state=4
        msg_add_section(msg, 6, cap=1280)         // DAT_10034098=0x500; reuse if present
        markers = mrklist_init(mask=0xfff9, heap)  // 0x1000ad20
        r = pp_process_sentence(h, msg, &markers, types={6}, 1)   // 0x10001920
            0 ok | 2 → return 0x3002005 | 3 → state=6 | -4 → 0x8110200a
            -3 → pp_reset_state, state=2, return 0x3002003        // end of input
        if markers.head.value.byte0 == 2: pp_reset_state, state=2 // PP/language switch
        count records; sum strlen of 0x8001/0x8002/0x8003 strings
        msg_remove_section(0x12); msg_add_section(0x12, n)          // 0x18-B elems
        if strings: msg_remove_section(0x27); msg_add_section(0x27, total)
        copy each node's 6 dwords → 0x12[i]; string types: copy into 0x27, +0x14 := pool offset
        0x12.used = n; 0x27.used = total (or 0)
        return 0
```

CONFIRMED. The message helpers are the same library as ttseg's `msg_*`, statically linked
(`0x1000a570`..`0x1000a9e0`). `pp_msg_section_elem_size` (`0x1000a8b0`) reproduces ttseg's
element-size table, 0x12 → 0x18. CONFIRMED

### 3.1 `pp_process_sentence` (`0x10001920`): order of operations

```
    if h+4 is empty and h+0xc has no nodes:
        lexer_out = pp_yylex(lex, {strbuf, &h->nodes})      // 0x100046e0; one "sentence"
            -2 → OOM;  -1 → return 2 (input would block: 0x3002005 from app)
            empty strbuf → return -3 (EOF)
        shift node dst_pos by +0x34; pad strbuf with ' ' if nodes overrun
        h+4 = copy of strbuf
        pp_expand_spell_regions(h, &h+0x36)                 // 0x10001db0, §8.3
    pp_chunk_by_readmode(param, &len, &nodes_out, text+off, &h->nodes)   // 0x10002300, §3.3
    copy text[off..off+len] → section 6; used = len; off += len
    if header node value == 3 (EOF) and buffer consumed: append kind 0x21 (→ 0x80 "wait 0")
    DOMAIN_MNGR (objc) iface+0x44(…, &nodes_out, msg, h+0x3c)            // optional
    pp_user_dict_lookup(rc, msg, nodes_out, h+0x3e)                     // 0x10009170, §8.4
    pp_apply_charmap(msg, nodes_out, h+0x38, types, 1)                  // 0x10004370, §8.1
    pp_insert_inband_codes(msg, nodes_out, h+0x3a, types, 1)            // 0x10003dd0, §7
    mrklist_set_mask(out, pp_get_marker_mask(param))                    // §9
    pp_nodes_to_markers(nodes_out, out)                                 // 0x10003820, §4
```

CONFIRMED. The order means the user dictionary sees CP1252 text, and the charmap then runs over
the dictionary's output too. CONFIRMED (call order); the consequence is INFERRED.

### 3.2 Sentence boundaries (lexer, INITIAL start condition)

The rule numbers are flex `yy_act` values in `pp_yylex`. The patterns come from the DFA
emulator. CONFIRMED

| rule | matches | action |
|---|---|---|
| 0x79 | a word (any non-space run) | append; at a word start, add kind 3 (→ word marker) |
| 0x06 | a word ending in `[.?!:;]` followed by whitespace (`abc.`, `U.S.A.`, `3.`, `"quoted.`) | sentence-end **candidate** (below) |
| 0x07 | lone `.` `?` `!` + whitespace | candidate: move to SC 4 |
| 0x77 / 0x04 | e-mail `x@y.z` (0x04 = followed by final punctuation) | region 0x11 ("ad"), §7 |
| 0x78 / 0x05 | URL `www.…`, `http://…`, `ftp://…` (0x05 = + final punctuation) | region 0x12 ("ur"), §7 |
| 0x7b | space, tab, 0xa0 | append `' '`, set word-start |
| 0x7c | a single `\n` or `\r\n` | append `' '` (in `tn=address`: kind 5 → in-band `\x11\n`) |
| 0x7a | blank line (`\n[ \t]*\n`) | **flush the utterance** (no 0x200 record) |
| 0x80 | control characters | dropped |

What rule 0x06 does with a candidate (CONFIRMED, `pp_yylex` case 6):
- Last char `!`, `?` or `;` → end. +0x28 = (char==`;`).
- Last char `.` or `:` → look up the word core with `pp_is_abbreviation` (`0x1000a300`, §8.2).
  - Hit → **no break**.
  - Miss, but the word has the `X.Y.` initial pattern → look up `Y.`. Hit → no break.
  - Otherwise → end. +0x28 = (char==`:`).

After a sentence end the lexer looks ahead in **SC 4** (directly after the punctuation) and
**SC 5** (after whitespace):

| next | . ? ! | : ; |
|---|---|---|
| uppercase / CP1252 upper / `"` `'` `“` `‘` (rule 0x68) | **break** | no break |
| digit (0x69) | no break | **break** |
| lowercase / other (0x6a) | no break | no break |
| blank line (0x5a / 0x62) | break | break |

In SC 4 a closing `"` or `'` directly after the punctuation is absorbed into the sentence
(0x5d). The utterance is also force-flushed past 2000 bytes (`2000 < strbuf_len`, @`0x10007858`
and @`0x1000561c`). CONFIRMED

### 3.3 Chunking (`pp_chunk_by_readmode` `0x10002300`)

The input is one lexer sentence. The output is the piece placed in this message. `newreadmode`
is read from paramc:

| newreadmode | meaning | chunk | tag |
|---:|---|---|---|
| 1 | sentence | the whole lexer sentence | CONFIRMED |
| 2 | character | one character, after skipping whitespace. In spell mode, one token | CONFIRMED (meaning INFERRED) |
| 3 | word | up to the next whitespace, or the next kind-3 word node in spell mode | CONFIRMED (meaning INFERRED) |
| 4 | line | the whole lexer sentence. The lexer switches to SC 2 / SC 3, where `\n` ends the utterance (rules 0x7e / 0x6c) | CONFIRMED |

Then a size cap applies, in cost units against the 1280-byte text section:
- Each letter costs 2. Each digit or `()[]<>$%~+-/\{}_` costs 25 (0x19). Inside a URL or e-mail
  region a character costs 8 or 9.
- Soft limit 0x340 (832): split after `,` or `:` followed by whitespace.
- Limit 0x380 (896): split at whitespace.
- Hard limit 0x3c0 (960): split at whitespace or a `[`/`]` bracket, else force-split.

All three limits are the u16s at `0x1003409c` / `0x1003409e` / `0x100340a0`. CONFIRMED

Special nodes (kinds 2, 0xe, 0x11, 0x24, 0x25: PP switch, ART, RST, beep, tone) are cut into
their **own message** with empty text (`pp_find_special_head_node` `0x10003600`). Kind 0x19
(readmode) and kind 0x1c (tn) update paramc as the chunk passes over them. CONFIRMED

---

## 4. Records written to section 0x12 (`pp_nodes_to_markers` `0x10003820`)

Record layout (0x18 B, the same as ttseg §2.3):

| off | field written by PP | tag |
|---|---|---|
| +0x00 | type | CONFIRMED |
| +0x04 / +0x08 | source position / length (offsets in the xcoder-converted input) | CONFIRMED |
| +0x0c / +0x10 | position / length in the section-6 text. INFERRED: the VF later replaces +0xc with a sample offset before ttseg adds obj+0xab8 | CONFIRMED (PP side) |
| +0x14 | value (below); string types: offset into section 0x27 | CONFIRMED |

The list is gated by the mask set from `markermode`: `pp_mrklist_append` (`0x1000ad50`) drops
a record when `(type & mask) == 0`. The type-1 header (`0x1000aed0`) bypasses the mask and is
always prepended. CONFIRMED

| out type | from node kind ← source | +0x14 value | tag |
|---|---|---|---|
| **1** header | kind 4 (every utterance) | bytes `{01, 01, 0, 0}` | CONFIRMED |
| 1 | kind 2 ← `ESC\pp=<lang>\`, `ESC%<lang>` | byte0 = **2**. The language name is written as the section-6 text (`pp_insert_inband_codes` @`0x10003e96`). The rest of the input is handed back through `pp_cb.unget_input` (`pp_unget_rest_of_input` `0x10008420`) | CONFIRMED |
| 1 | kind 0x24 ← `ESC\beep=n\`, `ESC B<n>` | `{0x10, '0'+n}` | CONFIRMED |
| 1 | kind 0x25 ← `ESC\tone=x\`, `ESC T<x>` | `{0x20, '0'..'9' / 'a'..'f'}` | CONFIRMED |
| 1 | kind 0xe ← `ESC\art=[fp]\`, `ESC A[FP]` | `{0x40, …}` (the letter is dropped) | CONFIRMED |
| 1 | kind 0x11 ← `ESC\rst\`, `ESC F` | `{0x80, …}` | CONFIRMED |
| **2** word | kind 3 (word start, rules 0x79 / 0x06 / 0x77 / 0x78) | `0x30` | CONFIRMED |
| **8** | kind 0x26 ← `ESC\mrk=n\`, `ESC N<n>` (u32, `> 4294967295` rejected); also `ESC\audio="…"\` after a successful AUDIO_FETCHER call | n (audio: the local at @`0x10006872`, 0 as decompiled) | CONFIRMED (audio value INFERRED) |
| **0x10** control | kinds 0x13 / 0x14 / 0x16 / 0x17 / 0x18 / 0x1a / 0x1f / 0x20 / 0xf | `u16 subtype | u16 arg << 16`, table below | CONFIRMED |
| **0x20** pause | kind 9 ← `ESC\pause=n\` (n ms), `ESC P<n>` (n·100), `ESC H<n>` (1..10^7) | n | CONFIRMED (unit INFERRED: ms) |
| **0x80** wait | kind 0x21 ← `ESC\wait=n\`, `ESC W<n>`; also EOF | `'0'+n` | CONFIRMED |
| **0x200** paragraph | kind 6 ← `ESC\p\` | 0 | CONFIRMED |
| **0x8001** | kind 0x1c ← `ESC\tn=<mode>\`, auto at each utterance if tnmode≠normal | pool string (tn mode) | CONFIRMED |
| **0x8002** | kind 0x1e ← `ESC\voice=<name>\` | pool string, consumed by ttseg (voice switch) | CONFIRMED |
| **0x8003** | kind 0x10 ← `ESC\domain=<x>\` | pool string | CONFIRMED |
| **0x8004** | kind 0x23 ← `ESC\domain\` | 0 | CONFIRMED |

Type-0x10 subtypes (`0x10003a53`..`0x10003b9a`). CONFIRMED:

| subtype | source | arg |
|---:|---|---|
| 0x01 | `ESC V<n>` | n (0..9) |
| 0x02 | `ESC I<n>` | '0'+n (1..9) |
| 0x04 | `ESC R<n>` | '0'+n (1..9) |
| 0x08 | `ESC S<n>`, `ESC\s=n\` | '0'+n (1..9) |
| 0x10 | `ESC\chr=<style>\` | NORMAL 0, CALM 1, MONOTONE 2, WHISPER 3, NOPROSODY 4, COMPUTER 5, EXCITED 6, SINGING 7, LOUD 8 |
| 0x40 | `ESC\vol=n\` | 0..100 |
| 0x80 | `ESC\pitch=n\` | 1..100 |
| 0x100 | `ESC\rate=n\` | 1..100 |
| 0x800 | `ESC\rate_wpm=n\` | 1..1000 |

Types **4 (phoneme)** and **0x10/0x20 on-off regions** (ttseg §6) are never produced by this
PP. They come from elsewhere (VF, or mparser). CONFIRMED (no producer here)

---

## 5. The lexer (flex)

### 5.1 Tables and machinery

| table | addr | |
|---|---|---|
| yy_accept (s16) | `0x1000c0c8` | 1598 states |
| yy_ec (s32 ×256) | `0x1000cd44` | 104 classes. Every ASCII letter is its own class, `Q`/`Z` share one, digits are one class |
| yy_meta (s32) | `0x1000d144` | |
| yy_base (s32) | `0x1000d2e4` | jam base 0x8b8e |
| yy_def (s16) | `0x1000ed00` | meta threshold 0x63c |
| yy_nxt (s16) | `0x1000fa10` | |
| yy_chk (s16) | `0x100211fc` | |

CONFIRMED. Actions 1..0x80 are rules, 0x81 is ECHO→ignored, 0x82 is end-of-buffer, and
0x83..0x91 are `<<EOF>>` per start condition. Input arrives through `pp_yy_input` (`0x10008cd0`):
- It calls `pp_cb.get_input_text(appctx, &n, buf[, &markers if cb.mode==1])`, at most 0x400
  bytes per call into a 0x800-byte flex buffer.
- Trailing `^Z` (0x1a) is stripped (`pp_yy_get_next_buffer` `0x10007e00`).
- `0x3002003` → EOF flag at lex+0x198. `0x3002005` → "would block", which reaches the caller as
  `0x3002005`.

CONFIRMED

Start conditions (`yy_start = 1 + 2·SC`). CONFIRMED (codes); the purposes are INFERRED where
noted:

| SC | role |
|---:|---|
| 0 | sentence mode (readmode states 0) |
| 1 | `ESC /` literal region within sentence mode: words take punctuation, there is no sentence-end detection, `\n` is ignored |
| 2 / 3 | line mode (readmode 4), and line mode + literal region |
| 4 / 5 | look-ahead after a sentence-final punctuation mark / after the following whitespace (§3.2) |
| 6 / 7 | readmode states 4 / 5 (set by `ESC\` inside the look-ahead) |
| 8 | after a bare `ESC`: legacy single-letter L&H codes |
| 9 | after `ESC\`: long tags `name=value\` |
| 10 | skip an unknown long tag up to `\` |
| 11 / 12 | inside `ESC/+ … ESC/+` / `ESC/~ … ESC/~` (raw copy) |
| 13 | inside `ESC[TE] … ESC[\TE]` (raw copy) |
| 14 | inside `ESC\audio="…"` (supports `&quot;` and `&backslash;`) |

### 5.2 Lexer context (0x1b0 B, `pp_lex_create` `0x10008a60`)

Offsets CONFIRMED from use:
- +0x00: output strbuf. +0x04..+0x10: the sentence node list with its header node (kind 4).
  +0x18: pending nodes.
- +0x24: word-start flag. +0x28: colon / semicolon flag. +0x2c: inside-tag flag.
- +0x30 / +0x34: src tag start / src pos. +0x38 / +0x3c: dst tag start / dst pos.
- +0x48: readmode state 0..3. +0x4c: saved SC. +0x54: newreadmode value. +0x58: spell flag.
- +0x5c: `char[32]` current tn mode. +0x7c: `char[256]` audio URI.
- +0x188: rc. +0x18c: `pp_cb*`. +0x190: appctx. +0x194: flex buffer state.
- +0x19c: `INET` object. +0x1a0: `AUDIO_FETCHER` object.

### 5.3 Pass-through of upstream markers

When `pp_cb.mode == 1`, `get_input_text` also returns a list of marker records, the mparser
markup case. Each record becomes a kind-1 node holding the original record. It is re-positioned
by `pp_lex_merge_input_markers` (`0x10008920`) and emitted unchanged by case 1 of
`pp_nodes_to_markers`. ttseg sets mode 0 (ttseg §1.3), so this applies only to other hosts.
CONFIRMED (code); the host usage is INFERRED.

---

## 6. Escape tags (all case-insensitive)

### 6.1 `ESC \ name = value \` (SC 9)

| rule | tag | node kind → output |
|---:|---|---|
| 0x21 | `art=f\|p` | 0xe → header 0x40 |
| 0x22 | `beep=n` | 0x24 → header 0x10 |
| 0x23 | `mrk=n` | 0x26 → type 8 |
| 0x24–0x2c | `chr=calm\|computer\|excited\|loud\|monotone\|noprosody\|normal\|singing\|whisper` | 0xf → 0x10/0x10 |
| 0x2d / 0x2f / 0x30 | `domain=x` / `domain=` / `domain` | 0x10 → 0x8003 / 0x8003 "" / 0x23 → 0x8004 |
| 0x2e | `prompt=x` | 0x28. **No record.** INFERRED: for DOMAIN_MNGR. A closing `\` in SC 6/7 flushes the utterance (case 0x4c) |
| 0x31 | `p` | 6 → 0x200 |
| 0x32 | `pause=n` | 9 → 0x20, plus one `' '` |
| 0x33 | `pos=[ajnrv@]` | 0x22 → in-band `\x11@<c>` |
| 0x34 | `pp=<lang>` | 2 → header 2 + unget (PP/language switch) |
| 0x35 | `"` | 0xb → in-band `\x11"`. INFERRED: emphasis |
| 0x36 / 0x37 / 0x38 | `rate=` / `rate_wpm=` / `pitch=` | 0x17 / 0x18 / 0x14 → 0x10 subtypes 0x100 / 0x800 / 0x80 |
| 0x39 | `rst` | tn := normal (0x8001 "normal"), readmode state normalised, 0x11 → header 0x80 |
| 0x3a | `s=n` | 0x1a → 0x10/0x08 |
| 0x3b–0x3d | `tone=0-9 / a-f / A-F` | 0x25 → header 0x20 |
| 0x3e | `tn=<mode>` | 0x1c → 0x8001. `spell` sets the spell flag; the same mode twice is ignored |
| 0x3f | `voice=<name>` | 0x1e → 0x8002 |
| 0x40 / 0x41 | `vol=` / `wait=` | 0x20 → 0x10/0x40 ; 0x21 → 0x80 |
| 0x42 | `audio="uri"` | SC 14. Then `AUDIO_FETCHER` iface `+0x1c` (+ `INET`.`+0x20` with `inet.urlBase`) → kind 0x26 → type 8 |
| 0x44 | anything else | SC 10, swallowed up to `\` |

All CONFIRMED (emulator + `pp_yylex` cases). **Not present:** `lang=`, `eos=`, `readmode=`,
`spell=`, `para`. They fall into rule 0x44 and are swallowed. CONFIRMED (emulator)

`ESC\prn=…\` is a single rule (3) in SC 0 whose action only advances the source offset, so
**phonetic input via `\prn` is dropped** by this PP. CONFIRMED (`pp_yylex` case 3 →
`switchD_10004884_caseD_3`: `src_pos += yyleng` only)

### 6.2 Bare `ESC` + code (SC 8, L&H TTS-3000 style)

| rule | code | effect |
|---:|---|---|
| 0x08 | `E` | force end of utterance |
| 0x09 | `C` | in the sentence-end look-ahead: append a space, **continue** (suppress the break) |
| 0x0a | `[TE]` | kind 7 v=1 → `\x1ete`, raw copy (SC 13) until `ESC[\TE]` (kind 7 v=0 → `\x1fte`); the chunker never splits inside |
| 0x0b | `/+` / `/~` | region 0x21 / 0x30 → `\x11/+` / `\x11/~`, raw copy until the same code (SC 11 / 12) → region close |
| 0x0c | `/` | toggle the literal region (readmode state 0↔1, 2↔3) → `\x11/` open and close |
| 0x0d | `"` | kind 0xb → `\x11"` |
| 0x0e | `@[ajnrv@]` | kind 0x22 → `\x11@<c>` |
| 0x0f | `M<n>` | readmode: M0→2 (char), M1→3 (word), M2→1 (sentence), M3→4 (line) (kind 0x19 → paramc `newreadmode`) |
| 0x10 / 0x11 / 0x12 / 0x13 | `R<n>` / `I<n>` / `V<n>` / `S<n>` | 0x10 subtypes 4 / 2 / 1 / 8 |
| 0x14 | `SF<n>` | ignored |
| 0x15 | `W<n>` | type 0x80 |
| 0x16 | `F` | same as `rst` |
| 0x17 / 0x1e | `P<n>` / `H<n>` | pause n·100 / n |
| 0x18 | `B<n>` | beep |
| 0x19–0x1b | `T<x>` | tone |
| 0x1c | `A[FP]` | ART |
| 0x1d | `N<n>` | bookmark (type 8) |
| 0x1f | `%<lang>` | PP/language switch (as `pp=`) |
| 0x20 | other | `yyless(0)`, back to the previous SC (invalid ESC dropped) |

All CONFIRMED. The meanings of R, I, V, S, T, A, `/` and `"` are INFERRED from L&H usage; the
code only carries values.

---

## 7. In-band codes inserted into section 6 (`pp_insert_inband_codes` `0x10003dd0`)

After the charmap pass, nodes positioned in the text are turned into byte sequences spliced into
the type-6 text (and into any other section in `types[]`; only 6 is passed). CONFIRMED:

| node | inserted bytes |
|---|---|
| kind 5 (`\n` in `tn=address`) | `" \x11\\n "` |
| kind 7 v=1 / v=0 | `\x1e t e` / `\x1f t e` |
| region 0x11 (e-mail) open / close | `\x1e a d` / `\x1f a d` (suppressed in spell mode) |
| region 0x12 (URL) open / close | `\x1e u r` / `\x1f u r` |
| region 0x13 | `\x1e ? u r` / `\x1f ? u r` (no producer found) |
| region 0x20 (`ESC /`) | `" \x11/ "` |
| region 0x21 (`ESC /+`, dictionary phonetic) | `" \x11/+ "` |
| region 0x24 | `"\x12\x11/ "` / `" \x11/\x12"` (no producer found; charmap skips it) |
| region 0x30 (`ESC /~`) | `"\x11/~"` |
| kind 9 pause | `" \x11P "`. The record dst_pos is moved back 3 |
| kind 0xb | `" \x11\" "` |
| kind 0x22 POS | `" \x11@<c> "` |
| kind 2 with empty text | the language name becomes the whole text |

INFERRED: 0x11 is the L&H internal stand-in for ESC, consumed by `g2p_enu`; 0x1e/0x1f + two
letters open and close typed text regions (te / ad / ur).

---

## 8. Normalisation pieces that live here

### 8.1 Character map (`pp_charmap_get` `0x10009ec0`, table of `char*` @`0x10034244`)

Applied per byte of section 6 by `pp_apply_charmap` (`0x10004370`). A NULL entry deletes the
byte; a string replaces it. The target is **DOS CP437**. CONFIRMED (table); the CP437 name is
INFERRED from é→0x82, ü→0x81, ¢→0x9b, £→0x9c, ƒ→0x9f, §→0x15, ñ→0xa4, ¿→0xa8.

Samples:
- Whitespace: `\t \n \r 0xa0 ¤` → `' '`.
- Expansions: `€`→`EUR`, `°`→`" deg. "`, `ß`→`ss`.
- Punctuation: `‚`→`,`, `„“”`→`"`, `‘`→`` ` ``, `’ ´`→`'`, `– — ­`→`-`, `‹ ›`→`< >`, `˜`→`~`,
  `¦`→`|`, `×`→`x`.
- Š Œ š œ → S E s e. Ã Õ ã õ Ø ø Ý ý Ð ð → A O a o O o Y y D d. Every other accented letter → its
  CP437 code.
- **Deleted:** 0x00–0x08, 0x0b, 0x0c, 0x0e, 0x10, 0x12–0x1f, 0x7f, `…` `†` `‡` `‰` `•` `™`, 0x81,
  0x8d–0x90, 0x9d, 0x9e, `¨ © ® ¯ ± ² ³ µ ¶ · ¸ ¹ ¾ Þ ÷ þ`.

### 8.2 Abbreviations: sentence-boundary suppression only (`pp_is_abbreviation` `0x1000a300`)

- **Table structure:**
  - Keys are 1..7 bytes long, including the final `.` or `:`.
  - The first character's class comes from `0x10033417`.
  - Per-length blocks at `0x10033520 + L·0x3a`: `+2` u16 base, `+4..` start indices.
  - The remaining characters are 6-bit codes (`0x10033337`), bit-packed by `pp_bitpack`
    (`0x1000b800`).
  - Lookup is a binary search over `0x100336b8` (`pp_abbrev_bsearch` `0x1000a420`), with key
    lengths from `0x10033518`.

  CONFIRMED
- **210 entries**, decoded by `pptables.py` and verified by re-packing. CONFIRMED:
  - `A.`..`Z.` and `a.`..`z.`
  - `Dr. Ft. Jr. Lt. Mr. Ms. Mt. Sr. St. Vs.`
  - `NB. NB: PS. PS:`
  - `Adm. Col. Cpl. Dir. Drs. E.g. Fri. Gen. Gov. Hon. I.e. I.e: Maj. Mgr. Mon. Mrs. N.b: P.s: Pvt. Rep. Rev. Sat. Sen. Sgt. Sun. Thu. Tue. Viz. Wed.`
  - `Asst. Brig. Capt. Cmdr. Cong. Miss. Prof. Reps. Supt.`
  - `A.k.a. Cmdrs. Messrs.`
  - Each word appears in UPPER, Capitalised and lower forms (not every combination).
- It is used only by rule 0x06 to veto a sentence break. **Nothing in the PP expands an
  abbreviation.** CONFIRMED

### 8.3 Spell mode (`tn=spell`)

- **Expansion:** `pp_expand_spell_regions` (`0x10001db0`) walks each spell region (kind 0x1c
  "spell", or region ≥0x20 while spell is on). Each character is lowercased (`pp_tolower_1252`
  `0x10009130`) and written as `"%u"` (its decimal code). `pp_spell_char_name` (`0x10009ef0`)
  looks that code up and replaces the character with the result plus `' '`. CONFIRMED
- **The table holds L&H phonetic strings, not words.** Structure:
  - keys are the decimal codes "32".."255", packed as 4-bit digits
    (`0x10033043` / `0x10032f63` / `0x10033148` / `0x1003316c`)
  - a 10-bit offset table at `0x10033244` (`pp_unpack10` `0x1000a120`)
  - a string pool at `0x10032b84`, terminated by 0x05 and BPE-compressed with the pair table at
    `0x100329b6`

  Samples:

  ```
      '32'  'spJs                          '97'  '?J
      '33'  `?Eks-kl$-'mJ-S$n_'mark        '98'  'bi
      '36'  'da-l$r_'sYn                   '64'  '?\xe6t
      '65'  'k\xe6-pI-t$l_'J               '128' 'jU-rO_'sYn
      '153' 'trJd-mark                     '233' '?i_?$-'kjut
  ```

  Notation: `'` primary and `` ` `` secondary stress, `-` syllable, `_` word boundary, `?`
  glottal onset, `$` schwa, `J` /eɪ/, `Y` /aɪ/. CONFIRMED (data); the notation reading is
  INFERRED.
- INFERRED: G2P recognises these strings as phonetic because the 0x8001 "spell" record
  brackets them. No in-band code is added around them.

### 8.4 User dictionary (`pp_user_dict_lookup` `0x10009170`, `pp_user_dict_query_word` `0x10009940`)

- **Skipped:** when `newreadmode` is 2 or 3. CONFIRMED
- **Lookup object:** `WORD_DCTEG` from the objc registry. Each whitespace token outside spell
  and region spans is passed to `iface+0x34(rc, word, &len, out[0x400])`. CONFIRMED
- **Retries:** if the lookup misses, it retries in order with leading and trailing punctuation
  stripped, with trailing dots peeled one at a time, and lowercased. CONFIRMED
- **Applying a hit:** the token is replaced in section 6 only while the new text stays under
  65 % of the capacity. CONFIRMED
- **Hit with a leading 0x11:** an `\x11/+…` result opens region 0x21 (`/+`); any other
  `\x11/…` result opens region 0x30 (`/~`). CONFIRMED
- **Hit with a leading 0x10:** region 0x20. CONFIRMED
- INFERRED: phonetic dictionary entries come back already wrapped.

### 8.5 Not here

There is no code for numbers, ordinals, dates, times, currency, units, roman numerals,
telephone numbers or acronym spelling. The only digit handling is digits costing 25 units in the
chunker and a digit after `:`/`;` forcing a break. CONFIRMED (absence across every function decompiled;
`.text` is only 45 KB, and `pp_yylex` alone is 14 KB). That `g2p_enu` does that work is INFERRED.

---

## 9. Parameters

| key / id | where | effect | tag |
|---|---|---|---|
| SetParam 0x81 (markermode), 0x87 (readmode) | `pp_SetParam` | **accepted, ignored** | CONFIRMED |
| GetParam 0x84 | `pp_GetParam` | → `"windows-1252"` | CONFIRMED |
| paramc `markermode` | `pp_get_marker_mask` `0x1000b2e0` | value & 2 → mask 0xfffb, else 0xfff9. **Only the word bit matters.** If the key is missing it is written as "65529". ttseg's default 0xFFF9 → no word markers | CONFIRMED |
| paramc `newreadmode` | default "1" (ObjOpen); `ESC M<n>`; Reset/Stop → "1" | 1 sentence, 2 char, 3 word, 4 line (§3.3) | CONFIRMED (names INFERRED) |
| paramc `tnmode` | default "normal"; `ESC\tn=…\` | `spell` → §8.3; `address` → newlines become `\x11\n`; any other string → 0x8001 record only | CONFIRMED |
| paramc `typeofchar` | set to "windows-1252" at ObjOpen | the encoding xcoder converts to | CONFIRMED |

INFERRED: ttseg's API `readmode` (id 10) never reaches this PP. ttseg forwards it only as the
ignored SetParam 0x87. `newreadmode` appears elsewhere only in `domain_mngr.dll` and
`stdpp_spm.dll` (string census), so any mapping would be in domain_mngr.

---

## 10. Build and lineage

- **Version and build info.** CONFIRMED:
  - VERSIONINFO: `pp_std_enu`, FileVersion **4.0.2.6136**, "Nuance Communications, Inc.",
    "© 2002-2006 ScanSoft".
  - Link time 2006-05-16 06:45 UTC, linker 6.0.
  - CodeView NB10 PDB `F:\ttssrc.a\win32.x86\rel\tts_predev_prd\pp\std\enu\stdpp_enu.pdb`.
  - Banner @`0x10034010`: `#TTSSO_VER\nScanSoft\nCDF stdpp_enu 2.00\nCopyright 2003`.
- **The 2004 ScanSoft build** (`/ss_stdpp_enu.dll`, `ScanSoft\speech\components\pp\stdpp_enu.dll`,
  read-only peek). CONFIRMED:
  - Link time 2004-07-22, VERSIONINFO "CDF - STDPP Eng USA" 4.00, description
    `/tts_predev_prd/pp/std/enu - Release`, no PDB.
  - Same banner, the same flex error strings, the same `()[]<>$%~+-/\{}_` and `.?!:;` sets, and
    the same packed-table key strings.
  - It adds trace strings: "Entering/Exiting stdpp_ObjOpen", "SentLexCreate() or P2MCreate()
    failed", "Invalid PP specific resource structure".
  - It lacks `markermode`, `tnmode`, `newreadmode`, `DOMAIN_MNGR`, `address` and `INET`.
  - Its .rdata is 80 KB against 160 KB here.

  INFERRED: the same source tree (`tts_predev_prd/pp/std`). The 2006 build grew the DFA (domain,
  prompt, `tn=address`, URL/e-mail regions) and moved readmode, tn and markermode into paramc.
- **Sibling builds.** CONFIRMED:
  - `stdpp_spm.dll` (2006-06): same size (225362), banner `CDF stdpp_spm 1.01`, the same PDB tree
    `pp\std\spm`.
  - `stdpp_eng.dll` and `stdpp_spe.dll` (2005/2006) are 143–147 KB.
- **EMPP** (`ScanSoft\…\pp\empp_enu.dll`, 463 functions): not examined. The only shared marker
  found is the `WORD_DCTEG` string (string census). INFERRED: unrelated code.

---

## 11. Open

- The VF side of header subtypes 0x10 (beep), 0x20 (tone), 0x40 (ART), 0x80 (RST), of the
  type-0x10 subtypes (pitch 0x80 especially) and of type 0x80 (wait). Check `vf_GenPcm` /
  `synth_*` for `+0x14` readers.
- How `g2p_enu` consumes the in-band codes `\x11/`, `\x11/+`, `\x11/~`, `\x11P`, `\x11"`,
  `\x11@c`, `\x11\n` and the regions `\x1e/\x1f te|ad|ur`, and whether it treats the spell
  strings (§8.3) as phonetic.
- The `AUDIO_FETCHER` / `INET` call signatures in rule 0x45 (@`0x10006872`), and the value
  placed in the type-8 record for audio.
- The DOMAIN_MNGR `+0x44` hook (in `domain_mngr.dll`), `prompt=` (kind 0x28) and the
  `newreadmode` link to ttseg `readmode`.
- Producers for region codes 0x13 and 0x24. They are possibly DOMAIN_MNGR.
- A full DFA regex dump. The emulator gives behaviour per input but not the source patterns
  (for example the exact URL/e-mail grammar).
- `pp_ResetParam` (`+0x28`): confirm the role from the ttseg caller.

---

## 12. Functions created and renamed (unsaved Ghidra session, `/rs_stdpp_enu.dll`)

**Created** (the interface slots were undefined): `0x10001480`, `0x100014c0`, `0x100014e0`,
`0x10001520`, `0x10008cd0`.

**Renamed** (by a batch script, which reported 105 renames; `pp_ObjOpen` was renamed separately):

| addr | name | addr | name |
|---|---|---|---|
| 0x10001000 | pp_dllmain_crt | 0x10009070 | pp_is_lower_1252 |
| 0x10001170 | pp_ObjOpen | 0x100090b0 | pp_is_upper_1252 |
| 0x10001390 | pp_reset_state | 0x100090f0 | pp_is_word_char |
| 0x10001400 | pp_ObjClose | 0x10009130 | pp_tolower_1252 |
| 0x10001480 | pp_GetParam | 0x10009170 | pp_user_dict_lookup |
| 0x100014c0 | pp_SetParam | 0x10009940 | pp_user_dict_query_word |
| 0x100014e0 | pp_ResetParam | 0x10009e80 | pp_strlower_1252 |
| 0x10001500 | pp_ResetReadMode | 0x10009ec0 | pp_charmap_get |
| 0x10001520 | pp_Process | 0x10009ee0 | pp_spell_maxlen |
| 0x10001920 | pp_process_sentence | 0x10009ef0 | pp_spell_char_name |
| 0x10001db0 | pp_expand_spell_regions | 0x1000a0f0 | pp_is_graphic_run |
| 0x10002250 | pp_Stop | 0x1000a120 | pp_unpack10 |
| 0x100022c0 | pp_paramobj_create | 0x1000a1b0 | pp_spell_bsearch |
| 0x100022f0 | pp_get_text_capacity | 0x1000a300 | pp_is_abbreviation |
| 0x10002300 | pp_chunk_by_readmode | 0x1000a420 | pp_abbrev_bsearch |
| 0x10003600 | pp_find_special_head_node | 0x1000a570 | pp_msg_get_section |
| 0x10003680 | pp_find_special_node_before | 0x1000a5f0 | pp_msg_add_section |
| 0x10003740 | pp_find_last_readmode_node | 0x1000a650 | pp_msg_resize_section |
| 0x10003780 | pp_find_open_region_node | 0x1000a680 | pp_msg_resize_section_impl (INFERRED) |
| 0x100037d0 | pp_find_next_region_node | 0x1000a750 | pp_msg_remove_section |
| 0x10003820 | pp_nodes_to_markers | 0x1000a840 | pp_msg_find_section |
| 0x10003db0 | pp_count_nodes_at_pos | 0x1000a8b0 | pp_msg_section_elem_size |
| 0x10003dd0 | pp_insert_inband_codes | 0x1000a9e0 | pp_msg_alloc_section (INFERRED) |
| 0x10004370 | pp_apply_charmap | 0x1000aaf0 | pp_stricmp |
| 0x100046e0 | pp_yylex | 0x1000ab80 | pp_itoa |
| 0x10007e00 | pp_yy_get_next_buffer | 0x1000ac00 | pp_atoi |
| 0x10008050 | pp_yy_get_previous_state | 0x1000acb0 | pp_mrklist_free |
| 0x10008130 | pp_yy_try_nul_trans | 0x1000ad00 | pp_mrklist_clear |
| 0x100081e0 | pp_yyrestart | 0x1000ad20 | pp_mrklist_init |
| 0x10008230 | pp_yy_load_buffer_state | 0x1000ad40 | pp_mrklist_set_heap |
| 0x10008290 | pp_yy_create_buffer | 0x1000ad50 | pp_mrklist_append |
| 0x10008320 | pp_yy_delete_buffer | 0x1000ae60 | pp_mrklist_append_ctrl |
| 0x10008380 | pp_yy_init_buffer | 0x1000aed0 | pp_mrklist_prepend_header |
| 0x100083b0 | pp_yy_flush_buffer | 0x1000af30 | pp_mrklist_set_mask |
| 0x10008410 | pp_yy_fatal_error_stub | 0x1000af40 | pp_node_new |
| 0x10008420 | pp_unget_rest_of_input | 0x1000b020 | pp_node_alloc |
| 0x100084d0 | pp_lex_begin_sentence | 0x1000b050 | pp_nodelist_init |
| 0x100087a0 | pp_drop_empty_sentence_nodes | 0x1000b070 | pp_nodelist_clear |
| 0x10008830 | pp_lex_commit_pending_nodes | 0x1000b0a0 | pp_nodes_free |
| 0x10008860 | pp_lex_close_sentence_header | 0x1000b110 | pp_nodelist_append |
| 0x100088e0 | pp_lex_hand_out_sentence | 0x1000b170 | pp_node_insert_after |
| 0x10008920 | pp_lex_merge_input_markers | 0x1000b1d0 | pp_paramobj_destroy |
| 0x10008a60 | pp_lex_create | 0x1000b200 | pp_get_newreadmode |
| 0x10008cd0 | pp_yy_input | 0x1000b250 | pp_get_tnmode |
| 0x10008e10 | pp_lex_destroy | 0x1000b290 | pp_tnmode_is_spell |
| 0x10008f00 | pp_lex_reset | 0x1000b2e0 | pp_get_marker_mask |
| 0x10008fc0 | pp_lex_apply_readmode | 0x1000b350 | pp_set_newreadmode |
| 0x1000b3b0 | pp_reset_newreadmode | 0x1000b3f0 | pp_set_default_markermode |
| 0x1000b440 | pp_strbuf_create | 0x1000b480 | pp_strbuf_set |
| 0x1000b520 | pp_strbuf_destroy | 0x1000b560 | pp_strbuf_is_empty |
| 0x1000b590 | pp_strbuf_len | 0x1000b5c0 | pp_strbuf_append |
| 0x1000b6d0 | pp_strbuf_compact | 0x1000b740 | pp_strbuf_read |
| 0x1000b790 | pp_strbuf_append_strbuf | 0x1000b800 | pp_bitpack |
