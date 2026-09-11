@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start-Argus.ps1"
if errorlevel 1 (
  echo.
  echo Argus Desktop failed to start.
  pause
)
endlocal
