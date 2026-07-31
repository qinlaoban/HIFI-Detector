@echo off
REM Build script for HIFI Detector desktop app (Windows)
REM
REM Steps:
REM   1. Build Svelte frontend
REM   2. Build Python server with PyInstaller
REM   3. Copy to Tauri resources
REM   4. Build Tauri desktop app
REM
REM Usage:
REM   build.bat              Full production build
REM   build.bat --dev        Dev: PyInstaller only, then npx tauri dev

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..
set PYINSTALLER_SPEC=%SCRIPT_DIR%hifi-detect.spec
set PYINST_DIST=%SCRIPT_DIR%dist-python
set PYINST_BUILD=%SCRIPT_DIR%build-python
set TAURI_RESOURCES=%SCRIPT_DIR%src-tauri\python

echo === HIFI Detector Desktop Build (Windows) ===
echo.

REM Find Python in venv first, then system
set PYTHON=
if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
    set PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe
) else (
    where python >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "delims=" %%i in ('where python') do set PYTHON=%%i
        goto :found_python
    )
    echo ERROR: Python not found. Install Python 3.11+ or create a .venv.
    exit /b 1
)
:found_python
echo Using Python: %PYTHON%

REM Step 1: Frontend (Svelte) -> hifi_detector\web\static
echo.
echo [1/4] Building Svelte frontend...
cd /d "%PROJECT_ROOT%\web"
call npm ci
if %errorlevel% neq 0 (
    echo    ERROR: npm ci failed.
    exit /b 1
)
call npm run build
if %errorlevel% neq 0 (
    echo    ERROR: frontend build failed.
    exit /b 1
)
echo    OK: frontend built to hifi_detector\web\static

REM Step 2: PyInstaller
echo.
echo [2/4] Building Python server (PyInstaller)...
cd /d "%PROJECT_ROOT%"
%PYTHON% -m PyInstaller ^
    --distpath "%PYINST_DIST%" ^
    --workpath "%PYINST_BUILD%" ^
    --noconfirm ^
    "%PYINSTALLER_SPEC%" 2>&1 | findstr /C:"Building" /C:"completed" /C:"ERROR" /C:"WARNING"

set BINARY_DIR=%PYINST_DIST%\hifi-detect-server
set BINARY=%BINARY_DIR%\hifi-detect-server.exe
if exist "%BINARY%" (
    for %%f in ("%BINARY%") do echo    OK: %%~zf bytes
) else (
    echo    ERROR: PyInstaller binary not found at %BINARY%
    exit /b 1
)

REM Step 3: Copy to Tauri resources
echo.
echo [3/4] Copying Python server to Tauri resources...
if not exist "%TAURI_RESOURCES%" mkdir "%TAURI_RESOURCES%"
copy /Y "%BINARY%" "%TAURI_RESOURCES%\hifi-detect-server.exe" >nul
if exist "%BINARY_DIR%\_internal" (
    if exist "%TAURI_RESOURCES%\_internal" rd /s /q "%TAURI_RESOURCES%\_internal"
    xcopy /E /I /Y "%BINARY_DIR%\_internal" "%TAURI_RESOURCES%\_internal" >nul
)
echo    OK

REM Step 4: Tauri build
echo.
echo [4/4] Building Tauri desktop app...
cd /d "%SCRIPT_DIR%"
call npx tauri build

if %errorlevel% neq 0 (
    echo.
    echo ERROR: Tauri build failed.
    exit /b 1
)

echo.
echo === Build complete ===
echo.
echo Output bundles:
dir /s /b "%SCRIPT_DIR%src-tauri\target\release\bundle\msi\*.msi" 2>nul
dir /s /b "%SCRIPT_DIR%src-tauri\target\release\bundle\nsis\*.exe" 2>nul

endlocal
