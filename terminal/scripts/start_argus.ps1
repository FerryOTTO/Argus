# Argus API 启动脚本
# 在前台运行，本窗口就是 Argus 的实时日志控制台。
#   关闭窗口 = 停止 Argus；日志同时追加写入 <包根>\logs\argus-YYYYMMDD.log

$ErrorActionPreference = "Continue"

# 让窗口标题一眼看出这是 Argus 日志
try { $Host.UI.RawUI.WindowTitle = "Argus 实时日志 - http://127.0.0.1:8000" } catch { }

# 切到包根目录（scripts 的上一级）
Set-Location "$PSScriptRoot\.."

# ---- 选择 Python 解释器：优先 py 启动器，其次 python，都没有则提示并退出 ----
$py = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $py = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $py = "python"
}
if (-not $py) {
    Write-Host "[Argus] 未找到 Python，请先安装 Python 并加入 PATH。" -ForegroundColor Red
    Read-Host "按回车关闭窗口"
    exit 1
}

# ---- 日志文件：实时输出同时落盘，方便事后排查（目录只读时自动降级为仅窗口显示）----
$env:PYTHONUNBUFFERED = "1"
$logFile = $null
try {
    $logDir = Join-Path $PSScriptRoot "..\logs"
    New-Item -ItemType Directory -Force -Path $logDir -ErrorAction Stop | Out-Null
    $logFile = Join-Path $logDir ("argus-{0:yyyyMMdd}.log" -f (Get-Date))
    New-Item -ItemType File -Force -Path $logFile -ErrorAction Stop | Out-Null
} catch {
    $logFile = $null
}

$uvArgs = @('-m', 'uvicorn', 'argus.api.main:app', '--host', '0.0.0.0', '--port', '8000', '--log-level', 'info')

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Argus API    http://127.0.0.1:8000"                        -ForegroundColor Cyan
Write-Host " Python: $py"                                                    -ForegroundColor DarkGray
if ($logFile) {
    Write-Host " 实时日志同时写入: $logFile"                                 -ForegroundColor DarkGray
} else {
    Write-Host " 日志目录不可写，仅在窗口显示实时日志。"                       -ForegroundColor DarkGray
}
Write-Host " 关闭本窗口即停止 Argus。"                                     -ForegroundColor DarkGray
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 前台运行：stdout/stderr 实时打印到本控制台，同时追加写入日志文件
if ($logFile) {
    & $py @uvArgs 2>&1 | Tee-Object -FilePath $logFile -Append
} else {
    & $py @uvArgs 2>&1
}

# 进程退出后保留窗口，方便查看报错原因
Write-Host ""
Write-Host "[Argus] 服务已退出（退出码 $LASTEXITCODE）。按回车关闭窗口。" -ForegroundColor Yellow
Read-Host
