@echo off
REM Argus gateway launcher (Windows)
REM Port / DB path / JWT secret are all read from configs\config.yaml
cd /d "%~dp0"

if not exist "llmgate.exe" (
    echo [1/2] Building llmgate.exe ...
    where go >nul 2>nul
    if errorlevel 1 (
        echo Go toolchain not found on PATH. Install Go 1.21+ from https://go.dev/dl/
        goto :fail
    )
    go build -o llmgate.exe ./cmd/server/
    if errorlevel 1 goto :fail
) else (
    echo [1/2] llmgate.exe already built, skipping.
)

for /f "tokens=2 delims=:" %%p in ('findstr /r "port:" configs\config.yaml') do set PORT=%%p
echo [2/2] Starting Argus gateway on http://127.0.0.1%PORT%  (first run creates admin / admin123)
llmgate.exe -config configs/config.yaml
goto :eof

:fail
echo Build failed.
pause
