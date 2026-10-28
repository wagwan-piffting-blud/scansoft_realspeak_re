@echo off
rem build.bat -- opstep.exe: one instruction per case through the oracle's cpu.c.
rem Used by `cargo run -p xtask -- opgate`. Toolchain: MSYS2 mingw64 gcc, the
rem same compiler and flags as ..\emu\build.bat. Run from PowerShell.
setlocal
if "%MSYS_ROOT%"=="" set "MSYS_ROOT=C:\msys64"
set "GCC=%MSYS_ROOT%\mingw64\bin\gcc.exe"
if not exist "%GCC%" goto no_gcc
set "PATH=%MSYS_ROOT%\mingw64\bin;%PATH%"
cd /d "%~dp0"
if not exist build mkdir build
"%GCC%" -O2 -g -std=gnu11 -Wall -Wno-unused-function -Wno-unused-variable -Wno-unused-but-set-variable ^
    -o build\opstep.exe ^
    opstep.c ..\emu\cpu.c ..\emu\mem.c ..\emu\recomp_stub.c -lm
if errorlevel 1 goto compile_failed
echo build: OK -^> build\opstep.exe
endlocal
exit /b 0

:no_gcc
echo build: gcc not found at "%GCC%"
endlocal
exit /b 1

:compile_failed
echo build: FAILED
endlocal
exit /b 1
