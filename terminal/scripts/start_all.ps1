# Clawguard V2.1 全服务启动脚本
# 按顺序检查并启动所有服务

$ErrorActionPreference = "Continue"
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$ROOT = Split-Path -Parent $ROOT

Write-Host ""
Write-Host "============================================"  -ForegroundColor Cyan
Write-Host "  Clawguard V2.1 — 全服务启动"              -ForegroundColor Cyan
Write-Host "============================================"  -ForegroundColor Cyan
Write-Host ""

# 1. 环境检查
Write-Host "[Check] Python: " -NoNewline
$pyCmd = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $pyCmd = "py" }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $pyCmd = "python" }
if ($pyCmd) {
    $pyVer = & $pyCmd --version 2>&1
    Write-Host "$pyVer" -ForegroundColor Green
} else {
    Write-Host "MISSING（请安装 Python 并加入 PATH）" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

Write-Host "[Check] Node.js: " -NoNewline
if (Get-Command node -ErrorAction SilentlyContinue) {
    $nodeVer = node --version 2>&1
    Write-Host "$nodeVer" -ForegroundColor Green
} else {
    Write-Host "MISSING (OpenGuard Bridge 需要)" -ForegroundColor Yellow
}

# 2. 启动 Sandbox MCP (如果有 Docker)
Write-Host ""
Write-Host "--- Sandbox MCP ---" -ForegroundColor Cyan
$dockerOk = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerOk) {
    Start-Process powershell -ArgumentList "-File `"$ROOT\scripts\start_sandbox.ps1`"" -WindowStyle Minimized
    Write-Host "[START] Sandbox MCP — waiting for port 9876..."
} else {
    Write-Host "[SKIP] Docker 未安装，跳过 Sandbox MCP"
}

# 3. 启动 Clawguard FastAPI（单独开一个可见控制台窗口，实时显示日志）
Write-Host ""
Write-Host "--- Clawguard ---" -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoLogo -ExecutionPolicy Bypass -File `"$ROOT\scripts\start_clawguard.ps1`"" -WindowStyle Normal
Write-Host "[START] Clawguard FastAPI — 已打开“Clawguard 实时日志”窗口，等待端口 8000..."

# 等待 Clawguard 就绪
$clawguardOk = $false
for ($i = 1; $i -le 15; $i++) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2 -ErrorAction Stop
        Write-Host "[OK] Clawguard API       http://127.0.0.1:8000/health"
        $clawguardOk = $true
        break
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $clawguardOk) { Write-Host "[WARN] Clawguard 未能在 30s 内就绪" -ForegroundColor Yellow }

# 4. 启动 OpenClaw (手动步骤提示)
Write-Host ""
Write-Host "--- OpenClaw ---" -ForegroundColor Cyan
$openclawOk = $false
try {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:18789/health" -TimeoutSec 2 -ErrorAction Stop
    Write-Host "[OK] OpenClaw Gateway     http://127.0.0.1:18789"
    $openclawOk = $true
} catch {
    Write-Host "[--] OpenClaw 未启动，请在另一个终端运行: openclaw gateway run" -ForegroundColor Yellow
}

# 5. 启动 OpenGuard
Write-Host ""
Write-Host "--- OpenGuard ---" -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-File `"$ROOT\scripts\start_openguard.ps1`"" -WindowStyle Minimized
Write-Host "[START] OpenGuard — waiting for port 3000..."

$openguardOk = $false
for ($i = 1; $i -le 10; $i++) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:3000/health" -TimeoutSec 2 -ErrorAction Stop
        Write-Host "[OK] OpenGuard            http://127.0.0.1:3000/health"
        $openguardOk = $true
        break
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $openguardOk) { Write-Host "[WARN] OpenGuard 未能在 20s 内就绪" -ForegroundColor Yellow }

# 6. 总结
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  启动完成" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "[OK] Clawguard API       http://127.0.0.1:8000/health" -ForegroundColor $(if($clawguardOk){'Green'}else{'Red'})
Write-Host "[OK] OpenClaw Gateway    http://127.0.0.1:18789"         -ForegroundColor $(if($openclawOk){'Green'}else{'Yellow'})
Write-Host "[OK] OpenGuard           http://127.0.0.1:3000"          -ForegroundColor $(if($openguardOk){'Green'}else{'Red'})
Write-Host ""
if ($clawguardOk) {
    Write-Host "Clawguard 实时日志见单独的“Clawguard 实时日志”窗口（关闭该窗口即停止服务）" -ForegroundColor DarkGray
}
if ($openclawOk -and $clawguardOk -and $openguardOk) {
    Write-Host "全服务就绪，浏览器访问: http://localhost:3000" -ForegroundColor Green
}
