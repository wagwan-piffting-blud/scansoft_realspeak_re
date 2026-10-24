# ScanSoft 2004 / RealSpeak Solo v4 2006 vs Speechify: Engine Internals

> **Status:** Live, started 2026-10-23. This file is the plain-English summary.
> `README_TECHNICAL.md` has the binary detail (offsets, struct layouts,
> measurements) and `DLL_ANALYSIS.md` has the per-DLL reverse engineering.
> The three are kept in sync.
>
> Everything here is measured or read out of the disassembly. Guesses are
> marked INFERRED. Retractions stay on the page with the reason.

**Prior art, kept here historically:** `OLD_README.md` and `OLD_README_TECHNICAL.md`
(2026-08-10/11). They decode the unit database (`useld`), the preselect, the
position/length tiling, the precomputed join-cost table, and the `radar` work.
This folder builds on them and corrects them where noted (see "Corrections to
the `ss_rs` notes" at the bottom).

---

## What is on disk

| we call it | working copy | build dates | voices |
|---|---|---|---|
| **ScanSoft** (NextUp pack) | `ScanSoft\speech\` | 2004-07 … 2005-01 | Tom (enu), Kyoko (jpj), Narae (kok) |
| **RealSpeak** (Solo v4) | `RealSpeak\speech\` | 2004-10 … 2006-08 | Tom, Jill, Samantha (enu); Daniel, Emily (eng); Karen, Lee (ena); Isabel (spe); Paulina (spm) |
| **Speechify 3.0.5** | `..\Speechify\bin\` | 2005-02-15 | Tom, Jill, Paulina, Javier, Felix |

Both ScanSoft and RealSpeak have the same layout: `components\{common,g2p,pp,synthesizer,voicefont,xlit,data}`
plus plain-text `rssolov4\*.hdr` files that declare the component graph.

**Paths in these notes.**
- Paths are relative to this folder (`ssrs_re`).
- `..\Speechify` is the sibling Speechify checkout.
- `%TEMP%\claude\<session>\` is a Claude Code session scratch folder.
- `C:\tmp\…` is local build and render output, not kept.
- The tools in `tools\` locate both folders from their own path, so they run from any checkout
  that keeps the two side by side.

**Decoded corpora (SSoT).** `ScanSoft\ss_tom_full.wav` and `RealSpeak\rs_tom_full.wav` are the
full Tom bodies from the fixed `codsb_dump` (D1+D2). They sit inside the git-ignored pack
folders (`.gitignore`). `tools\tom_overlap.py` (`SS_WAV` / `RS_WAV`) and the `hybrid16_*`
tools read them from there.

⚠ **The ScanSoft pack's `synth_155mrf22.dll` is not a 2004 file.** It is the
2006 Nuance build (FileVersion 4.0.2.6136, PE stamp 2006-05-16), byte-identical
to RealSpeak's. The other two synth DLLs in that folder are the 2004 originals.
Someone dropped the newer decoder into the NextUp install. Everything we know
about the `codsb` codec was read from the 2006 build.

---

## Q1. How related are they to Speechify?

**Short answer: a different engine underneath, with a Speechify unit-selection
design transplanted into it.** Neither "descended from Speechify" nor
"unrelated" is right.

### The chassis is L&H RealSpeak

Every piece of build forensics points the same way, and none of it matches Speechify:

| | Speechify 3.0.5 | ScanSoft 2004 / RealSpeak 2006 |
|---|---|---|
| compiler | MSVC 7.1 (13.10.3077) | **MSVC 6.0** (Rich 8966/8797) |
| build root | `C:\Speechify_3.0.5\Build_5046\i386-win32\...` | `F:\ttssrc.a\win32.x86\rel\tts_predev_prd\...` |
| version control | CVS `$Id$` in every module | none at all |
| framework | SBlog, VXI, SWIutil, Xerces, Flite | `CDF` components, `paramc_*`, `heap_*`, `brk_*` broker |
| front end | ETI-Eloquence Delta rules | `g2p_*.dll` + `stdpp_*.dll` / `empp_*.dll` |
| audio store | 8 kHz G.711 μ-law (`.vdb`) | 22 kHz **ACELP** (`codsb`) |
| waveform engine | WSOLA | LPC synthesis from ACELP parameters |
| vendor marks | SpeechWorks | `Lernout & Hauspie Speech Products (tm) N.V.` (`empp_*.dll`, 1993–2000), `lh_ErrorGetString`, `L&H TTS ActiveX`, `L&H: %s SAPI5: %d` |

The clearest single marker: **the Tom voice font was cloned from a template called Jennifer.**
Both packs' `vf_tom_full.dll` (and RealSpeak's `vf_jill_full.dll`) carry the
banner `CDF vf_jennifer_full 1.00`. Jennifer was the name of L&H RealSpeak's
US English female voice (public record, not from the binaries).

The dates rule out "predecessor" too. The ScanSoft pack's DLLs are dated
mid-2004, earlier than Speechify 3.0.5 (Feb 2005).

### But the unit selection borrowed Speechify's design

This is the part that surprised us. The two engines share **no object code**:
an instruction-sequence comparison of every function finds nothing above the
C-runtime noise floor. But the 2004 ScanSoft unit selection runs Speechify's
algorithms, rewritten in integer arithmetic (1.0 = 100,000):

- **Join-cost fallback:** the same three gates, the same table index, the same 0.6 scale.
- **Join-cost lookup table:** the same row-displacement sparse matrix, with the same
  `0xFFFFFFFF` empty-slot markers.
- **Pruner:** the same 40-bin histogram with the same cut rule and the same 0.005 slope.
- **One table copied outright.** The 100-byte duration-continuity table in
  ScanSoft's `vf_tom_full.dll` (`DAT_100b75b0`) is **Speechify Tom's own table**
  from `tom.vin`, multiplied by 10 and floored. All 100 entries match, verified
  twice. It is not in Speechify's Jill, Paulina, Javier or Felix, so it is
  output of Tom's voice build, not an engine constant.

So ScanSoft took a SpeechWorks unit-selection design (and at least one of Tom's
voice-build outputs) and rebuilt it inside the L&H RealSpeak framework. That
happened after the 2003 acquisition and before the 2004 voice-font build.

RealSpeak 2006 keeps evolving the same source tree. It drops the precomputed
join table for a runtime join cost that still has Speechify's three-point shape,
it drops the histogram pruner, it goes from 8 to 12 target sub-costs, and it
retrains the duration table.

### The only Speechify link at the API level

`swisolo.dll` (the same file in both packs) exports the **entire Speechify C API**:
`SWIttsInit`, `SWIttsOpenPortEx`, `SWIttsSpeakEx`, and the rest, plus
`SWIttsPause`/`SWIttsResume`, which Speechify never had. It is a ScanSoft
VC6 build that imports only `comrsrc`/`combrk`: a compatibility shim so Speechify
customers could point their code at RealSpeak Solo. It contains no Speechify code.

Corporate dates, from public record (not from the binaries): ScanSoft bought
L&H's speech business in Dec 2001 and SpeechWorks in Aug 2003, then merged with
Nuance and took its name in Oct 2005. The 2006 DLLs' CompanyName flips to
"Nuance Communications, Inc.", which agrees.

---

## Q3. The audio: what `codsb` is and how it decodes

Each voice keeps its audio in `vf_<voice>_full_155mrf22_270_06.dat`: a
`SCANSOFT` container of type `codsb` ("coded speech database").
The decoder is `synth_155mrf22.dll`. A working reimplementation
already exists: `codsb\` (`codsb_dump`), and it produced the
full-corpus WAVs in `C:\tmp\codsb_corpus\`. `codsb\README.md`
documents the tool itself.

### The file

```
0x00   144-byte SCANSOFT header (magic 0xFEFF, "SCANSOFT", "codsb", coder "155mrf22", toc_len, ...)
0x90   41,032-byte codec header: version, MODE, lookback, then the LSF codebook
0xa0d8 frames, end to end, nothing else
```

The codec header (the "TOC") is a **per-voice trained LSF codebook**: 5 stages
of 256 sixteen-coefficient vectors. Each of the 12 voices has its own, with one
exception: **the two Toms share a codebook byte-for-byte**. So the 2006 Tom was
encoded with the 2004 Tom's codebook, even though not one coded frame is shared
between them (7 of 1.23 M, chance level).

### The codec

ACELP, a CELP family member closely related to ITU G.729, tuned for 22,050 Hz:

- **Frames and subframes:** 320-sample frames (14.5 ms) in 4 subframes of 80.
- **Spectrum:** order-16 LPC, sent as 5-stage vector-quantised LSFs and
  interpolated per subframe.
- **Pitch:** a pitch lag every subframe, absolute on even subframes and a delta
  on odd ones, plus a pitch gain.
- **Pulses:** 1 to 3 stages of algebraic pulse codebooks (4 or 5 pulses each).
- **Gains:** a G.729-style moving-average predictor in the log domain. The 4
  coefficients are exactly G.729's 0.68 / 0.58 / 0.34 / 0.19.
- **Output:** an LPC synthesis filter, then a DC-blocking high-pass.

`155mrf22` names the **decoder family**, not the bitrate. One DLL serves three modes:

| mode | bytes/frame | bits | nominal rate | stages | pulses/stage |
|---:|---:|---:|---:|---:|---|
| 1 | 28 | 224 | 15.5 kbps | 1 | 5 |
| 2 | 37 | 296 | 20.4 kbps | 2 | 4, 4 |
| 3 | 49 | 392 | **27.0 kbps** | 3 | 5, 4, 4 |

Every shipped voice is **mode 3**. That is the `270` in the filename, and the
mode is stored in the codec header (`u16[1] = 3`). The old notes said the mode
had to be guessed. It doesn't.

### How a unit's audio is fetched

The unit database gives a start position and a length. The synth DLL:

1. adds a fixed 40-sample codec delay to the start,
2. backs up 6 frames (`OVERHEADFRAMES = 6` in the `.hdr`),
3. resets the decoder,
4. decodes from there and throws away the warm-up samples.

That warm-up is why a unit's audio starts 87 ms "before" its position. The old
notes found that offset from the audio alone; the code now confirms it.

### How good the reimplementation is

`codsb_dump` produces clean, intelligible speech. It is not bit-exact, and
Ghidra now shows exactly where it departs from the engine. In order of audibility:

1. ✔ **Pitch sharpening: FIXED 2026-10-23.** When the pitch lag is shorter than
   a subframe, the engine filters the pulse vector with the previous subframe's
   pitch gain. This is the G.729 trick for high voices. Kyoko has short lags in
   34.5% of subframes, Tom in 9%.
2. ✔ **Output high-pass: FIXED 2026-10-23.** It is `y = x − x₁ + 0.99·y₁`. (The
   code comment called it a postfilter; it isn't one.) The DC offset is now ~0.
3. **Gain-predictor history starts at 0** instead of the engine's `0xE400`
   (−7168) ×4.
4. **The LSF ordering rule differs.** The engine's stabiliser mode for this data
   is 0: at most two bubble-sort passes and **no** minimum spacing. The tool
   imposes a full sort and a 40-unit gap.
5. **The starting LSF differs.** The engine starts from a flat spectrum; the
   tool starts from the first frame.

Items 3 and 5 only affect the first frames after a reset. Item 4 matters only
when the coded LSFs arrive out of order. The A/B numbers for items 1 and 2 are in
`codsb\README.md`. Listening pairs: `C:\tmp\codsb_ab\{kyoko,tom04}_{old,new}.wav`.

---

## Q2. How these notes are organised

| file | what it holds |
|---|---|
| `README.md` | this: the plain-English answers |
| `README_TECHNICAL.md` | the living technical document: container and codec-header layouts, decoder state struct, frame pipeline, measurements, corrections |
| `DLL_ANALYSIS.md` | per-DLL RE: build forensics, `synth_155mrf22.dll` function map, the three-way unit-selection comparison, `swisolo.dll`, `vf_GetInterface` |
| `tools\` | every probe used here; each script takes paths on the command line or has them at the top |
| `codsb\` | the audio container decoder (sources, `build.bat`, `README.md`, `build\codsb_dump.exe`) |

---

## Corrections to the `ss_rs` notes

These are not reruns. Each one changes a claim in
`Speechify\reveng\ss_rs\README_TECHNICAL.md`:

- **§1, header +0x84** was called a "per-pack build stamp". It is not.
  `265498` appears in both packs (ScanSoft Tom/Kyoko/Narae **and** RealSpeak
  Daniel/Isabel/Jill/Karen/Lee). `822349082` is RealSpeak Paulina/Samantha/Tom.
  `839126298` is RealSpeak Emily. It identifies a voice-build batch, and it
  still pairs a voice's `useld` with its `codsb`.
- **§6h, "the `codsb` TOC is codec tables because both packs share it".** The
  TOC is a per-voice LSF codebook; 11 distinct codebooks across 12 files. It
  matches between packs only because the two Toms share one. The conclusion that
  it is not a recording map still stands.
- **§0, "`synth_155mrf22.dll` is byte-identical across packs".** True for the
  file, but only because the NextUp install carries the 2006 build (see the top
  of this file).
- **§6d, "are the 300-tick gaps really cuts" (INCONCLUSIVE there).** They are
  not. Audio locked to a Speechify recording runs straight across them: 344
  gaps fall *inside* locked runs, and run ends land near a gap at chance rate.
  The real cuts in the store are elsewhere, and the contiguous pieces run
  ~0.4–0.5 s, not the ~0.2 s gap-to-gap "stretches". The "repacked" conclusion
  stands; its unit was wrong. See `README_TECHNICAL.md` §10.
- **§6f, record bytes +13/+14** are edge-duration values that feed the
  duration-continuity join fallback, not F0 or energy. INFERRED from the
  line-for-line match with Speechify (`DLL_ANALYSIS.md` §3).

---

## Answered

- **Is it the same Tom?** **Yes. All three Toms (Speechify, ScanSoft 2004,
  RealSpeak 2006) are Tom Glynn, the Boston voice-over talent.** Source: the
  user, 2026-10-23; the binaries carry no talent name. This fits everything
  measured:
  - **Speechify ↔ ScanSoft 2004:** they share Tom's duration table, which is
    output of his voice build.
  - **ScanSoft 2004 ↔ RealSpeak 2006:** they share an LSF codebook and the `173`
    tag.
  - **The audio is still three separate builds.** Speechify is 8 kHz μ-law and
    cannot be the source of 22 kHz ACELP. The two ACELP Toms share 7 coded frames
    out of 1.2 M, and their unit counts and corpus lengths differ (4.07 h vs 4.98 h).
- **Do the recordings themselves overlap? YES, in both packs. MEASURED 2026-10-23.**
  ScanSoft 2004 and RealSpeak 2006 each contain stretches of **the same physical
  takes** that are in Speechify's `tom8.vdb`, re-coded. Not just the same man
  saying the same words: the same recording.
  - **The test** (`tools\tom_overlap.py`, `tom_overlap_runs.py`) is waveform
    correlation at 8 kHz. Two different takes of a word never line up sample by
    sample, so it cannot be fooled by "sounds the same". It was calibrated
    against a null of Tom vs *other* Tom takes inside Speechify itself.
  - **The result:**
    - 15% of random 200 ms ScanSoft speech windows and 6% of RealSpeak ones
      beat that null's 99.9th percentile; the null rate is 0.1%.
    - Of those hits, 198/200 in each pack **stay locked** when the window
      slides along the corpus, at a time slope of exactly 1.0000.
    - They spread over 193 different Speechify recordings, from 14 of its 18
      prompt families.
  - **What it means:** the 2004 and 2006 voices were built (at least partly)
    from Tom Glynn's SpeechWorks session audio: the masters that Speechify's
    8 kHz database was also made from.
  - **Every direction, all lock-confirmed at slope 1.0000:**
    - **~23% of Speechify's windows are in ScanSoft 2004 and ~8% in RealSpeak 2006.**
    - **ScanSoft 2004 and RealSpeak 2006 share takes directly: 36% of ScanSoft's
      windows are in RealSpeak, and 27% the other way.** Most of that shared audio
      is *not* in Speechify at all.
    - So ScanSoft had a larger pool of Tom Glynn session audio than Speechify's
      8 kHz subset, and built both voices from it.
    - The 2006 voice is a fresh encode of those masters, not a copy of the 2004
      file: zero coded frames are shared.
    - In hours, as rough floors: ≥ 0.7 h of Speechify inside ScanSoft, and
      ≥ 1.8 h shared between ScanSoft and RealSpeak.
  - **Same sessions or later ones?** The room-tone check is inconclusive. The
    non-Speechify shared audio is acoustically close to the Speechify-shared
    audio, but a little quieter in the noise floor and brighter up top, in both
    packs. Content type could explain that just as well as a different studio
    day (`README_TECHNICAL.md` §10.7).
  - **Is ScanSoft's extra audio from the same script? OPEN, and leaning no
    for the news script.**
    - Speechify kept every numbered SpeechWorks prompt, so the extra audio
      isn't "dropped prompts".
    - Templates of Tom's own Speechify words, searched for *other takes* in
      ScanSoft's non-Speechify audio, find:
      - common words (34%)
      - letter names and numbers (`ess`, `aitch`, `doubleyou`, `seventy`)
      - **no** news-specific words: Belgrade, Barak and the Hague turned out
        to be Speechify's own takes. The user caught that by ear, and the first
        run's "probably yes" is retracted.
    - So there's no sign of retakes of the news script in the extra audio.
    - The files themselves (`DLL_ANALYSIS.md` §6) carry no recording date,
      only build dates: Speechify May 2003, ScanSoft June 2004, RealSpeak
      April–May 2006. The 2006 builds point to a Central-European build site.
    - Details: `README_TECHNICAL.md` §10.9–10.10.
  - **A real 16 kHz Speechify Tom? DONE and deployed (H8, 2026-10-23).**
    About **47% of Tom's speech time** has a genuine 22 kHz source in ScanSoft or
    RealSpeak; almost no recording is fully covered, so a pure build is impossible.
    - The winner, after eight variants judged by ear, is **H8** (§10.8.4):
      - **below 4 kHz:** the real ScanSoft/RealSpeak take wherever it is verified
        (35.5 of 123.7 min), resampled 22.05 → 16 kHz in one step onto tom8's exact
        timing and EQ'd to AudioSR's balance; AudioSR elsewhere
      - **above 4 kHz:** pure AudioSR everywhere, so the top band never changes source
    - **Installed as** `Documents\Speechify\en-US\tom\tom16.vdb`, a byte-for-byte drop-in.
      spfy plays it with `--16k`.
    - **What failed, and why it matters:**
      - The real takes' own 4–8 kHz is ~⅓ codec noise ("crunchy").
      - Mixing two different top bands is audible as Tom "fading between voices",
        however well the levels are matched.
      - The user's reference for "right" is AudioSR, not the real take.
  - **Listen:** `C:\tmp\tom_overlap\listen\*.wav`, stereo with left = Speechify,
    right = ScanSoft/RealSpeak, time-aligned. Clearest: `ss_10`, `ss_08`,
    `ss_09`, `rs_05`, `rs_07`.
  - Details, controls and caveats: `README_TECHNICAL.md` §10.

## How RealSpeak 2006 actually speaks (engine round 2, 2026-10-23)

The plain-English version. Details are in `DLL_ANALYSIS.md` §7 and the three files in `notes\`.

- **The engine core is only a dispatcher.** `ttsengine.dll` passes each sentence through:
  - text-encoding conversion (`xcoder`, which handles text only, not audio)
  - text clean-up
  - pronunciation
  - the voice font
  - the audio callback
- **Prosody is about where to pause, not how to pitch.** The voice font decides:
  - phrase breaks (a small decision tree)
  - pauses (a learned decision tree, four fixed lengths: 101/121/138/160)
  - stress and intonation *labels* (654 rewrite rules)
  It never computes a pitch curve or target durations.
- **The melody and timing are the recordings'.** Unit selection picks recorded pieces
  whose labels fit, and their own pitch and timing are what you hear.
  - The synthesizer joins them in one of four ways: a short fade, a pitch-peak-aligned
    crossfade, a correlation-aligned crossfade, or a fade with a pause.
  - It never shifts pitch.
  - Speed change (WSOLA) and volume come after the joins.
- **The "pitch" setting does nothing (tested).** It is accepted, range-checked and stored,
  but no other component reads it.
  - Pitch tags (`ESC\pitch=…\`, SAPI `<pitch>`) and even per-sound pitch and length targets
    in phonetic input give byte-for-byte the same audio as no tag at all.
  - Speed, volume and pauses do work. See `notes\pitch_control_test.md`.
- **This differs sharply from Speechify,** which predicts a pitch curve and durations with
  CART trees and uses them to choose units.

## How RealSpeak reads text (front end, 2026-10-23)

The plain-English version. Details are in `DLL_ANALYSIS.md` §8 and four files in `notes\`.

- **Text clean-up (`stdpp`) only cuts and tags.** It finds sentence ends (with a
  210-abbreviation list so "Dr." does not end one), applies the reading mode, and spots URLs
  and e-mail addresses. It also turns embedded control tags into markers. It does not expand
  numbers or dates.
- **Pronunciation (`g2p`) does the real language work.**
  - It expands numbers, dates, currency and units (69 "say-as" modes).
  - It looks words up in a 34,813-word lexicon.
  - It tags parts of speech and resolves homographs (`read`, `lead`, `wind`, …).
  - It sounds out unknown words with ~680 hand-written rules.
  - All of it is one program of 4,517 rewrite rules, the same rule engine the voice font uses
    for prosody.
- **ScanSoft 2004 had an e-mail mode (`empp`).** This alternative clean-up stage read mail
  headers, time zones, domain names and smileys. RealSpeak 2006 dropped it.
- **2004 → 2006 is the same front end, grown.** 99.5% of lexicon entries are unchanged, and
  the rules grew by a third, mostly new say-as handling.
- **Nothing is shared with Speechify's front end** (ETI-Eloquence), in code or in data.
  Nothing in it is Tom-specific either.

## Open questions

- Codec-header words that no function examined so far reads:
  - `u16[3]`: 50 for most voices, 47 for Daniel/Emily/Lee/Samantha
  - blob ints `[11]`, `[13..15]`: `3, 0x5400, 60, 0x7EFA0000`
- Why the 2004 Tom body has 11,852 duplicate frames (1.17%) while the 2006 Tom
  has none at all.
- What the 2006 runtime join cost's three 7-bit feature codes are.
