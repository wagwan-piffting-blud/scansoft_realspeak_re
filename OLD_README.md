# THIS DOCUMENT HAS BEEN SUPERSEDED BY `README.md` — it is kept here for HISTORICAL PURPOSES ONLY.

## ScanSoft / RealSpeak Solo v4 Voice Format: Reverse Engineering Summary

> **Status:** Live. **Both packs are now substantially decoded** — container,
> section directory, phone alphabet, the preselect index and its key encoding,
> and the 22.7 MB that turned out to be a precomputed join-cost table. The
> recording id is **absent from both**, measured against a ceiling of 1.0 taken
> from Speechify's real one. Still open: which key digit is the phone (which is
> why the `radar` candidate counts are retracted), and the `codsb` audio
> container, which has never been scanned. This document is kept in sync with
> `README_TECHNICAL.md` (the
> technical living document); that file has the raw binary detail, this one has
> the plain-English explanation.
>
> Everything here is measured. Where something is a guess it says so, and where
> something was **retracted** it stays on the page with the reason.

---

## Why this exists

The Speechify 3.0.5 reproduction in `../Speechify/spfy/` is byte-exact on every shipped
voice, and a single tool can now answer the question:  "can this voice say
this word as one continuous recorded stretch?" for any Speechify VIN. The
answer for Tom and the word **radar** was *no* — the phone trigram `ey-d-aa`
occurs **zero** times in 169,579 units, so the engine splices the word out of
five separate recordings with a seam inside the diphthong.

A tip said ScanSoft's Tom "treats it almost like two words as well", which
raised the obvious question: **does the ScanSoft inventory have the material
Speechify's lacks?** Answering that needs the same three facts from ScanSoft's
files that the VIN gives us — a per-unit phone, a recording id, and time order.
That is what this folder is about.

---

## Which "RealSpeak" is which

Three things on this machine carry the name and only two are related. Getting
this wrong invalidates any cross-engine claim, so it is the first thing on the
page. (Also in memory as `reference_scansoft_vs_realspeak_vs_lh`.)

**Family A — RealSpeak Solo v4.** Has Tom. Two packs of one architecture; the
NextUp tree literally contains `speech\rssolov4\`.

| we call it | path | data date | `useld` | notes |
|---|---|---|---|---|
| **ScanSoft** | `C:\Program Files (x86)\NextUp-ScanSoft\` | 2004 | 39.2 MB, **plaintext** | the tractable one |
| **RealSpeak** | `C:\Program Files (x86)\ScanSoft\RealSpeakSolov4\` | 2006 | 20.2 MB, **`encrypt`** | header says so |

Shared: `SCANSOFT` container magic, `useld` + `codsb` types, `vf_<voice>_full.dll`
voice fonts, and `synth_155mrf22.dll` — which is **byte-identical** between the
two packs.

**Family B — L&H.** No Tom, female voices only. **Unrelated. Nothing measured
there transfers.**
`ScanSoft\RealSpeak Standard v2\` (the `lhsp\rsstdv2` tree, `lhcom02w.dll`,
`lhtts01.dll`) and `Documents\L&H PCMM RealSpeak V1` (`RSMGR10`, `rsenu1f1`,
`.cod`, RPC).

⚠ **Two things that make Family B look related and do not make it so.** The
brand "RealSpeak" spans both. And Family A's shared runtime still exports
`lh_ErrorGetString` while its lexicon uses the same SAMPA notation L&H used —
a house style and a leftover symbol name both survive an acquisition.

⚠ **The two Toms are different recordings.** The `codsb` bodies match for 135
bytes (the header preamble) and **0 of 47** aligned 1 MB blocks; the `useld`
pair diverges after 44 bytes at `Tom` vs `tom`. 2006 is not an extension of
2004. A result about one pack is not a result about the other.

---

## How a voice is put together

```
vf_tom_full.dll   the VOICE FONT — orchestrates, and carries the section directory
  ├─ us_ObjOpen / us_ToSeg     unit selection      (internal, no separate DLL)
  ├─ pros_ObjOpen / pros_ToEpt prosody
  └─ synth_ToPcm               → synth_155mrf22.dll, ACELP decoder

us_tom_full.dat                UNITSELECTDATA — the unit database
vf_tom_full_155mrf22_270_06.dat REALSPEAKDATA — the coded audio (ACELP)
combrk.dll                     the file broker — opens and maps, nothing more
```

`combrk.dll` reads plain-text `.hdr` files that declare the whole component
graph. Those are readable in any editor and gave up, for free, the fact that
`OVERHEADFRAMES = 6` — a constant that had been an unexplained number in the
older `codsb` notes.

---

## The finding that unblocked everything

Every earlier attempt to parse `us_tom_full.dat` looked inside the file for a
section directory. **There isn't one.**

`brk_DataMap` has exactly **one** call site in the whole voice font. The file
is mapped once, whole, and then two functions assign **hardcoded absolute
offsets** into it. The directory is compiled into the DLL — which is also why
a voice font is per-voice at all.

That single fact explains every failed probe in the earlier work: they were
searching a file for something that only ever existed in code.

With the offsets in hand, six of the eight sections turn out to span exactly
`count x 4` for a count the DLL also hardcodes, and one field reads **324,263**
— the unit count that had been derived years earlier from the *audio* decoder
by a completely different route. The addresses are right.

---

## The phone label

The candidate scorer indexes two per-unit tables: an 8-byte feature record and
a 16-byte record. In the 16-byte record, two byte lanes are compared against
the synthesis target and, on mismatch, priced through a substitution-cost
matrix — the signature of phone context.

Those lanes hold **the SAMPA character itself, as an ASCII byte.** The DLL
carries a sparse 256-entry map that is `255` (invalid) everywhere except at the
46 codes that occur, where it gives a dense class `0..45`:

```
#$@ACDEGIJLNORSTUYZ^abdefghijklmnpqrstuvwyz  + 0x8b 0x91 0xa4   = 46 phones
```

Seven lanes of the record contain **only** ids from that 46-value set — zero
exceptions across all 324,263 units, which is a test that could easily have
failed. And the centre lane's frequency histogram is plainly English:

```
n 30181   t 23881   0x8b 23611   i 21728   $ 21023   # 15511   z 14713
e 13644   r 13592   d 12445   q 9254   s 9064   l 9015   u 7983  ...
```

`$` is schwa and `#` is silence, exactly where you would expect them. The same
notation appears in the DLL's own embedded pronunciation lexicon (`'Al-sO` =
also, `wE-D$r` = weather, `In-'kor-p$-'rJ-tId` = incorporated), which is how
the symbols were read in the first place.

---

## Position and length: found, and half understood

The engine's own adjacency test gave them away. `FUN_10007060` decides whether
two chosen units were neighbours in the original recording by checking

```text
pos[k] == pos[k-1] + len[k-1]
```

so both fields are in the 16-byte record: `pos` is a 31-bit value (unique
across all 324,263 units) and `len` a 12-bit one. They **tile**: sorting by
`pos`, the difference `pos[k+1] - pos[k] - len[k]` is **0** on 81.2% of steps
and exactly **300** on essentially all the rest — 324,258 of 324,262 steps are
one of those two — and the total accounting closes to 800 parts in 146.6
million. Those fields are right beyond reasonable doubt.

**And the space is the recorded corpus.** The decoded inventory
(`/Document/ssrs_re/ScanSoft/ss_tom_full.wav`, produced by `codsb/`)
is a clean linear image of the audio — its decoder writes frames end
to end at 320 samples each — so it can arbitrate. Building a "where the
silence-labelled units say silence should be" track and cross-correlating
it against the corpus's actual silence over all four hours:

| reading of `pos` | correlation | significance |
|---|---:|---|
| samples at 22,050 Hz | +0.006 | 3.7 sd — nothing |
| **100 µs ticks** | **+0.315** | **14.0 sd**, peak at +70 ms |

Ticks by a factor of fifty. And with that offset applied the phone classes sort
themselves the way phonetics says they should — fricatives `s` 2887 Hz and
`z` 2761 Hz sitting about 1200 Hz above the vowels `i` 1671 and `a` 1603, with
the nasal `n` 1621 down among them.

The offset is pinned too. Sweeping it against a null of 300 random global
offsets — which preserves every unit length and corpus statistic and destroys
only alignment — the fricative separation peaks at **+1338 Hz at −80 ms, 11.9
standard deviations** out, where the null sits at 0 ± 113 Hz. Six
`OVERHEADFRAMES` of decoder warm-up is 87 ms, and the sign is negative: a
unit's audio begins six frames *before* `pos`, which is precisely what
`fi = pos/320 − lookback` says. The disassembly and the audio agree.

**So the per-unit facts are solid: what phone a unit is, and where its audio
lives.**

## ⚠ And a correction that matters more than any of it

The obvious next step was to run the contiguity search and compare `radar`
against the Speechify answer. **That comparison would have been wrong, and it
is worth saying why plainly.**

Sorting the ScanSoft units by position and cutting at the boundary gaps gives
stretches averaging **1.8 phones** — 53% are a single phone, and the longest in
the entire voice is 16. Even those longest ones read as gibberish:
`septYne.iOeun.Ez`, `ndn^i$dnz.imr`. The Speechify VIN, by contrast, holds
recordings of median 10 and maximum 79 phones that read as real words —
`greater`, `trade`, `Belgrade`.

So consecutive ScanSoft units are **not** consecutive in speech. The inventory
is stored repacked, and "adjacent in the file" does not mean "adjacent when Tom
said them". `ss_inventory.py` does run, and does report `r J d a r`: zero
contiguous instances, two pieces at best. Those numbers look like a tidy
parallel to the Speechify result and **they are not one** — they answer a
question about storage layout, not about what was recorded.

Recovering true recording adjacency needs whatever maps the packed stream back
to takes. **That map is now known not to be in the file** — see the next
section. Until something outside the file supplies it, **the radar question
stays open on the ScanSoft side**, and the honest answer to "does ScanSoft have
the material Speechify lacks" is that this inventory cannot be asked that
question.

---

## The take id is not there — and that is a result, not a gap

Speechify's VIN carries `file_idx`, a recording id. One field. It is the entire
reason `inventory.py` can answer "was this said as one continuous stretch", and
the entire reason the same question stalls here. So the obvious move was to
sweep every per-unit field in the ScanSoft table for an equivalent.

The first attempt asked "is this field the same for two units the engine calls
neighbours". ⚠ **That was the wrong question**, and it is worth saying why,
because it looked reasonable. It can only find a recording id if the file
stores units in the order they were recorded — which is exactly what is in
dispute here. In a repacked inventory a perfectly good recording id would score
as noise under it and be thrown away.

The replacement asks something that holds no matter how the file is packed. A
recording is a continuous stretch of the corpus, so the units sharing one
recording id must sit close together **in time**, whatever order they are
written in. Score each candidate field by how tightly its groups clump on the
timeline: 1.0 means perfectly contiguous.

Run first on Speechify, where the answer is known:

| field | compactness | shuffled | above chance |
|---|---:|---:|---:|
| **`file_idx`** — a real recording id | **1.0000** | 0.0002 | **+0.9998** |
| `phone` | 0.0329 | 0.0328 | +0.0000 |
| `dur_like` | 0.0181 | 0.0181 | +0.0000 |
| `local_pos` | 0.0019 | 0.0019 | +0.0000 |

A real recording id scores a **perfect 1.0**. Everything else scores nothing at
all. That is about as clean a ruler as this project has ever had.

Then run blind over **every 1-to-4-byte window at every offset** — including
unaligned ones, since a 16-bit id sitting at an odd offset is invisible to a
tidier sweep — across both packs:

| voice | best field found | above chance |
|---|---|---:|
| ScanSoft 2004 Tom | `+7 w4` | +0.058 |
| RealSpeak 2006 Tom | `+7 w3` | **+0.000** |

Against a ceiling of 1.0. That is not a close call.

⚠ And the run contains a trap worth keeping, because it fired. The first pass
proudly reported a field scoring a perfect 1.0000 — which turned out to be the
top half of the position field itself. Any slice of `pos` is contiguous in time
because that is what time is; it could not have scored anything else. It is now
kept deliberately, as the **positive control**: it proves the measurement can
reach 1.0 on these files, so the flat result everywhere else is a real absence
rather than a broken instrument.

**So neither engine carries a recording id, and now we know why.** The join
cost only ever asks "can B follow A naturally", which it answers by arithmetic
on the positions, and every other pairing was priced in advance at build time
(see below). The engine never needs to know which take a unit came from — so
that information was used when the voice was built and then dropped. Recording
membership survives *structurally*, in the position arithmetic and the 30 ms
guards, not as a number you can look up.

The scanner is kept as `rec_scan.py` in this folder.

**And it is not hiding elsewhere either.** The audio container was the last
plausible home. It does carry a 41 KB table of contents that the unit file
lacks — but that table is **byte-for-byte identical between the 2004 and 2006
packs**, and two different corpora cannot share per-recording data, so it is
codec tables. Past it, the audio is exactly frames and nothing else: 1,010,009
of them in the 2004 pack and 1,234,792 in the 2006 one, both dividing with zero
remainder, and the 2006 figure independently reproduces that voice's own
timeline to 3 parts per million.

The unit files close out the same way. The 2004 file has **zero bytes** left
after its tables — every byte is spoken for. The 2006 file's 358 KB remainder
is its model tables, and the voice font's own directory of them runs to within
400 bytes of the region's size.

So every byte of both packs is placed, and none of it is a recording map.

---

## What the two mystery sections turned out to be

The last 22.7 MB of the ScanSoft file — 58% of it — had no known purpose. It is
a **precomputed join-cost table**: for every pair of units the engine might want
to splice, the cost of splicing them, worked out when the voice was built and
stored. Section G is the lookup table that finds a unit's row in it.

Three predictions had to hold and all three did exactly, including
`G.max() + n_units = |H|` landing on the array size to the byte. It also
explains two earlier oddities for free: the 5,927 units that G marks dead are
*necessarily* the ones the big table never mentions, and the reason
engine-contiguous pairs are missing from it is that the code only consults it
for pairs that are **not** contiguous — the naturally-adjacent ones take a fast
path.

And the two index sections are the **preselect**: given a phone and its left and
right neighbours, hand back every unit worth considering. A/B/C serves left
half-phones, D/E/F right ones, with two fallback levels when the exact context
was never recorded. The key is a three-digit number in base 131, which finally
explains a constant that had been flagged as unexplained for weeks: both tables
max out at 2,247,959 because that is simply the largest number the encoding can
express — the same value appears in the 2006 pack over a completely different
corpus, for the same reason.

⚠ One thing is still open, and it blocks the obvious next step. Which of the
three digits is the phone itself is **not** yet pinned down, so candidate counts
for `radar` measured through this route have been **retracted** rather than
quoted.

---

## The 2006 pack is open too, and it is a different machine

The RealSpeak Solo v4 voice font gave up its own section directory, and the
comparison is striking:

| | ScanSoft 2004 | RealSpeak 2006 |
|---|---:|---:|
| units | 324,263 | **420,109** |
| corpus | 4.07 h | **4.98 h** |
| file | 39.2 MB | **20.2 MB** |
| join-cost table | 22.8 MB | **none** |

**A 30% bigger voice in half the space**, because 2006 threw away the
precomputed join-cost table entirely and spent the room on more recordings and
a wider phonetic context. Same format family — the preselect encoding is
provably identical — but a real architectural decision between the two.

Also worth recording: the 2006 file announces itself as `encrypt` in its header
and **is not encrypted**. Every structure in it reads as clean plaintext. The
word is a component name in the internal path the loader builds, not a
statement about the bytes. ⚠ What it *does* gate is still unknown, and one
component (`comrsrc.dll`) has not been looked at.

Also confirmed on the way: sections A/B/C are a **key → postings index** (the
key table tiles the posting list exactly, 835,567 of 835,567, with every
posting a valid unit id) — the same shape as Speechify's PRSL. They are a
lookup structure, not a timeline, which is why an early attempt to read them as
"recording → units" failed. That attempt is written up as a dead end rather
than quietly dropped.

---

## Prosody: which side are they on?

The interesting question was never really the file format. Speechify 3 came
from SpeechWorks; ScanSoft bought SpeechWorks in 2003 and became Nuance in
2005. If the lost Speechify 4 is prosodically closer to ScanSoft than to
Speechify 3, the natural reading is that **S4 is a ScanSoft-lineage engine
rather than an evolution of Speechify 3** — which would explain the whole "same
voice data, different prosody" puzzle at a stroke.

There is one place S3 and S4 are known to differ mechanically: **S3 puts no
silence at all between words, and S4 puts a gap at every single one** — about
22–24 ms each, found by the real S3 engine and confirmed by an independent
acoustic sweep. So: which do ScanSoft and RealSpeak do?

All three engines run locally, so this needs no broadcast recordings at all.
The trick is the carrier phrases: they are built from words containing **no
stop consonants anywhere**, because a /p/ or /t/ closure is real silence and
would be indistinguishable from an inserted gap. Between sonorants there is
nothing, so any silence found is the engine's doing.

| engine | gaps per word boundary |
|---|---:|
| Speechify 3 (our byte-exact engine) | 0.10, all at the detector's floor |
| **ScanSoft 2004** | **0.00** |
| **RealSpeak 2006** | **0.00** |
| Speechify 4 would predict | ~1.00, at 20–30 ms each |

**Neither inserts anything. They sit with S3.** Cleaner than S3, in fact — our
own engine's four tiny gaps are 9–15 ms against an 8 ms floor, and ScanSoft and
RealSpeak have literally none. The comma phrases confirm the measurement can
see silence when it is there, in all three engines.

### The more interesting consequence

Three engines spanning 2003 to 2006 — one from each side of the acquisition —
all insert **zero**. That makes S4's behaviour odd for the entire generation
rather than a house style one lineage had. Which raises a question nobody has
asked: **is that gap the engine at all, or the message-assembly system
downstream of it?** Something that stitches together word- or phrase-level
audio would leave exactly this fingerprint, and the project's single strongest
"the engines differ" claim rests on it.

### So we settled it, and the claim does not survive

The direct NOAA download never passed through a transmitter, so it decides
whether the broadcast chain put the gaps there. It didn't — silences of exactly
the reported length, median **23 ms**, are already in the direct audio.

But then the same text was put through all four engines — the real S4
recording, our Speechify 3, ScanSoft and RealSpeak — through the same codec,
measured with the same aligner, at all 141 word boundaries of the same message:

| | silence at a word boundary | same search mid-word |
|---|---:|---:|
| **Speechify 4 (real recording)** | **7.8%** | 2.8% |
| Speechify 3 (our engine) | 1.4% | 3.5% |
| ScanSoft | 2.8% | 5.0% |
| **RealSpeak** | **12.1%** | 9.2% |

RealSpeak is the one that settles it. We had already proved it inserts
**nothing** between words — and it still scores the highest of anyone here.
So around 12% is simply what ordinary speech looks like to this measurement,
and **S4's 7.8% is lower than an engine that inserts none at all.**

"A gap at every word boundary" would be ~100%. The measured figure is 7.8%,
beneath a known-zero control. **The claim does not hold at the size it was
stated.** What does survive is smaller and worth keeping: 23 ms silences really
are in the direct S4 audio, they are not the transmitter's doing, and S4 shows
the biggest gap-at-boundary-versus-mid-word difference of any engine tested
(+5.0%). Something is there. It is not what was claimed.

⚠ One message, one set of settings. This kills the magnitude, not the idea.

---

## What was already answered without any of this

The tip was testable directly, because both ScanSoft Toms are registered
**32-bit** SAPI5 voices (a 64-bit host cannot see them). Driving them through
SAPI on Windows 11 and measuring with the same forced aligner used for the
off-air work:

| render | `radar` | vs off-air 323 ± 17 ms |
|---|---:|---|
| Speechify 3.0.5 `radar` | 363 ms | **outside**, +2.36 sd |
| Speechify 3.0.5 `ray dar` | 363 ms | byte-identical to the above |
| ScanSoft 2004 `radar` | 302 ms | inside |
| ScanSoft 2004 `ray dar` | 302 ms | same to the aligner's ~20 ms grid |
| RealSpeak 2006 `radar` | 343 ms | inside |

Both engines give `ray dar` and `radar` the same word, so the two-word
treatment is a family trait. **The excess length is not** — ScanSoft sits
inside the broadcast band and Speechify 3.0.5 does not.

---

## Files here

| file | what it is |
|---|---|
| `README.md` | this — the plain-English summary |
| `README_TECHNICAL.md` | the living technical document: offsets, layouts, open questions, retractions |
| `ss_inventory.py` | contiguity search over the packed stream ⚠ read its docstring before comparing anything to `inventory.py` |
| `rec_scan.py` | the recording-id scanner. Run `--calibrate` first, always |

⚠ **Before spending anything more on "are the 300-tick gaps really cuts":** it
was attacked from the audio and came back INCONCLUSIVE — not because the
measurements disagreed, but because the floor control was itself a join, and
because an ACELP decoder launders a coded-domain splice. `README_TECHNICAL` §6d
has what was measured and exactly what would be needed to do it properly.
