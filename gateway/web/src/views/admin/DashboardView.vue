<template>
  <div class="dashboard">
    <div class="page-head">
      <h2 class="page-title">仪表盘</h2>
      <div class="page-head-right">
        <span v-if="lastUpdated" class="last-updated">更新于 {{ lastUpdated }}</span>
        <el-button :loading="loading" @click="loadAll">
          <el-icon style="margin-right: 4px"><Refresh /></el-icon>刷新
        </el-button>
      </div>
    </div>

    <!-- 终端与安全态势 -->
    <el-row :gutter="20" v-loading="loading">
      <el-col v-for="c in terminalCards" :key="c.key" :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-icon" :style="{ background: c.bg }">
            <el-icon :size="30" :color="c.color"><component :is="c.icon" /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value" :style="{ color: c.color }">{{ c.value }}</div>
            <div class="stat-label">{{ c.label }}</div>
            <div v-if="c.sub" class="stat-sub">{{ c.sub }}</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 平台与网关流量 -->
    <el-row :gutter="20" class="row-gap" v-loading="loading">
      <el-col v-for="c in platformCards" :key="c.key" :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-icon" :style="{ background: c.bg }">
            <el-icon :size="30" :color="c.color"><component :is="c.icon" /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value" :style="{ color: c.color }">{{ c.value }}</div>
            <div class="stat-label">{{ c.label }}</div>
            <div v-if="c.sub" class="stat-sub">{{ c.sub }}</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" class="row-gap">
      <el-col :span="12">
        <el-card class="panel-card">
          <template #header>
            <div class="card-head">
              <span>最近安全事件</span>
              <el-link type="primary" :underline="false" @click="$router.push('/admin/audit')">查看全部 →</el-link>
            </div>
          </template>
          <el-table :data="recentEvents" v-loading="loading" size="small" stripe :empty-text="eventsEmptyText">
            <el-table-column label="时间" width="150">
              <template #default="{ row }">
                <span class="cell-time">{{ formatDate(row.event_time) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="终端" width="110" show-overflow-tooltip>
              <template #default="{ row }">{{ terminalLabel(row) }}</template>
            </el-table-column>
            <el-table-column label="阶段" width="86">
              <template #default="{ row }">
                <el-tag size="small" type="info" effect="plain">{{ stageLabel(row.stage) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="动作" width="92">
              <template #default="{ row }">
                <el-tag size="small" :type="actionTagType(row.action)">{{ actionLabel(row.action) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="风险" width="78">
              <template #default="{ row }">
                <el-tag size="small" :type="riskTagType(row.risk_score)">{{ riskPercent(row.risk_score) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="事件说明" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">{{ eventSummary(row) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card class="panel-card">
          <template #header>
            <div class="card-head">
              <span>终端安全概况</span>
              <el-link type="primary" :underline="false" @click="$router.push('/admin/terminals')">终端管理 →</el-link>
            </div>
          </template>
          <el-table :data="terminalRows" v-loading="loading" size="small" stripe :empty-text="terminalsEmptyText">
            <el-table-column label="终端" min-width="130" show-overflow-tooltip>
              <template #default="{ row }">
                <div class="cell-main">{{ row.terminal_name || '终端 #' + row.terminal_id }}</div>
                <div v-if="row.hostname" class="cell-sub">{{ row.hostname }}</div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="82">
              <template #default="{ row }">
                <el-tag :type="statusOf(row).type" size="small">{{ statusOf(row).text }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="今日事件" width="82" align="right">
              <template #default="{ row }">{{ row.today_events }}</template>
            </el-table-column>
            <el-table-column label="今日拦截" width="82" align="right">
              <template #default="{ row }">
                <span :class="{ 'num-alert': row.alerts_today > 0 }">{{ row.alerts_today }}</span>
              </template>
            </el-table-column>
            <el-table-column label="今日高危" width="82" align="right">
              <template #default="{ row }">
                <span :class="{ 'num-danger': row.high_risk_today > 0 }">{{ row.high_risk_today }}</span>
              </template>
            </el-table-column>
            <el-table-column label="最近审计" width="130">
              <template #default="{ row }">
                <span class="cell-time">{{ lastEventLabel(row) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { getDashboard, getAdminModels, getAgentAuditEvents, getAgentTerminalStats } from '@/api/admin'

const loading = ref(false)
const lastUpdated = ref('')
const models = ref(0)

const stats = reactive({
  totalRequests: 0,
  totalUsers: 0,
  totalApiKeys: 0,
  totalProviders: 0,
  requestsToday: 0,
  tokensToday: 0,
  tokensTotal: 0,
  terminalTotal: 0,
  terminalOnline: 0,
  terminalOffline: 0,
  terminalPending: 0,
  terminalTokenTotal: 0,
  terminalAlertTotal: 0,
  eventTotal: 0,
  eventToday: 0,
  alertsToday: 0,
  highRiskToday: 0,
})

const recentEvents = ref<any[]>([])
const terminalRows = ref<any[]>([])
const eventsEmptyText = '暂无安全事件，等待终端 Argus 上报'
const terminalsEmptyText = '暂无终端，请先添加终端接入'

// 数字格式化：万/亿 简洁展示（token 量级较大时避免挤爆卡片）
function compact(n: number | undefined): string {
  const v = n || 0
  if (v >= 1e8) return trim1(v / 1e8) + ' 亿'
  if (v >= 1e4) return trim1(v / 1e4) + ' 万'
  return String(v)
}
function trim1(x: number): string {
  return Number(x.toFixed(1)).toString()
}
function comma(n: number | undefined): string {
  return (n || 0).toLocaleString('zh-CN')
}

function formatDate(dateStr?: string) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}
function lastEventLabel(t: any) {
  return t.last_event_time ? formatDate(t.last_event_time) : '暂无上报'
}
function terminalLabel(row: any) {
  return row.terminal_name || '终端 #' + row.terminal_id
}
function statusOf(row: any) {
  if (row.status !== 'active') return { type: 'warning' as const, text: '未接入' }
  if (row.online) return { type: 'success' as const, text: '在线' }
  return { type: 'info' as const, text: '离线' }
}

// 阶段/动作/风险展示口径与「审计日志 · 终端审计」一致
const STAGE: Record<string, string> = {
  input: '输入检测',
  tool_pre: '工具前置',
  content: '内容复检',
  output: '输出检测',
  audit: '审计复核',
}
const ACTION_LABEL: Record<string, string> = { allow: '放行', block: '拦截', rewrite: '改写', human_review: '人工复核' }
function stageLabel(v: string) {
  return STAGE[v] || v || '-'
}
function actionLabel(v: string) {
  return ACTION_LABEL[v] || v || '-'
}
function actionTagType(v: string) {
  const map: Record<string, string> = { allow: 'success', block: 'danger', rewrite: 'warning', human_review: 'info' }
  return map[v] || ''
}
function riskTagType(r: number) {
  if (r >= 0.85) return 'danger'
  if (r >= 0.6) return 'warning'
  if (r >= 0.3) return 'primary'
  return 'info'
}
function riskPercent(r: number) {
  return `${Math.round((r || 0) * 100)}%`
}
function eventSummary(row: any) {
  const base = `${stageLabel(row.stage)} · ${actionLabel(row.action)}` + (row.source_module ? ` · ${row.source_module}` : '')
  return row.reason || base
}

// ---- 统计卡片（行 1：终端与安全；行 2：平台与网关） ----
function card(key: string, icon: string, bg: string, color: string, label: string, value: string, sub = '') {
  return { key, icon, bg, color, label, value, sub }
}

const terminalCards = computed(() => [
  card(
    'terminalTotal', 'Monitor', '#ecf5ff', '#409eff', '终端总数', comma(stats.terminalTotal),
    `在线 ${stats.terminalOnline} · 离线 ${stats.terminalOffline} · 待接入 ${stats.terminalPending}`
  ),
  card(
    'terminalToken', 'DataLine', '#f0f9eb', '#67c23a', 'Token 消耗', compact(stats.terminalTokenTotal),
    `全部终端累计用量（${comma(stats.terminalTokenTotal)}）`
  ),
  card(
    'terminalAlert', 'WarningFilled', '#fef0f0', '#f56c6c', '安全预警', compact(stats.terminalAlertTotal),
    `累计拦截/告警 ${comma(stats.terminalAlertTotal)} 次 · 今日 ${stats.alertsToday} 次`
  ),
  card(
    'eventTotal', 'Document', '#fdf6ec', '#e6a23c', '审计事件', compact(stats.eventTotal),
    `今日 ${stats.eventToday} 条 · 今日高危 ${stats.highRiskToday}`
  ),
])

const platformCards = computed(() => [
  card(
    'requestsToday', 'Odometer', '#f9f0ff', '#722ed1', '今日请求（北京时间）', comma(stats.requestsToday),
    `网关累计 ${comma(stats.totalRequests)} 次`
  ),
  card(
    'tokensToday', 'Coin', '#e6fffb', '#13c2c2', '今日 Token（北京时间）', compact(stats.tokensToday),
    `网关累计 ${compact(stats.tokensTotal)}（${comma(stats.tokensTotal)}）`
  ),
  card(
    'users', 'User', '#f4f4f5', '#606266', '用户总数', comma(stats.totalUsers),
    `API 密钥 ${comma(stats.totalApiKeys)} 个`
  ),
  card(
    'models', 'Grid', '#fff0f6', '#eb2f96', '模型数量', comma(models.value),
    `接入供应商 ${comma(stats.totalProviders)} 家`
  ),
])

async function loadAll() {
  loading.value = true
  try {
    const [dashRes, modelsRes, eventsRes, termRes] = await Promise.allSettled([
      getDashboard(),
      getAdminModels(),
      getAgentAuditEvents({ page: 1, page_size: 8 }),
      getAgentTerminalStats(),
    ])

    if (dashRes.status === 'fulfilled') {
      const d = dashRes.value.data || {}
      stats.totalRequests = d.total_requests || 0
      stats.totalUsers = d.total_users || 0
      stats.totalApiKeys = d.total_api_keys || 0
      stats.totalProviders = d.total_providers || 0
      stats.requestsToday = d.requests_today || 0
      stats.tokensToday = d.tokens_today || 0
      stats.tokensTotal = d.tokens_total || 0
      stats.terminalTotal = d.terminal_total || 0
      stats.terminalOnline = d.terminal_online || 0
      stats.terminalOffline = d.terminal_offline || 0
      stats.terminalPending = d.terminal_pending || 0
      stats.terminalTokenTotal = d.terminal_token_total || 0
      stats.terminalAlertTotal = d.terminal_alert_total || 0
      stats.eventTotal = d.event_total || 0
      stats.eventToday = d.event_today || 0
      stats.alertsToday = d.alerts_today || 0
      stats.highRiskToday = d.high_risk_today || 0
    }

    if (modelsRes.status === 'fulfilled') {
      models.value = (modelsRes.value.data?.data || []).length
    }

    if (eventsRes.status === 'fulfilled') {
      recentEvents.value = (eventsRes.value.data?.data || []).slice(0, 8)
    }

    if (termRes.status === 'fulfilled') {
      terminalRows.value = (termRes.value.data?.data || []).slice(0, 8)
    }

    lastUpdated.value = new Date().toLocaleTimeString('zh-CN')
  } catch {
    // 各子请求失败已由 allSettled 容错；卡片保留原值
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)
</script>

<style scoped lang="scss">
.dashboard {
  padding: 0;
}

.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-title {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
  color: #303133;
}

.page-head-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.last-updated {
  font-size: 12px;
  color: #a8abb2;
}

.row-gap {
  margin-top: 20px;
}

.stat-card {
  :deep(.el-card__body) {
    display: flex;
    align-items: center;
    gap: 16px;
  }
}

.stat-icon {
  width: 56px;
  height: 56px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-info {
  min-width: 0;
  flex: 1;

  .stat-value {
    font-size: 26px;
    font-weight: 700;
    line-height: 1.2;
    white-space: nowrap;
  }

  .stat-label {
    font-size: 13px;
    color: #303133;
    font-weight: 500;
    margin-top: 2px;
  }

  .stat-sub {
    font-size: 12px;
    color: #909399;
    margin-top: 4px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
}

.panel-card {
  :deep(.el-card__header) {
    padding: 12px 16px;
  }
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
}

.cell-main {
  font-weight: 500;
  color: #303133;
}

.cell-sub {
  font-size: 12px;
  color: #909399;
  margin-top: 1px;
}

.cell-time {
  font-size: 12px;
  color: #909399;
}

.num-alert {
  color: #e6a23c;
  font-weight: 600;
}

.num-danger {
  color: #f56c6c;
  font-weight: 600;
}
</style>
