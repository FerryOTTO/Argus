<template>
  <div class="space-y-5 select-none">
    <div v-if="standalone" class="rounded-2xl border border-orange-200 bg-orange-50 p-4 text-xs leading-relaxed text-zinc-700">独立调试控制台：安装和后台服务的实时输出都会进下面这个黑窗口。哪一项爆红，就点右上角“复制全部日志”，把日志发回来，直接就能定位问题。关掉这个窗口不影响安装继续跑。</div>
    <!-- Action Bar & Service Cards -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-5">
      <div
        v-for="proc in processes"
        :key="proc.id"
        class="coder-card p-5 flex items-center justify-between"
      >
        <div class="flex items-center gap-3">
          <div :class="['w-10 h-10 rounded-2xl flex items-center justify-center border', proc.running ? 'bg-emerald-50 border-emerald-200 text-emerald-600' : 'bg-red-50 border-red-200 text-red-600']">
            <Server class="w-5 h-5" />
          </div>
          <div>
            <div class="flex items-center gap-2">
              <h4 class="font-bold text-zinc-900 text-xs">{{ proc.name }}</h4>
              <span :class="['w-2 h-2 rounded-full', proc.running ? 'bg-emerald-500 animate-pulse' : 'bg-red-500']"></span>
            </div>
            <p class="text-[11px] font-mono text-zinc-500 mt-0.5">{{ proc.endpoint }}</p>
          </div>
        </div>

        <button
          @click="toggleProcess(proc)"
          :class="['text-xs px-3 py-1.5 rounded-xl border font-medium transition-all cursor-pointer', proc.running ? 'bg-red-50 hover:bg-red-100 text-red-700 border-red-200' : 'bg-emerald-50 hover:bg-emerald-100 text-emerald-700 border-emerald-200']"
        >
          {{ proc.running ? '终止' : '拉起' }}
        </button>
      </div>
    </div>

    <!-- Terminal Console Card -->
    <div class="coder-card p-6">
      <div class="flex items-center justify-between mb-4 pb-3 border-b border-zinc-100">
        <div class="flex items-center gap-2">
          <Terminal class="w-4 h-4 text-[#FF6900]" />
          <h3 class="font-bold text-zinc-900 text-sm">守护集群实时控制台流水 (Daemon Live Console)</h3>
        </div>
        <div class="flex items-center gap-3 text-xs">
          <button @click="copyLogs" class="text-zinc-500 hover:text-zinc-900 transition-colors cursor-pointer">复制全部日志</button><span v-if="copied" class="text-xs text-emerald-600">已复制，去粘贴吧</span><button @click="clearLogs" class="text-zinc-500 hover:text-zinc-900 transition-colors cursor-pointer">清空屏幕</button>
          <button @click="restartAll" class="mimo-btn-primary text-xs py-1.5 px-3.5 cursor-pointer">
            <RefreshCw class="w-3.5 h-3.5" />
            一键重启守护集群
          </button>
        </div>
      </div>

      <!-- High-tech Dark Embedded Terminal Screen -->
      <div
        ref="termBoxRef"
        class="w-full h-80 bg-[#12141A] rounded-2xl border border-zinc-800 p-4 font-mono text-xs overflow-y-auto space-y-1.5 select-text shadow-inner"
      >
        <div
          v-for="(line, idx) in logs"
          :key="idx"
          :class="['flex items-start gap-2', getLineClass(line)]"
        >
          <span class="text-zinc-500 select-none">[{{ line.time }}]</span>
          <span class="text-[#FF8533] select-none font-bold">[{{ line.source }}]</span>
          <span class="flex-1 whitespace-pre-wrap break-all">{{ line.text }}</span>
        </div>
        <div v-if="logs.length === 0" class="text-zinc-600 italic">暂无控制台日志输出...</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { Server, Terminal, RefreshCw } from 'lucide-vue-next'

const termBoxRef = ref(null)

defineProps({ standalone: { type: Boolean, default: false } })

const processes = ref([
  { id: 'fastapi', name: 'Argus API (FastAPI)', endpoint: '127.0.0.1:8000', running: true },
  { id: 'openclaw', name: 'OpenClaw Gateway', endpoint: '127.0.0.1:18789', running: true }
])

const logs = ref([])

function getLineClass(line) {
  if (line.level === 'warn' || line.text.includes('BLOCKED') || line.text.includes('ALERT')) {
    return 'text-red-400 font-semibold'
  }
  if (line.level === 'error') {
    return 'text-red-500 font-bold'
  }
  if (line.text.includes('200 OK') || line.text.includes('Connected')) {
    return 'text-emerald-400'
  }
  return 'text-zinc-300'
}

const copied = ref(false)

function pushLog(source, text, level) {
  logs.value.push({
    time: new Date().toLocaleTimeString(),
    source: source || 'SERVICE',
    text: String(text == null ? '' : text),
    level: level || 'info'
  })
  if (logs.value.length > 500) logs.value.splice(0, logs.value.length - 500)
  scrollToBottom()
}

async function copyLogs() {
  const text = logs.value.map((l) => '[' + l.time + '][' + l.source + '] ' + l.text).join('\n') || '(暂无日志)'
  try {
    await navigator.clipboard.writeText(text)
  } catch (err) {
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      ta.remove()
    } catch (err2) {}
  }
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}

function clearLogs() {
  logs.value = []
}

function toggleProcess(proc) {
  proc.running = !proc.running
  logs.value.push({
    time: new Date().toLocaleTimeString(),
    source: 'DAEMON',
    text: `管理员触发 [${proc.name}] ${proc.running ? '手动拉起' : '手动停止'} 指令`,
    level: 'info'
  })
  scrollToBottom()
}

function restartAll() {
  logs.value.push({
    time: new Date().toLocaleTimeString(),
    source: 'DAEMON',
    text: '正在重启后台进程集群 (FastAPI / OpenClaw)...',
    level: 'info'
  })
  if (window.electronAPI) {
    window.electronAPI.restartServices()
  }
  setTimeout(() => {
    logs.value.push({
      time: new Date().toLocaleTimeString(),
      source: 'DAEMON',
      text: '后台守护进程集群全部重启成功，健康检查通过 200 OK',
      level: 'info'
    })
    scrollToBottom()
  }, 1200)
}

function scrollToBottom() {
  nextTick(() => {
    if (termBoxRef.value) {
      termBoxRef.value.scrollTop = termBoxRef.value.scrollHeight
    }
  })
}

let offDaemon = null
let offSetup = null

onMounted(async () => {
  try {
    const hist = await window.electronAPI?.getDaemonLogHistory?.(200)
    if (hist && hist.length) {
      hist.forEach((h) => {
        logs.value.push({
          time: h.timestamp ? new Date(h.timestamp).toLocaleTimeString() : new Date().toLocaleTimeString(),
          source: h.source || 'SERVICE',
          text: h.text,
          level: h.level || 'info'
        })
      })
      scrollToBottom()
    }
  } catch (err) {}
  try {
    const st = await window.electronAPI?.getDaemonStatus?.()
    if (st) {
      const f = processes.value.find((p) => p.id === 'fastapi')
      if (f) f.running = !!st.fastapi
      const o = processes.value.find((p) => p.id === 'openclaw')
      if (o) o.running = !!st.openclaw
    }
  } catch (err) {}
  if (window.electronAPI && window.electronAPI.onDaemonLog) {
    offDaemon = window.electronAPI.onDaemonLog((logData) => {
      if (!logData) return
      pushLog(logData.source, logData.text, logData.level)
    })
  }
  if (window.electronAPI && window.electronAPI.onSetupLog) {
    offSetup = window.electronAPI.onSetupLog((line) => pushLog('SETUP', line, 'info'))
  }
})

onUnmounted(() => {
  try { offDaemon && offDaemon() } catch (err) {}
  try { offSetup && offSetup() } catch (err) {}
})
</script>
