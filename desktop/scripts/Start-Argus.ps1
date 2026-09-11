# Clawguard Desktop portable launcher
# Starts all local services and then launches the desktop application.

$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$bundleRoot = Split-Path -Parent $projectDir
# The Argus monorepo calls the backend `terminal/`; `ClawguardV2.1/` is the
# historical name kept so older portable bundles still start.
$backendDir = @('terminal', 'ClawguardV2.1') |
    ForEach-Object { Join-Path $bundleRoot $_ } |
    Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1
if (-not $backendDir) { $backendDir = Join-Path $bundleRoot 'terminal' }
$openGuardDir = Join-Path $backendDir 'openguard\original'
$builderCmd = Join-Path $projectDir 'node_modules\.bin\electron-builder.cmd'
$packagedExe = Join-Path $projectDir 'release\win-unpacked\Clawguard.exe'
$logDir = Join-Path $projectDir 'runtime-logs'
$bundledStateDir = Join-Path $bundleRoot 'openclaw-data'
$userStateDir = Join-Path ($env:USERPROFILE) '.openclaw'
$userConfigPath = Join-Path $userStateDir 'openclaw.json'
if ($env:OPENCLAW_STATE_DIR) {
    $stateDir = $env:OPENCLAW_STATE_DIR
} elseif ($env:OPENCLAW_HOME) {
    $stateDir = $env:OPENCLAW_HOME
} elseif (Test-Path -LiteralPath $userConfigPath) {
    $stateDir = $userStateDir
} else {
    $stateDir = $bundledStateDir
}
$portableNodeDir = Join-Path $bundleRoot 'nodejs'
$portablePythonExe = Join-Path $bundleRoot 'python\python.exe'
$portableNodeExe = Join-Path $portableNodeDir 'node.exe'
$portableNpmCmd = Join-Path $portableNodeDir 'npm.cmd'

function Select-ExistingPath {
    param([string[]]$Candidates)
    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

# Put the bundled Node.js first so npm, Electron and all child services use the
# copy shipped beside the project. The system PATH remains as a fallback.
if (Test-Path -LiteralPath $portableNodeDir) {
    $env:Path = "$portableNodeDir;$env:Path"
}

$pythonExe = Select-ExistingPath @(
    $env:CLAWGUARD_PYTHON,
    $portablePythonExe,
    (Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source),
    (Get-Command py.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
)
if (-not $pythonExe) { throw 'Python was not found. Install Python (or set CLAWGUARD_PYTHON, or put a portable copy in ..\python).' }

$nodeExe = Select-ExistingPath @(
    $env:CLAWGUARD_NODE,
    $portableNodeExe,
    (Get-Command node.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
)
if (-not $nodeExe) { throw 'Node.js was not found. Put a portable Node.js copy in ..\nodejs or set CLAWGUARD_NODE.' }

$npmCmd = Select-ExistingPath @(
    $env:CLAWGUARD_NPM,
    $portableNpmCmd,
    (Get-Command npm.cmd -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
)

# Use an explicitly configured state directory first; otherwise use the current
# Windows user's real OpenClaw profile when openclaw.json exists. FastAPI and
# OpenClaw inherit these variables so the desktop and gateway read one config.
if (Test-Path -LiteralPath $stateDir) {
    $env:OPENCLAW_HOME = $stateDir
    $env:OPENCLAW_STATE_DIR = $stateDir
}
$env:ARGUS_BUNDLE_ROOT = $bundleRoot
$env:CLAWGUARD_BUNDLE_ROOT = $bundleRoot
$env:ARGUS_BACKEND_DIR = $backendDir
$env:CLAWGUARD_BACKEND_DIR = $backendDir
$env:ARGUS_PYTHON = $pythonExe
$env:CLAWGUARD_PYTHON = $pythonExe
$env:ARGUS_NODE = $nodeExe
$env:CLAWGUARD_NODE = $nodeExe

function Repair-PortableOpenClawConfig {
    $configPath = Join-Path $stateDir 'openclaw.json'
    if (-not (Test-Path -LiteralPath $configPath)) { return }
    $raw = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8
    $portableSecurityShield = Select-ExistingPath @(
        (Join-Path $bundleRoot 'security-shield'),
        'E:\tiaozhanbei\7\security-shield'
    )
    $replacements = @{
        'E:/tiaozhanbei/7/security-shield' = if ($portableSecurityShield) { ($portableSecurityShield -replace '\\','/') } else { '' }
        'E:\tiaozhanbei\7\security-shield' = if ($portableSecurityShield) { $portableSecurityShield } else { '' }
        'E:/tiaozhanbei/MAC/security-shield' = if ($portableSecurityShield) { ($portableSecurityShield -replace '\\','/') } else { '' }
        'E:\tiaozhanbei\MAC\security-shield' = if ($portableSecurityShield) { $portableSecurityShield } else { '' }
        'G:/claw/security-shield' = if ($portableSecurityShield) { ($portableSecurityShield -replace '\\','/') } else { '' }
        'G:\claw\security-shield' = if ($portableSecurityShield) { $portableSecurityShield } else { '' }
        'C:/Users/admin/.openclaw' = ($stateDir -replace '\\','/')
        'C:\Users\admin\.openclaw' = $stateDir
        'G:/claw/openclaw-data' = ($stateDir -replace '\\','/')
        'G:\claw\openclaw-data' = $stateDir
    }
    foreach ($oldPath in $replacements.Keys) { $raw = $raw.Replace($oldPath, $replacements[$oldPath]) }
    try {
        $config = $raw | ConvertFrom-Json
        # OpenClaw validates every configured plugin path even when that plugin
        # is disabled. Keep only paths that exist on this machine so an old
        # developer-machine path cannot prevent the gateway from starting.
        if ($config.plugins -and $config.plugins.load -and $null -ne $config.plugins.load.paths) {
            $config.plugins.load.paths = @($config.plugins.load.paths | Where-Object {
                $_ -and (Test-Path -LiteralPath ([string]$_))
            })
        }
        $config | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $configPath -Encoding UTF8
    }
    catch { Write-Host "OpenClaw config was not valid after path migration: $configPath" -ForegroundColor Yellow }
}

function Sync-ClawguardAdapterPlugin {
    $pluginSource = Join-Path $backendDir 'openclaw_adapter\plugins\clawguard-adapter'
    $sourceDist = Join-Path $pluginSource 'dist'
    if (-not (Test-Path -LiteralPath $sourceDist)) {
        Write-Host "Clawguard adapter plugin was not found: $sourceDist" -ForegroundColor Yellow
        return
    }
    $pluginTarget = Join-Path $stateDir 'extensions\clawguard-adapter'
    $targetDist = Join-Path $pluginTarget 'dist'
    New-Item -ItemType Directory -Force -Path $targetDist | Out-Null
    Get-ChildItem -LiteralPath $sourceDist -Force | Copy-Item -Destination $targetDist -Recurse -Force
    foreach ($fileName in @('openclaw.plugin.json', 'package.json', 'README.md')) {
        $sourceFile = Join-Path $pluginSource $fileName
        if (Test-Path -LiteralPath $sourceFile) {
            Copy-Item -LiteralPath $sourceFile -Destination $pluginTarget -Force
        }
    }
    Write-Host "Clawguard adapter plugin synced to $pluginTarget" -ForegroundColor DarkGray
}

Repair-PortableOpenClawConfig
Sync-ClawguardAdapterPlugin
function Test-LocalPort {
    param([int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync('127.0.0.1', $Port)
        if (-not $task.Wait(500)) { return $false }
        return $client.Connected
    }
    catch { return $false }
    finally { $client.Dispose() }
}

function Wait-LocalPort {
    param([int]$Port, [int]$TimeoutSeconds = 20)
    for ($i = 0; $i -lt ($TimeoutSeconds * 2); $i++) {
        if (Test-LocalPort -Port $Port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Start-BackendService {
    param(
        [string]$Name,
        [int]$Port,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory
    )

    if (Test-LocalPort -Port $Port) {
        Write-Host "$Name is already running on port $Port." -ForegroundColor DarkGray
        return $true
    }
    if (-not (Test-Path -LiteralPath $WorkingDirectory)) {
        Write-Host "$Name skipped: working directory not found: $WorkingDirectory" -ForegroundColor Yellow
        return $false
    }

    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $stdoutPath = Join-Path $logDir ("$Name.out.log")
    $stderrPath = Join-Path $logDir ("$Name.err.log")
    $consoleLogPath = Join-Path $logDir ("$Name.console.log")
    Write-Host "Starting $Name on port $Port..." -ForegroundColor Cyan

    # 默认用隐藏模式拉起服务（不弹窗），日志落 $stdoutPath/$stderrPath。
    # 需要可见的「日志终端」窗口时，显式设 ARGUS_CONSOLE_LOG=1。
    $useConsoleWindow = (("$env:ARGUS_CONSOLE_LOG" -eq '1') -or ("$env:CLAWGUARD_CONSOLE_LOG" -eq '1'))
    if ($useConsoleWindow) {
        $consoleScript = Join-Path $projectDir 'scripts\ClawguardServiceConsole.ps1'
        if (Test-Path -LiteralPath $consoleScript) {
            $argsB64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject @($ArgumentList) -Compress)))
            Start-Process powershell -ArgumentList @(
                '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $consoleScript,
                '-Title', "Clawguard · $Name 日志",
                '-Name', $Name,
                '-Executable', $FilePath,
                '-ArgumentsB64', $argsB64,
                '-WorkingDirectory', $WorkingDirectory,
                '-LogFile', $consoleLogPath
            ) -WindowStyle Normal
            Write-Host "  -> 已打开日志终端窗口（$consoleLogPath）" -ForegroundColor DarkGray
        } else {
            Write-Host "  日志终端脚本缺失，回退隐藏模式：$consoleScript" -ForegroundColor Yellow
            $useConsoleWindow = $false
        }
    }
    if (-not $useConsoleWindow) {
        $startProcessParams = @{
            FilePath               = $FilePath
            ArgumentList           = $ArgumentList
            WorkingDirectory       = $WorkingDirectory
            WindowStyle            = 'Hidden'
            RedirectStandardOutput = $stdoutPath
            RedirectStandardError  = $stderrPath
        }
        Start-Process @startProcessParams | Out-Null
    }

    if (Wait-LocalPort -Port $Port -TimeoutSeconds 20) {
        Write-Host "$Name is ready." -ForegroundColor Green
        return $true
    }
    Write-Host "$Name did not become ready. Check $consoleLogPath / $stderrPath" -ForegroundColor Yellow
    return $false
}

if (-not (Test-Path -LiteralPath $builderCmd)) {
    throw "electron-builder was not found: $builderCmd. The desktop project's node_modules is missing."
}
if (-not (Test-Path -LiteralPath $backendDir)) { throw "Backend project was not found: $backendDir" }

Write-Host ''
Write-Host 'Building, starting all services, and launching Clawguard Desktop...' -ForegroundColor Cyan

Push-Location -LiteralPath $projectDir
try {
    if ($npmCmd) { & $npmCmd run build } else { & npm.cmd run build }
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed. Exit code: $LASTEXITCODE" }

    $devElectronExe = Join-Path $projectDir 'node_modules\electron\dist\electron.exe'
    $oldProcesses = Get-CimInstance -ClassName Win32_Process -Filter "Name = 'Clawguard.exe' OR Name = 'electron.exe'" |
        Where-Object {
            ($_.ExecutablePath -and $_.ExecutablePath -ieq $packagedExe) -or
            ($_.ExecutablePath -and $_.ExecutablePath -ieq $devElectronExe)
        }
    foreach ($processInfo in $oldProcesses) { Stop-Process -Id $processInfo.ProcessId -Force -ErrorAction SilentlyContinue }

    & $builderCmd --win dir --x64 --publish never
    if ($LASTEXITCODE -ne 0) { throw "Windows packaging failed. Exit code: $LASTEXITCODE" }
    if (-not (Test-Path -LiteralPath $packagedExe)) { throw "Packaged Clawguard executable was not created: $packagedExe" }

    $fastApiArgs = @('-m', 'uvicorn', 'clawguard.api.main:app', '--host', '127.0.0.1', '--port', '8000')
    $null = Start-BackendService -Name 'FastAPI' -Port 8000 -FilePath $pythonExe -ArgumentList $fastApiArgs -WorkingDirectory $backendDir

    $openClawEntry = Select-ExistingPath @(
        $env:CLAWGUARD_OPENCLAW_ENTRY,
        (Join-Path $bundleRoot 'openclaw\openclaw.mjs'),
        (Join-Path $env:APPDATA 'npm\node_modules\openclaw\openclaw.mjs'),
        (Join-Path $env:USERPROFILE 'AppData\Roaming\npm\node_modules\openclaw\openclaw.mjs')
    )
    if ($openClawEntry) {
        $env:ARGUS_OPENCLAW_ENTRY = $openClawEntry
$env:CLAWGUARD_OPENCLAW_ENTRY = $openClawEntry
        $openClawArgs = @($openClawEntry, 'gateway', 'run', '--allow-unconfigured', '--port', '18789', '--bind', 'loopback')
        $null = Start-BackendService -Name 'OpenClaw' -Port 18789 -FilePath $nodeExe -ArgumentList $openClawArgs -WorkingDirectory $bundleRoot
    } else { Write-Host 'OpenClaw skipped: openclaw.mjs was not found.' -ForegroundColor Yellow }

    # Bridge and the old OpenGuard chain are retired. The desktop now uses only
    # FastAPI and OpenClaw, matching the three-part status ring in the renderer.

    Start-Process -FilePath $packagedExe -WorkingDirectory $projectDir
    Write-Host 'All services and Clawguard Desktop started.' -ForegroundColor Green
}
finally { Pop-Location }





