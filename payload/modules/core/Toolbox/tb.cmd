@echo off
rem Toolbox\tb.cmd - entry point of the project toolbox for cmd.exe and PowerShell.
rem Same contract as Toolbox/tb (POSIX sh); keep both in sync.
rem
rem   Toolbox\tb.cmd COMMAND [ARGS...]      runs Toolbox\agentic\cli.py
rem   Toolbox\tb.cmd run SCRIPT [ARGS...]   runs a script with uv (PEP 723 inline metadata)
rem
rem Bootstrap: uv from PATH if it is at least the minimum version below; else
rem Runtime\tools\uv\uv.exe; else download the pinned uv release with curl.exe, verify its
rem SHA256 with certutil against the values below and unpack it with tar.exe (all three are
rem built into Windows 10 1803 and later). Python and caches go to Runtime\ as well.
rem
rem "hook ..." (agent hooks) never blocks the agent: exit code 0 whatever happens, no downloads of
rem uv, Python or packages (offline; does nothing until "tb setup" prepared Runtime\).
rem
rem Environment: TB_ROOT (root override for the template's own tb, required by it; must contain
rem .agents\agentic.lock or setup\VERSION; ignored by the tb of an initialized project),
rem AGENTIC_UV_DOWNLOAD_URL (base URL of uv
rem releases; the asset is fetched from BASE/VERSION/ASSET), HTTPS_PROXY. UV_* variables that
rem are already set are respected. Exported to tools: AGENTIC_ROOT, PYTHONUTF8=1.
rem
rem No labels or GOTO on purpose: cmd.exe can fail to find labels when a batch file ends up
rem with LF line endings. The last line must stay one line that ends with the exit /b command,
rem because cmd.exe re-reads batch files from disk and init deletes this copy while it runs.

setlocal EnableExtensions DisableDelayedExpansion
rem Never run uv.exe, curl.exe or certutil.exe from the current directory.
set "NoDefaultCurrentDirectoryInExePath=1"

set "TB_UV_VERSION=0.12.23"
rem Oldest uv taken from PATH: 0.11.8, the first release with UV_NO_PROJECT (used by "run").
set "TB_UV_MIN_MAJOR=0"
set "TB_UV_MIN_MINOR=11"
set "TB_UV_MIN_PATCH=8"
rem SHA256 of the release assets of uv 0.12.23 (from the ASSET.sha256 files of the release).
set "TB_SHA_AMD64=75d05de6762778c31ee183398de7dd15093fad0ed90b1f236d8205ea5ec00c90"
set "TB_SHA_ARM64=13294e232ececbe709c06b74e6ced06f2a225ea5591476685362f22be56a50d5"

rem --- Paths -------------------------------------------------------------------------------
set "TB_DIR=%~dp0"
set "TB_DIR=%TB_DIR:~0,-1%"
for %%I in ("%TB_DIR%\..") do set "TB_HOME=%%~fI"
set "ROOT=%TB_HOME%"
if defined TB_ROOT for %%I in ("%TB_ROOT%\.") do set "ROOT=%%~fI"
if not exist "%ROOT%\" (>&2 echo error: TB_ROOT is not a directory: "%TB_ROOT%"& exit /b 1)
rem An inherited TB_ROOT (e.g. from template development) must not redirect a project's tb.
if /i not "%ROOT%"=="%TB_HOME%" if exist "%TB_HOME%\.agents\agentic.lock" (>&2 echo tb: TB_ROOT ignored: this Toolbox belongs to the project "%TB_HOME%"& set "ROOT=%TB_HOME%")
if defined TB_ROOT if not exist "%ROOT%\.agents\agentic.lock" if not exist "%ROOT%\setup\VERSION" (>&2 echo error: TB_ROOT "%TB_ROOT%" is neither an agentic project nor the template: no .agents\agentic.lock or setup\VERSION& exit /b 1)
set "TB_HOOK="
if "%~1"=="hook" set "TB_HOOK=1"
rem The template's own copy (payload\modules\core\Toolbox) is not a project: without TB_ROOT it would
rem put Runtime\ (uv, Python) into the payload, where git ignores it and init would install it.
set "TB_PAYLOAD="
if /i "%ROOT%"=="%TB_HOME%" if not exist "%ROOT%\.agents\agentic.lock" if exist "%TB_HOME%\..\..\..\setup\VERSION" if exist "%TB_HOME%\..\..\..\payload\modules\core\module.toml" set "TB_PAYLOAD=1"
if defined TB_PAYLOAD if defined TB_HOOK exit /b 0
if defined TB_PAYLOAD (>&2 echo error: this tb is the template's payload copy; run it from the template root with TB_ROOT=. - see AGENTS.md& exit /b 1)

rem --- Environment -------------------------------------------------------------------------
set "AGENTIC_ROOT=%ROOT%"
set "PYTHONUTF8=1"
if not defined UV_PYTHON_INSTALL_DIR set "UV_PYTHON_INSTALL_DIR=%ROOT%\Runtime\tools\python"
if not defined UV_PYTHON_BIN_DIR set "UV_PYTHON_BIN_DIR=%ROOT%\Runtime\tools\python-bin"
if not defined UV_CACHE_DIR set "UV_CACHE_DIR=%ROOT%\Runtime\cache\uv"
if not defined UV_PYTHON_PREFERENCE set "UV_PYTHON_PREFERENCE=only-managed"

rem --- uv, step 1: PATH --------------------------------------------------------------------
set "TB_UV="
set "TB_V="
for /f "tokens=2" %%V in ('uv --version 2^>nul') do if not defined TB_V set "TB_V=%%V"
set "TB_V1=0"
set "TB_V2=0"
set "TB_V3=0"
if defined TB_V for /f "tokens=1-3 delims=.-+" %%a in ("%TB_V%") do (set "TB_V1=%%a" & set "TB_V2=%%b" & set "TB_V3=%%c")
if not defined TB_V1 set "TB_V1=0"
if not defined TB_V2 set "TB_V2=0"
if not defined TB_V3 set "TB_V3=0"
rem Anything that is not a plain number counts as 0.
for /f "delims=0123456789" %%x in ("%TB_V1%") do set "TB_V1=0"
for /f "delims=0123456789" %%x in ("%TB_V2%") do set "TB_V2=0"
for /f "delims=0123456789" %%x in ("%TB_V3%") do set "TB_V3=0"
if defined TB_V if %TB_V1% GTR %TB_UV_MIN_MAJOR% set "TB_UV=uv"
if defined TB_V if %TB_V1% EQU %TB_UV_MIN_MAJOR% if %TB_V2% GTR %TB_UV_MIN_MINOR% set "TB_UV=uv"
if defined TB_V if %TB_V1% EQU %TB_UV_MIN_MAJOR% if %TB_V2% EQU %TB_UV_MIN_MINOR% if %TB_V3% GEQ %TB_UV_MIN_PATCH% set "TB_UV=uv"

rem --- uv, step 2: Runtime\tools\uv --------------------------------------------------------
set "TB_UV_DIR=%ROOT%\Runtime\tools\uv"
if not defined TB_UV if exist "%TB_UV_DIR%\uv.exe" set "TB_UV=%TB_UV_DIR%\uv.exe"

rem --- uv, step 3: download the pinned release (runs only when steps 1-2 found nothing) ----
set "TB_ARCH=%PROCESSOR_ARCHITECTURE%"
if defined PROCESSOR_ARCHITEW6432 set "TB_ARCH=%PROCESSOR_ARCHITEW6432%"
set "TB_ASSET="
set "TB_SHA="
if /i "%TB_ARCH%"=="AMD64" set "TB_ASSET=uv-x86_64-pc-windows-msvc.zip"
if /i "%TB_ARCH%"=="AMD64" set "TB_SHA=%TB_SHA_AMD64%"
if /i "%TB_ARCH%"=="ARM64" set "TB_ASSET=uv-aarch64-pc-windows-msvc.zip"
if /i "%TB_ARCH%"=="ARM64" set "TB_SHA=%TB_SHA_ARM64%"
set "TB_BASE=https://github.com/astral-sh/uv/releases/download"
if defined AGENTIC_UV_DOWNLOAD_URL set "TB_BASE=%AGENTIC_UV_DOWNLOAD_URL%"
if "%TB_BASE:~-1%"=="/" set "TB_BASE=%TB_BASE:~0,-1%"
set "TB_URL=%TB_BASE%/%TB_UV_VERSION%/%TB_ASSET%"
set "TB_TMP=%TB_UV_DIR%\.download-%RANDOM%%RANDOM%"
set "TB_ZIP=%TB_TMP%\%TB_ASSET%"
set "TB_CURL=%SystemRoot%\System32\curl.exe"
if not exist "%TB_CURL%" set "TB_CURL=curl.exe"
set "TB_TAR=%SystemRoot%\System32\tar.exe"
if not exist "%TB_TAR%" set "TB_TAR=tar.exe"

if not defined TB_UV if defined TB_HOOK (>&2 echo tb: hook skipped: uv is not installed in Runtime yet, run Toolbox\tb.cmd setup& exit /b 0)
if not defined TB_UV if not defined TB_ASSET (>&2 echo error: no pinned uv build for Windows on "%TB_ARCH%"; install uv %TB_UV_MIN_MAJOR%.%TB_UV_MIN_MINOR%.%TB_UV_MIN_PATCH% or newer and put it on PATH& exit /b 1)

rem Download. The second attempt skips the certificate revocation check, which fails behind
rem some corporate TLS proxies; the SHA256 check below still guarantees the file is genuine.
if not defined TB_UV (
  >&2 echo tb: downloading uv %TB_UV_VERSION% [%TB_ASSET%] into Runtime\tools\uv ...
  mkdir "%TB_TMP%" 2>nul
  "%TB_CURL%" -fsSL --retry 3 --connect-timeout 30 -o "%TB_ZIP%" "%TB_URL%" <nul || "%TB_CURL%" --ssl-no-revoke -fsSL --retry 3 --connect-timeout 30 -o "%TB_ZIP%" "%TB_URL%" <nul || (
    rmdir /s /q "%TB_TMP%" 2>nul
    >&2 echo error: failed to download "%TB_URL%"; check the network connection or HTTPS_PROXY, or set AGENTIC_UV_DOWNLOAD_URL to use a mirror
    exit /b 1
  )
)

rem Verify. certutil prints a header line, the hash, then a status line; older versions put
rem spaces between the bytes of the hash.
set "TB_HASH="
if not defined TB_UV for /f "skip=1 delims=" %%H in ('certutil -hashfile "%TB_ZIP%" SHA256') do if not defined TB_HASH set "TB_HASH=%%H"
if defined TB_HASH set "TB_HASH=%TB_HASH: =%"
if not defined TB_UV if /i not "%TB_HASH%"=="%TB_SHA%" (
  del /f /q "%TB_ZIP%" 2>nul
  rmdir /s /q "%TB_TMP%" 2>nul
  >&2 echo error: checksum mismatch for %TB_ASSET%: expected %TB_SHA%, got "%TB_HASH%"; the downloaded file was deleted
  exit /b 1
)

rem Unpack with the built-in tar.exe (bsdtar reads zip); PowerShell is the fallback.
if not defined TB_UV (
  "%TB_TAR%" -xf "%TB_ZIP%" -C "%TB_TMP%" 2>nul <nul || powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%TB_ZIP:'=''%' -DestinationPath '%TB_TMP:'=''%' -Force" <nul || (
    rmdir /s /q "%TB_TMP%" 2>nul
    >&2 echo error: failed to unpack %TB_ASSET%
    exit /b 1
  )
  "%TB_TMP%\uv.exe" --version >nul 2>&1 <nul || (
    rmdir /s /q "%TB_TMP%" 2>nul
    >&2 echo error: the downloaded uv does not run on this system; install uv %TB_UV_MIN_MAJOR%.%TB_UV_MIN_MINOR%.%TB_UV_MIN_PATCH% or newer and put it on PATH
    exit /b 1
  )
)

rem Install: uvx.exe first, so an existing uv.exe means the installation is complete. A failed
rem move is fine when a parallel tb call has just installed uv.exe.
if not defined TB_UV (
  move /y "%TB_TMP%\uvx.exe" "%TB_UV_DIR%\uvx.exe" >nul 2>nul
  move /y "%TB_TMP%\uv.exe" "%TB_UV_DIR%\uv.exe" >nul 2>nul
  rmdir /s /q "%TB_TMP%" 2>nul
  if not exist "%TB_UV_DIR%\uv.exe" (
    >&2 echo error: cannot move uv.exe into "%TB_UV_DIR%"
    exit /b 1
  )
  >&2 echo tb: uv %TB_UV_VERSION% installed
  set "TB_UV=%TB_UV_DIR%\uv.exe"
)

if defined TB_HOOK set "UV_OFFLINE=1"
if defined TB_HOOK set "UV_PYTHON_DOWNLOADS=never"
if not defined TB_HOOK if /i "%UV_PYTHON_PREFERENCE%"=="only-managed" if not exist "%UV_PYTHON_INSTALL_DIR%\" (>&2 echo tb: first run: uv is preparing Python in Runtime, this can take a minute ...)

rem --- Dispatch ----------------------------------------------------------------------------
rem "hook": exit code 0 whatever uv returns (2 would block the prompt in Claude Code).
rem "run": uv gets the original arguments, "run SCRIPT ARGS", so --no-project is passed through
rem UV_NO_PROJECT (cmd.exe cannot drop the first word of the argument line safely).
if "%~1"=="run" if "%~2"=="" (>&2 echo error: usage: tb run SCRIPT [ARGS...]& exit /b 1)
set TB_PRE=run --no-project --quiet "%TB_DIR%\agentic\cli.py"
if "%~1"=="run" set "TB_PRE=--quiet"
if "%~1"=="run" set "UV_NO_PROJECT=1"
"%TB_UV%" %TB_PRE% %* & if defined TB_HOOK (exit /b 0) else exit /b
