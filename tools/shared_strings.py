import os, re, sys, collections
from concurrent.futures import ThreadPoolExecutor
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPFY = os.path.join(os.path.dirname(ROOT), "Speechify")

ROOTS = {
    "SS": ROOT + r"\ScanSoft\speech\components",
    "RS": ROOT + r"\RealSpeak\speech\components",
    "SPFY": SPFY + r"\bin",
}
# CRT / Win32 noise that every MSVC binary carries
NOISE = re.compile(rb"(?i)(runtime error|microsoft|kernel32|user32|advapi|msvcr|msvcp|"
                   rb"GetProc|LoadLibrary|_initterm|SetUnhandled|IsDebuggerPresent|"
                   rb"Interlocked|Critical|TlsAlloc|HeapAlloc|VirtualAlloc|GetModule|"
                   rb"FlsAlloc|R60\d\d|DOMAIN error|SING error|TLOSS|abnormal program|"
                   rb"pure virtual|bad allocation|`[a-z ]+'|\.CRT|\.rdata|\.text|\.data|"
                   rb"This program cannot|Rich|GetLast|CloseHandle|WriteFile|ReadFile|"
                   rb"CreateFile|MultiByte|WideChar|GetString|GetEnvironment|SetFilePointer|"
                   rb"FreeLibrary|ExitProcess|TerminateProcess|GetStartupInfo|GetCommandLine|"
                   rb"GetVersion|GetCurrent|LCMap|GetCPInfo|GetACP|GetOEMCP|RtlUnwind|"
                   rb"SetHandleCount|GetStdHandle|GetFileType|HeapCreate|HeapDestroy|"
                   rb"HeapFree|HeapReAlloc|HeapSize|VirtualFree|SetStdHandle|FlushFileBuffers|"
                   rb"RaiseException|UnhandledExceptionFilter|QueryPerformance|GetTick|"
                   rb"GetSystemTime|Sleep|WaitFor|SetEvent|CreateEvent|ResetEvent|"
                   rb"Reg[A-Z][a-z]+|SysAllocString|CoCreate|CoInitialize|CoTaskMem|"
                   rb"ole32|oleaut32|winmm|wave[A-Z]|mmio|GetSystemInfo|OutputDebugString|"
                   rb"__CxxFrameHandler|_except_handler|_purecall|std::|GetTimeZone|"
                   rb"WideCharToMultiByte|CompareString|GetLocaleInfo|GetUserDefault|"
                   rb"EnumSystemLocales|IsValidCodePage|IsValidLocale|GetDateFormat|"
                   rb"GetTimeFormat|GetStringType|SetEnvironment|GetFullPathName|"
                   rb"MessageBox|GetActiveWindow|GetLastActivePopup|DllMain|DllRegister|"
                   rb"DllUnregister|DllCanUnload|DllGetClassObject|CorExitProcess|mscoree|"
                   rb"January|February|Sunday|Monday|Saturday|Thursday|Wednesday|"
                   rb"December|November|October|September|August|\(null\)|"
                   rb"^[A-Z][a-z]+[A-Z][A-Za-z]+(A|W|Ex|ExA|ExW)?$)")

def strings(path):
    d = open(path, "rb").read()
    out = set()
    for m in re.finditer(rb"[\x20-\x7e]{8,}", d):
        s = m.group()
        if not NOISE.search(s):
            out.add(s)
    for m in re.finditer(rb"(?:[\x20-\x7e]\x00){8,}", d):
        s = m.group().replace(b"\x00", b"")
        if not NOISE.search(s):
            out.add(b"W:" + s)
    return out

def gather(tag):
    files = []
    for dp, _, fs in os.walk(ROOTS[tag]):
        for f in fs:
            if f.lower().endswith((".dll", ".exe", ".ocx")):
                files.append(os.path.join(dp, f))
    owner = collections.defaultdict(set)
    with ThreadPoolExecutor(24) as ex:
        for p, ss in zip(files, ex.map(strings, files)):
            for s in ss:
                owner[s].add(os.path.basename(p))
    return owner

def main():
    pools = {t: gather(t) for t in ROOTS}
    ssrs = set(pools["SS"]) | set(pools["RS"])
    shared = ssrs & set(pools["SPFY"])
    print(f"SS strings {len(pools['SS'])}  RS {len(pools['RS'])}  SPFY {len(pools['SPFY'])}")
    print(f"SS&RS {len(set(pools['SS']) & set(pools['RS']))}   (SS|RS)&SPFY {len(shared)}")
    for s in sorted(shared, key=lambda x: -len(x))[:int(sys.argv[1]) if len(sys.argv) > 1 else 200]:
        a = sorted(pools["SS"].get(s, set()) | pools["RS"].get(s, set()))[:3]
        b = sorted(pools["SPFY"][s])[:3]
        print(f"{s.decode('latin-1')[:90]!r:94} {','.join(a)} | {','.join(b)}")

if __name__ == "__main__":
    main()
