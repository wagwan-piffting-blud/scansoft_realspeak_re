# ss-rs-ng oracle (dev only)

These are the references the Rust engine is gated on. Nothing here ships.

| part | what it is | build |
|---|---|---|
| `native\` | `rs_native.exe`: loads the vendor `rssoloapi.dll` in a 32-bit process and drives it | `native\build.bat` (MSVC x86) |
| `emu\` | `rs_oracle.exe`: the same vendor DLLs under spfy's `host_emu` x86 interpreter, plus a multi-module loader | `emu\build.bat` (MSYS2 mingw64 gcc) |
| `corpus_gate.py` | renders `corpus_en.txt` through both in parallel and compares PCM | `python corpus_gate.py --pack realspeak\|scansoft` |
| `corpus_wide.txt` | 25 harder lines: numbers, dates, money, URLs, e-mail, abbreviations, inline `ESC` rate/pause/volume, a long paragraph. Oracle == native 25/25 on both packs (`--corpus corpus_wide.txt --out C:\tmp\ssrsng_gate_wide`) | |
| `opstep\` | `opstep.exe`: runs one instruction per case through `emu\cpu.c` unchanged; the M2 gate (`xtask opgate`) drives it | `opstep\build.bat` (MSYS2 mingw64 gcc) |

## Status (2026-10-27): M1 done

| check | RS 2006 Tom | SS 2004 Tom |
|---|---|---|
| emulator == native, 20-line corpus | **20/20 byte-identical** | **20/20 byte-identical** |
| native == installed SAPI voice | identical with `ESC\vol=100\` at the start of the text (the RS SAPI wrapper's fade from the default 80) | identical with `ESC\vol=60\` (the NextUp wrapper's level) |
| speed | native 0.1–0.4 s per line; emulator about 1.5–2× real time | same |

Both runs load the same 14 modules in the same order:
- `rssoloapi`, `comrsrc`, `combrk`, `ttsengine`
- `dcteg`, `xcoder`, `audiofetch`, `domain_mngr`, `rettt`
- `stdpp_enu`, `g2p_enu`, `vf_tom_full`, `synth_155mrf22`, `xlit_1252`

## The API (`rssoloapi.dll`, all cdecl, recovered in Ghidra)

```c
u32 ssft_ttsInitialize(const char *speech_dir, void *hcls[2]);        /* hcls = {ptr, 99999} */
u32 ssft_ttsOpen(void *hcls, u32 99999, const char *product,          /* "RealSpeak Solo v4.0" */
                 void *hinst[2], void *appdata);                       /* hinst = {ptr, 'mTTS'} */
u32 ssft_ttsSetParamList(void *h, u32 magic, tts_param *p, u16 n);    /* {u32 id; u16 num | char str[128]}, 0x84 B */
u32 ssft_ttsSetOutDevice(void *h, u32 magic, void *dev[2]);           /* {ctx, cb} */
u32 ssft_ttsSetText(void *h, u32 magic, u32 rec[3]);                  /* {0, len, char *text} */
u32 ssft_ttsProcess(void *h, u32 magic, 0);                           /* synchronous */
u32 ssft_ttsClose(void *h, u32 magic);
u32 ssft_ttsUnInitialize(void *hcls, u32 99999);
```

`ssft_ttsSpeak` is the asynchronous version: it runs through `tts/comsyssvc` threads and
`tts/audioout`. The oracle uses `ssft_ttsProcess`.

Parameter ids. The API id is translated to a ttseg id; per `ssft_ttsSetParamList` @`0x10003620`:

| API id | ttseg id | meaning |
|---|---|---|
| 0x01 | 2 | frequency (kHz: 8 / 11 / 16 / 22) |
| 0x02 | 7 | volume (default 80) |
| 0x04 | 5 | rate |
| 0x08 | 4 | |
| 0x10 | 8 | |
| 0x20 | 10 | |
| 0x40 | 3 | language, string (`American English`) |
| 0x80 | 6 | voice, string (`Tom`) |
| 0x100 | 0xb | typeofdoc, string |
| 0x400 | 0xd | typeofchar |
| 0x800 | 9 | |
| 0x1000 | 0x17 | reduction, string |
| 0x2000 / 0x4000 | 0x13 / 0x14 | custom G2P load / unload, string |
| 0x200 | — | API-side value stored at inst+0xd4 |

The output callback is `cb(hinst, magic, ctx, u32 msg[3], appdata)`, with `msg = {type, status, out*}`
and `out = {?, bytes, pcm*, nmarks, marks*}`:
- **type 8:** the app supplies a buffer by setting `out->pcm` and `out->bytes`.
- **type 0x10:** `bytes` of 16-bit PCM are ready at `pcm`. Status 0xffff marks the last
  block.
- **types 1 / 2:** start / end.

## Emulator changes against the donor

The donor is `..\..\..\Speechify\spfy\src\host_emu`, commit `1fbe62b3`; hashes are in
`emu\DONOR_SHA256.txt`.

- **`modules.c` (new, replaces `loader.c`):**
  - each module gets a 64 KB-aligned base from 0x10000000, in load order, and is relocated
  - guest-to-guest imports bind to exports; system DLLs go to the shim table
  - `_pctype` / `__mb_cur_max` / `_iob` are bound as data
  - DllMain runs through a nested guest call
- **`ssrs_shims.c` (new, overrides the donor by name):**
  - module-aware `LoadLibraryA` / `GetProcAddress` / `GetModuleHandleA` / `GetModuleFileNameA`
  - real `CreateFileA` / `ReadFile` / `SetFilePointer` / `GetFileSize`, plus
    `FindFirstFileA` and file mapping (read-only views cached in an arena at 0x62000000)
  - stdio and a full `sprintf` bridge
  - `_ftol`, `_isctype`, `wcs*`, `strtoul`, `strpbrk`, `strrchr`, `strncat`, and
    `time`/`ctime`, which return fixed values for determinism
- **`win32_donor.c`:** one hook in `win32_register_import`, consulting `ssrs_shim_lookup`
  first.
- **`emu.h`:** `MAX_REGIONS` raised from 32 to 64.
- **`recomp_stub.c`:** turns the recompiler hook off, so everything is interpreted.
- **`cpu.c` + `eiptrace.c`:** one hook before each instruction, compiled only with
  `-DSSRS_EIPTRACE`. `build.bat trace` builds `rs_oracle_trace.exe`, which writes every unique
  (previous EIP, EIP) pair to `%SSRS_EIPTRACE%`; `tools\xlate_cover.py` uses it. The normal
  `rs_oracle.exe` does not contain the hook, and stays 20/20 on both packs.
