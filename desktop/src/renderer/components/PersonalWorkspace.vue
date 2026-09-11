<template>
  <div class="personal-workspace">
    <aside class="personal-sidebar">
      <div class="sidebar-brand">
        <div class="brand-mark"><ShieldCheck :size="18" :stroke-width="1.8" /></div>
        <div class="brand-copy">
          <strong>Argus</strong>
          <span>个人版工作台</span>
        </div>
      </div>

      <div class="session-heading">
        <span>最近对话</span>
      </div>

      <div class="session-list" aria-label="会话列表">
        <!-- Step 5：老链路会话列表（:3000）已下线，聊天记录由原生 OpenClaw 自己存。 -->
        <div class="session-empty">
          <MessageSquare :size="18" />
          <span>聊天已搬到原生 OpenClaw</span>
          <small>本工作台只保留审计页，会话请在原生通道查看</small>
        </div>
      </div>

      <div class="sidebar-footer">
        <div class="local-status"><span class="status-dot" :class="connectionClass" />{{ connectionLabel }}</div>
        <button type="button" class="back-home-button" @click="emit('back-home')">
          <ArrowLeft :size="15" />
          <span>返回官网</span>
        </button>
      </div>
    </aside>

    <main class="chat-shell">
      <header class="chat-header">
        <div class="chat-heading">
          <div>
            <div class="eyebrow">CLA守护 · PERSONAL</div>
            <h1>实时安全审计</h1>
          </div>
        </div>
        <div class="header-actions">
          <span class="connection-badge" :class="connectionClass"><span class="status-dot" />{{ connectionLabel }}</span>
          <button class="icon-button" type="button" title="返回官网" @click="emit('back-home')"><ArrowLeft :size="17" /></button>
        </div>
      </header>

      <div class="workspace-tabs" role="tablist" aria-label="工作台模块">
        <button class="workspace-tab active" type="button" role="tab" aria-selected="true"><MessageSquare :size="15" />聊天</button>
        <button class="workspace-tab disabled" type="button" role="tab" aria-selected="false" title="技能管理将在后续版本开放"><Sparkles :size="15" />我的技能<span>即将支持</span></button>
      </div>

      <section class="audit-panel" aria-label="实时审计层">
        <header class="audit-panel-header">
          <div>
            <div class="audit-kicker"><Activity :size="13" />AUDIT LAYER</div>
            <h2>实时安全活动</h2>
          </div>
          <div class="audit-panel-actions">
            <span class="audit-sync-label"><span class="status-dot" :class="auditConnectionClass" />{{ auditConnectionLabel }}</span>
            <button class="refresh-button" type="button" title="同步审计数据" :disabled="auditLoading" @click="loadAuditData()">
              <RefreshCw :size="14" :class="{ spinning: auditLoading }" />
            </button>
          </div>
        </header>

        <div v-if="auditLoading && !auditOverview" class="audit-loading"><LoaderCircle :size="15" class="spinning" />正在连接审计层...</div>
        <div v-else-if="auditError && !auditOverview" class="audit-error"><AlertCircle :size="15" /><span>{{ auditError }}</span><button type="button" @click="loadAuditData()">重试</button></div>
        <template v-else-if="auditOverview">
          <div class="audit-metrics">
            <div class="audit-metric"><span>审计事件</span><strong>{{ auditOverview.event_count }}</strong><small>累计捕获</small></div>
            <div class="audit-metric"><span>任务链路</span><strong>{{ auditOverview.trace_count }}</strong><small>{{ auditOverview.risk_trace_count }} 条含风险</small></div>
            <div class="audit-metric risk"><span>已拦截</span><strong>{{ auditOverview.blocked_event_count }}</strong><small>{{ auditOverview.direct_risk_source_count }} 个风险源</small></div>
            <div class="audit-metric"><span>链路完整度</span><strong>{{ formatPercent(auditOverview.chain_integrity_rate) }}</strong><small>基于审计图谱</small></div>
          </div>
          <div class="audit-traces-heading"><span>最近审计链路</span><small v-if="auditLastSynced">同步于 {{ formatAuditTime(auditOverview.generated_at || auditLastSynced) }}</small></div>
          <div v-if="auditTraces.length" class="audit-trace-list">
            <button v-for="trace in auditTraces" :key="trace.trace_id" type="button" class="audit-trace-item" @click="openAuditTrace(trace.trace_id)">
              <div class="trace-main">
                <span class="trace-severity" :class="trace.blocked_event_count ? 'blocked' : 'safe'">{{ trace.blocked_event_count ? '已拦截' : '已记录' }}</span>
                <div class="trace-copy">
                  <strong>{{ trace.display_name || trace.user_input || '未命名审计链路' }}</strong>
                  <small>{{ formatAuditTime(trace.ended_at || trace.started_at) }} · {{ trace.event_count }} 个事件 · {{ trace.source_modules.join(' · ') || '审计层' }}</small>
                </div>
              </div>
              <div class="trace-risk"><span>风险值</span><strong>{{ formatRisk(trace.max_risk_score) }}</strong></div>
            </button>
          </div>
          <div v-else class="audit-empty"><ShieldCheck :size="16" />暂无审计链路，发送一条消息后这里会自动同步。</div>
        </template>
      </section>

      <div v-if="auditDetail" class="audit-detail-backdrop" @click.self="closeAuditDetail">
    <aside class="audit-detail-drawer" role="dialog" aria-modal="true" aria-label="审计链路详情">
      <header class="audit-detail-header">
        <div>
          <div class="audit-kicker"><Activity :size="13" />TRACE DETAIL</div>
          <h2>{{ auditDetail.display_name || auditDetail.user_input || '审计链路详情' }}</h2>
        </div>
        <button class="icon-button" type="button" aria-label="关闭审计详情" @click="closeAuditDetail"><X :size="18" /></button>
      </header>

      <div v-if="auditDetailLoading" class="audit-loading"><LoaderCircle :size="15" class="spinning" />正在加载链路证据...</div>
      <div v-else-if="auditDetailError" class="audit-error"><AlertCircle :size="15" /><span>{{ auditDetailError }}</span><button type="button" @click="openAuditTrace(auditDetailTraceId)">重试</button></div>
      <template v-else>
        <div class="audit-detail-meta">
          <span><strong>{{ auditDetail.event_count ?? auditDetail.nodes?.length ?? 0 }}</strong> 个事件</span>
          <span><strong>{{ auditDetail.risk_event_count ?? auditDetail.direct_risk_source_ids?.length ?? 0 }}</strong> 个风险事件</span>
          <span>{{ formatAuditTime(auditDetail.started_at) }} — {{ formatAuditTime(auditDetail.ended_at) }}</span>
        </div>
        <div class="audit-event-list">
          <div v-for="(event, index) in auditDetail.nodes || []" :key="event.node_id || event.event_id || index" class="audit-event-item">
            <div class="audit-event-index">{{ String(index + 1).padStart(2, '0') }}</div>
            <div class="audit-event-copy">
              <div class="audit-event-topline">
                <strong>{{ event.stage || 'unknown' }}</strong>
                <span :class="event.action === 'block' ? 'event-blocked' : 'event-allowed'">{{ event.action || 'recorded' }}</span>
              </div>
              <p>{{ event.reason || '审计层已记录该事件' }}</p>
              <small>{{ event.source_module || 'unknown module' }} · 风险 {{ formatRisk(event.risk_score) }} · {{ formatAuditTime(event.timestamp) }}</small>
            </div>
          </div>
          <div v-if="!(auditDetail.nodes || []).length" class="audit-empty"><ShieldCheck :size="16" />该链路暂未返回事件证据。</div>
        </div>
      </template>
    </aside>
  </div>

  <section ref="messageList" class="message-list" aria-live="polite" aria-label="对话消息">
        <!-- Step 5：老链路消息区（:3000 WS）已下线，聊天走原生 OpenClaw，本页只保留审计。 -->
        <div class="welcome-state">
          <div class="welcome-icon"><ShieldCheck :size="24" /></div>
          <h2>聊天已搬到原生 OpenClaw</h2>
          <p>个人版工作台不再内置聊天，防护由 :18789 的 argus-adapter 插件执行。本页只保留实时审计，拦截与放行记录会自动同步到上方。</p>
        </div>
      </section>

      <footer class="composer-wrap">
        <div v-if="backendError" class="composer-error"><AlertCircle :size="14" />{{ backendError }}</div>
        <!-- Step 5：聊天已搬到原生 OpenClaw（:18789 + argus-adapter 插件），本工作台不再直连 :3000。
             保留输入框作本地备注占位，发送走原生通道；审计页（:8000）不受影响。 -->
        <form class="composer" @submit.prevent="sendNativeHint">
          <textarea
            ref="inputElement"
            v-model="input"
            rows="1"
            placeholder="聊天已搬到原生 OpenClaw：在此输入可复制后发送"
            @keydown.enter.exact.prevent="sendNativeHint"
            @keydown.esc="input = ''"
          ></textarea>
          <button class="send-button" type="submit" :disabled="!input.trim()">
            <Send :size="16" />
          </button>
        </form>
        <div class="composer-hint"><span>个人版聊天请用原生 OpenClaw（:18789），防护由 argus-adapter 插件执行</span><span>审计数据来自 :8000</span></div>
      </footer>
    </main>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  Activity,
  AlertCircle,
  ArrowLeft,
  ArrowUpRight,
  ChevronRight,
  LoaderCircle,
  Menu,
  MessageSquare,
  Plus,
  PlugZap,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  UserRound,
  X,
} from 'lucide-vue-next'

const emit = defineEmits(['back-home'])

// Step 5：老链路（:3000 OpenGuard）已下线。聊天走原生 OpenClaw（:18789），
// 本页只保留审计（:8000）。下面 API_BASE/sessions/socket 等老链路代码整体停用，
// 保留 audit 相关与通用工具函数；回滚时把 ARGUS_LEGACY_CHAIN=1 打开并恢复本文件备份即可。
const AUDIT_API_BASE = String((import.meta.env.VITE_ARGUS_AUDIT_BASE) || 'http://127.0.0.1:8000').replace(/\/$/, '')
const input = ref('')
const inputElement = ref(null)
const backendError = ref('')
const auditOverview = ref(null)
const auditTraces = ref([])
const auditLoading = ref(false)
const auditError = ref('')
const auditLastSynced = ref(null)
const auditDetail = ref(null)
const auditDetailLoading = ref(false)
const auditDetailError = ref('')
const auditDetailTraceId = ref('')
let auditRequestInFlight = false
const messageList = ref(null)
let auditTimer = null

// 老链路状态（已停用，保留变量名防模板报错，回滚时恢复逻辑）
const connected = ref(false)
const connectionLabel = computed(() => '原生 OpenClaw 通道')
const connectionClass = computed(() => 'online')
const auditConnectionLabel = computed(() => {
  if (auditLoading.value && !auditOverview.value) return '连接中'
  if (auditError.value) return auditOverview.value ? '同步异常' : '连接异常'
  if (auditLoading.value) return '同步中'
  return auditOverview.value ? '已同步' : '等待连接'
})
const auditConnectionClass = computed(() => {
  if (auditLoading.value && !auditOverview.value) return 'pending'
  if (auditError.value) return 'offline'
  return auditOverview.value ? 'online' : 'idle'
})

// Step 5：老链路登录（:3000 /auth/desktop）已停用，个人版用默认身份 desktop-local，
// 企业版走 LLMGate 登录（见迁移计划 §2.2）。函数壳保留防模板引用报错。
async function ensurePersonalSession() {
  return true
}

function authHeaders() {
  const headers = {}
  const token = window.localStorage.getItem('argus_token') || getCookie('token')
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}

function getCookie(name) {
  const item = document.cookie.split('; ').find((entry) => entry.startsWith(`${name}=`))
  return item ? decodeURIComponent(item.slice(name.length + 1)) : ''
}

function auditApiUrl(path) {
  return `${AUDIT_API_BASE}${path}`
}

// 老链路 apiFetch/apiUrl（:3000）已停用，保留空壳防引用报错
async function apiFetch() {
  throw new Error('老链路已下线：聊天请用原生 OpenClaw（:18789）')
}

async function auditFetch(path, options = {}) {
  const headers = { Accept: 'application/json', ...authHeaders(), ...(options.headers || {}) }
  return fetch(auditApiUrl(path), { ...options, headers, credentials: 'include' })
}

function normalizeAuditOverview(data) {
  return {
    event_count: Number(data?.event_count || 0),
    trace_count: Number(data?.trace_count || 0),
    risk_trace_count: Number(data?.risk_trace_count || 0),
    direct_risk_source_count: Number(data?.direct_risk_source_count || 0),
    blocked_event_count: Number(data?.blocked_event_count || 0),
    chain_integrity_rate: Number(data?.chain_integrity_rate || 0),
    generated_at: data?.generated_at || null,
  }
}

function normalizeAuditTraces(data) {
  const source = Array.isArray(data) ? data : (Array.isArray(data?.items) ? data.items : [])
  return source.filter(Boolean).map((item) => ({
    trace_id: String(item.trace_id || item.id || ''),
    display_name: String(item.display_name || ''),
    user_input: String(item.user_input || ''),
    event_count: Number(item.event_count || 0),
    started_at: item.started_at || item.created_at || null,
    ended_at: item.ended_at || item.updated_at || null,
    blocked_event_count: Number(item.blocked_event_count || 0),
    max_risk_score: Number(item.max_risk_score || 0),
    source_modules: Array.isArray(item.source_modules) ? item.source_modules.map(String) : [],
  })).filter((item) => item.trace_id)
}

function normalizeAuditDetail(data) {
  const source = data || {}
  return {
    ...source,
    display_name: String(source.display_name || ''),
    user_input: String(source.user_input || ''),
    event_count: Number(source.event_count ?? source.nodes?.length ?? 0),
    risk_event_count: Number(source.risk_event_count ?? source.direct_risk_source_ids?.length ?? 0),
    nodes: Array.isArray(source.nodes) ? source.nodes.map((node) => {
      const event = node.raw_event || node
      return {
        ...node,
        event_id: String(node.event_id || event.event_id || node.node_id || ''),
        stage: String(node.stage || event.stage || ''),
        action: String(node.action || event.action || ''),
        reason: String(node.reason || event.reason || ''),
        source_module: String(node.source_module || event.source_module || ''),
        risk_score: Number(node.risk_score ?? event.risk_score ?? 0),
        timestamp: node.timestamp || event.timestamp || null,
      }
    }) : [],
  }
}

async function openAuditTrace(traceId) {
  if (!traceId) return
  auditDetailTraceId.value = traceId
  auditDetail.value = { display_name: '审计链路详情', nodes: [] }
  auditDetailLoading.value = true
  auditDetailError.value = ''
  try {
    const response = await auditFetch(`/v1/audit/traces/${encodeURIComponent(traceId)}`)
    if (!response.ok) throw new Error(`审计链路服务返回 ${response.status}`)
    auditDetail.value = normalizeAuditDetail(await response.json())
  } catch (error) {
    auditDetailError.value = error?.message || '审计证据暂不可用'
  } finally {
    auditDetailLoading.value = false
  }
}

function closeAuditDetail() {
  auditDetail.value = null
  auditDetailError.value = ''
  auditDetailTraceId.value = ''
}

async function loadAuditData({ silent = false } = {}) {
  if (auditRequestInFlight) return
  auditRequestInFlight = true
  if (!silent || !auditOverview.value) auditLoading.value = true
  try {
    const [overviewResponse, tracesResponse] = await Promise.all([
      auditFetch('/v1/audit/overview'),
      auditFetch('/v1/audit/traces?limit=4&offset=0'),
    ])
    if (!overviewResponse.ok) throw new Error(`审计概览服务返回 ${overviewResponse.status}`)
    if (!tracesResponse.ok) throw new Error(`审计链路服务返回 ${tracesResponse.status}`)
    auditOverview.value = normalizeAuditOverview(await overviewResponse.json())
    auditTraces.value = normalizeAuditTraces(await tracesResponse.json())
    auditLastSynced.value = new Date().toISOString()
    auditError.value = ''
  } catch (error) {
    auditError.value = error?.message || '审计层暂不可用'
    if (!auditOverview.value) auditTraces.value = []
  } finally {
    auditLoading.value = false
    auditRequestInFlight = false
  }
}

function formatPercent(value) {
  const numeric = Number(value || 0)
  return `${Math.round(numeric * 100)}%`
}

function formatRisk(value) {
  return Number(value || 0).toFixed(2)
}

function formatAuditTime(value) {
  if (!value) return '时间未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间未知'
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

// ===== 以下为老链路（:3000 会话/WS）停用区：已移至 git 历史，回滚时用 git 恢复本文件即可 =====
// （注：块注释内含正则字面量会被 vue 编译器误解析，故整段删除不保留注释块）
// ===== 老链路停用区结束 =====

// Step 5：输入框改为原生通道提示占位（复制即用，不再经 :3000 发送）
function sendNativeHint() {
  const content = input.value.trim()
  if (!content) return
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(content)
  } catch {}
  input.value = ''
  backendError.value = '已复制，请到原生 OpenClaw（:18789）粘贴发送，防护自动执行'
}

function scrollToBottom() {
  return nextTick(() => {
    if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
  })
}

function handleGlobalShortcut() {}

onMounted(async () => {
  // Step 5：不再建 :3000 会话/聊天通道，只同步审计（:8000）。
  await loadAuditData()
  auditTimer = window.setInterval(() => loadAuditData({ silent: true }), 5000)
})

onBeforeUnmount(() => {
  if (auditTimer) window.clearInterval(auditTimer)
})
</script>

<style scoped>
.personal-workspace {
  --ink: #18181b;
  --muted: #71717a;
  --faint: #a1a1aa;
  --line: #e7e5e4;
  --surface: #ffffff;
  --canvas: #fafaf9;
  --orange: #f56b1f;
  --orange-soft: #fff3eb;
  display: flex;
  min-height: 100%;
  color: var(--ink);
  background: var(--canvas);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}
.personal-sidebar { width: 276px; display: flex; flex: 0 0 276px; flex-direction: column; border-right: 1px solid var(--line); background: rgba(255,255,255,.82); }
.sidebar-brand { display:flex; align-items:center; gap:11px; height:74px; padding:0 20px; border-bottom:1px solid #f0efed; }
.brand-mark, .welcome-icon { display:flex; align-items:center; justify-content:center; color:var(--orange); background:var(--orange-soft); border:1px solid #ffd9c3; border-radius:12px; }
.brand-mark { width:34px; height:34px; }
.brand-copy { display:flex; flex-direction:column; gap:3px; min-width:0; }
.brand-copy strong { font-size:14px; letter-spacing:-.01em; }
.brand-copy span, .eyebrow { color:var(--faint); font: 10px/1.2 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing:.12em; text-transform:uppercase; }
.new-session-button { display:flex; align-items:center; gap:9px; margin:18px 16px 22px; padding:11px 13px; border:1px solid #f1b18c; border-radius:11px; color:#b94a15; background:#fffaf7; font-size:13px; font-weight:600; cursor:pointer; transition:.2s; }
.new-session-button:hover { border-color:var(--orange); background:var(--orange-soft); transform:translateY(-1px); }
.new-session-button kbd { margin-left:auto; color:#b9a69d; font:10px ui-monospace, monospace; }
.session-heading { display:flex; align-items:center; justify-content:space-between; padding:0 18px 9px; color:#a1a1aa; font-size:11px; font-weight:600; letter-spacing:.07em; text-transform:uppercase; }
.refresh-button, .icon-button { display:inline-flex; align-items:center; justify-content:center; border:0; color:#8a8a91; background:transparent; cursor:pointer; transition:.2s; }
.refresh-button { padding:4px; border-radius:6px; }
.refresh-button:hover, .icon-button:hover { color:var(--ink); background:#f1f0ee; }
.session-list { flex:1; min-height:0; overflow:auto; padding:0 10px; }
.session-item { display:flex; width:100%; align-items:center; gap:9px; padding:11px 9px; border:1px solid transparent; border-radius:10px; color:#71717a; background:transparent; text-align:left; cursor:pointer; transition:.18s; }
.session-item:hover { color:var(--ink); background:#f7f6f4; }
.session-item.active { color:#bc4b18; border-color:#ffe0d0; background:var(--orange-soft); }
.session-info { display:flex; flex:1; min-width:0; flex-direction:column; gap:4px; }
.session-info strong { overflow:hidden; color:inherit; font-size:12px; font-weight:600; text-overflow:ellipsis; white-space:nowrap; }
.session-info small { color:#a1a1aa; font-size:10px; }
.session-arrow { margin-left:auto; opacity:0; }
.session-item:hover .session-arrow, .session-item.active .session-arrow { opacity:1; }
.session-empty { display:flex; align-items:center; justify-content:center; flex-direction:column; gap:7px; padding:35px 16px; color:#b3b0ad; font-size:12px; text-align:center; }
.session-empty small { color:#c3c0bd; font-size:11px; }
.sidebar-footer { display:flex; flex-direction:column; gap:11px; padding:16px; border-top:1px solid #f0efed; }
.local-status { display:flex; align-items:center; gap:8px; color:#8e8b88; font-size:11px; }
.status-dot { width:7px; height:7px; flex:0 0 7px; border-radius:50%; background:#b5b3b0; }
.status-dot.online { background:#17a673; box-shadow:0 0 0 3px #e0f5ec; }.status-dot.pending { background:#e6a536; animation:pulse 1.2s infinite; }.status-dot.offline { background:#d95e55; }.status-dot.idle { background:#aaa7a4; }
.back-home-button { display:flex; align-items:center; gap:8px; padding:6px 0; border:0; color:#8e8b88; background:transparent; font-size:12px; cursor:pointer; }.back-home-button:hover { color:var(--ink); }
.chat-shell { display:flex; min-width:0; flex:1; flex-direction:column; min-height:100%; }
.chat-header { display:flex; align-items:center; justify-content:space-between; min-height:74px; padding:0 34px; border-bottom:1px solid var(--line); background:rgba(250,250,249,.84); backdrop-filter:blur(14px); }
.chat-heading { display:flex; align-items:center; gap:13px; }.chat-heading h1 { margin:6px 0 0; font-size:15px; font-weight:650; letter-spacing:-.02em; }.header-actions { display:flex; align-items:center; gap:16px; }.connection-badge { display:inline-flex; align-items:center; gap:7px; color:#8d8985; font-size:11px; }.connection-badge.online { color:#15885e; }.connection-badge.pending { color:#b3741f; }.connection-badge.offline { color:#c2524a; }
.mobile-menu, .mobile-close { display:none; }.workspace-tabs { display:flex; gap:4px; padding:16px 34px 0; border-bottom:1px solid #eeecea; background:rgba(250,250,249,.84); }.workspace-tab { display:flex; align-items:center; gap:7px; padding:9px 13px 11px; border:0; border-bottom:2px solid transparent; color:#9a9692; background:transparent; font-size:12px; cursor:pointer; }.workspace-tab.active { border-color:var(--orange); color:#c2551d; font-weight:650; }.workspace-tab.disabled { cursor:not-allowed; opacity:.58; }.workspace-tab span { padding:2px 5px; border-radius:4px; color:#aaa5a0; background:#f0eeeb; font-size:9px; }
.audit-panel { width:min(900px, calc(100% - 48px)); margin:18px auto 0; padding:17px 18px 16px; border:1px solid #e8e3df; border-radius:16px; background:rgba(255,255,255,.9); box-shadow:0 10px 28px rgba(55,42,30,.035); }
.audit-panel-header { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }
.audit-kicker { display:flex; align-items:center; gap:6px; color:#b45a26; font:10px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing:.14em; }
.audit-panel h2 { margin:6px 0 0; color:#272124; font-size:16px; letter-spacing:-.025em; }
.audit-panel-actions { display:flex; align-items:center; gap:9px; }
.audit-sync-label { display:flex; align-items:center; gap:6px; color:#8d8884; font-size:10px; white-space:nowrap; }
.audit-metrics { display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:9px; margin-top:16px; }
.audit-metric { display:flex; min-height:72px; flex-direction:column; justify-content:center; gap:3px; padding:10px 11px; border:1px solid #eeeae7; border-radius:11px; background:#fcfbfa; }
.audit-metric span { color:#96908b; font-size:10px; }.audit-metric strong { color:#302a27; font-size:21px; letter-spacing:-.045em; }.audit-metric small { color:#b1aba6; font-size:9px; }.audit-metric.risk { border-color:#f4d2c0; background:#fff8f4; }.audit-metric.risk strong { color:#c35420; }
.audit-traces-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; margin:18px 0 8px; color:#77716d; font-size:11px; font-weight:650; }.audit-traces-heading small { color:#b2aca7; font-size:9px; font-weight:400; }
.audit-trace-list { display:flex; flex-direction:column; gap:7px; }.audit-trace-item { display:flex; width:100%; align-items:center; justify-content:space-between; gap:12px; padding:10px 11px; border:1px solid #eeeae7; border-radius:10px; color:inherit; background:#fff; text-align:left; cursor:pointer; transition:.18s; }.audit-trace-item:hover { border-color:#f3b38f; background:#fffaf7; transform:translateY(-1px); }.trace-main { display:flex; min-width:0; align-items:center; gap:9px; }.trace-severity { flex:0 0 auto; padding:4px 6px; border-radius:5px; font-size:9px; font-weight:650; }.trace-severity.blocked { color:#bd4c25; background:#fff0e8; }.trace-severity.safe { color:#19855e; background:#eaf8f1; }.trace-copy { display:flex; min-width:0; flex-direction:column; gap:3px; }.trace-copy strong { overflow:hidden; color:#514944; font-size:11px; font-weight:600; text-overflow:ellipsis; white-space:nowrap; }.trace-copy small { overflow:hidden; color:#aaa39d; font-size:9px; text-overflow:ellipsis; white-space:nowrap; }.trace-risk { display:flex; flex:0 0 auto; align-items:flex-end; flex-direction:column; gap:2px; }.trace-risk span { color:#b0aaa5; font-size:9px; }.trace-risk strong { color:#c35420; font:600 11px ui-monospace, SFMono-Regular, Menlo, monospace; }.audit-detail-backdrop { position:fixed; z-index:40; inset:0; display:flex; justify-content:flex-end; background:rgba(31,24,20,.18); backdrop-filter:blur(3px); }.audit-detail-drawer { width:min(520px, 100vw); height:100%; overflow:auto; padding:25px 24px; border-left:1px solid #e8e0da; background:#fffdfb; box-shadow:-18px 0 38px rgba(45,30,18,.13); }.audit-detail-header { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; padding-bottom:18px; border-bottom:1px solid #eee8e3; }.audit-detail-header h2 { max-width:420px; margin:7px 0 0; color:#272124; font-size:17px; line-height:1.45; }.audit-detail-meta { display:flex; flex-wrap:wrap; gap:8px 14px; padding:14px 0; color:#9b938c; font-size:10px; }.audit-detail-meta strong { color:#c35420; font-size:16px; }.audit-event-list { display:flex; flex-direction:column; gap:8px; }.audit-event-item { display:flex; gap:12px; padding:12px; border:1px solid #eee8e3; border-radius:11px; background:#fff; }.audit-event-index { color:#c35420; font:600 11px ui-monospace, SFMono-Regular, Menlo, monospace; }.audit-event-copy { min-width:0; flex:1; }.audit-event-topline { display:flex; align-items:center; justify-content:space-between; gap:10px; color:#413a35; font-size:12px; text-transform:uppercase; }.audit-event-topline span { padding:3px 6px; border-radius:5px; font-size:9px; font-weight:650; text-transform:none; }.event-blocked { color:#bd4c25; background:#fff0e8; }.event-allowed { color:#19855e; background:#eaf8f1; }.audit-event-copy p { margin:6px 0; color:#69615b; font-size:11px; line-height:1.55; }.audit-event-copy small { color:#aaa39d; font-size:9px; }.audit-loading, .audit-error, .audit-empty { display:flex; align-items:center; justify-content:center; gap:7px; min-height:76px; margin-top:13px; color:#a59e99; font-size:11px; text-align:center; }.audit-error { color:#b85243; }.audit-error button { padding:4px 8px; border:1px solid #efc7b8; border-radius:6px; color:#a84827; background:#fff8f4; font-size:10px; cursor:pointer; }.audit-empty { min-height:54px; margin-top:0; }

.message-list { width:min(900px, calc(100% - 48px)); flex:1; min-height:0; overflow-y:auto; margin:0 auto; padding:42px 0 30px; scroll-behavior:smooth; }.welcome-state { display:flex; align-items:center; flex-direction:column; max-width:620px; margin:11vh auto 0; text-align:center; }.welcome-icon { width:52px; height:52px; margin-bottom:17px; border-radius:16px; }.welcome-state h2 { margin:0; font-size:25px; letter-spacing:-.04em; }.welcome-state p { max-width:530px; margin:10px 0 23px; color:#898682; font-size:13px; line-height:1.8; }.suggestion-row { display:flex; justify-content:center; flex-wrap:wrap; gap:8px; }.suggestion-row button { display:inline-flex; align-items:center; gap:5px; padding:9px 11px; border:1px solid #e4e0dc; border-radius:9px; color:#77726d; background:#fff; font-size:11px; cursor:pointer; }.suggestion-row button:hover { border-color:#f3b38f; color:#ba4d18; background:#fffaf7; }
.message-row { display:flex; align-items:flex-start; gap:12px; margin:0 auto 27px; max-width:780px; }.message-row.user { flex-direction:row-reverse; }.message-avatar { display:flex; width:28px; height:28px; flex:0 0 28px; align-items:center; justify-content:center; margin-top:2px; border-radius:9px; color:#71717a; background:#ecebea; }.message-avatar.assistant { color:var(--orange); border:1px solid #ffd8c0; background:#fff3eb; }.message-body { max-width:calc(100% - 40px); }.message-row.user .message-body { text-align:right; }.message-meta { margin:0 2px 6px; color:#a3a09c; font:10px ui-monospace, SFMono-Regular, Menlo, monospace; }.message-content { display:inline-block; padding:12px 15px; border:1px solid #ebe8e5; border-radius:4px 14px 14px 14px; color:#3f3f46; background:#fff; font-size:13px; line-height:1.75; white-space:pre-wrap; word-break:break-word; box-shadow:0 3px 14px rgba(50,40,30,.025); }.message-row.user .message-content { border-color:#ffd5bc; border-radius:14px 4px 14px 14px; color:#7d3817; background:#fff3eb; }.message-content.streaming { min-width:50px; }.typing-cursor { display:inline-block; width:5px; height:15px; margin-left:4px; vertical-align:-2px; background:var(--orange); animation:blink .85s step-end infinite; }.message-notice { display:flex; align-items:center; justify-content:center; gap:7px; margin:18vh auto 0; color:#aaa5a0; font-size:12px; }.message-notice.error { color:#c2524a; }.thinking-row { display:flex; align-items:center; gap:12px; max-width:780px; margin:0 auto 22px; }.thinking-bubble { display:flex; align-items:center; gap:4px; padding:12px 14px; border:1px solid #ebe8e5; border-radius:4px 14px 14px 14px; background:#fff; }.thinking-bubble span { width:5px; height:5px; border-radius:50%; background:#d6d1cc; animation:dot 1.1s infinite; }.thinking-bubble span:nth-child(2) { animation-delay:.15s; }.thinking-bubble span:nth-child(3) { animation-delay:.3s; }.thinking-bubble em { margin-left:5px; color:#aaa5a0; font-size:11px; font-style:normal; }
.composer-wrap { width:min(900px, calc(100% - 48px)); margin:0 auto; padding:0 0 23px; }.composer-error { display:flex; align-items:center; gap:6px; padding:0 4px 8px; color:#c2524a; font-size:11px; }.composer { display:flex; align-items:flex-end; gap:8px; padding:10px; border:1px solid #dcd8d4; border-radius:15px; background:#fff; box-shadow:0 8px 25px rgba(40,30,20,.05); transition:.2s; }.composer:focus-within { border-color:#ef9c70; box-shadow:0 8px 28px rgba(240,110,50,.11); }.composer textarea { min-height:23px; max-height:130px; flex:1; resize:none; padding:3px 5px; border:0; outline:0; color:#3f3f46; background:transparent; font:13px/1.65 inherit; }.composer textarea::placeholder { color:#aaa6a2; }.connect-button, .send-button { display:inline-flex; height:35px; align-items:center; justify-content:center; gap:6px; border:0; border-radius:9px; cursor:pointer; }.connect-button { padding:0 11px; color:#77716d; background:#f4f2ef; font-size:11px; }.connect-button:hover:not(:disabled) { color:#a94818; background:#fff0e7; }.send-button { width:35px; color:#fff; background:var(--orange); }.send-button:hover:not(:disabled) { background:#df5b17; }.send-button:disabled, .connect-button:disabled { cursor:not-allowed; opacity:.5; }.composer-hint { display:flex; justify-content:space-between; gap:10px; padding:8px 3px 0; color:#b0aca7; font-size:10px; }
.spinning { animation:spin 1s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } } @keyframes pulse { 50% { opacity:.45; } } @keyframes blink { 50% { opacity:0; } } @keyframes dot { 0%, 60%, 100% { transform:translateY(0); opacity:.45; } 30% { transform:translateY(-3px); opacity:1; } }
@media (max-width: 800px) { .personal-sidebar { position:fixed; z-index:20; inset:0 auto 0 0; width:min(86vw, 300px); transform:translateX(-102%); box-shadow:14px 0 30px rgba(30,20,10,.1); transition:transform .25s; }.personal-sidebar.is-open { transform:translateX(0); }.mobile-menu, .mobile-close { display:inline-flex; }.mobile-close { margin-left:auto; }.chat-header { padding:0 18px; }.workspace-tabs { padding-left:18px; padding-right:18px; }.audit-panel, .message-list, .composer-wrap { width:calc(100% - 28px); }.audit-metrics { grid-template-columns:repeat(2, minmax(0, 1fr)); }.message-list { padding-top:25px; }.composer-hint span:last-child { display:none; }.header-actions .icon-button { display:none; } }
@media (max-width: 520px) { .chat-heading h1 { max-width:150px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.connection-badge { display:none; }.connect-button span { display:none; }.connect-button { width:35px; padding:0; }.welcome-state { margin-top:8vh; }.welcome-state h2 { font-size:21px; }.suggestion-row { flex-direction:column; width:100%; }.suggestion-row button { justify-content:center; }.message-row { gap:8px; }.message-content { font-size:12px; }.composer-hint { font-size:9px; }.audit-panel { padding:14px 12px; }.audit-panel-header { align-items:center; }.audit-sync-label { font-size:9px; }.audit-trace-item { align-items:flex-start; }.trace-copy strong { max-width:165px; }.trace-risk { display:none; } }
</style>






