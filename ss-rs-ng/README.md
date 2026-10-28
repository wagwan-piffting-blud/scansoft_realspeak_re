# ss-rs-ng

The **ScanSoft 2004** (NextUp) and **RealSpeak Solo v4 2006** text-to-speech engines, voice
**Tom**, as one native program for Windows, Linux and macOS.

It is not a re-voicing or an imitation:
- the vendor's x86 code was translated instruction for instruction into Rust;
- its output is **byte-identical** to the original engine;
- no vendor DLL is executed, and nothing Windows-only is needed at run time.

```text
ss-rs-ng --version realspeak "Hello there." hello.wav
ss-rs-ng "Hello there." -o hello.wav --speech ..\RealSpeak\speech
ss-rs-ng --file script.txt out.wav --speech ../ScanSoft/speech
echo "Spoken to standard output." | ss-rs-ng -f - -o - --speech ../RealSpeak/speech > out.wav
ss-rs-ng --serve --speech ../RealSpeak/speech < requests.tsv
```

## You (may) need the voice data

Tom ships by default (hence the large binary sizes), but other voices (such as Samantha, Jill, or other language voices like Kyoko, Narae, etc.) are not included, and are **officially unsupported in this re-implementation (for now)**. The engine needs its `speech` directory, which is usually installed in `C:\Program Files (x86)\NextUp-ScanSoft\speech` for ScanSoft 2004 or `C:\Program Files (x86)\ScanSoft\RealSpeakSolov4\speech` for RealSpeak 2006. You can specify it with `--speech <dir>`. The engine will not run without it on un-bundled builds. The engine will only run with Tom's files.

## Options

The positionals are `"text" [out.wav]`, or only `[out.wav]` with `--file`. Options can go
anywhere.

| option | |
|---|---|
| `-o, --out <path>` | WAV output, the same as the last positional; `-` is standard output. Default `speech.wav` |
| `-f, --file <path>` | read the text from a file; `-` is standard input |
| `--speech <dir>` | the install's `speech` directory |
| `--version scansoft\|realspeak` | which engine, if not detected |
| `--volume <0-100>` | default: what the installed SAPI voice uses (RealSpeak 100, ScanSoft 60), so output matches it |
| `--speed <n>` | speaking rate, 100 = normal |
| `--raw` | headerless 16-bit mono PCM |
| `--serve` | keep the engine warm. One request per input line, `<out path><TAB><text>`; one `ok …` or `error …` line per reply |
| `-q`, `-V`, `-h` | quiet; version and what is built in; help |

Text is UTF-8, or Latin-1 if it is not valid UTF-8. It is passed to the engine as
Windows-1252. The engine's own control sequences pass through, for example `ESC \pause=500\`.

## Speed

On a desktop the engine is ready in 0.03–0.04 s, or about 0.05 s with a cold file cache, and
speaks at roughly 20× real time. Most of the load is the engine reading its whole lexicon
(19 MB RealSpeak, 37 MB ScanSoft); built-in voice data is prefetched in bulk before it is
copied.

The first run of a new binary can take noticeably longer, because the OS checks the
executable (Windows Defender, macOS code-signature assessment, a few seconds for the 360 MB
universal binary). The same thing happens when it runs from a network share, where every page
the engine touches crosses the network. Copy the binary to a local disk.

## Building

```text
cargo build -p ss-rs-ng --release                     # needs --speech at run time
$env:SSRSNG_BAKE="rs,ss"; cargo build -p ss-rs-ng --release   # Tom built in (about 190 MB)
pwsh -File build_targets.ps1 -Bake rs,ss -Check
```

`build_targets.ps1` builds for 8 targets and, with `-Check`, requires every binary to render
the same bytes:
- Windows x64 and x86 (MSVC, static CRT)
- Linux amd64, x86, arm64, armv7 and armv6 (static musl)
- macOS universal (on a Mac over ssh, `build_macos.sh`)

The generated engine is checked in. Regenerating it needs the vendor DLLs and Python:
`python tools\x86xlate.py manifest` (needs the oracle), then
`python tools\x86xlate.py translate --pack rs|ss`.

## How it was checked

Every step is gated against the step before; `PLAN.md` has the details.

| step | what it shows |
|---|---|
| `oracle\` | the vendor engine, run natively and under an x86 interpreter: identical |
| `xtask opgate` | every instruction helper against the interpreter, on 50 million random states |
| `tools\xlate_cover.py` | every instruction the engine executes is translated |
| `xtask engcorpus` | the Rust engine against the real one on 45 sentences per engine, byte for byte, also as a 32-bit build |
| `tools\cli_check.py` | the program itself, one-shot and `--serve`, from disk and built in |

## License

GPL-3 for this code. The voices and the engine they came from belong to their respective owners. The engine is a derivative work of the vendor's x86 code, which is not officially open source. The engine is provided for personal use only.
