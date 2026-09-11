param(
  [string]$Title = 'Argus 服务日志',
  [string]$Name = 'Service',
  [string]$Executable = '',
  [string]$ArgumentsB64 = '',
  [string]$WorkingDirectory = '',
  [string]$LogFile = ''
)

# Argus 服务日志控制台
# 由桌面端 daemon 或 Start-ClawguardDesktop.ps1 以「可见窗口」方式拉起：
#   实时打印完整日志行，同时把同样的内容追加写入 -LogFile。
# 关闭本窗口即结束该服务。

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
try { $Host.UI.RawUI.WindowTitle = $Title } catch {}
try { $env:PYTHONUNBUFFERED = '1' } catch {}

$svcArgs = @()
if ($ArgumentsB64) {
  try {
    $json = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($ArgumentsB64))
    if ($json.Trim()) {
      # PS 5.1 的 ConvertFrom-Json 不会展开数组，直接 @() 会得到嵌套数组 → 参数串成一个。
      # 这里显式摊平成字符串数组，避免服务收到 "System.Object[]" 这种参数。
      $parsed = ConvertFrom-Json -InputObject $json
      if ($parsed -is [System.Array]) {
        foreach ($item in $parsed) { if ($null -ne $item) { $svcArgs += [string]$item } }
      } elseif ($null -ne $parsed) {
        $svcArgs += [string]$parsed
      }
    }
  } catch {
    Write-Host "[$Name] 参数解析失败：$($_.Exception.Message)" -ForegroundColor Red
  }
}

$sep = '=' * 72
Write-Host ''
Write-Host $sep -ForegroundColor Cyan
Write-Host "  Argus · $Name  实时日志" -ForegroundColor Cyan
Write-Host $sep -ForegroundColor Cyan
Write-Host ("  可执行文件 : {0}" -f $Executable)
Write-Host ("  启动参数   : {0}" -f ($svcArgs -join ' '))
Write-Host ("  工作目录   : {0}" -f $WorkingDirectory)
Write-Host ("  日志落盘   : {0}" -f $LogFile)
Write-Host ("  启动时间   : {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Write-Host $sep -ForegroundColor Cyan
Write-Host ''

if (-not $Executable) { Write-Host "[$Name] 缺少 -Executable 参数" -ForegroundColor Red; Start-Sleep -Seconds 10; exit 1 }
if (-not (Test-Path -LiteralPath $WorkingDirectory)) { Write-Host "[$Name] 工作目录不存在：$WorkingDirectory" -ForegroundColor Red; Start-Sleep -Seconds 10; exit 1 }

if ($LogFile) {
  try {
    $logDir = Split-Path -Parent $LogFile
    if ($logDir -and -not (Test-Path -LiteralPath $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
  } catch {}
}

# 日志用 UTF-8（无 BOM）流式写盘：Tee-Object 在 PS 5.1 下会写 UTF-16，桌面端 tail 会读成乱码。
$writer = $null
if ($LogFile) {
  try {
    $writer = New-Object System.IO.StreamWriter($LogFile, $true, (New-Object System.Text.UTF8Encoding($false)))
    $writer.AutoFlush = $true
  } catch {
    Write-Host "[$Name] 日志文件无法打开：$($_.Exception.Message)" -ForegroundColor Yellow
  }
}

Push-Location -LiteralPath $WorkingDirectory
try {
  & $Executable @svcArgs 2>&1 | ForEach-Object {
    $line = if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { [string]$_ }
    Write-Host $line
    if ($writer) { try { $writer.WriteLine($line) } catch {} }
  }
} catch {
  Write-Host "[$Name] 启动异常：$($_.Exception.Message)" -ForegroundColor Red
} finally {
  Pop-Location
  if ($writer) { try { $writer.Flush(); $writer.Dispose() } catch {} }
}

$exitCode = $LASTEXITCODE
Write-Host ''
Write-Host $sep -ForegroundColor Yellow
Write-Host ("  [{0}] 进程已退出，退出码：{1}" -f $Name, $exitCode) -ForegroundColor Yellow
Write-Host '  本窗口 8 秒后自动关闭（关闭窗口即停止该服务）' -ForegroundColor DarkGray
Write-Host $sep -ForegroundColor Yellow
Start-Sleep -Seconds 8
