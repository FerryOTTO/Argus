// 首次启动安装向导：检查并安装个人版运行依赖（Python / Node / Python 依赖 / Bridge 依赖 / OpenClaw）。
// 通俗说：新机器第一次打开客户端，先把缺的东西装好，装完以后直接进个人版，不用再管这个页面。
const { spawn } = require('child_process')
const path = require('path')
const fs = require('fs')

// Python 依赖是否齐：直接试着 import，缺哪个报哪个。
function checkPythonDeps(pythonExe) {
  return new Promise((resolve) => {
    const proc = spawn(pythonExe, ['-c', 'import fastapi, uvicorn, pydantic, yaml, httpx, networkx, aiosqlite, apscheduler, bcrypt, jwt, websockets, numpy, docx, fitz, openpyxl, PIL, joblib, sklearn, dotenv, jinja2, aiofiles, faker'], { windowsHide: true, shell: process.platform === 'win32' })
    let stderr = ''
    proc.stderr.on('data', (d) => { stderr += d.toString() })
    proc.on('error', () => resolve({ ok: false, missing: ['python 不可用'] }))
    proc.on('close', (code) => {
      if (code === 0) return resolve({ ok: true, missing: [] })
      const m = /No module named '([^']+)'/.exec(stderr)
      resolve({ ok: false, missing: m ? [m[1]] : ['部分依赖缺失'] })
    })
  })
}

// 命令是否存在（python / node / openclaw）
function checkCommand(cmd, args) {
  return new Promise((resolve) => {
    const proc = spawn(cmd, args || ['--version'], { windowsHide: true, shell: process.platform === 'win32' })
    let out = ''
    proc.stdout.on('data', (d) => { out += d.toString() })
    proc.stderr.on('data', (d) => { out += d.toString() })
    proc.on('error', () => resolve({ ok: false, version: '' }))
    proc.on('close', (code) => resolve({ ok: code === 0, version: out.trim().split('\n')[0] || '' }))
  })
}

// 在带后端的安装包里补一个空 remote.json（令牌由绑定流程填，不随包走）。
function ensureRemoteTemplate(daemon) {
  try {
    const cfgDir = path.join(daemon.rootDir, 'configs')
    const rp = path.join(cfgDir, 'remote.json')
    if (fs.existsSync(cfgDir) && !fs.existsSync(rp)) {
      fs.writeFileSync(rp, JSON.stringify({
        base_url: 'http://127.0.0.1:8080', token: '', enterprise_name: '',
        terminal_name: '', note: '首次使用请在服务端管理后台创建终端、拿到注册码后绑定，token 由绑定流程自动填入'
      }, null, 2))
    }
  } catch {}
}

// OpenClaw 入口重找（刚装好时用，让桌面端不用重启就能认到）。
function findOpenClawEntry() {
  const home = process.env.USERPROFILE || process.env.HOME || ''
  const candidates = [
    (process.env.ARGUS_OPENCLAW_ENTRY),
    process.env.APPDATA && path.join(process.env.APPDATA, 'npm', 'node_modules', 'openclaw', 'openclaw.mjs'),
    home && path.join(home, 'AppData', 'Roaming', 'npm', 'node_modules', 'openclaw', 'openclaw.mjs')
  ]
  return candidates.find((c) => c && fs.existsSync(c)) || null
}

// 全量检查：返回每一项 ok / 版本 / 说明
function findOpenClawCommand() {
  try {
    const shims = [];
    if (process.env.APPDATA) shims.push(path.join(process.env.APPDATA, 'npm', 'openclaw.cmd'));
    const home = process.env.USERPROFILE || process.env.HOME || '';
    if (home) shims.push(path.join(home, 'AppData', 'Roaming', 'npm', 'openclaw.cmd'));
    const dirs = String(process.env.PATH || '').split(';');
    for (const d of dirs) {
      if (!d) continue;
      shims.push(path.join(d, 'openclaw.cmd'));
    }
    return shims.find((c) => c && fs.existsSync(c)) || null;
  } catch (e) { return null; }
}

async function checkAll(daemon) {
  ensureRemoteTemplate(daemon);
  const python = await checkCommand(daemon.pythonExecutable, ['--version'])
  const node = await checkCommand(daemon.nodeExecutable, ['--version'])
  let pyDeps = { ok: false, missing: [] }
  if (python.ok) pyDeps = await checkPythonDeps(daemon.pythonExecutable)
  const bridgeModules = path.join(daemon.openGuardDir, 'node_modules')
  const bridgeDeps = { ok: fs.existsSync(path.join(bridgeModules, 'ws')) }
  const openclaw = { ok: Boolean(daemon.openClawEntry), path: daemon.openClawEntry || '' }
  if (!openclaw.ok) {
    // daemon 启动时没找到，再试一次全局命令（用户可能刚装好）。
    const cmd = await checkCommand('openclaw', ['--version'])
    if (cmd.ok) { openclaw.ok = true; openclaw.path = 'openclaw（全局命令）' }
  }
  return { python, node, pyDeps, bridgeDeps, openclaw }
}

// 跑一条安装命令，把输出实时推给页面。
function runInstall(mainWindow, title, cmd, args, cwd) {
  return new Promise((resolve) => {
    const send = (text) => {
      try {
        if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('setup-log', { text: String(text) })
      } catch {}
    }
    if (cwd && !fs.existsSync(cwd)) {
      send('[' + title + '] 装不了：缺少终端文件目录（安装包不完整），请重新下载完整安装包')
      resolve({ ok: false, log: 'missing backend dir: ' + cwd })
      return
    }
    send('[' + title + '] 开始执行：' + cmd + ' ' + args.join(' '))
    const proc = spawn(cmd, args, { cwd, windowsHide: true, shell: process.platform === 'win32' })
    let log = ''
    const onData = (d) => { const s = d.toString(); log += s; send(s.length > 500 ? s.slice(-500) : s) }
    proc.stdout.on('data', onData)
    proc.stderr.on('data', onData)
    proc.on('error', (e) => {
      send('[' + title + '] 启动失败：' + e.message + '（-4058 一般是找不到命令或目录）')
      resolve({ ok: false, log: log + '\n启动失败：' + e.message })
    })
    proc.on('close', (code) => {
      let extra = ''
      if (code === -4058) extra = '（找不到命令或目录，请检查上面日志）'
      send('[' + title + '] 结束，退出码 ' + code + extra)
      resolve({ ok: code === 0, log })
    })
  })
}

module.exports = { checkAll, checkPythonDeps, checkCommand, runInstall, findOpenClawEntry, findOpenClawCommand, ensureRemoteTemplate }

