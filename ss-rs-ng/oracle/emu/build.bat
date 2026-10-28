@echo off
rem build.bat -- rs_oracle.exe: the vendor engine under the host_emu x86 interpreter.
rem Dev-time oracle only. Toolchain: MSYS2 mingw64 gcc. Run from PowerShell.
rem `build.bat trace` also builds rs_oracle_trace.exe, which records every
rem (previous EIP, EIP) pair for tools\xlate_cover.py.
setlocal
if "%MSYS_ROOT%"=="" set "MSYS_ROOT=C:\msys64"
set "GCC=%MSYS_ROOT%\mingw64\bin\gcc.exe"
if not exist "%GCC%" goto no_gcc
set "PATH=%MSYS_ROOT%\mingw64\bin;%PATH%"
cd /d "%~dp0"
if not exist build mkdir build
set "SRC=rs_oracle.c modules.c ssrs_shims.c cpu.c mem.c win32_donor.c spfy_extra_shims.c host_glue.c recomp_stub.c eiptrace.c"
set "FLAGS=-O2 -g -std=gnu11 -Wall -Wno-unused-function -Wno-unused-variable -Wno-unused-but-set-variable -Wno-misleading-indentation"
"%GCC%" %FLAGS% -o build\rs_oracle.exe %SRC% -lm
if errorlevel 1 goto compile_failed
echo build: OK -^> build\rs_oracle.exe
if /i not "%~1"=="trace" goto done
"%GCC%" %FLAGS% -DSSRS_EIPTRACE -o build\rs_oracle_trace.exe %SRC% -lm
if errorlevel 1 goto compile_failed
echo build: OK -^> build\rs_oracle_trace.exe
:done
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
