@echo off
rem build.bat -- 32-bit rs_native.exe (vendor engine driver, dev only). Run from PowerShell.
setlocal
set "VC2022=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars32.bat"
set "VC18=C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat"
set "VCVARS="
if exist "%VC2022%" set "VCVARS=%VC2022%"
if not defined VCVARS if exist "%VC18%" set "VCVARS=%VC18%"
if not defined VCVARS goto no_msvc
call "%VCVARS%" >nul
if errorlevel 1 goto vcvars_failed
cd /d "%~dp0"
if not exist build mkdir build
cl /nologo /W4 /WX /O2 /MT /D_CRT_SECURE_NO_WARNINGS /wd4311 /wd4312 /Fobuild\ /Febuild\rs_native.exe rs_native.c psapi.lib
if errorlevel 1 goto compile_failed
echo build: OK -^> build\rs_native.exe
endlocal
exit /b 0

:no_msvc
echo build: no vcvars32.bat found
endlocal
exit /b 1

:vcvars_failed
echo build: vcvars32 failed
endlocal
exit /b 1

:compile_failed
echo build: FAILED
endlocal
exit /b 1
