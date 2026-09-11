const { spawn } = require('child_process')
const http = require('http')
const path = require('path')

console.log('[DevRunner] 正在启动 Vite 开发服务器...')
const vite = spawn('npx', ['vite'], {
  cwd: path.resolve(__dirname, '..'),
  shell: true,
  stdio: 'inherit'
})

function checkViteReady(callback) {
  const req = http.get('http://localhost:5173', (res) => {
    callback()
  })
  req.on('error', () => {
    setTimeout(() => checkViteReady(callback), 300)
  })
}

checkViteReady(() => {
  console.log('[DevRunner] Vite 服务已就绪，正在拉起 Electron 桌面客户端...')
  const electron = spawn('npx', ['electron', '.'], {
    cwd: path.resolve(__dirname, '..'),
    shell: true,
    stdio: 'inherit',
    env: { ...process.env, NODE_ENV: 'development' }
  })

  electron.on('close', () => {
    console.log('[DevRunner] Electron 已关闭，清理 Vite 进程...')
    vite.kill()
    process.exit(0)
  })
})
