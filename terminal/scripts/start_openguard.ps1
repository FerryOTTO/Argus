# OpenGuard 启动脚本
# 在前台运行，本窗口显示 OpenGuard 的实时日志。

$ErrorActionPreference = "Continue"

try { $Host.UI.RawUI.WindowTitle = "OpenGuard 实时日志 - http://127.0.0.1:3000" } catch { }

Set-Location "$PSScriptRoot\..\openguard\original"

# ---- 选择 Python 解释器：优先 py 启动器，其次 python，都没有则提示并退出 ----
$py = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $py = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $py = "python"
}
if (-not $py) {
    Write-Host "[OpenGuard] 未找到 Python，请先安装 Python 并加入 PATH。" -ForegroundColor Red
    Read-Host "按回车关闭窗口"
    exit 1
}

$env:PYTHONUNBUFFERED = "1"
Write-Host "[OpenGuard] Starting on http://127.0.0.1:3000 ..." -ForegroundColor Cyan
Write-Host ""

& $py main.py

Write-Host ""
Write-Host "[OpenGuard] 服务已退出（退出码 $LASTEXITCODE）。按回车关闭窗口。" -ForegroundColor Yellow
Read-Host
