const { app, BrowserWindow, ipcMain, shell, nativeImage, session } = require('electron')
const path = require('path')
const fs = require('fs')
const DaemonManager = require('./daemon')
const setup = require('./setup')

const appIcon = path.join(__dirname, '../renderer/assets/logo.ico')
const appIconImage = nativeImage.createFromPath(appIcon)
app.setAppUserModelId('com.argus.desktop')
app.setName('Argus')
const gotSingleInstanceLock = app.requestSingleInstanceLock()

let mainWindow = null; let debugWin = null
let daemon = null

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1240,
    height: 840,
    minWidth: 980,
    minHeight: 650,
    frame: false,
    icon: appIconImage,
    backgroundColor: '#0B0E14',
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false,
      webSecurity: false,
      webviewTag: true
    }
  })

  // Use the Argus ICO for the native window and Windows taskbar entry.
  mainWindow.setIcon(appIconImage)

  const distPath = path.join(__dirname, '../../dist/index.html')
  if (process.env.NODE_ENV === 'development') {
    mainWindow.loadURL('http://localhost:5173')
  } else if (fs.existsSync(distPath)) {
    mainWindow.loadFile(distPath)
  } else {
    mainWindow.loadURL('http://localhost:5173')
  }

  // Electron 不会像普通浏览器那样自动处理 Ctrl + 滚轮缩放。
  // 在主窗口和嵌入的 OpenGuard webview 上统一接管缩放，避免页面滚动吞掉操作。
  const applyBrowserZoom = (contents, input, event) => {
    const modifiers = input.modifiers || []
    if (input.type === 'mouseWheel' && modifiers.includes('control')) {
      const current = Number(contents.getZoomFactor?.() || 1)
      const direction = Number(input.deltaY || 0)
      const next = Math.min(2, Math.max(0.5, current + (direction < 0 ? 0.1 : -0.1)))
      contents.setZoomFactor(next)
      event.preventDefault()
      return
    }

    // Ctrl + 0 恢复 100%，便于测试缩放后快速还原。
    if (input.type === 'keyDown' && modifiers.includes('control') && String(input.key || '').toLowerCase() === '0') {
      contents.setZoomFactor(1)
      event.preventDefault()
    }
  }

  mainWindow.webContents.on('before-input-event', (event, input) => {
    applyBrowserZoom(mainWindow.webContents, input, event)
  })

  // 企业版是在 webview 内打开的，单独监听 guest contents，否则主窗口收不到其滚轮事件。
  mainWindow.webContents.on('did-attach-webview', (_event, guestContents) => {
    guestContents.on('before-input-event', (event, input) => {
      applyBrowserZoom(guestContents, input, event)
    })
  })

  // External links must open in the system browser.
  // The enterprise page is embedded by the renderer instead of using this path.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) {
      shell.openExternal(url)
    }
    return { action: 'deny' }
  })

  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (/^https?:\/\//i.test(url) && !/^https?:\/\/(?:127\.0\.0\.1|localhost):5173/i.test(url)) {
      event.preventDefault()
      shell.openExternal(url)
    }
  })

  daemon = new DaemonManager(mainWindow)
  daemon.startAll()

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}


let debugConsoleNote = '0911b独立调试控制台';
function broadcastWin() {
  return {
    isDestroyed: () => { try { return !mainWindow || mainWindow.isDestroyed() } catch (e) { return true } },
    webContents: {
      send: (channel, data) => {
        try { if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send(channel, data) } catch (e) {}
        try { if (debugWin && !debugWin.isDestroyed()) debugWin.webContents.send(channel, data) } catch (e) {}
      }
    }
  };
}
function openDebugConsole() {
  if (debugWin && !debugWin.isDestroyed()) { try { debugWin.show(); debugWin.focus() } catch (e) {} return; }
  debugWin = new BrowserWindow({ width: 920, height: 660, minWidth: 640, minHeight: 420, title: 'Argus 调试控制台', icon: appIconImage, backgroundColor: '#12141A', autoHideMenuBar: true, webPreferences: { preload: path.join(__dirname, '../preload/index.js'), nodeIntegration: false, contextIsolation: true, sandbox: false } });
  try { debugWin.setMenuBarVisibility(false) } catch (e) {}
  const distPath = path.join(__dirname, '../../dist/index.html');
  if (process.env.NODE_ENV === 'development') { debugWin.loadURL('http://localhost:5173/?view=debug'); }
  else if (fs.existsSync(distPath)) { debugWin.loadFile(distPath, { query: { view: 'debug' } }); }
  else { debugWin.loadURL('http://localhost:5173/?view=debug'); }
  if (daemon) daemon.debugWin = debugWin;
  debugWin.on('closed', () => { debugWin = null; if (daemon) daemon.debugWin = null; });
}
ipcMain.handle('open-debug-console', () => { try { openDebugConsole(); return { ok: true } } catch (e) { return { ok: false, error: String((e && e.message) || e) } } });

// Window control IPCs
ipcMain.on('window-minimize', () => {
  if (mainWindow) mainWindow.minimize()
})

ipcMain.on('window-maximize', () => {
  if (mainWindow) {
    if (mainWindow.isMaximized()) {
      mainWindow.unmaximize()
    } else {
      mainWindow.maximize()
    }
  }
})

ipcMain.on('window-close', () => {
  if (mainWindow) mainWindow.close()
})

// Mini-window mode (enterprise): shrink the main window into a small
// draggable panel; restore the saved desktop bounds on exit.
let savedNormalBounds = null
let isMiniWindow = false

function enterMiniWindow(w, h) {
  if (!mainWindow || mainWindow.isDestroyed()) return
  const width = Number(w) || 380
  const height = Number(h) || 360
  if (!isMiniWindow) {
    savedNormalBounds = mainWindow.getBounds()
    isMiniWindow = true
  }
  if (mainWindow.isMaximized()) mainWindow.unmaximize()
  mainWindow.setMinimumSize(240, 80)
  mainWindow.setSize(width, height)
  mainWindow.setAlwaysOnTop(true)
}

ipcMain.on('window-enter-mini', (_event, size) => {
  enterMiniWindow(size && size.width, size && size.height)
})

ipcMain.on('window-set-mini-size', (_event, size) => {
  if (!mainWindow || mainWindow.isDestroyed() || !isMiniWindow) return
  const width = Number(size && size.width) || 380
  const height = Number(size && size.height) || 360
  mainWindow.setSize(width, height)
})

ipcMain.on('window-exit-mini', () => {
  if (!mainWindow || mainWindow.isDestroyed()) return
  isMiniWindow = false
  mainWindow.setAlwaysOnTop(false)
  mainWindow.setMinimumSize(980, 650)
  if (savedNormalBounds) {
    mainWindow.setBounds(savedNormalBounds)
  } else {
    mainWindow.setSize(1240, 840)
  }
  mainWindow.show()
})

ipcMain.on('open-external-url', (_event, url) => {
  if (typeof url !== 'string' || !/^https?:\/\//i.test(url)) return
  shell.openExternal(url)
})

// Step 5：老链路登录会话读取（:3000）已停用，保留空壳防 preload 引用报错。
// 企业版走 LLMGate 登录（见迁移计划 §2.2）。
ipcMain.handle('openguard-get-auth', async () => {
  return { token: '', refreshToken: '' }
})


// 首次启动安装向导：检查 / 安装 / 是否已完成（标记存在 userData，换机器重装会重新走一遍）。
const setupFlagFile = () => path.join(app.getPath('userData'), 'setup-done.json')
ipcMain.handle('setup-check', async () => {
  if (!daemon) return null
  return setup.checkAll(daemon)
})
ipcMain.handle('setup-install', async (_event, id) => {
  if (!daemon || !mainWindow) return { ok: false }
    if (id === 'pyDeps') {
    const mainReq = path.join(daemon.rootDir, 'requirements.txt');
    const guardReq = path.join(daemon.openGuardDir, 'requirements.txt');
    const r1 = await setup.runInstall(broadcastWin(), 'py-main', daemon.pythonExecutable,
      ['-m', 'pip', 'install', '--prefer-binary', '-r', mainReq], daemon.rootDir);
    if (!r1 || !r1.ok) return r1;
    if (fs.existsSync(guardReq)) {
      const r2 = await setup.runInstall(broadcastWin(), 'py-guard', daemon.pythonExecutable,
        ['-m', 'pip', 'install', '--prefer-binary', '-r', guardReq], daemon.openGuardDir);
      if (!r2 || !r2.ok) return r2;
    }
    const verify = await setup.checkPythonDeps(daemon.pythonExecutable);
    if (!verify.ok) return { ok: false, log: 'pip done but import still missing: ' + (verify.missing || []).join(',') };
    return { ok: true, log: 'pyDeps verified ok' };
  }
  if (id === 'bridgeDeps') {
    const r = await setup.runInstall(broadcastWin(), '工作台依赖', 'npm',
      ['install', '--no-audit', '--no-fund', '--prefer-online', '--no-offline'], daemon.openGuardDir)
    if (r && !r.ok && /EALLOWREMOTE|offline/i.test(r.log || '')) {
      r.log = (r.log || '') + '\n[提示] 你本机 npm 被设成了离线模式（拒绝联网下载）。请手动执行：npm config delete offline，然后回来点安装重试。'
    }
    return r
  }
  if (id === 'openclaw') {
    const r = await setup.runInstall(broadcastWin(), 'OpenClaw', 'npm',
      ['install', '-g', 'openclaw', '--prefer-online', '--no-offline'], daemon.rootDir)
    if (r && r.ok) {
      const found = setup.findOpenClawEntry()
      if (found) daemon.openClawEntry = found
      try { const oc = setup.findOpenClawCommand(); if (oc) daemon.openClawCmd = oc; } catch (e) {}
    }
    const v = await setup.checkCommand('openclaw', ['--version']);
    if (v && v.ok) return { ok: true };
    if (daemon.openClawEntry || daemon.openClawCmd) return { ok: true };
    return { ok: false, log: 'openclaw not found after install' }
  }
  return { ok: false }
})
ipcMain.handle('setup-is-done', () => {
  try { return fs.existsSync(setupFlagFile()) } catch { return false }
})
ipcMain.handle('setup-mark-done', () => {
  try { fs.writeFileSync(setupFlagFile(), JSON.stringify({ done: true, at: Date.now() })) } catch {}
  return { ok: true }
})

ipcMain.handle('daemon-log-history', (_event, limit) => daemon ? daemon.getLogHistory(limit) : [])
ipcMain.handle('enterprise-service-start', async () => {
  if (!daemon) return { ok: false, started: false, port: 8080, error: 'daemon_unavailable' }
  return daemon.ensureEnterpriseService()
})
ipcMain.handle('enterprise-service-stop', async () => {
  if (!daemon) return { ok: false, stopped: false, port: 8080, error: 'daemon_unavailable' }
  return daemon.stopEnterpriseService()
})

ipcMain.handle('openclaw-use-enterprise', async () => {
  if (!daemon) return { ok: false, reason: 'daemon_unavailable' }
  return daemon.switchOpenClawToEnterprise()
})
ipcMain.handle('openclaw-use-personal', async () => {
  if (!daemon) return { ok: false, reason: 'daemon_unavailable' }
  return daemon.switchOpenClawToPersonal()
})
ipcMain.handle('openclaw-restart', async (_event, reason) => {
  if (!daemon) return { restarted: false, reason: 'daemon_unavailable' }
  return daemon.restartOpenClawOnDemand(reason)
})
ipcMain.handle('daemon-status', async () => {
  if (!daemon) return { build: false, fastapi: false, openclaw: false, bridge: false, legacy: false }
  const legacy = daemon.isLegacyChain ? daemon.isLegacyChain() : false
  const [fastapi, openclaw, llmgate, bridge] = await Promise.all([
    daemon.checkPort(8000),
    daemon.checkGatewayPort ? daemon.checkGatewayPort(18789) : daemon.checkPort(18789),
    daemon.checkPort(8080),
    // 新链路下 Bridge 不再拉起：legacy=false 时直接报 false，前端不再等待它。
    legacy ? (daemon.checkGatewayPort ? daemon.checkGatewayPort(18080) : daemon.checkPort(18080)) : Promise.resolve(false),
  ])
  return { build: true, fastapi, openclaw, llmgate, bridge, legacy }
})
ipcMain.handle('app-set-auto-start', (_event, enabled) => {
  const openAtLogin = Boolean(enabled)
  try { app.setLoginItemSettings({ openAtLogin, path: process.execPath }) } catch {}
  return { enabled: openAtLogin }
})

ipcMain.on('daemon-restart', () => {
  if (daemon) {
    daemon.stopAll()
    setTimeout(() => {
      daemon.startAll()
    }, 1000)
  }
})

if (!gotSingleInstanceLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (!mainWindow || mainWindow.isDestroyed()) return
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.show()
    mainWindow.focus()
  })

app.whenReady().then(() => {
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('before-quit', () => {
  if (daemon) {
    daemon.stopAll()
  }
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
}

















