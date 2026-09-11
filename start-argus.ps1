<#
.SYNOPSIS
    Argus 一键启动脚本（Windows PowerShell）。

.DESCRIPTION
    按顺序把三个服务各自放到一个独立窗口里启动：
      1. gateway   企业网关     http://127.0.0.1:8080
      2. terminal  终端运行时   http://127.0.0.1:8000
      3. desktop   桌面客户端   开发模式（Vite 5173 + Electron）

    默认会先补齐依赖（go mod download / pip install / npm install）。

.PARAMETER SkipInstall
    跳过依赖安装，直接启动。依赖已装好时用它可以快很多。

.PARAMETER GatewayOnly / TerminalOnly / DesktopOnly
    只启动其中一块。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\start-argus.ps1
    powershell -ExecutionPolicy Bypass -File .\start-argus.ps1 -SkipInstall
#>
[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [switch]$GatewayOnly,
    [switch]$TerminalOnly,
    [switch]$DesktopOnly
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

function Write-Step {
    param([string]$Text)
    Write-Host ''
    Write-Host ('─' * 64) -ForegroundColor DarkCyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ('─' * 64) -ForegroundColor DarkCyan
}

function Resolve-Tool {
    param([string[]]$Names, [string]$Hint)
    foreach ($name in $Names) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cmd) { return $cmd.Source }
    }
    throw "找不到 $($Names -join ' / ')。$Hint"
}

function Test-LocalPort {
    param([int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync('127.0.0.1', $Port)
        if (-not $task.Wait(400)) { return $false }
        return $client.Connected
    } catch { return $false } finally { $client.Dispose() }
}

function Start-InWindow {
    param(
        [string]$Title,
        [string]$WorkingDirectory,
        [string]$Command
    )
    $inner = @"
`$Host.UI.RawUI.WindowTitle = '$Title'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location -LiteralPath '$WorkingDirectory'
Write-Host '  $Title' -ForegroundColor Cyan
Write-Host ''
$Command
"@
    Start-Process -FilePath 'powershell.exe' `
        -ArgumentList @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-NoExit', '-Command', $inner) `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Normal | Out-Null
}

# ─────────────────────────────── 前置检查 ───────────────────────────────
$go = Resolve-Tool @('go')            '请先安装 Go 1.21+：https://go.dev/dl/'
$py = Resolve-Tool @('py', 'python')  '请先安装 Python 3.10+：https://www.python.org/downloads/'
$npm = Resolve-Tool @('npm.cmd', 'npm') '请先安装 Node.js 18+：https://nodejs.org/'

Write-Host ''
Write-Host '  Argus 启动器' -ForegroundColor White
Write-Host "  仓库根目录 : $root"
Write-Host "  Go         : $go"
Write-Host "  Python     : $py"
Write-Host "  npm        : $npm"

$onlyOne = ($GatewayOnly -or $TerminalOnly -or $DesktopOnly)
$runGateway = $GatewayOnly -or (-not $onlyOne)
$runTerminal = $TerminalOnly -or (-not $onlyOne)
$runDesktop = $DesktopOnly -or (-not $onlyOne)

# ─────────────────────────────── 依赖安装 ───────────────────────────────
if (-not $SkipInstall) {
    if ($runGateway) {
        Write-Step '补齐网关依赖'
        Push-Location (Join-Path $root 'gateway')
        try { & $go mod download } finally { Pop-Location }
    }
    if ($runTerminal) {
        Write-Step '补齐终端依赖'
        Push-Location (Join-Path $root 'terminal')
        try {
            & $py -m pip install -r requirements.txt
        } finally { Pop-Location }
    }
    if ($runDesktop) {
        Write-Step '补齐桌面端依赖'
        Push-Location (Join-Path $root 'desktop')
        try { & $npm install } finally { Pop-Location }
    }
}

# ─────────────────────────────── 启动服务 ───────────────────────────────
if ($runGateway) {
    Write-Step '启动企业网关（:8080）'
    if (Test-LocalPort -Port 8080) {
        Write-Host '  8080 已被占用，跳过启动（可能网关已经在跑）。' -ForegroundColor Yellow
    } else {
        Start-InWindow -Title 'Argus · 企业网关 :8080' `
            -WorkingDirectory (Join-Path $root 'gateway') `
            -Command "& '$go' run cmd/server/main.go -config configs/config.yaml"
        Write-Host '  已在新窗口启动。首次运行会创建 admin / admin123。' -ForegroundColor Green
    }
}

if ($runTerminal) {
    Write-Step '启动终端运行时（:8000）'
    if (Test-LocalPort -Port 8000) {
        Write-Host '  8000 已被占用，跳过启动（可能终端已经在跑）。' -ForegroundColor Yellow
    } else {
        Start-InWindow -Title 'Argus · 终端运行时 :8000' `
            -WorkingDirectory (Join-Path $root 'terminal') `
            -Command "& '$py' -m uvicorn clawguard.api.main:app --host 0.0.0.0 --port 8000"
        Write-Host '  已在新窗口启动。' -ForegroundColor Green
    }
}

if ($runDesktop) {
    Write-Step '启动桌面客户端（Vite 5173 + Electron）'
    Start-InWindow -Title 'Argus · 桌面客户端' `
        -WorkingDirectory (Join-Path $root 'desktop') `
        -Command "& '$npm' run app:dev"
    Write-Host '  已在新窗口启动。' -ForegroundColor Green
}

Write-Host ''
Write-Host '  全部启动指令已下发。' -ForegroundColor White
Write-Host '  网关控制台 http://127.0.0.1:8080   账号 admin / admin123' -ForegroundColor Gray
Write-Host '  终端接口   http://127.0.0.1:8000' -ForegroundColor Gray
