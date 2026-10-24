# THIS DOCUMENT HAS BEEN SUPERSEDED BY `README_TECHNICAL.md` — it is kept here for HISTORICAL PURPOSES ONLY.

## ScanSoft / RealSpeak Solo v4 — technical living document

Binary-level detail for the `useld` (unit-selection) and `codsb` (coded audio)
containers, the voice-font DLL, and the broker. Companion to `README.md`.

**Everything dated 2026-08-10 unless noted.** Addresses are for the **NextUp
2004** pack unless stated, because its `useld` is plaintext and RS4's is not.
Every claim below is either measured against the file or read out of the
disassembly, and the ones that failed are kept with the reason.

---

## 0. Provenance and scope

| pack | root | build | `useld` | `codsb` |
|---|---|---|---|---|
| **ScanSoft** (NextUp) | `C:\Program Files (x86)\NextUp-ScanSoft\speech` | 2004 | 39,242,036 B, plaintext | 49,531,617 B |
| **RealSpeak** (Solo v4) | `C:\Program Files (x86)\ScanSoft\RealSpeakSolov4\speech` | 2006 | 20,225,396 B, **`encrypt`** | 60,545,984 B |

`synth_155mrf22.dll` is **byte-identical** across packs (sha256 prefix
`d12c7c0097daba3b`, 110,686 B). The voice fonts are not: NextUp `vf_tom_full.dll`
is 794,624 B with a 683 KB `.rdata`; RS4's is 204,896 B with 86 KB.

⚠ **L&H is a different lineage.** `RealSpeak Standard v2` (`lhsp\rsstdv2`) and
`L&H PCMM RealSpeak V1` (`RSMGR10`/`rsenu1f1`/`.cod`) share the brand and the
SAMPA house style and nothing else. Do not transfer findings. Memory:
`reference_scansoft_vs_realspeak_vs_lh`.

⚠ **The two Toms are different corpora.** `codsb` bodies identical for 135 B;
**0/47** aligned 1 MB blocks match. `useld` pair diverges at byte 44 (`Tom` vs
`tom`). Probe: `C:\tmp\usel_runs.py`.

---

## 1. The SCANSOFT container header (0x00..0x90)

Confirmed on four files, and cross-checked against the DLL's own validator.

| off | size | field | useld (NextUp) |
|---|---|---|---|
| 0x00 | 4 | magic, u32 | `0x0000feff` |
| 0x04 | 8 | vendor | `SCANSOFT` |
| 0x0c | 8 | type | `useld   ` / `codsb   ` |
| 0x14 | 4 | **hdr_len** | `0x90` |
| 0x18 | 8 | version | `1.00    ` |
| 0x20 | 12 | language | `enu         ` |
| 0x2c | 32 | voice | `Tom` (RS4: `tom`) |
| 0x4c | 48 | variant | `full` (RS4 useld: `full    encrypt`) |
| 0x7c | 4 | toc_len | `0x90` |
| 0x80 | 4 | 3 ASCII digits + space | `173 ` (RS4 useld `216 `) |
| 0x84 | 4 | **per-pack build stamp** | NextUp `265498`, RS4 `822349082` |

⚠ **+0x80 is NOT a tag count for the `useld`,** and **+0x84 is NOT a length.**
+0x84 carries the *same* value for a pack's `useld` and its `codsb`, so it
identifies the build, not the file. Reading either as a count produced a
"three-block table" in an early pass that does not exist — see §7.

The validator, `FUN_10003020` in `vf_tom_full.dll`:

```c
brk_DataOpen(class, brokerstring, &handle);
brk_DataMap (class, handle, 0, 0, &base);      /* whole file, cached */
if (*(u32*)base != 0xfeff) { if (memcmp(base+4,"SCANSOFT",8)) return 0x8113a019;
                             *out_hdrlen = 0; }
else                         *out_hdrlen = ((u32*)base)[5];   /* +0x14 */
```

so **`body = file + hdr_len` = file + 0x90**.

---

## 2. combrk.dll — the broker, and what it is NOT

`C:\Program Files (x86)\NextUp-ScanSoft\speech\components\common\combrk.dll`,
40,960 B, `.text` 18,890 B, base 0x10000000. **Closed out; do not reopen.**

| export | va | what it does |
|---|---|---|
| `brk_DataOpen` | 0x10003cf0 | resolve module, alloc 16-B cache record `{refcnt,size,base,handle}`, optionally pre-map whole file |
| `brk_DataMap` | 0x100041d0 | cached: `*out = base + offset` behind `cached_size < offset+len`; else `osspi_DataMap` |
| `brk_TagQuery` | 0x10003490 | look up a **named tag in a module's parsed `.hdr`**, return a strdup'd string |
| `brk_InfoQuery` | 0x10003cd0 | **stub** — `*out = 0; return 0x81506001` |
| `brk_ErrorGetString` | 0x10004670 | `(code,msg)` table walk at `DAT_100062b0` |

Tag nodes are a linked list `{char *name; char *value; …; node *next}` — walker
`FUN_10005360` (`[3]` next, `[1]` value).

**combrk never reads the SCANSOFT header and holds no section directory.**
Consumers pass **absolute file offsets** to `brk_DataMap`.

Error encoding: module = `(code >> 20) & 0x7ff` (0x15 combrk, 0x22 tag module);
bit `0x2000` routes to `lh_ErrorGetString`.

⚠ **Protection-module lead is DEAD.** `ERROR ON PROTECTION MODULE SETTING THE
OEM KEY` / `CHECK YOUR .PLH FILE` are rows in the error-message table, not code.
The only `.plh` on this machine is `RealSpeak Standard v2\lhsp\ss_wind32.plh`
— **L&H family**. Neither Solo v4 pack has one and neither `.hdr` mentions
encryption, so RS4's `encrypt` marker is handled by the consumer, not the
broker. **Where RS4 decrypts is still unknown** (candidates: `comrsrc.dll`'s
`osspi_*`/`filespi_*`, or the voice font).

### `.hdr` files (plain text, free)

`speech\rssolov4\enu\rssolo_*.hdr`, XML-ish. Tom's three:

```
us_tom_full.dat    COMPTYPE UNITSELECTDATA  BROKERSTRING us/rs/enu/tom/full/155mrf22/06
vf_tom_full_….dat  COMPTYPE REALSPEAKDATA   BROKERSTRING vf/rs/enu/tom/full/155mrf22/270/06
vf_tom_full.dll    COMPTYPE VOICEFONT       GETINTERFACE vf_GetInterface
CODER 155mrf22   BITRATE 270   OVERHEADFRAMES 06   VOICEFREQUENCY 22
```

**`OVERHEADFRAMES = 6` is the `lookback` constant** in `FUN_100060f0`. Previously an
unnamed number.

---

## 3. vf_tom_full.dll — the section directory is IN THE CODE

Base 0x10000000. `.text` 0x10001000..0x10016010, `.rdata` 0x10017000..0x100bde12,
`.data` 0x100be000..0x100bea58.

**`brk_DataMap` has exactly ONE call site** — `0x1000309e` in `FUN_10003020`.
The file is mapped once, whole; everything after is pointer arithmetic.

```
FUN_10003420  (us_ObjOpen-equivalent)
  └ FUN_10003020   open + map + validate header  ->  body
  └ FUN_100042c0(heap, n1, n2, body)   alloc 0x138 object, then:
      ├ FUN_10007280(body, obj+0x1c)   13 hardcoded stores
      └ FUN_10007240(body, obj+0x1c)   5 hardcoded stores
```

### `FUN_10007280` — section pointers and counts

```
s+0xd0 = 0x94d5   (38101)      s+0xd4  = body + 0x000000
s+0xdc = 0xcbfef  (835567)     s+0xd8  = body + 0x025354
s+0xe4 = 0x94d9   (38105)      s+0xe0  = body + 0x04a6a8
s+0xf0 = 0xd11ae  (856494)     s+0xe8  = body + 0x37a664
s+0xfc = 0x2b748c (2847884)    s+0xec  = body + 0x39f9c8
                               s+0xf4  = body + 0x3c4d2c
                               s+0xf8  = body + 0x7093e4
                               s+0x100 = body + 0x845e80
```

### `FUN_10007240` — the per-unit tables

```
*p    = *(u32*)(body + 0x1e002e0)      /* n_units */
p[2]  = body + 0x1e002e4               /* struct +0x08 */
p[3]  = body + 0x1e006f4               /* struct +0x0c */
p[5]  = body + 0x1e008fc               /* struct +0x14  — 8-byte record  */
p[4]  = p[5] + n_units * 8             /* struct +0x10  — 16-byte record */
```

**These are per-voice immediates.** The same store pattern (fixed struct
offsets 0xd0…0x100 with voice-specific constants) is findable with capstone in
every `vf_*_full.dll`, so all nine RS4 voices and NextUp's three can have their
tables extracted **without Ghidra — including RS4 Tom, whose `.dat` is
encrypted but whose DLL is not.** Not yet done.

### Validated against the file

`C:\tmp\useld_sections.py`. Six of eight spans are exactly `count x 4`.

| sec | file offset | size | reading |
|---|---|---:|---|
| A | 0x00000090 | 152,404 | 38,101 x u32, strictly ascending, max 2,247,959 |
| B | 0x000253e4 | 152,404 | 38,101 x u32, ascending from 0, max 835,420 |
| C | 0x0004a738 | 3,342,268 | 835,567 x u32, max 324,066 |
| D | 0x0037a6f4 | 152,420 | 38,105 x u32, ascending, max 2,247,959 |
| E | 0x0039fa58 | 152,420 | 38,105 x u32, ascending, max 856,298 |
| F | 0x003c4dbc | 3,425,976 | 856,494 x u32, contains 0xFFFFFFFF sentinels |
| G | 0x00709474 | 1,297,052 | **324,263 x u32 — one per unit** |
| H | 0x00845f10 | 30,566,948 | bulk; the two per-unit records live inside it |

**`*(u32*)(body+0x1e002e0) = 324,263`** — exactly the unit count we had derived
from the ACELP decoder by an entirely independent route. Independent confirmation
that the address is right.

⚠ **Unexplained:** sections A and D both max at **2,247,959**, and RS4's first
table maxes at the same value despite being a different corpus. Do not build on
it until it is understood.

---

## 4. The per-unit records

### 16-byte record — `p[4]` = file 0x2079ec4 + 16*uid

Found via `FUN_100073a0` (the candidate scorer), which indexes
`*(int*)(p+0x10) + unit*0x10`.

| off | distinct | notes |
|---|---:|---|
| +0..+2 | 256 | high-entropy; position/id, not yet read |
| +3 | 10 | small enum; 99.8% equal between adjacent uids |
| +4..+8 | 45/43/45/39/41 | **phone ids**, mostly 0 (= absent); non-zero count falls off with distance |
| **+9** | **46** | **the unit's own phone** — never 0, range 35..164 |
| +10 | 45 | phone, adjacent context |
| +11 | 166 | not a phone |
| +12 | 16 | multiples of 32 — bit-packed |
| +13,+14 | 53,52 | **not phones** (29–31 values outside the alphabet) |
| +15 | 1 | always 0 |

**Lanes +4..+10 contain only ids from the 46-value alphabet — zero exceptions
across 324,263 units.** That is the test that named them.

The scorer prices `+9`/`+10` mismatches through substitution tables
`PTR_DAT_100b6ba0` / `PTR_DAT_100b72d0`, indexed via the class map (§5);
`+4` and `+8` are equality-tested against target fields.

### 8-byte record — `p[5]` = file 0x1e0098c + 8*uid

`FUN_100073a0` scores **eight** sub-costs from it, each with its own function —
this is the target-cost feature vector:

| field | cost fn | field | cost fn |
|---|---|---|---|
| +0 | `FUN_1000f9b0` | +5 | `FUN_1000f900` |
| +1 | `FUN_1000f8a0` | +6 bits 0-2 | `FUN_1000f9f0` |
| +2 | `FUN_1000f7e0` | +6 bits 3-5 | `FUN_1000fa70` |
| +3 | `FUN_1000f960` | +6 bits 6-7 | `FUN_1000fb70` |
| +4 | `FUN_1000f840` | +7 bits 0-2 | `FUN_1000faf0` |

Lane alphabets: `154 / 46 / 46 / 38 / 46 / 46 / 75 / 5`.

⚠ Four lanes hold exactly 46 values, which is **coincidental with** the phone
count and is **not** the phone label — the phones are in the 16-byte record.
Do not re-derive this; see §7.

### Candidate list

`FUN_100073a0` maintains a sorted candidate array of **20-byte** rows
`{unit_id, cost, flag, ?, subst_cost}`, insertion-sorted by cost
(`FUN_10007320` is the 5-u32 swap). Beam: `best + 80000`, histogram-pruned in
0x9c4 (2500) buckets to ~0xa0 (160) survivors.

---

## 5. The ENU phone alphabet — 46 SAMPA characters

`DAT_100220f8` in `vf_tom_full.dll` (file offset 0x220f8) is a sparse
**phone id -> dense class** map: `255` everywhere except the 46 ids that occur,
which map onto `0..45`. **The id IS the SAMPA character's byte value.**

```
#  $  @  A  C  D  E  G  I  J  L  N  O  R  S  T  U  Y  Z  ^
a  b  d  e  f  g  h  i  j  k  l  m  n  p  q  r  s  t  u  v  w  y  z
0x8b  0x91  0xa4
```

Frequency of lane +9 (the unit's own phone), whole corpus:

```
n 30181  t 23881  0x8b 23611  i 21728  $ 21023  # 15511  z 14713  e 13644
r 13592  d 12445  q 9254  s 9064  l 9015  u 7983  I 7729  O 7412  J 7337
k 7134  v 6743  N 6176
```

`$` = schwa, `#` = silence. Readings so far, from the DLL's own embedded
lexicon: `'Al-sO` = also, `wE-D$r` = weather, `'DEn` = then, `dZ^st` = just,
`In-'kor-p$-'rJ-tId` = incorporated, so **`J` = /eɪ/**, `A` = /ɔ/, `D` = /ð/,
`N` = /ŋ/, `S` = /ʃ/.

Against the 44-symbol L&H RealSpeak V1 set recovered on this machine:
**42 shared**, only-here `L q`, only-L&H `? o`.
⚠ **A shared notation is a house style, not lineage evidence.**

⚠ The class map occupies indices **0..164 only**. The bytes after it are other
data (`232,3` / `208,7` = 1000 / 2000 as u16); reading all 256 invented ~40
phantom phones with class 0 in the first pass.

**"radar" in this notation should be `r J d a r` = bytes 114, 74, 100, 97, 114.**
Not yet searched — needs §6.

---

## 6. A/B/C is a KEY -> POSTINGS INDEX (confirmed); time order still OPEN

### Confirmed: A/B/C is a lookup index, not a time table

`C:\tmp\useld_index.py`. The counts pair up — A and B are both 38,101, D and E
both 38,105 — which is the shape of a sorted-key table plus an offset table
over a posting list. It holds:

```
A = 38,101 sorted keys, ascending, 1 .. 2,247,959
B = 38,101 offsets into C, ascending, 0 .. 835,420
C = 835,567 unit-id postings
```

- ⚠ ~~group sizes sum to 835,567 = |C| exactly~~ — **VOID, see §7.9.** That sum
  telescopes to `|C| - offsets[0]`, and `offsets[0]` is 0, so it equals `|C|`
  for ANY offset array. It cannot fail and is not evidence.
- **0 of 835,567 postings fall outside unit range** — this one can fail
- offsets ascending and bounded by `|C|`; group sizes 1..9,955, mean 21.93,
  none negative

That is the same shape as Speechify's PRSL. **So A/B/C says nothing about time**
and the search moves to G / H.

⚠ The key is **not** the (+9,+10) phone pair: +9 is constant in only 13.1% of
groups and the (+9,+10) pair in 1.1%, and the 13.1% is inflated because the
low-numbered keys are all silence (`#`) contexts. Key space max 2,247,959 is
still unexplained — and A, D and RS4's first table all max at that same value
across two different corpora.

⚠ **The D/E/F arm of that run is VOID** — I passed FILE offsets where the
helper adds `body`, so it read 0x90 bytes off and produced negative group
sizes. Re-run with body-relative 0x37a664 / 0x39f9c8 / 0x3c4d2c before quoting
anything about D/E/F.

### Ruled out as the position field

`C:\tmp\unit_order.py`, pre-registered as: >=99% of values under the frame
count (1,010,009) and a mean sorted gap near 1010009/324263 = 3.11.

| candidate | <frames | distinct | mean gap | verdict |
|---|---:|---:|---:|---|
| 16-B record +0..2, 24-bit | 6.2% | 321,496 | 51.74 | fail |
| 16-B record +0..3, 32-bit | 0.6% | **324,263** | 7074 | fail |
| +1..3, 24-bit @1 | 100.0% | 305,829 | 27.64 | fail |
| section G | 65.3% | 219,940 | 7.93 | fail |

And the chaining test — order by the field, then `+10(k) == +9(k+1)` — stays at
**3.1–4.0% under every ordering**, against 3.7% for raw array order. Chance.

**+0..+3 has exactly 324,263 distinct values, one per unit, all unique.** It is
a per-unit KEY (hash or id), not a position: a position would cluster, and this
spans 0..2,294,059,481.

**Section G**: 1.83% `0xFFFFFFFF` sentinels, 219,940 distinct otherwise,
distribution decaying from zero (`0:6579, 1:3889, 2:2764, 3:1991, 4:1651`),
36.5% below the unit count. That is the shape of a small per-unit COUNT or
distance, not a position.

### CONFIRMED: a per-unit POSITION and LENGTH that tile

`FUN_10007060` walks a chosen unit sequence and computes, per step:

```c
uVar3 = *puVar7;                                   /* u32[0] of the 16-B rec */
uVar6 = (uVar3 & 0x7fffffff) - pos_prev - (len_prev & 0xffff);
if (uVar6 == 0 && prev_flag != 1) mark[k-1] = 1;   /* CONTIGUOUS */
mark[k] = (byte)(*puVar7 >> 0x1f);                 /* bit 31 = own flag */
uVar6   = (b12 >> 4) | (b11 << 4);                 /* 12-bit LENGTH */
```

**The engine's own adjacency test is `pos[k] == pos[k-1] + len[k-1]`.** So:

```
pos  = u32[0] & 0x7fffffff      31 bits, 324,263 distinct (unique per unit),
                                0 .. 146,575,833
len  = (b11 << 4) | (b12 >> 4)  12 bits, 10 .. 4067, mean 395.66
bit31 of u32[0]                 a flag; set on exactly 1 unit of 324,263
```

Tiling test (`C:\tmp\unit_pos.py`), sort by `pos` then take
`pos[k+1] - pos[k] - len[k]` over 324,262 steps:

| value | count |
|---|---:|
| **0** | 263,334 (81.21%) |
| **300** | 60,924 |
| 200 | 4 |

**324,258 of 324,262 steps are 0 or 300**, and
`sum(len) + 300 x n_gaps = 128,299,085 + 18,277,200 = 146,576,285` against a
span of `146,577,085` — the accounting closes to **800 samples in 146.6
million**. The fields are right.

### The quantum: `pos` is in 100-microsecond ticks (geometry proven to 3 ppm)

Ground truth: `C:\tmp\nomorekillmyvibe\codsb_corpus\nextup_tom_full.wav`, the
project's own decode of the NextUp Tom inventory. Verified genuine speech
before use — header offset 44 confirmed from `size - frames*ch*sw`, RMS 2152 to
3766 across 20 windows spanning the file, 22.3% of the first minute below
|x|<100 (`C:\tmp\wav_sanity.py`).

```
wav          323,202,880 samples @ 22050 Hz = 1,010,009 frames x 320 = 14,657.71 s
pos span     146,577,085                               / 10,000/s   = 14,657.71 s
```

**`pos` is in ticks of 100 µs**, i.e. `sample = pos * 22050/10000 = pos * 2.205`.
Laying every unit end to end in `pos` order with its trailing gap gives
**323,201,810 samples against the wav's 323,202,880 — 1,070 samples in 323
million, 3 parts per million.** The `(pos, len)` model tiles the real corpus
exactly.

### ⚠ OPEN: the labels do not match the audio at those positions

The geometry is right and the CONTENT is not. Pre-registered test
(`C:\tmp\pos_vs_audio.py`, `pos_order2.py`): a unit whose phone (+9) is `#`
must be quiet and one whose phone is `s` must have a high spectral centroid,
with a random-span control that must NOT separate.

| mapping | total vs wav | result |
|---|---|---|
| `pos * 2.205` (= pos order, gaps kept) | **100.00%** | no separation |
| cumsum(len), uid order | 87.53% | no separation |
| cumsum(len), pos order, gaps squeezed | 87.53% | no separation |
| `pos * k` for k = 1, 2, 2.1, 0.5 | — | no separation |

Every group lands at RMS ≈ 2700–3100 and centroid ≈ 1600–2100, **identical to
its own random-span control**. The control behaved, so the instrument works;
the mapping does not.

So one of these is true and none is yet shown:

1. the decoded wav concatenates units in a different order from `pos` (the
   decoder walked codsb storage order, not the recording timeline) — the total
   would still match, since it is the same set of units;
2. `+9` is not the unit's phone after all, despite 7 lanes containing only
   valid alphabet ids;
3. there is a constant or per-recording offset between the two axes.

### RESOLVED (3): there is an offset, and the mapping is real

`C:\tmp\silence_align.py`. Two binary tracks at 10 ms over the whole 4 h
corpus — `expected[i]` = inside a `#`-labelled unit, `actual[i]` = audio below
10% of the median envelope — cross-correlated over ±20 s:

```
peak r = +0.315 at lag +7 frames (+70 ms)
correlogram sd 0.0225  ->  |peak| / sd = 14.0
r at lag 0 = +0.271;  neighbouring lags 4..9 all +0.307..+0.315
```

**A 14-sd peak.** `pos * 22050/10000` is the corpus timeline, with a ~70 ms
offset between the axes. That also explains the earlier null: the mean unit is
39.6 ms, so a 70 ms error moves a unit **completely off its own span**, and
every class then reads as a random span — which is exactly what was observed.

Confirmation on phone identity (`C:\tmp\pos_confirm.py`), spectral centroid per
class over 250-400 units each:

| phone | centroid | |
|---|---:|---|
| `s` | 2887 Hz | voiceless fricative — highest |
| `z` | 2761 Hz | voiced fricative |
| `#` | 2262 Hz | silence/noise floor |
| `t` | 1763 Hz | stop |
| `i` | 1671 Hz | vowel |
| `n` | 1621 Hz | nasal |
| `a` | 1603 Hz | vowel — lowest |

Fricatives sit ~1200 Hz above the vowels with nasals down among them: the
correct phonetic ordering across seven classes. **Lane +9 is the unit's phone
and `pos` addresses the corpus.**

### The quantum, decided by the audio: TICKS, not samples

The corpus decoder is `/Documents/ssrs_re/codsb/` (`codsb_dump`). `main.c` writes
frames sequentially at `CODSB_FRAME = 320` samples each from `start`, with no
gap handling and no overhead skipping, so **wav sample = frame_index x 320**
and the full dump is `start = 0`. That makes the wav a clean linear image of
the codsb, which is what lets it arbitrate.

The older addressing note (`fi = pos / S - lookback`, S = 320) reads `pos` as
SAMPLES at the codec rate. Both readings were put to the same
cross-correlation:

| reading | peak r | |peak|/sd | lag |
|---|---:|---:|---|
| `pos` = samples @ 22050 | +0.0061 | **3.7** | −16.5 s (i.e. nothing) |
| `pos` = 100 µs ticks | **+0.3150** | **14.0** | +70 ms |

**Ticks wins by 50x in correlation.** So `*param_3` in that addressing function
is already-converted samples supplied by the caller; the stored field is ticks,
and the conversion is `samples = ticks * rate / 10000`. A rate-independent
time base makes sense for a format that also ships 11 kHz and 16 kHz coders
(`synth_83swf11.dll`, `synth_112mrf16.dll`).

### RESOLVED: the offset, with a null (`C:\tmp\offset_final.py`)

Two statistics as a function of a global offset, 512-sample windows centred on
each unit's midpoint so length cannot confound, 600 units per class. **NULL =
300 random global offsets** across the corpus — that preserves every unit
length, class size and corpus statistic and destroys only alignment.

```
null:   sil_ratio  0.999 +- 0.052        fric_sep  -0 +- 113 Hz
```

The null is flat, as it must be. The sweep:

| statistic | best | at | z vs null |
|---|---:|---:|---:|
| fricative separation `centroid(s,z) - centroid(i,a)` | **+1338 Hz** | **−80 ms** | **+11.9** |
| silence ratio `rms(#)/rms(vowels)` | 0.450 | −136 ms | −10.4 |

**6 `OVERHEADFRAMES` = 1920 samples = 87 ms**, and the sharper statistic peaks
within 7 ms of it, NEGATIVE — exactly what `fi = pos/320 - lookback` means: a
unit's audio begins six frames BEFORE `pos`. Disassembly and audio now agree.

Per class at −80 ms:

| | `#` | `s` | `z` | `i` | `a` |
|---|---:|---:|---:|---:|---:|
| rms | **1757** | 2322 | 2512 | 3228 | **3546** |
| centroid Hz | 2983 | **3148** | 2729 | 1747 | **1454** |

Silence quietest, vowels loudest with the lowest centroids, fricatives highest
— and at random offsets the separation is 0 ± 113 Hz. **The centroid ordering
is NOT a property of the corpus.** Both items previously owed are discharged.

### ⚠⚠ BUT: the stored stream is REPACKED, not session recordings

`C:\tmp\stretch_stats.py`. Sorting by `pos` and cutting at the 300-tick gaps:

```
60,929 stretches over 108,779 phone runs = 1.8 runs each
53.1% are a SINGLE phone run; 29.0% are two; the longest in the whole voice is 16
stretch duration: median 144 ms, mean 211 ms
```

and even the longest read as gibberish:

```
septYne.iOeun.Ez     t.l$I.LmtvY.$     ndn^i$dnz.imr     ngrk$.ztRr.r.
```

against the Speechify VIN, where recordings run **median 10, mean 12.9, max 79**
phone runs and yield readable words (`greater`, `trade`, `Belgrade`).

So consecutive units in `pos` order are **not** consecutive in speech. Each
unit's audio at `pos` is genuinely the phone its label says — that is proven at
11.9 sd — but the inventory is stored repacked, so
`pos[k] == pos[k-1] + len[k-1]` means "adjacent in the packed stream", NOT
"adjacent when Tom said them".

⚠ **Consequence for the radar question.** `ss_inventory.py` runs and reports
`r J d a r`: 0 contiguous instances, 2 pieces at best, 2-grams `r-J:52 J-d:94
d-a:26 a-r:1`. **Those numbers must NOT be set beside `inventory.py`'s**, which
answers the recording-level question. The parallel is superficial and the
comparison would be wrong. Recovering original-recording adjacency needs
whatever maps the packed stream back to takes — not yet found; sections A–G and
the unexplored 22.7 MB are where it would live.

The tiling is real; **what it tiles is not identified.** Two tests say the
`pos` axis is not the recorded timeline:

- unit-level chaining `+10(k) == +9(k+1)` in `pos` order: **4.0%** (raw array
  order 3.7%, chance ~3%)
- collapsing to phone runs (108,779 runs, mean 2.98 units, cut at the 300-gaps)
  and testing `run[i].+10 == run[i+1].+9`: **1.2%**, i.e. *below* chance. Left
  context `+4..+8` likewise 0.1–1.7%.

And the phone string of the first 120 runs reads
`# # n n # n J # z # z # z J # Y # \x91 # # e # $ # # v i J …` — not speech.

⚠ The span is 146,577,085. If that were samples at 22,050 Hz it is **1.85 h**,
against a corpus the decoder puts at 1,010,009 frames x 320 = 323,202,880
samples = 4.07 h. Ratio 2.205, not a clean factor. Either the quantum is not
samples, or the older frame count is wrong, or `pos` indexes a repacked stream
rather than the recordings. **Do not assume samples.**

So the state is: we have a per-unit `(pos, len)` that provably tiles a
146.6 M-unit space with 300-wide guard bands at 60,924 boundaries — and no
demonstrated mapping from that space to recordings. That mapping is the
remaining gap.

### The 22.7 MB nobody has looked at

`FUN_10007280`'s last pointer is `body + 0x845e80`, and the per-unit records do
not start until `body + 0x1e002e0`. Between them lie **22,783,584 bytes** that
nothing else points at. The last declared count, `s+0xfc = 0x2b748c =
2,847,884`, divides that span at **8.0002 bytes per entry** — so H is very
likely a 2,847,884 x 8 table, 8.8 entries per unit. **It is the largest
unexplained region in the file and the most likely home for position data.**
Next place to look.

### Next Ghidra step

Find the reader of the section-struct fields `obj+0x1c+0xd0 … +0x100`.
`FUN_10007060` reads `obj+0x10` as a u32 index array and `obj+0x28` as the
16-byte-record base, so the consumers of the ascending tables are nearby. The
`vf_*` entry points (see §8) now need manual definition: `G` to the address,
`D` to disassemble, `F` to create the function — or Auto Analyze with
**Aggressive Instruction Finder** on.

---

## 6b. The hunt for a TAKE ID — a calibrated negative

**Added 2026-08-10 (second pass).** Speechify's VIN carries `file_idx`, a
recording id, and that one field is what lets `inventory.py` ask "was this said
as one continuous stretch". Everything blocking the same question here reduces
to: does the ScanSoft table carry an equivalent? **Measured over every per-unit
field: no.**

`C:\tmp\ss_takeid.py`. The statistic is `P(field equal)` over pairs the engine
itself calls contiguous (`pos[k] == pos[k-1] + len[k-1]`), read against
`P(field equal)` over random pairs, as

```
lift = (P_adj - P_rand) / (1 - P_rand)
```

⚠ The lift means nothing without knowing what a REAL take id scores, so it is
first measured on Speechify's VIN through the identical code path:

| calibration (tom.vin, 169,576 units, 6,849 recordings) | P_adj | P_rand | lift | distinct |
|---|---:|---:|---:|---:|
| **CEILING** `file_idx` — a real recording id | 1.0000 | 0.00018 | **1.000** | 6,849 |
| **FLOOR** `phone` — a real field that is not one | 0.4974 | 0.03236 | 0.481 | 46 |
| **NULL** `file_idx` shuffled across units | 0.0003 | 0.00021 | 0.000 | 6,849 |

Against that scale, ScanSoft's best per-unit fields:

| field | P_adj | P_rand | lift | distinct | P_gap |
|---|---:|---:|---:|---:|---:|
| 8B byte +7 | 0.9540 | 0.48585 | 0.910 | 5 | 0.6626 |
| 16B byte +8 | 0.9892 | 0.88765 | 0.904 | 41 | 0.9297 |
| 16B byte +9 (the phone) | 0.8183 | 0.04528 | 0.810 | 46 | 0.2402 |
| 16B u32 lane 2 | 0.1849 | 0.00005 | 0.185 | 64,759 | 0.0061 |
| section G | 0.0078 | 0.00122 | 0.007 | 219,923 | 0.0163 |
| `pos >> 20` | 0.9996 | 0.00741 | 1.000 | 140 | 0.9993 |

**Every high lift is bought with low entropy.** 8B +7 has five values and 16B
+8 agrees 88.8% of the time between *random* units — `P_rand` is the column
that exposes them, which is why the raw agreement is never read alone.
`pos >> 20` reaches the ceiling's lift and is disqualified by the fourth
column: `P_gap` 0.9993 says it agrees just as well across a boundary the engine
does **not** call contiguous, so it is tracking storage locality, not takes.

The only field with the right *shape* is **16B u32 lane 2** — `P_rand` 0.00005,
64,759 distinct, and `P_gap` 0.0061 far below its `P_adj` 0.185. But 0.185 is
nowhere near 1.000, so it is not a take id; whatever it is, chunk-mates share
it only 18% of the time.

**Consequence.** Recording-level contiguity is not recoverable from
`us_tom_full.dat`'s per-unit tables. This is a measured absence with a ceiling
beside it, not a "not found yet".

---

## 6c. Sections D/E/F, G and H — the owed re-runs

`C:\tmp\ss_sech.py`, `ss_gh.py`, `ss_h_pairs.py`, `ss_dead.py`, `ss_dead2.py`.

### D/E/F — the VOID arm, redone body-relative and CONFIRMED

38,105 keys ascending 1..2,247,959; offsets ascending 0..856,298; group sizes
1..10,263, mean 22.48, **none negative**; **0 sentinels; 0 of 856,494 postings
outside unit range**, max 324,262. Same shape as A/B/C, a second key→postings
index. **36,355 keys (95.4% of A's) occur in both A and D.**

⚠ Do not quote "the group sizes sum to |F|" — see §7.9, it cannot fail.

### Extents, now exact

| sec | body off | span | reading | leftover |
|---|---|---:|---|---:|
| G | 0x7093e4 | 1,297,052 | **324,263 x u32, one per unit** | 0 |
| H | 0x845e80 | 22,783,072 | **2,847,884 x 8 B** | **0** |

H runs exactly up to the per-unit records at `body+0x1e002e0` with nothing left
over, which closes the pairing of the count at `s+0xfc` with the pointer at
`s+0x100`. The earlier "8.0002 bytes/entry" was arithmetic slack in the note,
not in the file: it is 8.0000.

### H's lanes

```
lane0   a UNIT ID: non-sentinel range 2..324,262, 318,336 distinct
        or 0xFFFFFFFF on 733,986 rows (25.8%), mean 3.88 rows between sentinels
lane1   0..1,141,439, 205,402 distinct -- NOT a unit id (0.3% exceed n_units)
```

Neither lane is grouped: lane0 runs of equal value average 1.28 rows, lane1
1.31. lane0 has 1,118,716 ascending steps against 1,103,371 descending, so it
is not a sorted list either.

### ✔ EXACT: G and H exclude the SAME 5,927 units

```
G entries equal to 0xFFFFFFFF                     5,927
units never referenced by H lane0                 5,927
intersection                                      5,927     (108 expected by chance)
```

A set identity over 324,263 elements — it is exact or it is nothing. Also,
**every one of G's 318,336 live values is < |H| = 2,847,884**, so G's range sits
inside H's index space.

What those 5,927 units are: **99.4% are the FIRST unit of a chunk** against an
18.8% base rate, and 39.7% are also the last (i.e. many are one-unit chunks).
Their phone distribution and their lengths (median 355 vs 351 ticks) match the
corpus, and they are scattered across the whole `pos` span — 233 of 5,926 steps
consecutive. ⚠ The rule is **not** "8B byte +3 == 0": that holds for only 55.2%
of them and selects 125,764 units overall.

### ✘ G is NOT an offset table into H

The range fits, but an offset table must ascend in the order the postings were
written, and G does not ascend in any order — 141,853 inversions in uid order,
173,092 in `pos` order, against **159,069 for a random shuffle of G**. It loses
to its own control.

### ✘ H is NOT an adjacency table

Of the 263,334 pairs the engine itself calls contiguous, **7 occur in H
(0.0027%)**, against **4 (0.0015%)** for the same number of random pairs, on a
table whose density in the full pair space is **0.0020%**. The arm is at the
null in both lane orders. Whatever H lists, it is not "which unit follows
which".

---

## 6d. ⚠ The repack question — tested, INCONCLUSIVE, and why

An attempt was made to overturn §6's "the stored stream is REPACKED" using the
audio, on the competing reading that the 300-tick gaps are unlabelled HOLES in
a continuous recording. **It does not settle anything, and the reason is worth
more than the result.**

What was measured, and these numbers stand on their own:

| | result |
|---|---|
| gap content (`C:\tmp\ss_gap_audio.py`) | RMS 2846 against a `#`-unit floor of 1792 and a vowel ceiling of 3293 — **70% of the way to speech, and 0% digitally silent** |
| gap vs its neighbours | below both on only 25.2% of boundaries (padding would be ~100%) |
| waveform continuity (`ss_seam.py`, LPC-16 residual) | boundaries sit at **3%** of the way to a hand-cut splice, positive control +16.01 dB, d = +1.27 |
| pitch continuity (`ss_f0cont.py`) | across a gap Δ F0 19.44 Hz vs 18.45 within and 36.53 shuffled — **5.4%** of the way to unrelated |

**Why none of it decides the question.** Both continuity tests used 0-gap unit
boundaries as the "same take" FLOOR. In an inventory that is cut up at every
unit — which is what this is, exactly as Speechify's VDB is — those boundaries
are themselves joins. **The floor is the same kind of object as the arm, so it
bounds nothing**, and "REAL looks like LOW" reduces to "adjacent-in-storage
units resemble each other more than random ones", which was never in doubt.

A second, independent confound: the material is ACELP. A concatenation made in
the CODED domain is smoothed on the way out by the decoder's LP filter state,
LSP interpolation and adaptive-codebook memory, whereas the positive control
was cut in the decoded waveform. The control is harsher than the hypothesis,
so it proves the instrument works on a splice it would never have to find.

**§6's repack reading therefore stands.** To move it, the positive control must
be a coded-domain join built with `/Documents/ssrs_re/codsb/`, and the floor must be
a stretch known to be one take — which needs the take id §6b just showed is not
in the file.

Two by-products worth keeping:

- corpus F0, voiced windows, n = 10,225: **median 119.8 Hz**, mean 121.9,
  IQR 98.4–142.3 — a male voice, consistent with Tom.
- the 30 ms guard bands are **not silence**. Whatever the packer put between
  chunks, it is speech-level audio.

---

## 6e. THE PRESELECT — A/B/C and D/E/F fully decoded

**Read out of `FUN_10015e50` (NextUp `vf_tom_full.dll`), the function that
returns the candidate list.** This supersedes §6's "A/B/C is a key→postings
index of unknown key".

```c
if (target_half == 'l') { keys=A(+0xd4) n=+0xd0 offs=B(+0xd8) post=C(+0xe0) npost=+0xdc }
else                    { keys=D(+0xe8) n=+0xe4 offs=E(+0xec) post=F(+0xf4) npost=+0xf0 }

code(p) = byte(p) - 0x23        /* 0x23 = '#', so silence is 0 */
none    = 0x82 = 130            /* radix is 0x83 = 131        */
key     = (left * 0x83 + own) * 0x83 + right

i = binary_search(keys, key)                   /* FUN_10015e10 */
group = post[ offs[i] .. offs[i+1] )           /* last group runs to npost */
```

**A/B/C is the LEFT half-phone preselect, D/E/F the RIGHT.** Same role as
Speechify's PRSL. Three levels, in order: exact triphone; then a one-sided
backoff (`'l'` drops the RIGHT context, `'r'` drops the LEFT); then
context-free, `own*0x83 + 0x220b14`, which is `(130,own,130)` — verified, since
`130*131*131 + 130 = 2,231,060 = 0x220b14`.

The contexts come from `FUN_10004820`:

```c
i = slot / 2;                              /* slot runs 2 per phone */
ctx[0x14] = phonestring[i-1];              /* left,  0 at the edge  */
ctx[0x15] = phonestring[i+1];              /* right, 0 at the edge  */
```

### ✔ This explains the 2,247,959 constant

`(130*131 + 129)*131 + 130 = 2,247,959` — the largest representable key. It is
the observed max in NextUp's A, in NextUp's D, **and in RS4's tables over a
completely different corpus**, because it is a property of the ENCODING. §3's
"⚠ Unexplained: A and D both max at 2,247,959, do not build on it" is
**resolved**. And 129 + 0x23 = 164 = `0xa4`, exactly the top of the class map
(§5) — the two facts agree.

### ✔ Units are HALF-PHONES

`FUN_10007b00` builds the 13-byte target descriptor with
`param_2[1] = (slot & 1) ? 'r' : 'l'` and `slot/2` as the phone index, and
`FUN_10004610` runs the Viterbi over `2*n_phones - 1` slots.

### ✔ RESOLVED (live, §6j): the MIDDLE digit is the unit's own phone

`(left * 131 + own) * 131 + right` — `own` is the middle digit, confirmed
**68/68 slots over six words** by reading the engine's own key out of A/D at
run time (§6j). The static attempt below is superseded; it is kept because it
records why a 29.6% agreement was not enough to conclude anything.

### ⚠ SUPERSEDED (static attempt): which key digit is the unit's own phone

Not settled, and no candidate count may be quoted until it is. Per POSTING
(not per group modal — that statistic is capped by group purity and was
misleading):

| arm | digit | vs +9 | vs +10 | vs +4 | shuffle |
|---|---|---:|---:|---:|---:|
| A/B/C | high | **29.6%** | 2.2% | 13.2% | 2.6% |
| A/B/C | mid | 2.1% | 2.6% | **24.3%** | 2.7% |
| D/E/F | low | 2.3% | **28.4%** | 0.7% | 2.6% |
| D/E/F | mid | 2.6% | 2.1% | **26.3%** | 2.7% |

Real signal (10x chance) but far from identification. Part of the ceiling is
explained: **the preselect is substitution-tolerant by design** — `FUN_100073a0`
prices `+9`/`+10` mismatches through `PTR_DAT_100b6ba0`/`PTR_DAT_100b72d0`, so
a group is deliberately NOT phone-pure (modal share 0.60 in A, 0.45 in D).
That caps the achievable agreement well below 100%, but not as low as 30%.

⚠ `+9` as the unit's own phone still stands on the audio (§6, fricative/vowel
separation at 11.9 sd). What is unresolved is the mapping from key digits to
record lanes, not the acoustic identity of `+9`.

---

## 6f. G AND H — the precomputed JOIN COST table

**Read out of `FUN_10007f20`, the join cost.** Its `param_4`/`param_5` are
`obj[0x45]`/`obj[0x47]` = `obj+0x114` / `obj+0x11c` = **`obj+0x1c+0xf8` (G)**
and **`obj+0x1c+0x100` (H)**.

```c
if (!naturally_contiguous) {                 /* the `!bVar3` branch ONLY */
    disp = G[right_unit];                    /* 0xFFFFFFFF = no row     */
    row  = H + (left_unit + disp) * 8;
    if (disp == -1 || row[0] != right_unit)  cost += 10000000;  /* miss */
    else                                     cost += row[1];    /* hit  */
}
```

That is **row displacement**: a sparse `n_units x n_units` matrix packed into
one array, G giving each row's offset and `lane0` kept as a tag so a collision
is detectable. Verified against the file (`C:\tmp\ss_joincost.py`), three
predictions, each able to fail:

```
1  G.max() + n_units == |H|      2,523,621 + 324,263 = 2,847,884 = |H|   EXACT
2  l = i - G[tag] in [0, n)      2,113,898 / 2,113,898 = 100.0000%
     null, random tags                                    14.75%
     tags with no G row                                        0
3  tagged rows == non-sentinel   2,113,898 tagged, 733,986 unused slots
```

Occupancy: 318,336 units have a row; 1..1,415 partners each, median 3, mean
6.64; array fill 74.2%. Stored costs 0..1,141,439 — **none reach the 10,000,000
miss penalty**, which is the consistency a cost table must have.

**This retro-explains two earlier measurements:**

- G's 5,927 sentinels being exactly the units H never tags (§6c) is an
  identity, not a coincidence: a unit with no row can never appear as a tag.
- H containing only 7 of 263,334 engine-contiguous pairs is **what the code
  says must happen** — the lookup sits inside `if (!bVar3)`, so contiguous
  pairs take the fast path and are deliberately absent.

### The DP's own contiguity rule differs from `FUN_10007060`'s

`FUN_10004900`:

```c
d = (len_prev - pos_cur) + pos_prev;      /* pos_prev + len_prev - pos_cur */
if (bit31_flag != 0 || |d| > 3)  node[0xf] = 0;   /* clear natural-join */
```

**A ±3 tick tolerance**, not exact equality, and bit 31 of `pos` vetoes the
join outright. `FUN_10005060` then merges units whose mark survived into one
segment (`FUN_10004db0` extends, `FUN_10004e60` starts new) — the natural-join
fast path.

Record bytes `+13`/`+14` are copied into the synthesis node twice each by
`FUN_10004af0` and compared **by difference** in `FUN_10007f20` through a
100-entry table `DAT_100b75b0[delta + 0x32]`, clamped. Join-cost material —
F0 or energy at the unit edges. You do not compare an id by difference.

---

## 6g. RS4 Tom — the second pack, opened

`vf_tom_full.dll` from `ScanSoft\RealSpeakSolov4`, base 0x10000000. Same
architecture, different constants. Probes `C:\tmp\rs4_sections.py`,
`rs4_units.py`.

### Section directory — `FUN_1000a730`, struct at `obj+0x2c`

```
s+0x8c0 = 0x4af1  (19185)    s+0x8c4 = body+0x000000   A  keys   half 'l'
                             s+0x8c8 = body+0x012bc4   B  offsets
s+0x8cc = 0xd3a84 (866948)   s+0x8d0 = body+0x025788   C  postings
s+0x8d4 = 0x4b64  (19300)    s+0x8d8 = body+0x374198   D  keys   half 'r'
                             s+0x8dc = body+0x386f28   E  offsets
s+0x8e0 = 0xd4e6f (872047)   s+0x8e4 = body+0x399cb8   F  postings
```

**TEN stores against NextUp's thirteen. The three missing are exactly the G
pointer, the H count and the H pointer — RS4 Tom ships NO precomputed join-cost
table.**

Validated: all six spans are exactly `count x 4`; keys ascend, min 165, **max
2,247,959** decoding to a=130 b=129 c=130 — the same key encoding on a
different corpus; offsets ascend and stay in range; no negative group sizes; no
sentinels. **F ends at exactly `body+0x6ed674`, which is the address
`FUN_100124f0` reads `n_units` from** — the directory tiles the file with zero
gap, which is an independent confirmation nobody designed in.

### Unit tables — `FUN_100124f0`

```c
n_units = *(u32*)(body + 0x6ed674);            /* = 420,109 */
p[5]    = body + 0x6ed678;                     /* 10-byte records */
p[4]    = p[5] + ((n_units*10 + 3) & ~3);      /* 20-byte records */
return    p[4] + n_units*0x14;                 /* model tables follow */
```

420,109 matches the preselect's implied minimum exactly (postings max 420,108).
Layout fits with 358,116 B left for the ~350 sub-tables `FUN_10008990`
declares with `u16` sizes.

`pos` = `u32[0] & 0x7fffffff` of the wide record: **420,109 distinct of
420,109**, bit31 set on **exactly 1** unit — the identical signature to NextUp.
Span 179,198,204 ticks = **4.98 h** at 100 µs; median sorted gap 380 against
NextUp's mean `len` of 395.66.

| | NextUp 2004 | RS4 2006 |
|---|---:|---:|
| units | 324,263 | **420,109** |
| corpus | 4.07 h | **4.98 h** |
| `useld` | 39.2 MB | **20.2 MB** |
| preselect keys l / r | 38,101 / 38,105 | 19,185 / 19,300 |
| per-unit records | 8 + 16 B | **10 + 20 B** |
| phone-context lanes | 7 | **12**, 7-bit dense codes |
| join-cost table | 22.8 MB (**58% of the file**) | **none** |

RS4 Tom is a **30% larger inventory in half the file**, because 2006 dropped
the join-cost matrix and spent the space on units and a wider context window.

⚠ **Scope on the `encrypt` marker.** RS4's `useld` header variant reads
`full    encrypt`, and the file **is plaintext on disk** — every invariant above
was measured on raw bytes. `"encrypt"` is a brokerstring component assembled in
`FUN_10003410` (`langcode/voice/reduction/coder[/overheadframes]`), there is
exactly one `brk_DataMap` call site (`FUN_100032e0`), and nothing transforms the
mapping. **That is a statement about this file, not about the pack.** What the
marker gates is NOT established. Triage (`C:\tmp\rs4_triage.py`) found no DLL in
either pack importing the Windows CryptoAPI, and `comrsrc.dll` as the only
component carrying an `encrypt` signal beyond the brokerstring token
(`encrypt x2`, `licens x14`, both packs) — unexamined.

⚠ My own arithmetic error, caught by the file: `0xd4e6f` is **872,047**, not
871,535. The wrong value produced an out-of-range offset and one negative group
size in D/E/F, which is exactly what those checks are for.

---

## 6h. NO PER-UNIT RECORDING ID — in either pack, properly measured

Tool: **`rec_scan.py`** (in this folder, durable). Supersedes the take-id sweep
in §6b, whose statistic was wrong.

⚠ **Why §6b was the wrong instrument.** It scored "is this field equal along
storage runs", which can only find a take id if storage order tracks take
order — the very thing in dispute. In a repacked inventory a real recording id
scores at chance under it and gets thrown away.

**The statistic here is layout-independent.** A recording is a continuous span
of the corpus, so its units must occupy a compact range in TIME however the
file stores them:

```
rank        = index of a unit when all units are sorted by pos
per group:    span = max(rank) - min(rank) + 1
compactness = size / span          1.0 = perfectly contiguous in time
```

size-weighted over groups of 3+. Swept over **every 1..4 byte window at every
byte offset, unaligned included** — a 16-bit id at an odd offset is invisible
to a byte-lane sweep, which is how a first pass could miss one.

**Calibration on Speechify's VIN, same code path:**

| field | distinct | groups | med size | compact | shuffled | lift |
|---|---:|---:|---:|---:|---:|---:|
| **`file_idx`** — a real recording id | 6,849 | 6,745 | 20 | **1.0000** | 0.0002 | **+0.9998** |
| `phone` | 46 | 46 | 3,287 | 0.0329 | 0.0328 | +0.0000 |
| `dur_like` | 256 | 223 | 78 | 0.0181 | 0.0181 | +0.0000 |
| `local_pos` | 4,162 | 3,242 | 31 | 0.0019 | 0.0019 | +0.0000 |

A true recording id scores **1.0**. Everything else lifts **+0.0000**.

**Results:**

| voice | positive control | best genuine field | lift |
|---|---:|---|---:|
| NextUp Tom, 8-byte rec | — | `+4 w4` | +0.0003 |
| NextUp Tom, 16-byte rec | **1.0000** | `+7 w4` | **+0.0578** |
| RS4 Tom, 10-byte rec | — | `+5 w4` | +0.0005 |
| RS4 Tom, 20-byte rec | **1.0000** | `+7 w3` | **+0.0000** |

⚠ **The positive control is a field that CANNOT fail, and it is used as one on
purpose.** Windows overlapping `pos` itself (bytes 0..3 of the wide record) are
monotone functions of the sort key — `pos >> 16` cuts the timeline into blocks
and a block is contiguous because that is what a block is. The first run of the
tool duly reported `+2 w2` at compactness 1.0000 as a *find*; it is `pos>>16`.
They are now split out and reported as the positive control, which is their
honest use: they prove the statistic reaches 1.0 **on this data**, so a flat
result elsewhere is a real absence rather than a dead instrument.

**Conclusion: neither pack carries a per-unit recording id.** And the design
reason is now visible rather than mysterious — `FUN_10007f20` only ever asks
"is B a natural continuation of A", answered by `|pos_prev + len_prev -
pos_cur| <= 3` with a bit-31 veto, everything else precomputed into H. The
engine never needs to know which take a unit came from, so provenance was
consumed at build time. **Recording membership is encoded STRUCTURALLY** — pos
contiguity, the 300-tick guards, the bit-31 flag — not as an id.

### ✔ And the remaining regions are now accounted for too

`C:\tmp\codsb_toc.py`, `codsb_tail.py`. The three places left after the
per-unit sweep, all closed:

**The `codsb` TOC.** `toc_len = 0xa0d8`, so there IS a 41,032 B region between
the fixed header and the body — the `useld` has none (`toc_len == hdr_len`).
But it is **byte-identical between the two packs, 41,032 / 41,032 = 100.00%**.
Per-voice data over two different corpora cannot be identical, so it is codec
tables, consistent with `synth_155mrf22.dll` itself being byte-identical.

**The `codsb` body is pure frames.** NextUp: 49,490,441 B = **exactly**
1,010,009 x 49 B, remainder 0, and 1,010,009 is the frame count derived years
earlier by an independent route. RS4: 60,504,808 B = **exactly** 1,234,792 x
49 B, and 1,234,792 x 320 / 22050 = 17,919.88 s against RS4's `pos` span of
179,198,204 ticks = 17,919.82 s — **3 ppm**, the same confirmation NextUp gave.
No trailing table in either.

**The `useld` tails.**

| | tail after the record tables |
|---|---|
| NextUp | **0 bytes** — the records end at `body+0x256c8a4`, which is the end of the file body exactly |
| RS4 | 358,116 B — the model tables, whose directory in `FUN_10008990` runs to offset **0x57350 = 357,712**, i.e. this region and nothing else |

**So every byte of both `useld` files and both `codsb` files is placed, and
none of it is a recording map.** The RS4 leftover reads as 89,529 u32 with a
max of 3,379,337,501 and only 17.1% below `n_units` — model coefficients, not
indices, exactly as its own directory says.

⚠ Not checked: `tom.dat` (0 bytes in NextUp, unchecked in RS4) and the `.hdr`
files, neither of which is large enough to hold a per-recording map for
324k-420k units.

---

## 6i. PROSODY — ScanSoft and RealSpeak side with S3, not S4

Tool: **`prosody_gap.py`** (this folder, durable).

The question: is RealSpeak Solo v4 prosodically closer to Speechify 3 or to
Speechify 4? Tested on the one axis where S3 and S4 are known to differ
mechanically — **S3 inserts ZERO inter-word silence** (real-engine oracle via
`spfy_dumpwav`: one 28 ms leading silence, nothing between words) while **S4
inserts a gap at every word boundary** (eight at 22–24 ms in one utterance,
converged on independently by a 96-chunk CMVN-MFCC/DTW sweep, 22 ms p=3.1e-07).

All three engines render locally — no transmitter, no codec, no off-air
material anywhere in the comparison. Carrier phrases contain **no stops or
affricates at all**, so every word boundary joins two sonorants and there is no
phonetic closure that could masquerade as an inserted gap. Every render is
resampled to 8 kHz before analysis and the silence threshold is set relative to
each file's own speech level, so no arm passes through a gentler process.

**VALIDATE-DETECTOR** — comma/period phrases, which must show silence:

| engine | runs/phrase | total ms | longest |
|---|---:|---:|---:|
| spfy | 6.0 | 536 | 343 |
| scansoft | 3.0 | 1032 | 726 |
| realspeak | 3.0 | 790 | 421 |

**THE TEST** — sonorant-only phrases, where any internal silence is inserted:

| engine | gaps/phrase | **per boundary** | total ms | median ms |
|---|---:|---:|---:|---:|
| spfy (byte-exact S3) | 0.50 | **0.10** | 5.4 | 9.5 |
| **ScanSoft 2004** | 0.00 | **0.00** | **0.0** | — |
| **RealSpeak 2006** | 0.00 | **0.00** | **0.0** | — |

**VALIDATE-BASELINE**: spfy 0.10 gaps/boundary, the four durations being
9, 9, 10, 15 ms against an 8 ms detector floor — i.e. at the floor, and against
an S4 prediction for that column of **~1.00 at 20–30 ms each**.

**ScanSoft and RealSpeak insert no inter-word silence at all — cleaner than our
own S3 engine.** On this discriminator they are S3-like, and the "S4 is a
ScanSoft/RealSpeak-lineage engine" hypothesis makes the opposite prediction.

### ⚠ And a consequence for the S4 work, which matters more

Three engines of the era — SpeechWorks 2003, ScanSoft 2004, RealSpeak Solo v4
2006 — all insert **zero**. That makes S4's per-boundary gap anomalous for the
whole generation, not a normal design choice one lineage made. Which raises a
question the repo has not asked: **are those gaps the ENGINE, or the CRS /
broadcast assembly downstream of it?** A message assembler that concatenates
word- or phrase-level audio would produce exactly this signature, and the
repo's "strongest engine-level difference" rests on it.

### ✔ DONE — and the per-boundary claim does not survive

Two probes, `direct_gap.py` then `boundary_gap.py`.

**Step 1 — the broadcast chain is NOT the source.** Silence runs of exactly the
claimed duration are present in the direct NOAA downloads, which never passed a
transmitter: 130 runs in the 15–35 ms band over 247 s of speech, **median
23.0 ms**, 0.53/s. So the gaps are upstream of the broadcast chain. ⚠ That rate
is ~5x below what "one per word boundary" predicts (~2.5/s), and the arms used
unmatched text, so it could not test the claim as stated.

**Step 2 — matched text, matched ruler, and a control that decides it.** Every
arm speaks `NWS_Warning.vip.txt` (the IEM text that was the engine's actual
input), goes through the same mp3 chain, and is aligned by the same forced
aligner.

⚠ **The aligner cannot point at a boundary.** `fa_align.py --selftest` against
our engine's exact marks: median error **64.8 ms** = a systematic **+64.2 ms**
offset with **15.6 ms** scatter (p90 38.5). Subtracting the offset still leaves
scatter the size of the effect. So the test never asks "is there silence AT the
boundary"; it asks whether a 15–35 ms run occurs anywhere within ±60 ms, and
prices that against the identical search at WORD CENTRES.

| arm | boundaries | at boundary | mid-word null | lift |
|---|---:|---:|---:|---:|
| **S4 direct (NOAA)** | 141 | **7.8%** | 2.8% | +5.0% |
| spfy → same chain | 141 | 1.4% | 3.5% | −2.1% |
| scansoft → same chain | 141 | 2.8% | 5.0% | −2.1% |
| **realspeak → same chain** | 141 | **12.1%** | 9.2% | +2.8% |

**RealSpeak is the control that decides it.** §6i above proves it inserts
*exactly zero* inter-word silence, and it scores **12.1%** here — higher than
S4's 7.8%. So ~12% is what an engine inserting nothing looks like under this
search, the number is dominated by phonetics, and **S4 sits below a known-zero
engine.**

**Conclusion: "S4 inserts silence at every word boundary" is not supported.**
The observed rate is 7.8%, not ~100%, and it is beneath a control that inserts
none. What survives is weaker and worth keeping: 15–35 ms silences of median
23.0 ms do exist in direct S4 audio, they are upstream of the transmitter, and
S4 has the largest lift over its own within-word null (+5.0%) of any arm.

### ⚠⚠ THE CROSS-ARM ROW OF THAT TABLE IS CONFOUNDED — do not quote it

The word list came from `NWS_Warning.crs.words.json`, which is **Whisper-derived
and derived from the target audio itself** (`feedback_crs_text_layers`). Two
asymmetries follow, and neither was accounted for:

1. **Alignment quality is not equal across arms.** A wrong word list misplaces
   S4's boundaries, while our three arms were rendered *from that exact word
   string*, so their alignment is right by construction. The S4 arm was
   handicapped relative to its own controls.
2. **Our renders lost all phrase structure.** The words were joined with
   spaces, stripping the punctuation that CRS uses as phrase-break markup — so
   spfy/scansoft/realspeak spoke with no phrase breaks while S4's recording
   kept its own. That pushes the other way.

Audited on the one reference with verified engine-input text
(`NWS_Warning.vip.txt` vs the Whisper list): 148 vs 151 tokens, similarity
0.903, **~8.8% token error**, and all four discrepancies are the same class —
VIP `4:00 Ay em EST` against Whisper `am eastern standard time`. So the engine
was *given* `Ay em EST` and *said* something Whisper heard as the expansion.
**VIP is the right text to RENDER; the spoken form is the right list to ALIGN.**
They are different sequences, which is exactly why the arms did not compare.

**What survives is the WITHIN-ARM contrast**, where the same audio and the same
alignment serve both cells so a degraded transcript hurts them equally:

| arm | at boundary | mid-word | lift |
|---|---:|---:|---:|
| S4 direct | 7.8% | 2.8% | **+5.0%** |
| spfy | 1.4% | 3.5% | −2.1% |
| scansoft | 2.8% | 5.0% | −2.1% |
| realspeak | 12.1% | 9.2% | +2.8% |

S4 has the largest boundary-over-mid-word lift of any arm, and its absolute
boundary rate is nowhere near the ~100% "every boundary" predicts. That much is
robust. **The claim that S4 sits below RealSpeak is NOT** — that is the
cross-arm comparison, and it is confounded.

⚠ Scope. One reference file (141 boundaries), one window (±60 ms), one band
(15–35 ms), one global offset. `21_s3_vs_s4_findings.md` must not carry "a gap
at every word boundary", and must not yet carry the reverse either.

---

## 6j. THE LIVE ENGINE — Frida on the SAPI voice, and the `radar` answer

Everything above was read out of the FILE and the decompilation. This section is
read out of the engine while it is running, which is what finally moved the
`radar` question.

```
reveng/ss_rs/run_ss_frida.py            spawn the 32-bit host, inject, trace
reveng/ss_rs/frida_hooks/ss_usel_recon.js   argument reconnaissance
reveng/ss_rs/frida_hooks/ss_preselect.js    the candidate pool per slot
reveng/ss_rs/ss_trace_view.py               read a recon trace
reveng/ss_rs/ss_preselect_view.py           read a preselect trace
```

### Two things that had to be right before anything worked

* **The host must be spawned, not attached to.** `vf_tom_full.dll` is the whole
  selection engine and it lives for the length of one utterance —
  ~0.2 s under `SysWOW64\cscript.exe`. `frida.spawn` + inject + `resume`.
* **⚠ POLLING FOR THE MODULE IS TOO LATE.** The first run polled every 5 ms and
  missed `FUN_10003020`, `FUN_10007280` and `FUN_10007240` **completely** —
  SAPI maps the font and calls us_ObjOpen inside one window, so the section
  directory is already built by the time the module appears in the list. Hooking
  `LdrLoadDll` on leave (plus `Process.attachModuleObserver` where available)
  catches all three. Without them there is no body pointer and no trace pointer
  can be converted to a file offset.

The DLL relocates — observed at `0x8b60000`, `0x8200000`, `0x8070000` across
three runs. Every absolute address in this document is Ghidra's `0x10000000`
view and must be applied as an RVA.

### ✔ The static decode, confirmed against the running engine

`FUN_10007240`'s out-struct read live: `n_units = 0x4f2a7 = 324,263`, and
`p4 == p5 + n_units*8` **exactly**. `p2 - 0x1e002e4` gives the mapped body, and
with it every returned pointer becomes a file offset:

| slot | half | return − body | lands in |
|---|---|---|---|
| 1 | `'r'` | `0x3c4ec0` | **F**, which starts at `0x3c4dbc` |
| 2 | `'l'` | `0x04ad84` | **C**, which starts at `0x04a738` |

`'l'` → A/B/C and `'r'` → D/E/F, exactly as §6e read it out of the code.

### ✔ RESOLVED: the middle key digit is the unit's own phone

§6e could not settle this statically — best per-posting agreement 29.6% against
a 2.6% shuffle, "real signal but far from identification". The hook does not
have to infer it. The engine returns `&post[offs[i]]`; inverting that index
through the same B/E array yields `i`, and `A[i]`/`D[i]` **is the key the engine
used**. Comparing it to the descriptor's own phone byte:

| word | slots | mid == phone | high == phone | low == phone |
|---|---:|---:|---:|---:|
| radar | 12 | **12** | 1 | 1 |
| weather | 10 | **10** | 1 | 1 |
| tomorrow | 14 | **14** | 1 | 1 |
| doppler | 12 | **12** | 1 | 1 |
| zorquat | 16 | **16** | 1 | 1 |
| the | 6 | **6** | 1 | 1 |

**68/68.** The high and low columns score exactly 1 each per word — the
leading-silence slot, where the digit coincides for a degenerate reason. So the
test discriminates, and `(left*131 + own)*131 + right` is confirmed.

**The control that makes the counts quotable:** the posting index was found
EXACTLY in the offset array for **68/68** slots, and the engine's own candidate
count equalled the span computed from the index for **68/68**. Either could have
missed; `group = post[offs[i] .. offs[i+1])` held.

### The `radar` candidate pools — the numbers §6e forbade quoting

`radar` → `# r J d a r #`, 12 half-phone slots:

| slot | phone | half | key | triphone | candidates |
|---:|---|---|---:|---|---:|
| 1 | `#` | r | 79 | `# # r` | 34 |
| 2,3 | `r` | l,r | 10388 | `# r J` | 15, 16 |
| 4,5 | `J` | l,r | 1360893 | `r J d` | 111, 64 |
| 6,7 | `d` | l,r | 677856 | `J d a` | **10, 6** |
| 8,9 | `a` | l,r | 1123666 | `d a r` | 23, 22 |
| 10,11 | `r` | l,r | 1074331 | `a r #` | 25, 12 |
| 12 | `#` | l | 1355719 | `r # #` | 29 |

The pinch is `/d/` in `J_a`: **6 candidates on the right half.**

### ⚠ And the concatenation shape, with a nonsense-word control

`FUN_10004e60` starting a segment is a JOIN; `FUN_10004db0` extending one is a
natural continuation, i.e. the two half-phones were adjacent IN THE CORPUS:

| word | slots | continuations | rate |
|---|---:|---:|---:|
| weather | 10 | 7 | **78%** |
| tomorrow | 14 | 9 | **69%** |
| **zorquat** (invented) | 16 | 7 | 47% |
| **radar** | 12 | 5 | **45%** |
| **doppler** | 12 | 5 | **45%** |
| the | 6 | 1 | 20% |

`radar` and `doppler` sit **at the invented word's rate**, not at a real word's.
This corpus does not appear to hold either of them as recorded material.

⚠ **Scope, and it is narrow.** One render per word, n = 6 words, and this is
NextUp ScanSoft Tom 2004 — a general-purpose voice, NOT the CRS weather corpus.
`the` at 20% shows the statistic also moves with length, which is not controlled
here. Treat the rate as a screen, not a measurement, until it has a proper null.

### ✔ THE CHOSEN PATH — `FUN_10004610` decompiled 2026-08-11

```c
parent  = *(u32*)graph                       /* graph[0]            */
n_slots = (*(u16*)(parent + 2) << 1) - 1     /* 2*n_phones - 1      */
out     = *(u32*)(parent + 0x1c)
/* traceback writes out[1 .. n_slots-1]; out[0] and out[n_slots] are
   boundary values computed from graph[9]/graph[10], NOT selections. */
```

The array it traces back through is filled by `*param_1 = *piVar8` inside
`FUN_10004900` — **node[0] is the unit id**. Node layout, same function:

| off | field | evidence |
|---|---|---|
| +0x00 | unit id | `*param_1 = *piVar8`, copied to the traceback array |
| +0x04 | pos | the `(len_prev - pos_cur) + pos_prev` term |
| +0x0c | accumulated cost | `piVar8[3] = uVar5`, and the argmin reads it |
| +0x10 (u16) | len | the other term of the same expression |
| +0x34 | join-eligibility flag | gates the `FUN_10007f20` call |
| +0x3c | natural-join mark | `piVar8[0xf] = 0` on failure — §6f's field |
| +0x2c,+0x2d | phone, `'l'`/`'r'` | a copy of the target descriptor |

Node stride is **0x40**. `FUN_10004820` is called for slot 1 and then slots
2..n_slots-1, which is why a 13-slot utterance shows exactly **12** preselect
calls.

### ⭐ `radar`, the whole selection, with two controls that agree

```
slot  unit id  in pool   rec[0:3]      delta
   1     2721      yes    5036504
   2   229397      yes    8427375   +3390871
   3   237369      yes    8427676       +301   <- natural
   4    52522      yes    9704511   +1276835
   5    59168      yes     416037   -9288474
   6   113257      yes     416666       +629   <- natural
   7   118991      yes     416926       +260   <- natural
   8    96823      yes   10565296  +10148370
   9   100388      yes   10566244       +948   <- natural
  10   222683      yes    5301735   -5264509
  11   230275      yes     201204   -5100531
  12      215      yes     201743       +539   <- natural
```

* **CONTROL 1 — the chosen unit was in its own preselect group 12/12.** The
  path and the pools are read by different hooks from different memory; a
  mismatch was available and did not happen.
* **CONTROL 2 — the engine's own `seg_ext` count is 5, and the record
  positions give 5 small positive steps, at the same five slots.** Two
  independent routes to the same concatenation.

So `radar` is assembled from **7 fragments**, longest run 3 half-phones:

```
[# r] [r_l r_r] [J_l] [J_r d_l d_r] [a_l a_r] [r_l] [r_r # _l]
```

The only cross-phone natural join inside the word is `J -> d`. A word held in
the corpus as recorded material would show one segment spanning slots 2..11.
**This corpus does not contain `radar` as a contiguous recording.**

### ⚠ A field mapping from §4 that did NOT survive contact

§4 reads the 16-byte record's `+9` as "the unit's own phone — never 0, range
35..164". Against these 12 chosen units it does not hold: uid 229397 is the
`'r'` of `# r J` and its `+9` is `0x23` `'#'`, while `+4` is `0x72` `'r'`; but
uid 59168 (`'J'`, right half) has `+4 = 0` and `+9 = 0x69`. Neither lane is the
own phone consistently. The acoustic evidence for `+9` (§6, fricative/vowel
separation at 11.9 sd) is untouched — what is wrong is one of the lane
assignments, and it needs re-deriving. **Nothing here depends on it**: the key
read out of A/D gives the phone authoritatively.

### ⭐ CONTEXT DOES NOT RESCUE `radar` — a WITHIN-UTTERANCE control

The isolated-word result was fairly objected to: unit selection is globally
optimised, so `radar` inside a carrier phrase is a different search. Rendered
`"This is a radar indicated threat"` — 26 phones, 51 slots, 50 selections, and
the preselect control still 50/50 exact.

The phrase supplies its own control. Same engine, same voice, same render, same
DP; the only thing separating the two groups of slots is which word they are in.

| | transitions | natural | rate |
|---|---:|---:|---:|
| `radar` span (slots 14–23) **in the phrase** | 9 | 4 | **44.4%** |
| the REST of the same utterance | 42 | 30 | **71.4%** |
| `radar` **alone** (slots 2–11) | 9 | 4 | **44.4%** |

`radar` scores **identically in isolation and in context**, and sits 27 points
below the material surrounding it in the very same utterance. This is a much
better control than the six-word screen, because word length, render, engine
state and phrasing are all held fixed.

**And the objection was still half right, at the unit level.** The same
triphone key, different render:

| triphone | half | alone | in phrase | same unit? |
|---|---|---:|---:|---|
| `r J d` | l | 52522 | 54861 | no |
| `r J d` | r | 59168 | 58953 | no |
| **`J d a`** | l | **113257** | **113257** | **YES** |
| **`J d a`** | r | **118991** | **118991** | **YES** |
| `d a r` | l | 96823 | 94747 | no |
| `d a r` | r | 100388 | 98350 | no |

Global optimisation moves the choice everywhere it has room — but `J d a` has
only **10 and 6** candidates, and with a pool that tight the engine picks the
same units regardless of context. The pinch is not a statistical artefact of
one render.

### RS4 — groundwork done, two addresses still missing

`FUN_1000a730` decompiled: the same field ORDER as NextUp's `0xd0..0xf4`, based
at `obj+0x2c+0x8c0` = **`obj+0x8ec`**, and **A–F only, no G/H** — confirming
§6g's "no join-cost table".

| obj offset | field | value |
|---|---|---|
| +0x8ec | nA | 19,185 |
| +0x8f0 / +0x8f4 | A / B | body+0 / body+0x12bc4 |
| +0x8f8 / +0x8fc | nC / C | 866,948 / body+0x25788 |
| +0x900 / +0x904 | nD / D | 19,300 / body+0x374198 |
| +0x908 | E | body+0x386f28 |
| +0x90c / +0x910 | nF / F | 872,047 / body+0x399cb8 |

RS4 folds the voice and the graph into ONE 0x960-byte object
(`FUN_10004880`, allocated from `FUN_100036e0`):

```
obj+0x0c (u8)  max candidates      obj[4] unit-id array   n_slots*ncand*4
obj+0x0e (u16) max slots           obj[5] backpointers    n_slots*ncand  (BYTES)
obj+0x2c       section directory   obj[6] node buffer     ncand*0x90
obj+0x914      mapped body         obj+0x94c/0x950        handle / resource
```

⚠ **CORRECTION.** An earlier version of this section read `obj[6]`'s
`ncand * 0x90` allocation as a node stride of 0x90. It is not:
`FUN_10004bf0` splits that one block into TWO slot buffers,
`obj[7] = obj[6]` and `obj[8] = obj[6] + ncand*0x12` (0x12 ints = 0x48 bytes).
**RS4's node stride is 0x48**, NextUp's is 0x40. Backpointers are bytes here,
shorts there — so the NextUp hook cannot simply be re-pointed.

**The only export is `vf_GetInterface`**, returning a 6-slot vtable that is
**byte-identical in both packs** (`0x100012b0`, `0x100012c0`, `0x10001350`).
The thunks diverge at their call targets:

```
slot 4  0x10001350   NextUp -> 0x1000fba8      RS4 -> 0x10012ba8   (+0x3000)
slot 5  0x100012c0   NextUp -> 0x10010360, 0x100024b0, 0x10003550
                     RS4    -> 0x100132e0, 0x10002980, 0x10003820
```

⚠ **A signature scan for the base-131 arithmetic FAILED ITS OWN CONTROL** and
must not be revived: scoring 0x400 blocks by their use of the immediates 0x83 /
0x82 / 0x23 did not put NextUp's KNOWN preselect block (`0x10015c00`) anywhere
in the top 12, so its RS4 ranking meant nothing. `C:\tmp\rs4_find_preselect.py`
is kept only because it prints that control.

### ✔ RS4's PRESELECT IS `FUN_10018e00` — found by what it RETURNS

Ghidra could not cheaply name it, so the engine was made to name itself
(`frida_hooks/ss_find_preselect.js`). The preselect has a property nothing else
in the DLL has: it returns a pointer INTO the postings arrays, whose bounds
`FUN_1000a730` hands over. So: hook every function entry, watch return values,
and see which one lands in C or F.

Entry points come from `C:\tmp\rs4_funcs.py`, which takes them from `call
rel32` immediates — **a call target IS a function entry**, so nothing there can
put a hook mid-function. Its own control: 5/5 known NextUp functions found in
NextUp, 5/5 known RS4 functions found in RS4, and neither pack's addresses
found in the other.

**Validated on the pack where the answer was already known**, over the full
121-function list, three runs:

| pack | hits | RVA | calls | into C | into F |
|---|---|---|---|---|---|
| NextUp (control) | 1 | **0x15e50** — the known preselect | 12 | 6 | 6 |
| RS4 | 1 | **0x18e00** | 12 | 6 | 6 |

Six left halves and six right halves is exactly `radar`'s slot structure, and
in both packs the identification is unique.

⚠ The `+0x3000` shift suggested by the vtable thunks predicted 0x18e50. The
answer is **0x18e00**. The shift idea was close enough to look right and wrong
enough to be useless — do not resurrect it.

#### Three failures worth keeping, because each was silent

1. **Installing ~119 hooks from the module-load callback** runs the patching on
   the loader's thread mid-flight. The host hung ~57 s and produced no audio,
   twice.
2. **Deferring the install to a timer** fixed the hang and broke the timing:
   the module event arrived ~120–160 ms after load, selection had already run,
   and only the voice-OPEN hooks ever fired. 7/7 attached, 1 called.
3. **The driver's config REPLACED the agent's defaults**, leaving `sect_rva`
   undefined, so `mod.base.add(undefined)` threw "missing argument" before a
   single hook existed — with no module event to say so.

The fix is to install from the section-directory hook's `onLeave`: that point
is deterministic (the directory is built during voice-open, so selection has
provably not run) and it is not the loader's thread. A tick-based install is a
RACE — the same build found RS4's preselect and simultaneously missed NextUp's
known one.

### ⭐ `radar` IN BOTH CORPORA — same keys, different inventory

Both packs produce the SAME triphone keys for `radar`, so the front ends agree
on the phone string and the encoding is shared. What differs is what is behind
each key:

| triphone | key | NextUp 2004 l/r | RS4 2006 l/r |
|---|---:|---:|---:|
| `# r J` | 10388 | 15 / 16 | 18 / 19 |
| `r J d` | 1360893 | 111 / 64 | 101 / 82 |
| **`J d a`** | 677856 | **10 / 6** | **21 / 24** |
| `d a r` | 1123666 | 23 / 22 | 44 / 56 |
| `a r #` | 1074331 | 25 / 12 | 63 / 55 |

RS4 is 2–4x deeper at exactly the places NextUp is thinnest. The `J d a` pinch
that forced NextUp to pick the same two units regardless of context is much
looser in 2006 (10/6 → 21/24).

⚠ **RS4 reaches the CONTEXT-FREE backoff for the leading and trailing
silence** — key 2,231,060 = `(130, '#', 130)`, and **exactly one candidate**.
NextUp used specific keys there (79 = `# # r`, 1,355,719 = `r # #`) with 34 and
29 candidates. Same encoding, materially different silence handling.

Control on the RS4 run: posting index found exactly 12/12, engine's own count
equals the span 12/12, and the middle-digit test is **12/12 mid, 0/12 high,
0/12 low** — cleaner than NextUp's, because RS4's silence slots use the
context-free key and so cannot match degenerately.

### ✔ RS4's VITERBI IS `FUN_10004bf0` — found by CALL PROFILE

The return-value trick cannot reach it: the Viterbi returns a status, not a
pointer into the voice font. But its call profile is rigid and is anchored by
the preselect count the same run already gives (`ss_find_viterbi.py`):

```
n_slots  = 2 * n_phones - 1
preselect / context builder   n_slots - 1     per SLOT
DP step                       n_slots - 2     per TRANSITION
the Viterbi itself            1               per UTTERANCE
```

Render two texts of very different length (`radar` → 12 preselect calls,
`This is a radar indicated threat` → 50) and only the right functions track
both formulae. Then the caller settles it: the per-slot and per-transition
stages are called BY the Viterbi, so the return address recorded on their hooks
lies inside it.

⚠ **The discriminator is "drives ONE OF EACH KIND", not "calls two or more".**
The context builder calls three per-slot helpers and wins the weaker test while
driving no DP at all. With the correct rule the answer is unique in both packs.

| | NextUp (control) | RS4 |
|---|---|---|
| Viterbi | **0x04610** ✓ known | **0x04bf0** |
| context build, per slot | 0x04820 | 0x04e00 |
| DP step, per transition | 0x04900 | 0x04f10 |
| candidate scorer | 0x073a0 | 0x0a7b0 |
| preselect | 0x15e50 | 0x18e00 |
| segment merge | 0x05060 | 0x059e0 |

The whole selection pipeline maps across, stage for stage.

#### Confirmed by decompiling it, and it corrects the node layout

```c
obj[7] = obj[6];  obj[8] = obj[6] + ncand * 0x12;   /* two buffers, 0x48 each */
obj[4][i] = *(u32*)(obj[7] + 0x18 + i * 0x48);      /* unit id at node+0x18   */
cost      = *(u32*)(obj[7] + 0x14 + i * 0x48);      /* cost    at node+0x14   */
out       = *(u32*)(obj[1] + 0x1c);                 /* traceback target       */
n_phones  = *(u16*)(obj[1] + 2)
```

So RS4 differs from NextUp in three places and agrees everywhere else: node
stride 0x48 vs 0x40, unit id at node+0x18 vs node+0x00, parent at obj+4 vs
obj+0. `n_phones` at parent+2 and the output at parent+0x1c are identical.

### `radar` chosen path, RS4 2006

```
slot   1      2      3      4      5      6      7      8      9     10     11     12
uid    1 291714 302971  68479  69395 134863 147029 120102 124541 289486 300710      0
```

**CONTROL: the chosen unit was in its own preselect group 12/12** — path and
pools are read by different hooks from different memory.

Slots 1 and 12 select units 1 and 0: the single silence unit reached through
the context-free backoff. NextUp picked from 34 and 29 candidates there.

### ✔ THE RECORD'S POSITION LANE — cross-identified, and §4 corrected

`ss_lane.js` + `ss_lane_match.py`. At the DP step every node carries a unit id
at a known offset (NextUp node+0x00, RS4 node+0x18, both from the Viterbi's own
code), so each node pairs with its record. Dump both and find the (node offset,
record offset, width) that agrees across MANY DISTINCT units — a coincidence
does not survive eighty of them.

**NextUp, 80 distinct units:**

| width | node | record | distinct values |
|---:|---|---|---:|
| **4** | **+0x04** | **+0x00** | **80** |
| 2 | +0x12 | +0x0d | 32 |

* `node+0x04` is what `FUN_10004900`'s contiguity arithmetic reads as `pos`
  (§6f), so **the 16-byte record's `+0x00..+0x03` is a 32-bit position**.
* ⚠ **§4 IS WRONG ABOUT `+3`.** It reads `+0..+2` as position and `+3` as a
  "small enum, 10 values, 99.8% equal between adjacent uids". The match is
  **four bytes wide**: `+3` is the HIGH BYTE of the position. Ten values and
  near-equality between adjacent units is exactly what a top byte does. Correct
  §4 rather than working around it.
* The second row independently confirms §6f: record `+0x0d/+0x0e` (the
  "+13/+14" F0-or-energy pair) is copied into the node at +0x12.

**RS4, 60 distinct units: NO node field copies any record lane.** `n_units`
reads 420,109 live, so the body is right; either §6g's
`p4 = p5 + align4(n*10)` is off or RS4's node does not carry the record
verbatim. **Reported, not guessed.**

### ✔ CONTIGUITY WITHOUT THE RECORD — the segment pair, both packs

The record was never needed. Segment-start and segment-extend are called once
each per slot between them, so their counts SUM to `n_slots-1` while neither
alone tracks it — which is why the per-slot search misses them
(`ss_find_segments.py`).

⚠ Both members must SCALE with utterance length. Without that filter the
per-transition function pairs with every once-per-utterance function to make
the sum, and the output is nothing but that noise.

| pack | pair | caller | `radar` | phrase |
|---|---|---|---|---|
| NextUp (control) | **0x04e60 / 0x04db0** ✓ known | 0x05060 | 7 / 5 | 16 / 34 |
| RS4 | **0x05730 / 0x057f0** | 0x059e0 | 7 / 5 | 33 / 17 |

The control recovers the known pair exactly, with the known split.

### ✔ WHICH ONE IS "EXTEND" — settled, not inferred

Counts cannot say which member starts a segment and which extends one, and the
assignment is load-bearing: flip it and RS4's `radar` goes from 58.3% to 41.7%
and the 2004-vs-2006 difference vanishes.

⭐ **The first call must be a START.** There is no segment to extend at slot 1.
So `ss_segorder.js` records the ORDER the two functions fire in and reads the
answer off — no argument interpretation, no decompilation.

**Control, NextUp `radar`:**

```
slot: 123456789012
call: SSESSEESESSE
first call 0x04e60 -> START (7)     therefore 0x04db0 -> EXTEND (5)
EXTEND at slots [3, 6, 7, 9, 12]
natural joins from RECORD POSITIONS [3, 6, 7, 9, 12]     MATCH
```

The first-call rule recovers the known assignment, and the extend slots are
**the same five slots** derived earlier by the completely unrelated route of
differencing record positions. Two routes, one answer.

**RS4 `radar`:**

```
slot: 123456789012
call: SSEESESEEEES
first call 0x057f0 -> START (5)     therefore 0x05730 -> EXTEND (7)
EXTEND at slots [3, 4, 6, 8, 9, 10, 11]
```

**0x05730 is extend — the growth-rate and address-order hints were right**, and
this no longer rests on them.

#### The segment structure, ISOLATED WORD

```
NextUp  [1] [2,3] [4] [5,6,7] [8,9] [10] [11,12]     7 segments, longest 3
RS4     [1] [2,3,4] [5,6] [7,8,9,10,11] [12]         5 segments, longest 5
```

Slots 7–11 are `d_r a_l a_r r_l r_r`, so in isolation RS4 renders "-dar" as one
contiguous five-half-phone run where NextUp's longest is three.

### ⚠⚠ AND THAT DIFFERENCE DOES NOT SURVIVE THE CARRIER PHRASE

Run `This is a radar indicated threat` through both packs and locate the radar
span by TRIPHONE KEY (the keys are identical across packs, so the same lookup
works for either — `C:\tmp\span2.py`):

| | slots | overall | radar span | rest of utterance | longest run in radar |
|---|---:|---:|---:|---:|---:|
| NextUp 2004 | 50 | 68.0% | **44.4%** `ESSSESESE` | 75.0% | 2 |
| RS4 2006 | 50 | 66.0% | **44.4%** `EESSESSES` | 72.5% | 3 |

**Identical, 4/9 in both.** The 58.3% vs 41.7% gap measured on the isolated word
is an ISOLATION-ONLY effect, and the contiguous "-dar" run RS4 finds when the
word stands alone is not the path it takes inside a sentence (longest run there
is 3 half-phones, not 5). The global Viterbi re-optimises and the corpora
converge.

**Retract** any reading of the isolated-word numbers as a 2004-vs-2006
inventory difference in radar's favour. The deeper RS4 pools are real (they are
read off the engine), but they do not translate into more contiguous material
once the word has neighbours.

#### ⭐ WHAT DOES REPLICATE

The within-utterance contrast, and now across two independent corpora and two
different builds:

    radar span    44.4%      44.4%
    rest of it    75.0%      72.5%

`radar` runs ~30 points below the material surrounding it in the SAME
utterance, in BOTH packs. Everything is held fixed inside one render — engine,
voice, DP, phrasing — and the only thing separating the two groups of slots is
which word they belong to. That is the finding; the pack-to-pack comparison is
not.

On the settled assignment:

| | `radar` alone | the phrase |
|---|---|---|
| NextUp 2004 | 5/12 = **41.7%** continuations | 34/50 = 68% |
| RS4 2006 | 7/12 = **58.3%** continuations | 33/50 = 66% |

The two packs run the same contiguity over a whole sentence, but RS4 assembles
`radar` itself from noticeably more contiguous material — which is what the
candidate counts already implied: 2–4x deeper pools exactly where NextUp is
thinnest.

### Still open

* The contiguity rate has **one render per word** outside the phrase, and no
  permutation null. The within-utterance contrast above is the strongest
  version of it; a matched-length word set would make it a measurement.

---

## 6k. OFF-AIR VERBATIM MATCHING — the ceiling, measured

`ss_offair_ceiling.py`. Speechify 3.0.5 applies no signal modification, so a
reused unit is the SAME SAMPLES; "is `radar` contiguous in S4" becomes "do two
radar tokens share a long verbatim run". Radar exists ONLY off-air here — 0 of
138 verified Wayback texts mention it; its 400+ cues are all severe-weather
warnings in `D:\__crs` — so the method lives or dies on the off-air channel.

The engine is deterministic, so the same warning broadcast twice is the same
synthesised audio. `corpus.db` yields 1,360 texts repeating ACROSS files and
376 WITHIN one. Those are known-same-units pairs through the REAL channel, with
no simulation (the part that failed at 0.999 before).

### ⚠⚠ THE FIRST CEILING WAS AN IDENTITY — check this before quoting any pair

`KDO94_SVR(4)` vs `KDO94_SVR(5)` scored **1.000, 100% of windows ≥ 0.99**. It is
the SAME CAPTURE in two files: the cue starts at 7.02 s in both, and NCC is
1.000 at the file head and 20 s before the cue as well. A pair whose
SURROUNDINGS also match is one recording split in two, and it proves nothing.

**Always compare a region outside the cue.** Cue high + surroundings high =
identity. Cue high + surroundings low = two genuine broadcasts.

⚠⚠ **AND HASHING WOULD NOT HAVE CAUGHT IT.** The two KDO94 files have DIFFERENT
sizes (1,146,260 vs 1,151,425), different SHA-1s, and different decoded-PCM
SHA-1s — file (5) is 462 ms longer and re-encoded. They are one capture trimmed
two ways, and every hash says "different". Only the surroundings test finds
that. Use both: a hash catches exact copies cheaply, the surroundings test
catches trimmed or re-encoded ones.

Hashed the whole off-air corpus (`C:\tmp\hash_dups.py`, 4,260 files):

```
distinct by content  4,255      duplicate groups  5      redundant  0.1%
```

So the corpus is essentially free of exact duplicates and the near-duplicate
problem is the one that matters. ⭐ The five that ARE byte-identical are
**cataloguing errors worth fixing**, because their filenames disagree with
their content:

| | |
|---|---|
| `WXK63_stationID-SHORT(DONNA)_2013` | = `WXK63_stationID-SHORT(TOM)_2006` |
| `KEC65_stationID_2014` | = `KZZ79_stationID_2016` |
| `KIH42_stationID(PAUL)_2000` | = `KIH42_stationID_2000` |
| `WXJ96_SVR(1)_2009` | = `WXJ96_SVR(2)_2009` |
| `WXL55_RWT_2010` | = `WXL55_Winter-Info-Week(live-voice)_2009` |

⚠ The first two claim different SPEAKERS, different STATIONS and different
YEARS while being the same bytes. Any measurement that grouped by those labels
was grouping on a false premise.

### What survives once identities are excluded

| pair | what it is | median NCC | ≥0.95 | ≥0.99 |
|---|---|---:|---:|---:|
| KDO94 SVR(4)/(5) | **same capture, two files** | 1.000 | 100% | 100% |
| WNG588 2006 pair | same station, same session | 0.998 | 99% | 99% |
| KEC86 2016 | same station, two captures | 0.897 | 5.7% | 0% |
| WXL38 2015 | same station, two captures | 0.599 | 0% | 0% |
| WNG588 2014 vs 2016 | same station, **2 years apart** | 0.256 | 0% | 0% |
| KIH54 vs KIH56 | **different stations** | 0.311 | 0% | 0% |
| WITHIN one file, best two | same channel, different moment | 0.975–0.979 | 97–98% | **0%** |
| FLOOR, different speech | — | **0.073** | 0% | 0% |

All six across-file pairs have duration ratios of 1.000–1.007, so every one is
genuinely the same synthesis. The failures are therefore the CHANNEL, not the
pair selection.

### The read, and it is narrower than the tool's own verdict

⚠ `ss_offair_ceiling.py` printed "verbatim matching SURVIVES" from medians that
still included the duplicate. Excluding it:

* **Sample-exact (≥0.99) matching does NOT survive independent off-air
  captures.** Nothing reached it except one identity and one same-session pair.
  Two captures of the same station days apart score 0.60–0.90; two years apart,
  0.26; two stations, 0.31.
* **Within ONE recording it very nearly does**: 0.975–0.979 median with 97–98%
  of windows ≥ 0.95, against a 0.073 floor. Those are different moments of one
  capture, so they are genuine repeats, not identities.

**So a radar comparison must be WITHIN a single recording, and read at the 0.95
level, not 0.99.** That is exactly the design the off-air constraint forced, and
it now has a measured yardstick: ceiling ~0.98, floor 0.073.

### ⚠ THE FLOOR ABOVE IS THE WRONG FLOOR FOR RADAR

0.073 is "different speech". The radar question compares two tokens of the SAME
WORD, which are acoustically similar whatever units they use, so the relevant
floor is **"same word, different units, same channel"** — and it is not
measured. Until it is, a radar score between 0.073 and 0.98 cannot be read.

### ✔ THE FLOOR, MANUFACTURED — `ss_unit_floor.py`

`SPFY_UID_DUMP` reports the pool and the pick per slot; `SPFY_UID_OVERRIDE`
forces a chosen valid unit back in. So our byte-exact engine renders the same
text twice out of genuinely different units — exactly what S4 would have done
if `radar` is assembled rather than stored. 256 slots, 252 substituted (98%),
duration 8,864 → 9,028 ms.

Noise is added until IDENTICAL audio scores the off-air ceiling (0.978), so the
floor is read at the same working point rather than clean against noisy:

| condition | median NCC | ≥0.95 | ≥0.99 |
|---|---:|---:|---:|
| IDENTITY, re-render clean | 1.000 | 100% | 100% |
| **CEILING** off-air, same units, same recording | **0.978** | 97–98% | 0% |
| **FLOOR** same text, DIFFERENT units, @ SNR 17 dB | **0.153** | 0.0% | 0.0% |
| floor, different speech entirely | 0.073 | 0.0% | 0.0% |

**Usable window +0.825.** Not marginal — the test is decisive.

⭐ **And note where the unit floor sits: 0.153, barely above the 0.073 of
COMPLETELY DIFFERENT SPEECH.** Two renderings of the same words from different
units are, at the waveform level, almost as unrelated as unrelated speech. That
is the property that makes this work: NCC here is a UNIT-identity test, not a
word-identity test, so "same word" contributes almost nothing to the score.

⚠⚠ **THE FIRST RUN REPORTED A PERFECT 1.000 FLOOR AND IT WAS AN ARTEFACT.**
`spfy_synth.c` matches the literal `"t":"pick"` with `strstr`, so
`json.dumps`'s default `"t": "pick"` is skipped and EVERY override line is
silently ignored — the substituted render was byte-identical to the baseline
and the "floor" was the baseline against itself. Write the override with
`separators=(",", ":")`. `ss_unit_floor.py` now aborts if the two renders come
out identical, because that failure is otherwise indistinguishable from a
flawless result.

### Scaled to n = 32 — the floor is a constant

8 texts x 4 substitution draws, 32/32 usable, 98% of slots substituted:

| | median | IQR | min | max |
|---|---:|---:|---:|---:|
| clean | 0.165 | 0.136–0.178 | 0.116 | 0.205 |
| @ SNR 17 dB | **0.158** | 0.131–0.173 | 0.116 | 0.195 |

Per-text medians span only 0.133–0.171 across eight very different warnings, so
**0.158 can be treated as a constant.** The n = 1 value (0.153) was accurate.

### ⚠⚠ BUT THE CURVE IS NOT LINEAR, AND THAT CHANGES WHAT CAN BE ASKED

| substituted | shared | median NCC | ≥0.95 |
|---:|---:|---:|---:|
| 0% | **100%** | **0.978** | 97–98% |
| 10% | 90% | 0.449 | 7.7% |
| 25% | 75% | 0.432 | 0.0% |
| 50% | 50% | 0.320 | 0.0% |
| 75% | 25% | 0.188 | 0.0% |
| 100% | 0% | 0.142 | 0.0% |

Going from 100% shared to **90%** shared costs **0.53**; going from 90% all the
way to 0% costs only another 0.31. One substituted unit changes the duration of
everything after it, so a handful of swaps desynchronises the whole tail.

**So this statistic is a near-BINARY detector, not a graded one.** It answers
"did these two tokens use the same units THROUGHOUT" with a huge margin, and it
**cannot distinguish 90% shared from 0% shared.**

⚠ **Retract** the earlier claim that a radar score gives "the length of the
matching run, in the same units as §6j's half-phone counts". Window-median NCC
does not, and neither does the ≥0.95 fraction — both collapse by 10%
substitution. A graded figure needs a different statistic: the longest run of
consecutive matching windows with re-anchoring after each break, which is not
built.

**What the instrument DOES license**, on a within-recording pair:

* **≈0.98** → the two tokens are the same units end to end, i.e. `radar` is
  stored and replayed verbatim.
* **≲0.45** → they are not, i.e. the engine rebuilt the word — but HOW much it
  reused is not readable from this number.

That is still a direct answer to the original question, just not a measurement
of degree.

⚠ Additive white noise; real off-air is filtered and non-stationary. The
calibration ties the working point to the measured ceiling but does not
reproduce its spectrum.

### ⭐ A ROBUST AUDIO HASH BEATS NCC AT THIS — `ss_audio_hash.py`

foobar2000's Audio MD5 hashes decoded PCM, so it is exact; it already showed
the two KDO94 files are not byte-equal while their content plainly is. The
useful question is whether a SIMILARITY-PRESERVING hash exists — invariant to
the channel, sensitive to the audio. That field is acoustic fingerprinting, and
the classic is **Haitsma & Kalker** (Philips, ISMIR 2002): 33 log-spaced bands,
a 0.37 s window hopped every 11.6 ms, one 32-bit sub-fingerprint per frame from
the SIGN of the second difference of band energies, compared by BIT ERROR RATE.
Signs of differences are what make it survive EQ, level and codecs.

⚠ The obvious risk was that it is TOO robust: a perceptual hash is built to
ignore anything a listener would not notice, and two unit selections of the
same word sound identical. Measured over 6 texts:

| condition | median BER | min | max |
|---|---:|---:|---:|
| identical, clean | **0.0000** | 0.0000 | 0.0000 |
| identical, through the calibrated noise | **0.1077** | 0.063 | 0.158 |
| same text, DIFFERENT units | **0.4725** | 0.460 | 0.480 |
| different speech entirely | 0.4731 | 0.452 | 0.484 |

**Different units score the same as unrelated speech** (0.4725 vs 0.4731,
chance 0.5) while identical audio through the same noise sits at 0.108. It is a
UNIT-identity test, and the separation is 0.365.

**And it fixes the defect NCC has.** Window-median NCC collapses at 10%
substitution because one swapped unit desynchronises the whole tail, so it
cannot grade partial sharing (see the retraction above). The hash is a
sequence of INDEPENDENT 11.6 ms sub-fingerprints, so a partial match shows up
as a RUN of low-BER frames rather than destroying the whole score. The longest
matching run is then a length, in frames — which is the graded contiguity
figure NCC could not give.

### ✔ VALIDATED ON REAL OFF-AIR AUDIO — `ss_hash_offair.py`

24 pairs from `corpus.db`, both instruments computed on every one, NCC deciding
which pairs are genuine BEFORE the hash is read on them:

| group (by NCC) | n | median BER | range |
|---|---:|---:|---|
| **GENUINE repeats, NCC ≥ 0.95** | 8 | **0.0678** | 0.000–0.101 |
| partial, 0.50 ≤ NCC < 0.95 | 8 | 0.1312 | 0.044–0.230 |
| not the same audio, NCC < 0.50 | 8 | 0.1877 | 0.108–0.488 |

**0.068 through the REAL channel, better than the 0.108 my white-noise model
predicted.** The off-air chain is gentler on a sign-of-difference hash than
additive noise is, which is the point of the design.

    REAL off-air, same units   0.068
    different units            0.472      <- 0.40 apart
    different speech           0.473

### ⚠ BUT THE TWO INSTRUMENTS DISAGREE ON A THIRD OF THE PAIRS

Several pairs NCC calls "not the same audio" the hash calls close: NCC 0.381 →
BER 0.108, NCC 0.256 → 0.189, NCC 0.290 → 0.160. The likely reason is
alignment reach — NCC searches ±40 ms per window, the hash ±60 frames (~700 ms)
— so the hash recovers pairs NCC lost to drift rather than false-matching them.
WNG588 2014 vs 2016 is the clearest case: same station, same product, two years
apart, deterministic engine, so it SHOULD be the same synthesis, and the hash
says so while NCC does not.

⚠ That is an explanation, not a measurement. Until it is checked, treat
**BER 0.10–0.30 as an ambiguous band** and read only the extremes:

    BER < 0.15   the two tokens are the same units
    BER > 0.40   they are not
    0.15 - 0.40  unresolved -- do not score a radar pair that lands here

### ✔ THE SYNTHETIC FLOOR, VALIDATED BY EAR

The floor cannot be measured through the real off-air channel and never will be
— 0.472 comes from our engine's substituted renders, and S4 audio cannot be
re-rendered. So the open risk was not the channel but the SUBSTITUTION: if
forcing different units produced audible damage, the floor would be measuring
artefacts rather than unit identity, and no number could tell the two apart.

A number cannot settle that. Ears can. `ss_ab_listen.py` writes a labelled A/B
set (`C:\tmp\radar_ab`) — same text, same voice, same engine, only the unit
choice differing, at 100% / 25% / 10% substitution.

**User verdict, 2026-08-11: "Same voice, same words, just different."**

That is the answer the measurement needed and could not produce. The
substitution changes WHICH RECORDINGS are concatenated and nothing else
audible, so:

* the 0.472 floor measures **unit identity**, not damage;
* two renders that are perceptually the same word in the same voice are, at
  the waveform level, as unrelated as different sentences (NCC 0.16, BER
  0.47) — which is precisely the property the radar test needs;
* the NCC collapse from 0.978 to 0.449 at only 10% substitution is pure
  desynchronisation, not anything a listener hears.

The floor is synthetic in origin but no longer unvalidated. **The instrument is
ready to score radar pairs**, within a single recording, against 0.068 and
0.472.

### The three engines on the same statistic

`radar`, isolated, longest contiguous run in half-phones (§6j for the ScanSoft
pair; Speechify 3 read straight out of our own engine, which reports its
same-rec/cross-rec pairs directly and agrees with the unit-id run count):

| pack | segments | longest run |
|---|---:|---:|
| NextUp 2004 | 7 | 3 |
| RS4 2006 | 5 | **5** |
| **Speechify 3** | **9** | **3** |
| Speechify 3, in the carrier phrase | 18 | 8 |

⭐ **S3 is the most fragmented of the three for this word** — 9 segments from 14
units. Its inventory offers no more contiguous `radar` material than the 2004
ScanSoft corpus and less than RS4's. And its in-phrase row reaches a run of 8,
so the fragmentation is specific to `radar`, not general — the same pattern the
within-utterance control found in both ScanSoft packs.

⚠ Same statistic, different corpora AND different front ends. This compares
what each inventory offers for one word, not engine quality.

---

## 6l. S4 `radar` SCORED — and what the score does NOT say

`ss_radar_score.py` then `ss_radar_runlen.py`. 722 files hold a radar cue; 124
within-file pairs whose Whisper texts differ. Both ends re-calibrated at the
window actually used (500 ms), because the 0.068/0.472 pair was measured on
multi-second clips and a short window has more variance:

| | median BER | min |
|---|---:|---:|
| CEILING off-air repeats, same units | 0.0498 | 0.0254 |
| **RADAR pairs** | **0.1206** | **0.0131** |
| FLOOR same text, different units | 0.3158 | 0.2769 |

15 of 30 pairs matched at 500 ms. **That headline is not readable on its own**:
a broadcast CYCLE repeats the whole warning and Whisper transcribes the repeats
differently, so a "different text" pair can be the same sentence sharing
everything. Sweeping the window separates them — a same-sentence pair keeps
matching for seconds, a word-sized match stops:

    longest shared run   median 800 ms   min 500   max 8000
    stops by 1200 ms     10 pairs   <- informative
    still at 3000+ ms     3 pairs   <- whole sentence, discarded

The 10 informative pairs are genuinely different sentences, e.g.

    A  "Pacific Daylight Time, National Weather Service Doppler radar in..."
    B  "When a tornado warning is issued based on Doppler radar, it mean..."

sharing ~800 ms at BER 0.024–0.048 — **at or below the same-units ceiling** —
and then stopping where the surrounding words diverge. `Doppler radar` is about
that long, so the shared stretch is the phrase.

### ⚠⚠ THIS SHOWS STABLE SELECTION, NOT CONTIGUOUS STORAGE

**S4 renders `Doppler radar` from identical units across different sentences.**
That is established: the audio is verbatim-identical over ~800 ms through the
real off-air channel.

It does **not** follow that the corpus holds `radar` as one contiguous
recording. A deterministic unit-selection engine picks by triphone context, and
the interior of a repeated phrase has the SAME contexts whatever precedes it —
so identical output is what BOTH hypotheses predict:

* stored as one contiguous take, replayed; and
* assembled from the same fragments every time.

Separating those needs the JOIN structure inside the 800 ms, which is not
readable from audio without a join detector. §6j got it for ScanSoft only
because the engine was there to ask.

⚠ Do not write "S4 has a canned radar". What is measured is that S4's `radar`
is context-stable, and that the instrument works on real off-air S4 audio.

---

## 6m. CAN A JOIN BE DETECTED AT ALL? Ground truth from our own engine

§6l ends needing a join detector, and RESUME §5 proposed building one for
off-air S4. Before spending anything on the channel, the prior question: does a
join leave a trace in **clean** audio from an engine we fully control?

Tool: `ss_join_detect.py`. n = 3,093 joins against 3,497 continuations over 164
texts of the parity corpus. Runtime 12 s.

### The ground truth is exact, not estimated

`SPFY_WSOLA_TRACE` emits the output cursor per push, and wsola.c's emission
arithmetic then places everything to the sample:

    output [out0, out0+W)   the crossfade, W = 80 samples = 10 ms
    output [out0+W, out1)   a straight memcpy from ONE recording

Checked 18/18 on the radar phrase before anything was measured. Consecutive
unit ids are collapsed into one push upstream (wsola.h), so a within-run slot
boundary is a half-phone boundary where the recording simply **continued** —
which is the matched control, not a synthetic one:

| class | what it is |
|---|---|
| `JOIN` | run start, push > 0 — crossfade ran, units from different places |
| `CONT` | slot boundary inside a run — byte-continuous recording |
| `MID` | mid-body, no boundary — sanity: must sit below `CONT` |

Within-run positions come from `SPFY_UID_DUMP`'s `emit` records **corrected by
(W − lag)**; those records are written against the push's pre-blend cursor and
sit that far early. Two cross-checks (emit-group size == the push's `run_n`,
group's first `out` == the push's `out0`) must pass or the text is dropped —
0 of 164 dropped.

### ⚠ The confound that had to be killed first

Joins do not fall where continuations fall. The engine runs contiguously
through easy stretches and switches recordings at hard ones, so the two classes
differ in **phonetic context** before any join is considered. Everything is
therefore also scored stratified by the half-phone pair bracketing the boundary
(the `phone` field of the `cands` records), and the splice controls are built
from donors carrying the **same right half-phone**.

That control paid for itself immediately: `side_db` (energy step) reads AUC
0.597 pooled and **0.510 stratified** — the entire pooled effect was context,
not joins.

### AUC vs CONT, direction-agnostic, stratified by half-phone pair

| feature | JOIN | POS_XFADE | POS_RAW |
|---|---:|---:|---:|
| `side_lsd` LPC log-spectral distance | 0.638 | 0.819 | 0.802 |
| `side_mfcc` | 0.618 | 0.824 | 0.801 |
| `side_db` energy step | 0.510 | 0.634 | 0.617 |
| `side_f0` | 0.514 | 0.792 | 0.796 |
| `blend_step` the waveform click ⚠ | 0.515 | 0.543 | 0.767 |
| `blend_mis` blend fits neither side's LPC | 0.538 | 0.696 | 0.654 |
| `blend_dip` crossfade power dip | 0.628 | 0.643 | 0.522 |
| LDA, fitted on half, scored on the other half | **0.713** | 0.897 | 0.915 |

⚠ **Read `blend_step`'s 0.515 as the cautionary entry, not as a result.** The
click lives in the top few percent of the distribution and an AUC over the
whole of it is blind to that; the same feature as a tail rate says 10.6% vs a
5.0% floor. See the retraction below.

`POS_RAW` = a valid unit of the correct half-phone butt-spliced on; `POS_XFADE`
= the same donor through the **engine's own** lag search and linear crossfade.
Both are manufactured from real Tom audio, so the only thing separating
`POS_XFADE` from `JOIN` is which unit was chosen.

Controls: `POS_RAW` reaches 0.915, so the instrument sees a splice it is handed
(pre-registered ≥ 0.80 ✓). `MID` `side_lsd` 4.20 < `CONT` 6.11, so the features
do track acoustic discontinuity ✓.

### ⚠ WSOLA removes MOST of the click — the first version of this was wrong

**RETRACTED, 2026-08-11.** This section originally read "removes the click,
completely, and by construction", from `blend_step` AUC 0.515. That is wrong,
and a listener caught it: very slight clicks *are* audible on the butt-spliced
B files of `ss_join_ab.py`, on fewer than half the joins.

Two separate errors, and the second is the instructive one:

1. **Scale mismatch.** `blend_step` maxed `|Δx|` over FIVE samples at the cut
   and divided by a median over 400 that straddled the blend. The event is 80
   samples wide.
2. **⚠ AUC CANNOT SEE A RARE LOUD ARTEFACT.** A click affects the TOP of the
   distribution, not its bulk. On the same statistic, read as a detection rate
   at the join-free 95th percentile instead of as an AUC, real joins fire on
   **10.6%** against a 5.0% floor — while the AUC of that identical feature is
   0.507. The AUC was not merely imprecise, it was structurally blind.

`ss_click_probe.py` re-measures it. A click is a broadband transient, and at
8 kHz voiced speech leaves the top octave nearly empty, so the probe is a
2.5 kHz high-pass envelope at 1-sample resolution (0.125 ms), scaled by the
median of the two **join-free 80-sample windows flanking** the blend — matched
in length, and deliberately not straddling it.

Ear-calibrated before anything was read: the listener's "fewer than half" set a
pre-registered 25–65% band for butt splices. Two probes failed it and were
discarded, not tuned —

* self-normalised LPC(16) residual, max over the blend: **1.7%**. ⚠ In voiced
  speech the largest residual peaks are glottal pulses and a click is *smaller*
  than one, so any statistic whose maximum is a glottal pulse cannot find a
  click. Do not retry it.
* HF envelope, max over the whole 88-sample span: **18.2%**. Its own
  peak-position histogram said why, and that histogram is a finding:

| where the HF peak lands | <4 | 4–19 | 20–39 | 40–59 | 60–75 | 76+ |
|---|---:|---:|---:|---:|---:|---:|
| `CONT` join-free | 12.6% | 15.5% | 25.3% | 23.2% | 13.7% | 9.7% |
| `JOIN` | 19.0% | 16.4% | 16.4% | 17.6% | 14.6% | 15.9% |
| `POS_RAW` butt splice | **45.0%** | 8.8% | 14.3% | 13.6% | 10.3% | 8.0% |

A splice artefact is **localised to under 0.5 ms at the cut**, not smeared
across the crossfade — measured, not assumed. A max over 88 samples dilutes it
into the null's own max.

### The corrected numbers

Detection rate at each window's own join-free 95th percentile, so `CONT` is 5%
by construction. n = 2,980 joins, 3,497 continuations, 3,473 of each splice.

| HF window | tests | CONT | JOIN | POS_XFADE | POS_RAW |
|---|---|---:|---:|---:|---:|
| **at the cut** `[b−3, b+4]` | a step where the units are stitched | 5.0% | **9.3%** | 9.2% | **34.0%** |
| at the ramp end `[b+W−3, b+W+4]` | `win_in` tops out at 79/80 | 5.0% | 6.5% | 9.2% | 8.2% |
| mid-blend `[b+8, b+W−8]` | the smearing hypothesis | 5.0% | 6.0% | 8.8% | 9.4% |

* **The ear agrees with the probe.** 34.0% at corpus scale; **35%** (28 of 81)
  scored per-join on the exact three A/B files that were listened to, against a
  reported "fewer than half". `--ab` prints the timestamps so agreement is
  checkable event by event, not only in aggregate.
* **WSOLA removes ~85% of detectable clicks, not all of them.**
  (34.0 − 9.3) / (34.0 − 5.0) = 0.85. The residual is 4.3 points over the
  join-free floor — roughly **1 join in 23** carrying a transient above what
  the recording itself produces.
* **Both structural hypotheses about the crossfade are null.** The ramp's
  non-unity end (6.5% vs 5.0%) and smearing through the blend (6.0% vs 5.0%)
  are each within noise of the floor. Whatever survives is at the cut.

So the `win_in[0] = 0`, `win_out[0] = 1` anchoring (`FUN_08ee11e0`) does mean
the crossfade cannot produce a *step* — but a click is broadband transient
energy, not only a step, and lag-search failures leave some of it. The correct
claim is **large reduction, not elimination**.

The crossfade also leaves a trace of its own: `blend_mis` and `blend_dip` rise,
because 10 ms of output is a genuine spectral **mixture** of two units. WSOLA
trades most of an audible artefact for a measurable one.

### The two mechanisms, separated

| | | |
|---|---:|---|
| butt splice, correct phone | 0.915 | no smoothing, no selection |
| through the engine's crossfade | 0.897 | **WSOLA only** |
| what the engine actually emits | **0.713** | WSOLA **and** selection |

Read on the family each mechanism can actually touch: WSOLA acts only inside
the blend, and on `blend_*` it moves `POS_RAW` 0.782 → `POS_XFADE` 0.623.
Selection acts on the two sides, which no crossfade can reach, and on `side_*`
it moves `POS_XFADE` 0.819 → `JOIN` 0.638 — removing ~57% of the detectable
spectral mismatch.

**Selection, not WSOLA, is what makes joins hard to find.** WSOLA takes ~85% of
the click and nothing else; the inventory's job is everything else — including
the ~15% of clicks the crossfade leaves behind, since a well-matched unit has
little left to click about.

### Verdict on RESUME §5 — do not build the off-air detector

Pre-registered bands were ≤ 0.60 dead / ≥ 0.75 proceed. The stratified combined
figure is **0.713 — INCONCLUSIVE**, and reported as such. But the band was
written for the clean case only, and 0.713 is the ceiling under conditions the
S4 application cannot come close to:

* positions are **exact and known** here; on S4 every offset must be scanned,
  which multiplies false positives by the number of candidate positions;
* the audio is **clean 8 kHz**; §6k measured the off-air channel at BER 0.068
  for *byte-identical* material;
* the LDA is **fitted on the same engine** it is scored on. Nothing can fit on
  S4 — that is the whole problem.

An AUC of 0.713 with exact positions in clean audio is not a detector, it is a
weak tendency. Blind detection through a transmitter would need ~0.95.

### ⚠ AUC MISLEADS IN BOTH DIRECTIONS — the metric, fixed at corpus scale

The click retraction above showed AUC hiding a real tail effect. The same audit
applied to the join detector shows it doing the opposite: **0.713 flatters a
rule that delivers nothing at any operating point a scan could run at.** Both
failures have one cause — AUC integrates over the bulk of the distribution, and
neither "a rare loud artefact" nor "is this flag worth acting on" lives there.

The fix, in `ss_join_detect.py`, is three changes:

1. **Fold the tail-heavy features in.** `hf_cut` / `hf_end` / `hf_mid` from the
   click probe now compute inside the same span, so one tool measures both
   families.
2. **Standardise within stratum, then read the tail.** A per-stratum 0.1%
   quantile needs thousands of rows per stratum that do not exist, so each
   feature is robustly z-scored (median / MAD) against its own stratum's
   continuations, and one global threshold is then read at any FPR. Same
   confound control, now usable in the tail.
   ⚠ **Hierarchically** — `(pl,pr)` → `(pr)` → global. Requiring the exact
   pair dropped **58% of joins, and not at random**: a join happens precisely
   where the engine could not continue, so those contexts have the fewest
   continuations to standardise against. Restoring them moved JOIN's TPR@5%
   from 0.170 **down** to 0.140 — the dropped joins were the harder ones, and
   the exact-pair-only number was optimistic.
3. **Score against the measured base rate.** 3,704 joins in 2,696,634 samples
   = **1 join per 728 samples (0.137% of positions)**. Measured, not assumed.

TPR at fixed FPR, n = 3,011 joins / 3,497 continuations / 3,489 each splice:

| feature | J@5% | X@5% | R@5% | J@1% | X@1% | R@1% |
|---|---:|---:|---:|---:|---:|---:|
| `side_lsd` | 0.068 | 0.235 | 0.216 | 0.014 | 0.056 | 0.049 |
| `side_mfcc` | 0.070 | 0.255 | 0.236 | 0.015 | 0.070 | 0.063 |
| `blend_step` | 0.089 | 0.096 | **0.358** | 0.018 | 0.033 | **0.120** |
| `hf_cut` | 0.094 | 0.101 | **0.322** | 0.016 | 0.036 | 0.088 |
| `blend_dip` | 0.126 | 0.134 | 0.121 | 0.029 | 0.031 | 0.042 |
| `hf_mid` | 0.131 | 0.103 | 0.107 | 0.029 | 0.019 | 0.027 |
| LDA, mean-fit, held out | **0.140** | 0.189 | 0.244 | 0.019 | 0.038 | 0.052 |
| max-z, tail rule, unfitted | 0.100 | 0.222 | 0.228 | 0.021 | 0.037 | 0.035 |

⚠ 3,497 controls resolve FPR to 0.0003, so the 0.001 column is indicative only
and is not quoted. Both combiners are reported because they optimise different
things — LDA separates means (the AUC objective), max-z fires when any single
feature is extreme (the rare-loud objective) — and neither was selected after
the fact.

⭐ **Cross-check against the ear.** `hf_cut` reads R@5% = 0.322 and J@5% =
0.094 here; `ss_click_probe.py`, written separately and calibrated against a
listener's "fewer than half", independently gives **0.340 / 0.093** for the
same quantity. Two tools, one of them anchored to ears, agree.

### What a blind scan would actually cost

| FPR | TPR | false flags per real join | precision |
|---:|---:|---:|---:|
| 5% | 0.140 | 259x | **0.4%** |
| 1% | 0.019 | 391x | **0.3%** |

So AUC 0.713 and "99.6% of flags are wrong" describe the same distribution.
The AUC comes from a broad, weak shift with no detectable tail; a butt splice
by contrast has one (`blend_step` R@5% = 0.358 against J@5% = 0.089), which is
exactly why the ear finds those and not these.

⚠ **This criterion is POST HOC.** §6m's AUC band was pre-registered and returns
INCONCLUSIVE; the operating-point reading was added afterwards in response to a
demonstrated flaw in AUC. It is labelled as such wherever quoted. It does not
overturn the pre-registered result — it agrees with it and removes the
ambiguity, which is the only reason it is trusted here.

### Counting is not localising — and it does not rescue it either

Everything above is about *finding* joins, which needs precision. §6l does not
actually ask that. It asks whether one ~800 ms stretch is **one take or eight
units** — a rate, and counting tolerates a detector far too weak to point at
anything. So it gets its own arithmetic rather than inheriting the precision
verdict.

    flags if assembled  = f(C−r)T + t·r·T        flags if contiguous = f·C·T
    difference = (t−f)·r·T,  Poisson noise ≈ √(f·C·T)
    T = z² · f · C / ((t−f)·r)²

with the measured join rate **11.0 per second** (3,704 joins in 337 s). `C` is
*independent* candidates per second — the features span `CORR` samples, so
neighbouring positions are not separate tests — and it is the weakest
assumption here, so it is swept:

| independent candidates/s | FPR | TPR | audio needed for z = 3 |
|---:|---:|---:|---:|
| 8000 (every sample) | 5% | 0.140 | 3,672 s |
| 50 (one per feature window) | 5% | 0.140 | 23.0 s |
| 25 (one per two windows) | 5% | 0.140 | **11.5 s** |
| 25 | 1% | 0.019 | 252 s |

**Best case 11.5 s**, and that is generous three times over: clean engine
output, a detector fitted on the same engine, and the granularity assumption
chosen to flatter it. §6l's question is asked of **800 ms — 14× short in time**
— and the shortfall cannot be closed by taking more audio, because the next
word is a different question. The hypothesis cannot be held fixed for 11 s.

⚠ **So the honest headline of §6m is not "the detector is weak". It is: the
join structure of S4 audio is not recoverable from the audio, at the length
scale at which the question is asked, and the cause is unit selection.** WSOLA
is a side issue; the channel never gets a chance to matter.

⚠ **This retires the RESUME §5 task.** Not because joins are inaudible — they
are, and now measurably so — but because unit selection makes the two sides of
a real join nearly as similar as a genuine continuation, and no channel-side
cleverness recovers a difference that is not in the clean signal either.

⚠ **Scope.** Everything here is Speechify **3**, our byte-exact engine. It says
what S3's joins look like; it does not measure S4. The one part that does
transfer is structural rather than statistical: the no-step property follows
from the crossfade's `win[0] = 0/1` anchoring, so any later build using this
WSOLA inherits it.

### `ss_join_ab.py` — the same thing for the ear

`SPFY_WSOLA_DUMP_JOIN` writes both inputs per push, so the blend can be
recomputed offline and the 80 samples at `[out0, out0+W)` swapped for a butt
splice. Same units, same lags, same durations, same file length — the **only**
difference is whether those 10 ms were crossfaded.

Self-check before writing: the recomputed blend is compared against the
engine's own WAV. 97.9% exact, **100.0% within 1 LSB** on all three texts, the
residual being exactly the x87 float32 rounding wsola.c documents in the window
tables. Reading the dump wrong would have failed this.

Output in `C:\tmp\join_ab`: radar 17 joins, warning 44, pangram 30.

---

## 7. Retractions and dead ends — do not re-run

1. **`rho` correlation column (`C:\tmp\unit_lanes.py`) — VOID.** It Spearman-
   correlated two frequency profiles that were each already sorted descending;
   monotonic by construction, so it returned **+1.000 for every lane** and could
   not have returned anything else. No lane assignment rests on it.
2. **"+0x80 is a tag count / three-block table"** — the useld body's head is one
   long ascending run (38,101 u32 for NextUp, 19,185 for RS4), not 173/216
   blocks. The split was imposed by me, not by the file.
3. **B/C as recording -> units** — wrong, see §6.
4. **8-byte record as sliding phone context** — best cross-lane agreement
   **4.1%** (chance for a 46-value alphabet); run lengths 91–94% singletons in
   array order, 60–78% along either section walk. The phones are in the 16-byte
   record.
5. **Byte-lane sweep of assumed `N x 10` / `N x 20` tail records** — no
   phone-sized alphabet in either pack. The record offsets were guessed from
   older notes; the real ones are in §3.
6. **The 2.4 MB "structured" region at 0x1a82000** is `ff ff ff ff 00 00 00 00`
   filler. A whole megabyte at 0x1d00000 holds **2** distinct byte values.
7. **`radar` as text or SAMPA anywhere in any component** — every `rJd*` hit is
   a coincidence inside an ACELP payload. The lexicon in `vf_tom_full.dll`'s
   `.rdata` (683 KB in 2004, 86 KB in 2006) is a G2P **exception** list, not the
   inventory.
8. **Protection module / `.plh`** — see §2.
9. **"the group sizes sum to |C| exactly, so the key table tiles the posting
   list" — VOID for BOTH index arms.** `sizes = diff(append(offsets, npost))`
   telescopes to `npost - offsets[0]`, and `offsets[0]` is 0, so the sum equals
   `npost` for any offset array whatsoever, including a random one. It was read
   as the headline confirmation of the A/B/C reading and it confirms nothing.
   What does survive, because it CAN fail: the offsets ascend, they are bounded
   by the posting count, no group size is negative, and **0 of 835,567 / 0 of
   856,494 postings fall outside unit range**.
10. **G as an offset table into H** — the value range fits inside `|H|` and
    every live G value is below it, which is suggestive and is not enough. G
    does not ascend in any order and loses to a shuffle of itself (§6c).
11. **H as an adjacency / successor table** — at the null, §6c.
12. **"the 300-tick gaps are unlabelled holes in a continuous recording"** —
    tested three ways and INCONCLUSIVE, not because the arms disagreed but
    because the floor control was invalid. See §6d before spending anything
    more on it.
13. **⚠ RETRACTED: the `radar` preselect candidate counts.**
    `C:\tmp\ss_preselect.py` printed `d [J _ a]`: 10 candidates (l), 6 (r) and
    `a [d _ r]`: 23 / 22, against Speechify's 4 and 6. **Do not quote these.**
    The lookup machinery is right, but which key digit is the own-phone is
    unresolved (§6e), so the query may not be asking for the triphone it names.
    Its self-check — "are the returned candidates the phone requested" — read
    0.0-3.2%, which ALSO proved to be the wrong test, because the preselect is
    substitution-tolerant and returns non-matching phones by design.
14. **"the take id is absent" as established by `C:\tmp\ss_takeid.py`** — the
    conclusion happens to survive, but that run did not establish it. Its
    statistic assumed storage order tracks take order and so could not detect a
    take id in a repacked file. Superseded by `rec_scan.py` (§6h), which is the
    version to cite.
15. **`+2 w2` scoring compactness 1.0000 in the first `rec_scan.py` run** — it
    is `pos >> 16`, a monotone function of the sort key. Now reported as the
    positive control instead. §6h.
16. **"the RS4 `encrypt` question resolves to nowhere"** — overreach. What is
    shown is that RS4's `useld` is plaintext on disk and nothing on the
    voice-font path decrypts it. What the marker gates is NOT shown, and
    `comrsrc.dll` is unexamined. §6g.

---

## 8. Probes

All in `C:\tmp`, all read-only against the installs.

| script | what it establishes |
|---|---|
| `usel_probe.py`, `usel_map.py` | header, entropy profile, `encrypt` marker |
| `usel_runs.py` | ascending-run length; the two Toms are different corpora |
| `usel_toc.py` | kills the tag-table reading (§7.2) |
| `vf_survey.py`, `vf_rdata.py` | PE survey; `synth_155mrf22.dll` identical across packs; the embedded lexicon |
| `combrk_probe.py` | broker exports/imports, container header dump |
| `vf_vtable.py` | reads the interface vtable Ghidra never typed |
| `useld_sections.py` | **validates the hardcoded section table against the file** |
| `unit_lanes.py` | 8-byte record lanes ⚠ carries the void `rho` column |
| `unit_lane_test.py`, `useld_walk.py` | the failed sliding-context tests |
| `unit16.py` | the 16-byte record |
| `phone_classmap.py`, `phone_alphabet.py` | **the 46-phone SAMPA alphabet** |
| `engine_cmp.py` | Speechify vs ScanSoft vs RealSpeak on one aligner |
| `ss_takeid.py` | **the take-id sweep, calibrated on Speechify's VIN** (§6b) |
| `ss_sech.py` | D/E/F redone body-relative; G and H extents (§6c) |
| `ss_gh.py` | kills G-as-offset-into-H |
| `ss_h_pairs.py` | kills H-as-adjacency-table |
| `ss_dead.py`, `ss_dead2.py` | **the exact G/H 5,927-unit set identity** |
| `ss_gap_audio.py`, `ss_seam.py`, `ss_f0cont.py` | the inconclusive repack tests ⚠ §6d |
| `ss_read.py` | phone stream in `pos` order; writes cuts to `C:\tmp\ss_cuts` |
| `ss_preselect.py` | ⚠ the retracted radar counts (§7.13) — machinery ok, key unresolved |
| `ss_keydecode.py`, `ss_keydigit.py` | the key-digit assignment attempt (§6e) |
| `ss_wordid.py` | kills "record +4 is a word id"; it is the packed ±2 context |
| `ss_joincost.py` | **verifies G/H as the row-displacement join cost** (§6f) |
| `rs4_sections.py`, `rs4_units.py` | **RS4 Tom's directory and unit table** (§6g) |
| `rs4_triage.py` | crypto-signal triage over every DLL in both packs |
| `../ss_rs/rec_scan.py` | **the recording-id scanner, calibrated** (§6h) — durable, not in `C:\tmp` |

Ghidra note: auto-analysis defines functions from **0x10003000** upward only.
The `vf_*` entry points at 0x10001000–0x100023xx are reachable only through the
vtable at `0x10017068`, so nothing calls them and Ghidra never created them —
`decompile_function_by_address` returns "No function found" there.
`C:\tmp\vf_vtable.py` reads the table from the file instead; to work on those
functions in Ghidra, define them manually first.
