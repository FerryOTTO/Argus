# ============================================================
# SafeGuard patch apply script (OpenClaw 2026.6.11)
# Usage : powershell -ExecutionPolicy Bypass -File .\apply-patch.ps1
# Adjust the 3 paths below if they differ on your machine.
# ============================================================

$ErrorActionPreference = "Stop"

# -- Paths ----------------------------------------------------
$BundleRoot   = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
$OpenClawRoot = Join-Path $BundleRoot "openclaw"                         # OpenClaw package root
$BundleRel    = "dist\proxy-CoylXPU6.js"                          # patch target (relative to root)
$Patch        = Join-Path $PSScriptRoot "..\openclaw-2026.6.11-retrieval-guard.patch"
$Node         = Join-Path $BundleRoot "nodejs\node.exe"                     # for syntax check; fallback to PATH

$Bundle = Join-Path $OpenClawRoot $BundleRel

Write-Host "== SafeGuard patch apply script ==" -ForegroundColor Cyan

# 1. Target exists?
if (-not (Test-Path $Bundle)) {
    Write-Host "ERROR: target not found: $Bundle" -ForegroundColor Red
    Write-Host "Check OpenClaw version (must be 2026.6.11) and fix OpenClawRoot at the top."
    exit 1
}

# 2. Already applied? Use patch dry-run (authoritative; PS Select-String misreads UTF-8)
Push-Location $OpenClawRoot
try {
    $dryRun = cmd /c "patch -p1 --dry-run < `"$Patch`"" 2>&1
} finally {
    Pop-Location
}
if ($dryRun -match "previously applied") {
    Write-Host "SafeGuard patch already applied. Skipped." -ForegroundColor Yellow
    Write-Host "To revert: patch -p1 -R < openclaw-2026.6.11-retrieval-guard.patch"
    exit 0
}

# 3. Find patch command (ships with Git for Windows)
$patchCmd = Get-Command patch -ErrorAction SilentlyContinue
if (-not $patchCmd) {
    Write-Host "ERROR: patch command not found. Install Git for Windows or run inside Git Bash." -ForegroundColor Red
    exit 1
}

# 4. Apply (run inside package root so -p1 matches the dist/ relative path)
Write-Host "Applying patch: $Patch"
Push-Location $OpenClawRoot
try {
    cmd /c "patch -p1 < `"$Patch`""
    if ($LASTEXITCODE -ne 0) {
        Write-Host "patch FAILED (exit $LASTEXITCODE). Not applied." -ForegroundColor Red
        exit 1
    }
} finally {
    Pop-Location
}

# 5. Verify marker count (expect 7; use node for reliable UTF-8 counting)
if (-not (Test-Path $Node)) { $Node = (Get-Command node.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source) }
if ($Node -and (Test-Path $Node)) {
    $count = & $Node -e "const fs=require('fs');const s=fs.readFileSync(process.argv[1],'utf8');process.stdout.write(String((s.match(/SafeGuard/g)||[]).length));" $Bundle
    Write-Host "Verify: 'SafeGuard' found $count time(s) (expected 7)"
    if ([int]$count -ne 7) {
        Write-Host "WARNING: count mismatch ($count != 7). Patch may be incomplete." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "WARNING: node not found, skip marker verification." -ForegroundColor Yellow
}

# 6. Syntax check (Node >= 22.19)
if ($Node -and (Test-Path $Node)) {
    & $Node --check $Bundle
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Syntax check PASSED."
    } else {
        Write-Host "Syntax check FAILED." -ForegroundColor Red
        exit 1
    }
}

Write-Host "Patch applied. Restart gateway to take effect: openclaw gateway run" -ForegroundColor Green
