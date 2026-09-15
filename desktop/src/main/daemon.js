const { spawn, exec, execSync, execFileSync } = require('child_process')
const path = require('path')
const os = require('os')
const fs = require('fs')
const http = require('http')
const net = require('net')
const modelSwitch = require('./openclaw_model_switch')

// Electron GUI processes may not have a live stdout pipe. Never let a diagnostic
// message crash the app when the parent shell has already closed its pipe.
function ignoreBrokenPipe(stream) {
  if (!stream || typeof stream.on !== 'function') return
  stream.on('error', (error) => {
    if (error?.code !== 'EPIPE') return
  })
}

ignoreBrokenPipe(process.stdout)
ignoreBrokenPipe(process.stderr)

function safeConsoleLog(...args) {
  try {
    if (!process.stdout || process.stdout.destroyed || process.stdout.writable === false) return
    process.stdout.write(`${args.join(' ')}\n`)
  } catch {
    // A packaged Electron app is allowed to run without a parent console.
  }
}

function firstExistingPath(candidates, fallback) {
  const existing = candidates.find((candidate) => candidate && fs.existsSync(candidate))
  return existing || fallback
}

// The bundle layout used to be `Argus/` + `LLMGate/`. The Argus
// monorepo renamed them to `terminal/` + `gateway/`. Both names are probed so
// this build also works with bundles produced by the older packaging scripts.
const BACKEND_DIR_NAMES = ['terminal', 'Argus']
const GATEWAY_DIR_NAMES = ['gateway', 'LLMGate']

function expandDirCandidates(bases, names) {
  const out = []
  for (const base of bases) {
    if (!base) continue
    for (const name of names) out.push(path.join(base, name))
  }
  return out
}

// ── 服务日志控制台（可选，默认关闭）─────────────────────────────
// 历史上启动服务时会同时弹出一个可见终端窗口实时打印日志。
// 现按需求改为**默认不弹窗**：服务以隐藏模式启动，日志仍进入应用内日志面板。
// 需要那个可见窗口时，显式设 ARGUS_CONSOLE_LOG=1。
const CONSOLE_SCRIPT_NAME = 'ArgusServiceConsole.ps1'

// 打包版里 scripts/ 不在可执行目录（asar 内无法被 powershell 直接运行），
// 因此同一份脚本在这里内嵌一份，运行时写到可写目录。改脚本时两边都要改。
const CONSOLE_SCRIPT_FALLBACK = [
  'param(',
  "  [string]$Title = 'Argus 服务日志',",
  "  [string]$Name = 'Service',",
  "  [string]$Executable = '',",
  "  [string]$ArgumentsB64 = '',",
  "  [string]$WorkingDirectory = '',",
  "  [string]$LogFile = ''",
  ')',
  '',
  '$ErrorActionPreference = "Continue"',
  'try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}',
  'try { $Host.UI.RawUI.WindowTitle = $Title } catch {}',
  "try { $env:PYTHONUNBUFFERED = '1' } catch {}",
  '',
  '$svcArgs = @()',
  'if ($ArgumentsB64) {',
  '  try {',
  '    $json = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($ArgumentsB64))',
  '    if ($json.Trim()) {',
  '      # PS 5.1 的 ConvertFrom-Json 不会展开数组，直接 @() 会得到嵌套数组，参数会被串成一个。',
  '      $parsed = ConvertFrom-Json -InputObject $json',
  '      if ($parsed -is [System.Array]) {',
  '        foreach ($item in $parsed) { if ($null -ne $item) { $svcArgs += [string]$item } }',
  '      } elseif ($null -ne $parsed) {',
  '        $svcArgs += [string]$parsed',
  '      }',
  '    }',
  '  } catch {',
  '    Write-Host "[$Name] 参数解析失败：$($_.Exception.Message)" -ForegroundColor Red',
  '  }',
  '}',
  '',
  "$sep = '=' * 72",
  'Write-Host ""',
  'Write-Host $sep -ForegroundColor Cyan',
  'Write-Host "  Argus · $Name  实时日志" -ForegroundColor Cyan',
  'Write-Host $sep -ForegroundColor Cyan',
  'Write-Host ("  可执行文件 : {0}" -f $Executable)',
  "Write-Host (\"  启动参数   : {0}\" -f ($svcArgs -join ' '))",
  'Write-Host ("  工作目录   : {0}" -f $WorkingDirectory)',
  'Write-Host ("  日志落盘   : {0}" -f $LogFile)',
  "Write-Host (\"  启动时间   : {0}\" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))",
  'Write-Host $sep -ForegroundColor Cyan',
  'Write-Host ""',
  '',
  'if (-not $Executable) { Write-Host "[$Name] 缺少 -Executable 参数" -ForegroundColor Red; Start-Sleep -Seconds 10; exit 1 }',
  'if (-not (Test-Path -LiteralPath $WorkingDirectory)) { Write-Host "[$Name] 工作目录不存在：$WorkingDirectory" -ForegroundColor Red; Start-Sleep -Seconds 10; exit 1 }',
  '',
  'if ($LogFile) {',
  '  try {',
  '    $logDir = Split-Path -Parent $LogFile',
  '    if ($logDir -and -not (Test-Path -LiteralPath $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }',
  '  } catch {}',
  '}',
  '',
  // 日志用 UTF-8（无 BOM）流式写盘：Tee-Object 在 PS 5.1 下会写 UTF-16，桌面端 tail 会读成乱码。
  '$writer = $null',
  'if ($LogFile) {',
  '  try {',
  '    $writer = New-Object System.IO.StreamWriter($LogFile, $true, (New-Object System.Text.UTF8Encoding($false)))',
  '    $writer.AutoFlush = $true',
  '  } catch {',
  '    Write-Host "[$Name] 日志文件无法打开：$($_.Exception.Message)" -ForegroundColor Yellow',
  '  }',
  '}',
  '',
  'Push-Location -LiteralPath $WorkingDirectory',
  'try {',
  '  & $Executable @svcArgs 2>&1 | ForEach-Object {',
  '    $line = if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { [string]$_ }',
  '    Write-Host $line',
  '    if ($writer) { try { $writer.WriteLine($line) } catch {} }',
  '  }',
  '} catch {',
  '  Write-Host "[$Name] 启动异常：$($_.Exception.Message)" -ForegroundColor Red',
  '} finally {',
  '  Pop-Location',
  '  if ($writer) { try { $writer.Flush(); $writer.Dispose() } catch {} }',
  '}',
  '',
  '$exitCode = $LASTEXITCODE',
  'Write-Host ""',
  'Write-Host $sep -ForegroundColor Yellow',
  'Write-Host ("  [{0}] 进程已退出，退出码：{1}" -f $Name, $exitCode) -ForegroundColor Yellow',
  'Write-Host "  本窗口 8 秒后自动关闭（关闭窗口即停止该服务）" -ForegroundColor DarkGray',
  'Write-Host $sep -ForegroundColor Yellow',
  'Start-Sleep -Seconds 8',
].join('\r\n')

function resolvePowerShellExe() {
  const candidates = [
    process.env.SystemRoot ? path.join(process.env.SystemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe') : null,
    process.env.SystemRoot ? path.join(process.env.SystemRoot, 'SysWOW64', 'WindowsPowerShell', 'v1.0', 'powershell.exe') : null,
  ].filter(Boolean)
  const found = candidates.find((c) => fs.existsSync(c))
  return found || 'powershell.exe'
}

// Windows 上并非每台机器都装有 py.exe，也可能没有随包 Python；更要命的是
// **PATH 上第一个 python.exe 有可能是 Python 2.7**，必须逐个校验版本后再使用。
// 所以不能"取第一个命中的"，必须逐个探测版本，只接受真正可用的解释器。
function resolveAllOnPath(names) {
  const out = []
  for (const name of names) {
    try {
      const lines = execSync(`where ${name}`, { stdio: ['ignore', 'pipe', 'ignore'] })
        .toString()
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter((line) => line && fs.existsSync(line))
      for (const line of lines) if (!out.includes(line)) out.push(line)
    } catch {
      // where 对未找到的命令返回非零退出码，属预期情况，继续尝试下一个。
    }
  }
  return out
}

/** 跑一次 --version，返回首行输出；跑不起来返回 null */
function probeVersion(exe, args) {
  try {
    const out = execFileSync(exe, args || ['--version'], {
      encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], timeout: 8000, windowsHide: true,
    })
    return String(out).trim().split(/\r?\n/)[0] || ''
  } catch (err) {
    const alt = err && err.stdout ? String(err.stdout).trim() : ''
    return alt.split(/\r?\n/)[0] || null
  }
}

/**
 * 解析可用的 Python（**必须 ≥ 3.10**）。
 * 顺序：显式环境变量 → 随包 Python → py 启动器 → python3 → python。
 * 每一档都实跑 --version 校验，Python 2.x / 坏路径会被跳过。
 */
function resolvePythonExecutable(bundleRoot) {
  const candidates = []
  const push = (p) => { if (p && !candidates.includes(p)) candidates.push(p) }
  push((process.env.ARGUS_PYTHON))
  if (bundleRoot) push(path.join(bundleRoot, 'python', 'python.exe'))
  for (const p of resolveAllOnPath(['py.exe', 'py'])) push(p)          // py 启动器会自己挑最新版
  for (const p of resolveAllOnPath(['python3.exe', 'python3'])) push(p)
  for (const p of resolveAllOnPath(['python.exe', 'python'])) push(p)

  for (const candidate of candidates) {
    const version = probeVersion(candidate)
    if (!version) continue
    const m = /(\d+)\.(\d+)/.exec(version)
    if (!m) continue
    const major = Number(m[1])
    const minor = Number(m[2])
    if (major > 3 || (major === 3 && minor >= 10)) return candidate
  }
  return 'py'   // 兜底：交给 py 启动器（它会选最新版本）
}

/** 解析可用的 Node（必须真能跑起来，顺带避开正在被删除的残留目录） */
function resolveNodeExecutable(bundleRoot) {
  const candidates = []
  const push = (p) => { if (p && !candidates.includes(p)) candidates.push(p) }
  push((process.env.ARGUS_NODE))
  if (bundleRoot) push(path.join(bundleRoot, 'nodejs', 'node.exe'))
  for (const p of resolveAllOnPath(['node.exe', 'node'])) push(p)

  for (const candidate of candidates) {
    const version = probeVersion(candidate)
    if (version && /^v?\d+\./.test(version)) return candidate
  }
  return 'node.exe'
}

class DaemonManager {
  constructor(mainWindow) {
    this.mainWindow = mainWindow
    // 保留最近的真实子进程输出，供首页与实时控制台在页面加载后同步。
    this.logHistory = []
    this.debugWin = null
    this.processes = {
      fastapi: null,
      openguard: null,
      bridge: null,
      openclaw: null,
      llmgate: null
    }

    // Resolve the backend from both development and packaged layouts. The
    // desktop folder and backend are siblings inside one portable bundle.
    this.rootDir = firstExistingPath(
      [
        (process.env.ARGUS_BACKEND_DIR),
        ...expandDirCandidates(
          [
            process.env.ARGUS_BUNDLE_ROOT,
            process.execPath && path.dirname(process.execPath),
            path.resolve(__dirname, '../../..'),
            process.cwd(),
            path.resolve(process.cwd(), '..'),
            process.resourcesPath && path.resolve(process.resourcesPath, '../../..')
          ],
          BACKEND_DIR_NAMES
        )
      ],
      path.resolve(__dirname, '../../../terminal')
    )
    this.bundleRoot = firstExistingPath(
      [
        (process.env.ARGUS_BUNDLE_ROOT),
        path.resolve(this.rootDir, '..'),
        path.resolve(process.cwd(), '..')
      ],
      path.resolve(this.rootDir, '..')
    )
    this.openGuardDir = path.join(this.rootDir, 'openguard', 'original')
    this.llmGateDir = firstExistingPath(
      [
        (process.env.ARGUS_LLMGATE_DIR),
        ...expandDirCandidates(
          [this.bundleRoot, path.resolve(this.rootDir, '..'), path.resolve(process.cwd(), '..')],
          GATEWAY_DIR_NAMES
        )
      ],
      path.join(this.bundleRoot, 'gateway')
    )
    this.llmGateExecutable = firstExistingPath(
      [
        (process.env.ARGUS_LLMGATE_EXECUTABLE),
        path.join(this.llmGateDir, 'llmgate.exe'),
        path.join(this.llmGateDir, 'bin', 'llmgate.exe')
      ],
      path.join(this.llmGateDir, 'llmgate.exe')
    )
    this.llmGateConfig = path.join(this.llmGateDir, 'configs', 'config.yaml')
    this.llmgateStartedByUs = false
    const userStateDir = path.join(process.env.USERPROFILE || os.homedir(), '.openclaw')
    const userConfigPath = path.join(userStateDir, 'openclaw.json')
    const bundledStateDir = path.join(this.bundleRoot, 'openclaw-data')
    const defaultStateDir = fs.existsSync(userConfigPath) ? userStateDir : bundledStateDir
    this.openClawStateDir = process.env.OPENCLAW_STATE_DIR || process.env.OPENCLAW_HOME || defaultStateDir

    // 解释器解析：显式环境变量 → 随包 → PATH，且**逐档校验版本**
    //（PATH 上第一个 python.exe 可能是 Python 2.7，取到它后端就起不来）
    this.pythonExecutable = resolvePythonExecutable(this.bundleRoot)
    this.nodeExecutable = resolveNodeExecutable(this.bundleRoot)
    this.openClawEntry = firstExistingPath(
      [
        (process.env.ARGUS_OPENCLAW_ENTRY),
        path.join(this.bundleRoot, 'openclaw', 'openclaw.mjs'),
        process.env.APPDATA && path.join(process.env.APPDATA, 'npm', 'node_modules', 'openclaw', 'openclaw.mjs'),
        path.join(process.env.USERPROFILE || '', 'AppData', 'Roaming', 'npm', 'node_modules', 'openclaw', 'openclaw.mjs')
      ],
      null
    )
    this.openClawCmd = this.resolveOpenClawCommand()
  }

  log(source, text, level = 'info') {
    const message = text?.toString?.().trim() || ''
    if (!message) return
    const entry = { source, text: message, level, timestamp: Date.now() }
    // stdout/stderr 有时会一次返回多行；保存原始控制台输出，页面会按行呈现。
    this.logHistory.push(entry)
    if (this.logHistory.length > 200) this.logHistory.splice(0, this.logHistory.length - 200)

    try {
      if (this.mainWindow && !this.mainWindow.isDestroyed() && !this.mainWindow.webContents.isDestroyed()) {
        this.mainWindow.webContents.send('daemon-log', entry)
      }
    try {
      if (this.debugWin && !this.debugWin.isDestroyed() && !this.debugWin.webContents.isDestroyed()) {
        this.debugWin.webContents.send('daemon-log', entry)
      }
    } catch (e) {}
    } catch {
      // The renderer can disappear while a child process is still shutting down.
    }

    safeConsoleLog(`[${source}] ${message}`)
  }

  getLogHistory(limit = 80) {
    return this.logHistory.slice(-Math.max(1, Math.min(Number(limit) || 80, 200)))
  }
  async checkTcpPort(port, timeoutMs) {
    timeoutMs = timeoutMs || 900;
    return new Promise((resolve) => {
      const socket = new net.Socket();
      let done = false;
      const finish = (ok) => { if (done) return; done = true; try { socket.destroy(); } catch (e) {} resolve(ok); };
      socket.setTimeout(timeoutMs);
      socket.once('connect', () => finish(true));
      socket.once('timeout', () => finish(false));
      socket.once('error', () => finish(false));
      try { socket.connect(port, '127.0.0.1'); } catch (e) { finish(false); }
    });
  }
  async checkHttpAlive(port, timeoutMs) {
    timeoutMs = timeoutMs || 900;
    const tryPath = (pathSuffix) => {
      return new Promise((resolve) => {
        const req = http.get({ host: '127.0.0.1', port: port, path: pathSuffix, timeout: timeoutMs }, (res) => {
          res.resume();
          resolve(true);
        });
        req.on('timeout', () => { try { req.destroy(); } catch (e) {} resolve(false); });
        req.on('error', () => resolve(false));
      });
    };
    const healthOk = await tryPath('/health');
    if (healthOk) return true;
    return await tryPath('/');
  }
  async checkGatewayPort(port) {
    const results = await Promise.all([this.checkTcpPort(port), this.checkHttpAlive(port)]);
    return Boolean(results[0] || results[1]);
  }
  async checkPort(port) {
    return new Promise((resolve) => {
      const req = http.get(`http://127.0.0.1:${port}/health`, (res) => {
        res.resume()
        resolve(res.statusCode === 200)
      })
      req.on('error', () => resolve(false))
      req.setTimeout(800, () => {
        req.destroy()
        resolve(false)
      })
    })
  }

  serviceSource(name) {
    return name === 'fastapi' ? 'FastAPI'
      : name === 'openguard' ? 'OpenGuard'
      : name === 'openclaw' ? 'OpenClaw'
      : name === 'llmgate' ? 'LLMGate'
      : 'Bridge'
  }

  attachProcess(name, proc) {
    this.processes[name] = proc
    const source = this.serviceSource(name)
    proc.stdout?.on('data', (data) => this.log(source, data))
    proc.stderr?.on('data', (data) => this.log(source, data, 'warn'))
    proc.once('error', (error) => {
      this.log(source, `启动失败：${error.message}`, 'error')
      this.processes[name] = null
    })
    proc.once('close', (code, signal) => {
      if (code !== 0 && code !== null) {
        this.log(source, `子进程退出，退出码: ${code}${signal ? `，信号: ${signal}` : ''}`, 'warn')
      } else {
        this.log(source, `子进程已退出${signal ? `，信号: ${signal}` : ''}`)
      }
      if (this.processes[name] === proc) this.processes[name] = null
    })
  }

  // 可见日志终端窗口：**默认关闭，不弹窗**。
  // 需要时显式设 ARGUS_CONSOLE_LOG=1 打开；非 Windows 平台始终关闭。
  consoleLogEnabled() {
    if (process.platform !== 'win32') return false
    return String((process.env.ARGUS_CONSOLE_LOG) || '0') === '1'
  }

  resolveLogDir() {
    const candidates = [
      path.join(__dirname, '..', '..', 'runtime-logs'),   // 开发态：argus-desktop/runtime-logs
      path.join(this.bundleRoot || '', 'runtime-logs'),
      process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, 'Argus', 'runtime-logs') : null,
      path.join(os.tmpdir(), 'Argus', 'runtime-logs'),
    ].filter(Boolean)
    for (const dir of candidates) {
      try {
        fs.mkdirSync(dir, { recursive: true })
        fs.accessSync(dir, fs.constants.W_OK)
        return dir
      } catch (e) { /* try next */ }
    }
    return os.tmpdir()
  }

  // 开发态直接用仓库里的脚本；打包态把它写到可写目录（asar 内无法被 powershell 执行）。
  consoleScriptPath() {
    if (this._consoleScript) return this._consoleScript
    const devCandidates = [
      path.join(__dirname, '..', '..', 'scripts', CONSOLE_SCRIPT_NAME),
      path.join(this.bundleRoot || '', 'argus-desktop', 'scripts', CONSOLE_SCRIPT_NAME),
    ]
    for (const candidate of devCandidates) {
      try { if (candidate && fs.existsSync(candidate)) { this._consoleScript = candidate; return candidate } } catch (e) {}
    }
    try {
      const fp = path.join(this.resolveLogDir(), CONSOLE_SCRIPT_NAME)
      const current = fs.existsSync(fp) ? fs.readFileSync(fp, 'utf8') : ''
      // PowerShell 5.1 读无 BOM 的 UTF-8 会按 ANSI 解码，中文会破坏字符串解析，必须带 BOM。
      const wanted = '\uFEFF' + CONSOLE_SCRIPT_FALLBACK
      const normalize = (s) => s.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n')
      if (normalize(current) !== normalize(CONSOLE_SCRIPT_FALLBACK)) {
        fs.writeFileSync(fp, wanted, 'utf8')
      }
      this._consoleScript = fp
      return fp
    } catch (error) {
      this.log('DAEMON', `写入日志控制台脚本失败：${error.message}`, 'warn')
      return null
    }
  }

  // 控制台窗口用 stdio:'ignore'，父进程拿不到管道，于是改为 tail 日志文件回填应用内控制台。
  // 同时兼容历史遗留的 UTF-16 日志（旧版 Tee-Object 写出来的）。
  tailLog(source, logFile) {
    if (!this._tailTimers) this._tailTimers = []
    let offset = 0
    let partial = ''
    let mode = null
    let emittedLines = 0
    const timer = setInterval(() => {
      try {
        if (!logFile || !fs.existsSync(logFile)) return
        const size = fs.statSync(logFile).size
        if (size === 0) return

        if (mode === null) {
          const head = Buffer.alloc(Math.min(4, size))
          const fd0 = fs.openSync(logFile, 'r')
          try { fs.readSync(fd0, head, 0, head.length, 0) } finally { fs.closeSync(fd0) }
          if (head.length >= 2 && head[0] === 0xFF && head[1] === 0xFE) mode = 'utf16le'
          else if (head.length >= 2 && head[0] === 0xFE && head[1] === 0xFF) mode = 'utf16be'
          else mode = 'utf8'
        }

        if (mode !== 'utf8') {
          const all = fs.readFileSync(logFile)
          const text = (mode === 'utf16le' ? all : Buffer.from(all).swap16()).toString('utf16le')
          const lines = text.replace(/^\uFEFF/, '').split(/\r?\n/).filter((l) => l.length > 0)
          for (const line of lines.slice(emittedLines)) this.log(source, line)
          emittedLines = lines.length
          return
        }

        if (size < offset) { offset = 0; partial = '' }   // 文件被截断/轮转
        if (size === offset) return
        const len = size - offset
        const buf = Buffer.alloc(len)
        const fd = fs.openSync(logFile, 'r')
        try { fs.readSync(fd, buf, 0, len, offset) } finally { fs.closeSync(fd) }
        offset = size
        const lines = (partial + buf.toString('utf8')).replace(/^\uFEFF/, '').split(/\r?\n/)
        partial = lines.pop() || ''
        for (const line of lines) { if (line.trim()) this.log(source, line) }
      } catch (e) { /* 日志暂时读不到，下个周期再试 */ }
    }, 400)
    this._tailTimers.push(timer)
  }

  spawnConsoleService(name, source, executable, args, cwd, script) {
    const logFile = path.join(this.resolveLogDir(), `${source}.console.log`)
    let argsB64 = ''
    try { argsB64 = Buffer.from(JSON.stringify(args || []), 'utf8').toString('base64') } catch (e) { argsB64 = '' }
    const psArgs = [
      '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script,
      '-Title', `Argus · ${source} 日志`,
      '-Name', source,
      '-Executable', executable,
      '-ArgumentsB64', argsB64,
      '-WorkingDirectory', cwd,
      '-LogFile', logFile,
    ]
    this.log(source, `已打开日志终端窗口（实时日志 + 落盘 ${logFile}）`)
    try {
      const proc = spawn(resolvePowerShellExe(), psArgs, {
        cwd,
        windowsHide: false,
        shell: false,
        detached: false,
        stdio: 'ignore',
        env: {
          ...process.env,
          ARGUS_BUNDLE_ROOT: this.bundleRoot,
          ARGUS_BACKEND_DIR: this.rootDir,
          OPENCLAW_HOME: process.env.OPENCLAW_HOME || this.openClawStateDir,
          OPENCLAW_STATE_DIR: process.env.OPENCLAW_STATE_DIR || this.openClawStateDir
        }
      })
      this.processes[name] = proc
      proc.once('error', (error) => {
        this.log(source, `日志终端启动失败：${error.message}`, 'error')
        this.processes[name] = null
      })
      proc.once('close', (code) => {
        if (code !== 0 && code !== null) this.log(source, `日志终端已关闭，退出码: ${code}`, 'warn')
        else this.log(source, '日志终端已关闭')
        if (this.processes[name] === proc) this.processes[name] = null
      })
      this.tailLog(source, logFile)
      return proc
    } catch (error) {
      this.log(source, `日志终端启动异常，回退隐藏模式：${error.message}`, 'warn')
      return null
    }
  }

  spawnService(name, source, executable, args, cwd, useShell) {
    if (!fs.existsSync(cwd)) {
      this.log(source, `工作目录不存在：${cwd}`, 'error')
      return null
    }

    this.log(source, `正在启动：${path.basename(executable)} ${args.join(' ')}`)

    if (this.consoleLogEnabled()) {
      const script = this.consoleScriptPath()
      if (script) {
        const consoleProc = this.spawnConsoleService(name, source, executable, args, cwd, script)
        if (consoleProc) return consoleProc
      }
    }

    try {
      // Do not use shell:true here. It makes Electron depend on a cmd.exe
      // inherited from the launching shell and is the cause of the ENOENT error.
      const proc = spawn(executable, args, {
        cwd,
        windowsHide: true,
        shell: Boolean(useShell),
        env: {
          ...process.env,
          ARGUS_BUNDLE_ROOT: this.bundleRoot,
          ARGUS_BACKEND_DIR: this.rootDir,
          OPENCLAW_HOME: process.env.OPENCLAW_HOME || this.openClawStateDir,
          OPENCLAW_STATE_DIR: process.env.OPENCLAW_STATE_DIR || this.openClawStateDir
        }
      })
      this.attachProcess(name, proc)
      return proc
    } catch (error) {
      this.log(source, `启动异常：${error.message}`, 'error')
      return null
    }
  }

  resolveOpenClawCommand() {
    try {
      const shims = [];
      if (process.env.APPDATA) shims.push(path.join(process.env.APPDATA, 'npm', 'openclaw.cmd'));
      const homeDir = process.env.USERPROFILE || os.homedir();
      if (homeDir) shims.push(path.join(homeDir, 'AppData', 'Roaming', 'npm', 'openclaw.cmd'));
      const pathDirs = String(process.env.PATH || '').split(';');
      for (const d of pathDirs) {
        if (!d) continue;
        shims.push(path.join(d, 'openclaw.cmd'));
        shims.push(path.join(d, 'openclaw.exe'));
      }
      for (const s of shims) {
        try { if (s && fs.existsSync(s)) return s; } catch (e) {}
      }
    } catch (e) {}
    return null;
  }
    ensureOpenClawState() {
    try {
      if (!fs.existsSync(this.openClawStateDir)) {
        fs.mkdirSync(this.openClawStateDir, { recursive: true });
        this.log('OpenClaw', 'state dir created, first run init');
      }
    } catch (e) {
      this.log('OpenClaw', 'state dir create failed, gateway may not start', 'warn');
      return;
    }
    try {
      const names = fs.readdirSync(this.openClawStateDir);
      for (const n of names) {
        if (!/lock/i.test(n)) continue;
        const fp = path.join(this.openClawStateDir, n);
        try {
          const txt = fs.readFileSync(fp, 'utf8');
          const m = /(\d{3,7})/.exec(txt);
          let alive = false;
          if (m) {
            try { process.kill(Number(m[1]), 0); alive = true; } catch (ee) { alive = false; }
          }
          if (!alive) {
            fs.unlinkSync(fp);
            this.log('OpenClaw', 'removed stale gateway lock, will restart fresh');
          }
        } catch (ee) {}
      }
    } catch (e) {}
  }
repairOpenClawConfig() {
    const configPath = path.join(this.openClawStateDir, 'openclaw.json')
    if (!fs.existsSync(configPath)) return
    try {
      const config = JSON.parse(fs.readFileSync(configPath, 'utf8'))
      const paths = config?.plugins?.load?.paths
      if (!Array.isArray(paths)) return
      const validPaths = paths.filter((pluginPath) => typeof pluginPath === 'string' && fs.existsSync(pluginPath))
      if (validPaths.length === paths.length) return
      config.plugins.load.paths = validPaths
      fs.writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`, 'utf8')
      this.log('OpenClaw', `已清理不存在的插件路径：${configPath}`)
    } catch (error) {
      this.log('OpenClaw', `配置路径修复跳过：${error.message}`, 'warn')
    }
  }
  // Step 5：默认只拉新链路（:8000 + :18789）。老链路（:18080 Bridge、:3000 OpenGuard）
  // 仅在 ARGUS_LEGACY_CHAIN=1 时拉起，用于回滚过渡。
  isLegacyChain() {
    return (process.env.ARGUS_LEGACY_CHAIN) === '1'
  }

  async startAll() {
    this.startWatchdog()
    this.log('DAEMON', '正在检测后台核心服务状态...')

    const isFastApiRunning = await this.checkPort(8000)
    if (!isFastApiRunning) this.startFastApi()
    else this.log('FastAPI', '检测到 127.0.0.1:8000 已由现有守护进程托管运行中')

    this.ensureOpenClawState();
    this.repairOpenClawConfig()

    const isOpenClawRunning = await this.checkPort(18789)
    if (!isOpenClawRunning) this.startOpenClaw()
    else this.log('OpenClaw', '检测到 127.0.0.1:18789 已由现有守护进程托管运行中')

    if (!this.isLegacyChain()) {
      this.log('DAEMON', '新链路模式：跳过 Bridge(:18080) 与 OpenGuard(:3000)，如需回滚请设置 ARGUS_LEGACY_CHAIN=1')
      return
    }

    // 老链路（过渡保留）：先启动 OpenClaw，再启动 Bridge，避免 Bridge 在网关未就绪时退出。
    this.log('DAEMON', '老链路模式（ARGUS_LEGACY_CHAIN=1）：拉起 Bridge 与 OpenGuard')
    const isBridgeRunning = await this.checkPort(18080)
    if (!isBridgeRunning) this.startBridge()
    else this.log('Bridge', '检测到 127.0.0.1:18080 已由现有守护进程托管运行中')

    // OpenGuard 提供个人版会话列表、历史消息和聊天 WebSocket（老链路）。
    const isOpenGuardRunning = await this.checkPort(3000)
    if (!isOpenGuardRunning) this.startOpenGuard()
    else this.log('OpenGuard', '检测到 127.0.0.1:3000 已由现有服务托管运行中')
  }

  async ensureEnterpriseService() {
    const running = await this.checkPort(8080)
    if (running) {
      this.log('LLMGate', '检测到 127.0.0.1:8080 已由现有企业服务托管运行中')
      return { ok: true, started: false, port: 8080 }
    }
    if (!fs.existsSync(this.llmGateExecutable)) {
      this.log('LLMGate', `找不到企业服务可执行文件：${this.llmGateExecutable}`, 'error')
      return { ok: false, started: false, port: 8080, error: 'executable_not_found' }
    }
    if (!fs.existsSync(this.llmGateConfig)) {
      this.log('LLMGate', `找不到企业服务配置文件：${this.llmGateConfig}`, 'error')
      return { ok: false, started: false, port: 8080, error: 'config_not_found' }
    }
    if (this.processes.llmgate?.pid) {
      const ready = await this.waitForPort(8080, 20)
      return { ok: ready, started: true, port: 8080 }
    }
    this.startLLMGate()
    this.llmgateStartedByUs = true
    const ready = await this.waitForPort(8080, 20)
    if (!ready) this.log('LLMGate', '企业服务启动后未在 20 秒内监听 127.0.0.1:8080', 'error')
    return { ok: ready, started: true, port: 8080 }
  }

  async waitForPort(port, timeoutSeconds = 20) {
    for (let i = 0; i < timeoutSeconds * 2; i += 1) {
      if (await this.checkPort(port)) return true
      await new Promise((resolve) => setTimeout(resolve, 500))
    }
    return false
  }

  startLLMGate() {
    this.spawnService(
      'llmgate',
      'LLMGate',
      this.llmGateExecutable,
      ['-config', this.llmGateConfig],
      this.llmGateDir
    )
  }

  // ── OpenClaw 模型跟随切换（企业版 <-> 个人版）─────────────────────
  openclawConfigPath() {
    return path.join(this.openClawStateDir, 'openclaw.json')
  }

  remoteJsonPath() {
    return path.join(this.rootDir, 'configs', 'remote.json')
  }

  // 只有本桌面端拉起的 OpenClaw 才自动重启（外部自带的网关不动，只改配置并提示手动重启）。
  restartManagedOpenClaw() {
    const proc = this.processes.openclaw
    if (!proc || !proc.pid) return { restarted: false, reason: 'not-managed' }
    const pid = proc.pid
    try {
      if (process.platform === 'win32') {
        exec(`taskkill /PID ${pid} /T /F`, { windowsHide: true }, () => {})
      } else {
        proc.kill('SIGTERM')
      }
    } catch (error) {
      this.log('OpenClaw', `重启旧进程失败：${error.message}`, 'warn')
      return { restarted: false, reason: 'kill-failed' }
    }
    this.processes.openclaw = null
    setTimeout(() => this.startOpenClaw(), 2000)
    return { restarted: true }
  }

  // 按端口查找占用 18789 的外部 OpenClaw 进程（用于守护开关/版本切换时的联动重启）。
  findPidByPort(port) {
    return new Promise((resolve) => {
      try {
        if (process.platform === 'win32') {
          exec('netstat -ano', { windowsHide: true, timeout: 5000 }, (err, stdout) => {
            if (err || !stdout) return resolve(null);
            const lines = String(stdout).split(/\r?\n/);
            const want = ':' + port + ' ';
            for (const ln of lines) {
              if (ln.indexOf('TCP') < 0 || ln.indexOf(want) < 0) continue;
              const parts = ln.trim().split(/\s+/);
              const pid = parseInt(parts[parts.length - 1], 10);
              if (Number.isFinite(pid) && pid > 0) return resolve(pid);
            }
            resolve(null);
          });
        } else {
          exec('lsof -ti tcp:' + port, { timeout: 5000 }, (err, stdout) => {
            if (err || !stdout) return resolve(null);
            const pid = parseInt(String(stdout).split(/\s+/)[0], 10);
            resolve(Number.isFinite(pid) ? pid : null);
          });
        }
      } catch (e) { resolve(null); }
    });
  }

  // 守护开关 / 版本切换的联动重启：托管的直接重启；外部占用的接管重启；端口空闲的直接拉起。
  async restartOpenClawOnDemand(reason) {
    const tag = reason || 'guard-toggle';
    const managed = this.processes.openclaw;
    if (managed && managed.pid) {
      this.log('OpenClaw', `守护联动重启 OpenClaw（${tag}）：正在重启本桌面端托管的网关…`);
      return this.restartManagedOpenClaw();
    }
    let busy = false;
    try { busy = await this.checkTcpPort(18789, 900); } catch (e) { busy = false; }
    if (!busy) {
      this.log('OpenClaw', `守护联动重启 OpenClaw（${tag}）：18789 空闲，直接拉起网关生效`);
      try { this.startOpenClaw(); } catch (e) { this.log('OpenClaw', `拉起失败：${e.message}`, 'warn'); return { restarted: false, reason: 'start-failed' }; }
      return { restarted: true, mode: 'started' };
    }
    const pid = await this.findPidByPort(18789);
    if (!pid) { this.log('OpenClaw', '18789 被外部占用但找不到进程号，请手动重启 OpenClaw 生效', 'warn'); return { restarted: false, reason: 'external-unknown-pid' }; }
    this.log('OpenClaw', `守护联动重启 OpenClaw（${tag}）：接管外部网关进程 ${pid} 并重启生效`);
    try {
      if (process.platform === 'win32') exec(`taskkill /PID ${pid} /T /F`, { windowsHide: true }, () => {});
      else try { process.kill(pid, 'SIGTERM'); } catch (e) {}
    } catch (e) { this.log('OpenClaw', `结束外部网关失败：${e.message}`, 'warn'); return { restarted: false, reason: 'kill-failed' }; }
    setTimeout(() => this.startOpenClaw(), 2000);
    return { restarted: true, mode: 'takeover', pid: pid };
  }

  // 进入企业版：OpenClaw 模型切到企业网关（切换即联动重启网关生效）。
  async switchOpenClawToEnterprise() {
    const result = modelSwitch.switchToEnterprise(this.openclawConfigPath(), this.remoteJsonPath())
    if (!result.ok) {
      this.log('OpenClaw', `企业版模型切换跳过（${result.reason}），仍用本地模型`, 'warn')
      return result
    }
    if (result.unchanged) {
      this.log('OpenClaw', '已在企业网关上，无需重复切换')
      return result
    }
    this.log('OpenClaw', `已切到企业网关模型：${result.baseUrl}，正在重启网关生效`)
    result.restart = await this.restartOpenClawOnDemand('enterprise-switch')
    if (!result.restart.restarted) this.log('OpenClaw', `网关自动重启失败（${result.restart.reason}），请手动重启 OpenClaw 生效`, 'warn')
    return result
  }

  // 回到个人版：OpenClaw 模型还原（切换即联动重启网关生效）。
  async switchOpenClawToPersonal() {
    const result = modelSwitch.switchToPersonal(this.openclawConfigPath())
    if (!result.ok) {
      this.log('OpenClaw', `个人版模型还原跳过（${result.reason}）`, 'warn')
      return result
    }
    if (result.unchanged) {
      this.log('OpenClaw', '已是个人版模型，无需重复还原')
      return result
    }
    this.log('OpenClaw', '已还原个人版模型，正在重启网关生效')
    result.restart = await this.restartOpenClawOnDemand('personal-switch')
    if (!result.restart.restarted) this.log('OpenClaw', `网关自动重启失败（${result.restart.reason}），请手动重启 OpenClaw 生效`, 'warn')
    return result
  }
  stopEnterpriseService() {
    // 不停止由管理员或其他程序预先启动的企业服务，只回收本桌面端拉起的进程。
    const proc = this.processes.llmgate
    if (!this.llmgateStartedByUs || !proc?.pid) return { ok: true, stopped: false, port: 8080 }
    if (process.platform === 'win32') {
      exec(`taskkill /PID ${proc.pid} /T /F`, { windowsHide: true }, () => {})
    } else {
      proc.kill('SIGTERM')
    }
    this.processes.llmgate = null
    this.llmgateStartedByUs = false
    this.log('LLMGate', '已退出企业版，停止本桌面端按需启动的企业服务')
    return { ok: true, stopped: true, port: 8080 }
  }

  startFastApi() {
    this.spawnService(
      'fastapi',
      'FastAPI',
      this.pythonExecutable,
      ['-m', 'uvicorn', 'argus.api.main:app', '--host', '127.0.0.1', '--port', '8000'],
      this.rootDir
    )
  }

  startOpenGuard() {
    this.spawnService(
      'openguard',
      'OpenGuard',
      this.pythonExecutable,
      ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '3000'],
      this.openGuardDir
    )
  }

  startBridge() {
    this.spawnService(
      'bridge',
      'Bridge',
      this.nodeExecutable,
      [path.join(this.rootDir, 'openguard', 'original', 'bridge.js')],
      this.rootDir
    )
  }

  startOpenClaw() {
    try { this.ensureOpenClawState(); } catch (e) {}
    if (!this.openClawEntry) {
      try { this.openClawCmd = this.resolveOpenClawCommand(); } catch (e) {}
      if (this.openClawCmd) {
        this.log('OpenClaw', 'found global command, starting gateway');
        this.spawnService('openclaw', 'OpenClaw', this.openClawCmd, ['gateway', 'run', '--allow-unconfigured', '--port', '18789', '--bind', 'loopback'], this.rootDir, true);
        return;
      }
      this.log('OpenClaw', 'no entry and no global command, install in wizard first', 'error');
      return;
    }

    this.spawnService(
      'openclaw',
      'OpenClaw',
      this.nodeExecutable,
      [this.openClawEntry, 'gateway', 'run', '--allow-unconfigured', '--port', '18789', '--bind', 'loopback'],
      this.rootDir
    )
  }

  // Watchdog: patrol every 60s. Restart FastAPI if :8000 is down; if :8000 is up but
  // the sync heartbeat is stale for 3+ minutes, fire one incremental sync-now round.
  // This keeps heartbeat/audit/usage auto-syncing from now on.
  startWatchdog() {
    if (this._watchdog) return
    const tick = async () => {
      try {
        let up = false
        try { up = await this.checkTcpPort(8000, 900) } catch (e) { up = false }
        if (!up) {
          this.log('DAEMON', 'watchdog: 127.0.0.1:8000 离线，正在拉起 FastAPI')
          try { this.startFastApi() } catch (e) { this.log('DAEMON', 'watchdog: 拉起失败', 'warn') }
          return
        }
        let stale = false
        try {
          const curPath = path.join(this.rootDir, 'runtime', 'remote', 'cursors.json')
          if (!fs.existsSync(curPath)) {
            stale = true
          } else {
            const cur = JSON.parse(fs.readFileSync(curPath, 'utf8'))
            const hb = Date.parse(cur.last_heartbeat_at || cur.last_report_at || 0)
            if (!Number.isFinite(hb) || Date.now() - hb > 3 * 60 * 1000) stale = true
          }
        } catch (e) { stale = true }
        if (!stale) return
        this.log('DAEMON', 'watchdog: 心跳超过 3 分钟没更新，触发一次增量同步')
        await new Promise((resolve) => {
          let done = false
          const finish = () => { if (!done) { done = true; resolve() } }
          try {
            const req = http.request({ host: '127.0.0.1', port: 8000, path: '/v1/remote/sync-now', method: 'POST', timeout: 25000 }, (res) => {
              res.resume()
              res.on('end', finish)
              res.on('close', finish)
            })
            req.on('timeout', () => { try { req.destroy() } catch (e) {} finish() })
            req.on('error', () => finish())
            req.end()
          } catch (e) { finish() }
        })
      } catch (e) {}
    }
    this._watchdog = setInterval(tick, 60000)
    setTimeout(tick, 65000)
  }

  stopAll() {
    this.log('DAEMON', '正在优雅退出并回收后台子进程资源...')
    if (this._tailTimers) {
      for (const timer of this._tailTimers) { try { clearInterval(timer) } catch (e) {} }
      this._tailTimers = []
    }
    for (const [name, proc] of Object.entries(this.processes)) {
      if (!proc || !proc.pid) continue

      if (process.platform === 'win32') {
        // taskkill is intentionally only used for cleanup, after the process
        // has been spawned without a shell. Ignore the callback error during quit.
        exec(`taskkill /PID ${proc.pid} /T /F`, { windowsHide: true }, () => {})
      } else {
        proc.kill('SIGTERM')
      }
      this.processes[name] = null
    }
  }
}

module.exports = DaemonManager






