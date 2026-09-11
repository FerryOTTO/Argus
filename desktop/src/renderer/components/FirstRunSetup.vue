<template>
  <div class="setup-wrap">
    <div class="setup-card">
      <div class="setup-eyebrow">首次启动 · 环境检查</div>
      <h1>正在准备你的个人版</h1>
      <p class="setup-sub">构建标识 0911c（双依赖安装+装后复验+网关自愈+全局命令兜底+独立调试控制台+npm离线模式修复）</p>
      <p class="setup-sub">第一次打开需要检查运行依赖，缺什么装什么。装完以后直接进个人版，以后打开不再显示这个页面。</p>

      <div class="setup-progress-block">
        <div class="setup-progress-text">{{ progressText }}</div>
        <div class="setup-progress-track">
          <div class="setup-progress-fill" :style="{ width: progressPercent + '%' }" />
        </div>
        <div class="setup-progress-count">{{ doneCount }} / {{ items.length }} 项就绪</div>
      </div>

      <ul class="setup-list">
        <li v-for="item in items" :key="item.id" class="setup-item" :class="item.status">
          <span class="setup-dot" />
          <div class="setup-item-main">
            <strong>{{ item.label }}</strong>
            <small>{{ item.detail }}</small>
          </div>
          <span class="setup-state">{{ stateText(item.status) }}</span>
          <button
            v-if="(item.status === 'missing' || item.status === 'failed') && item.id !== 'python' && item.id !== 'node'"
            class="setup-install-btn"
            type="button"
            :disabled="busy"
            @click="installOne(item.id)"
          >安装</button>
        </li>
      </ul>

      <div v-if="logLines.length" class="setup-log">
        <div v-for="(line, i) in logLines.slice(-80)" :key="i">{{ line }}</div>
      </div>

      <div class="setup-actions">
        <button class="setup-primary" type="button" :disabled="busy || allOk" @click="installAll">
          {{ busy ? '正在安装…' : '一键安装缺失项' }}
        </button>
        <button class="setup-primary go" type="button" :disabled="busy || !canEnter" @click="finish">
          进入个人版
        </button>
        <button class="setup-skip" type="button" :disabled="busy" @click="skip">
          跳过检查，直接进
        </button>
      </div>
      <p class="setup-hint">安装需要联网（用 pip / npm 拉依赖）。Python 和 Node 如果没装，需要你先装好，装好点下面“重新检查”。</p>
      <button class="setup-recheck" type="button" @click="openDebug">打开发布调试控制台（装不好点我，把日志发回来）</button>
      <button class="setup-recheck" type="button" :disabled="busy" @click="refresh">重新检查</button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'

const emit = defineEmits(['setup-done'])
const items = ref([
  { id: 'python', label: 'Python 环境', status: 'waiting', detail: '检查中…' },
  { id: 'node', label: 'Node.js 环境', status: 'waiting', detail: '检查中…' },
  { id: 'pyDeps', label: 'Python 依赖包', status: 'waiting', detail: '检查中…' },
  { id: 'bridgeDeps', label: '本地工作台依赖', status: 'waiting', detail: '检查中…' },
  { id: 'openclaw', label: 'OpenClaw', status: 'waiting', detail: '检查中…' },
])
const logLines = ref([])
const busy = ref(false)
const skipped = ref(false)

const doneCount = computed(() => items.value.filter((i) => i.status === 'ok').length)
const progressPercent = computed(() => Math.round((doneCount.value / items.value.length) * 100))
const allOk = computed(() => items.value.every((i) => i.status === 'ok'))
const canEnter = computed(() => allOk.value || skipped.value)

const progressText = computed(() => {
  const running = items.value.find((i) => i.status === 'installing' || i.status === 'checking')
  if (running) {
    const idx = items.value.indexOf(running) + 1
    const verb = running.status === 'installing' ? '正在安装' : '正在检查'
    return verb + '：' + running.label + '（第 ' + idx + ' / ' + items.value.length + ' 项）'
  }
  if (allOk.value) return '全部就绪，可以进入个人版了'
  const next = items.value.find((i) => i.status === 'missing' || i.status === 'failed')
  if (next) return '待处理：' + next.label + '（共 ' + (items.value.length - doneCount.value) + ' 项未就绪）'
  return '准备检查…'
})

function stateText(s) {
  return { waiting: '等待', checking: '检查中', ok: '正常', missing: '缺失', installing: '安装中', failed: '失败' }[s] || s
}

function pushLog(text) {
  String(text || '').split('\n').forEach((line) => {
    const t = line.trim()
    if (t) logLines.value.push(t)
  })
}

let offLog = null

function applyCheck(r) {
  const set = (id, ok, detailOk, detailMissing) => {
    const it = items.value.find((x) => x.id === id)
    it.status = ok ? 'ok' : 'missing'
    it.detail = ok ? detailOk : detailMissing
  }
  set('python', r.python.ok, '可用：' + r.python.version, '没找到 Python，请先安装 Python 再点重新检查')
  set('node', r.node.ok, '可用：' + r.node.version, '没找到 Node.js，请先安装再点重新检查')
  set('pyDeps', r.pyDeps.ok, '依赖齐全', '缺失：' + (r.pyDeps.missing || []).join('、'))
  set('bridgeDeps', r.bridgeDeps.ok, '依赖齐全', '本地工作台依赖没装，点安装即可')
  set('openclaw', r.openclaw.ok, '已找到：' + r.openclaw.path, '没找到 OpenClaw，点安装即可（需联网）')
}

function openDebug() { try { window.electronAPI?.openDebugConsole?.() } catch (err) {} }

  async function refresh() {
  busy.value = true
  items.value.forEach((i) => { i.status = 'checking'; i.detail = '检查中…' })
  try {
    const r = await window.electronAPI?.setupCheck?.()
    if (r) applyCheck(r)
  } catch (e) {
    pushLog('检查失败：' + e.message)
  } finally {
    busy.value = false
  }
}

async function installOne(id) {
  busy.value = true
  const it = items.value.find((x) => x.id === id)
  it.status = 'installing'
  it.detail = '正在安装…'
  try {
    const r = await window.electronAPI?.setupInstall?.(id)
    if (r && r.ok) {
      it.status = 'ok'
      it.detail = '安装成功'
    } else {
      it.status = 'failed'
      it.detail = '安装失败，看下面日志，点安装可重试'
    }
  } catch (e) {
    it.status = 'failed'
    it.detail = '安装出错：' + e.message
  } finally {
    busy.value = false
  }
}

async function installAll() {
  for (const it of items.value) {
    if ((it.status === 'missing' || it.status === 'failed') && it.id !== 'python' && it.id !== 'node') {
      // eslint-disable-next-line no-await-in-loop
      await installOne(it.id)
    }
  }
}

async function finish() {
  try { await window.electronAPI?.setupMarkDone?.() } catch {}
  try { localStorage.setItem('argus.setup-done', '1') } catch {}
  emit('setup-done')
}

async function skip() {
  skipped.value = true
  await finish()
}

onMounted(async () => {
  try {
    const done = await window.electronAPI?.setupIsDone?.()
    if (done) { emit('setup-done'); return }
  } catch {}
  try { if (localStorage.getItem('argus.setup-done') === '1') { emit('setup-done'); return } } catch {}
  offLog = window.electronAPI?.onSetupLog?.((line) => pushLog(line))
  await refresh()
})

onUnmounted(() => { try { offLog && offLog() } catch {} })
</script>

<style>
.setup-wrap { display: flex; align-items: center; justify-content: center; min-height: 100%; padding: 40px 20px; background: #fafaf8; }
.setup-card { width: 100%; max-width: 640px; background: #fff; border: 1px solid #e7e5e4; border-radius: 20px; padding: 32px; box-shadow: 0 12px 40px rgba(70, 55, 40, 0.08); }
.setup-eyebrow { font-family: monospace; font-size: 11px; color: #ff6900; letter-spacing: 2px; }
.setup-card h1 { margin: 8px 0 6px; font-size: 22px; }
.setup-sub { margin: 0 0 18px; font-size: 13px; color: #71717a; }
.setup-progress-block { margin-bottom: 16px; }
.setup-progress-text { font-size: 13px; font-weight: 600; margin-bottom: 8px; }
.setup-progress-track { height: 10px; border-radius: 999px; background: #f1efec; overflow: hidden; }
.setup-progress-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, #ff6900, #ff9a3d); transition: width 400ms ease; }
.setup-progress-count { margin-top: 6px; font-size: 12px; color: #a1a1aa; }
.setup-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.setup-item { display: flex; align-items: center; gap: 12px; padding: 12px 14px; border: 1px solid #e7e5e4; border-radius: 12px; }
.setup-item-main { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.setup-item-main strong { font-size: 14px; }
.setup-item-main small { font-size: 12px; color: #71717a; }
.setup-dot { width: 10px; height: 10px; border-radius: 50%; background: #d4d4d8; flex: none; }
.setup-item.checking .setup-dot, .setup-item.installing .setup-dot { background: #f59e0b; }
.setup-item.ok .setup-dot { background: #17a673; }
.setup-item.missing .setup-dot, .setup-item.failed .setup-dot { background: #d95e55; }
.setup-state { font-size: 12px; color: #71717a; }
.setup-install-btn { border: 1px solid #e4e4e7; background: #fff; border-radius: 8px; padding: 6px 12px; font-size: 12px; cursor: pointer; }
.setup-install-btn:hover { background: #f4f4f5; }
.setup-log { margin-top: 14px; max-height: 160px; overflow: auto; background: #0b0e14; color: #a7f3d0; font-family: monospace; font-size: 11px; border-radius: 10px; padding: 10px 12px; }
.setup-actions { display: flex; gap: 10px; margin-top: 16px; }
.setup-primary { flex: 1; border: 0; border-radius: 10px; padding: 11px; font-size: 14px; font-weight: 700; background: #18181b; color: #fff; cursor: pointer; }
.setup-primary.go { background: #ff6900; }
.setup-primary:disabled { opacity: 0.45; cursor: not-allowed; }
.setup-skip { border: 1px solid #e4e4e7; background: #fff; border-radius: 10px; padding: 11px 14px; font-size: 13px; cursor: pointer; }
.setup-hint { margin: 12px 0 0; font-size: 12px; color: #a1a1aa; }
.setup-recheck { margin-top: 8px; border: 0; background: none; color: #ff6900; font-size: 12px; cursor: pointer; }
</style>
