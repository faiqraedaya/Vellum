@echo off
setlocal
cd /d "%~dp0"

where uv >nul 2>&1
if errorlevel 1 (
    echo [ERROR] uv is not on PATH. Install it from https://docs.astral.sh/uv/.
    exit /b 1
)

echo [1/4] Syncing dev dependencies...
uv sync --group dev
if errorlevel 1 (
    echo [ERROR] uv sync failed.
    exit /b 1
)

echo [2/4] Cleaning previous build...
if exist "build" rmdir /s /q "build"
if exist "dist"  rmdir /s /q "dist"

echo [3/4] Running PyInstaller...
uv run --group dev pyinstaller --noconfirm --clean build.spec
if errorlevel 1 (
    echo [ERROR] PyInstaller failed.
    exit /b 1
)

echo [4/4] Build complete.
set "EXE=%~dp0dist\Vellum\Vellum.exe"
if not exist "%EXE%" (
    echo [ERROR] Expected exe not found at "%EXE%".
    exit /b 1
)
echo Output: %EXE%
powershell -NoProfile -Command "$s = (Get-ChildItem -Recurse '%~dp0dist\Vellum' | Measure-Object -Property Length -Sum).Sum; Write-Host ('Bundle size: {0:N1} MB' -f ($s/1MB))"

endlocal
