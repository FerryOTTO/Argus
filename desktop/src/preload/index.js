const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  minimize: () => ipcRenderer.send('window-minimize'),
  maximize: () => ipcRenderer.send('window-maximize'),
  close: () => ipcRenderer.send('window-close'),
  enterMiniMode: (size) => ipcRenderer.send('window-enter-mini', size || {}),
  setMiniSize: (size) => ipcRenderer.send('window-set-mini-size', size || {}),
  exitMiniMode: () => ipcRenderer.send('window-exit-mini'),
  openExternal: (url) => ipcRenderer.send('open-external-url', url),
  getOpenGuardAuth: () => ipcRenderer.invoke('openguard-get-auth'),
  restartServices: () => ipcRenderer.send('daemon-restart'),
  startEnterpriseService: () => ipcRenderer.invoke('enterprise-service-start'),
  stopEnterpriseService: () => ipcRenderer.invoke('enterprise-service-stop'),
  useEnterpriseModel: () => ipcRenderer.invoke('openclaw-use-enterprise'),
  usePersonalModel: () => ipcRenderer.invoke('openclaw-use-personal'),
  restartOpenClaw: (reason) => ipcRenderer.invoke('openclaw-restart', reason),
  getDaemonStatus: () => ipcRenderer.invoke('daemon-status'),
  setAutoStart: (enabled) => ipcRenderer.invoke('app-set-auto-start', Boolean(enabled)),
  setupCheck: () => ipcRenderer.invoke('setup-check'),
  setupInstall: (id) => ipcRenderer.invoke('setup-install', id),
  setupIsDone: () => ipcRenderer.invoke('setup-is-done'),
  setupMarkDone: () => ipcRenderer.invoke('setup-mark-done'),
  openDebugConsole: () => ipcRenderer.invoke('open-debug-console'),
  onSetupLog: (callback) => {
    const handler = (_event, data) => callback(data && data.text)
    ipcRenderer.on('setup-log', handler)
    return () => ipcRenderer.removeListener('setup-log', handler)
  },
  getDaemonLogHistory: (limit = 80) => ipcRenderer.invoke('daemon-log-history', limit),
  onDaemonLog: (callback) => {
    const handler = (_event, data) => callback(data)
    ipcRenderer.on('daemon-log', handler)
    return () => ipcRenderer.removeListener('daemon-log', handler)
  }
})




