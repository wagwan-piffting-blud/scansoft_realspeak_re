@echo off
rem build.bat -- build codsb_dump with MSVC. Run from PowerShell, not cmd.
rem
rem   cd %USERPROFILE%\Documents\ssrs_re\codsb
rem   .\build.bat
rem
rem Zero warnings at /W4 /WX is the standing bar for this repo.
rem
rem NOTE: goto-based flow, not parenthesised if-blocks. A literal "(x86)" in an
rem expanded path inside a ( ... ) block terminates the block early and cmd
rem misparses the rest -- that cost a build cycle here.

setlocal

set "VC2022=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
set "VC18=C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat"
set "VCBT19=C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat"

set "VCVARS="
if exist "%VC2022%" set "VCVARS=%VC2022%"
if not defined VCVARS if exist "%VC18%" set "VCVARS=%VC18%"
if not defined VCVARS if exist "%VCBT19%" set "VCVARS=%VCBT19%"
if not defined VCVARS goto no_msvc

call "%VCVARS%" >nul
if errorlevel 1 goto vcvars_failed

if not exist build mkdir build

cl /nologo /W4 /WX /O2 /MT /D_CRT_SECURE_NO_WARNINGS /Fobuild\ /Fdbuild\ /Febuild\codsb_dump.exe codsb.c acelp.c decode.c tables.c main.c
if errorlevel 1 goto compile_failed

echo build: OK -^> build\codsb_dump.exe
endlocal
exit /b 0

:no_msvc
echo build: no vcvars64.bat found; install the VC++ toolset
endlocal
exit /b 1

:vcvars_failed
echo build: vcvars64 failed
endlocal
exit /b 1

:compile_failed
echo build: FAILED
endlocal
exit /b 1
