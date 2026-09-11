<template>
  <div class="approvals-tab">
    <!-- 审批概览 -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-value pending-text">{{ stats.pending }}</div>
        <div class="stat-label">待审批</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ stats.today_created }}</div>
        <div class="stat-label">今日新增申请</div>
      </div>
      <div class="stat-card">
        <div class="stat-value ok-text">{{ stats.today_approved }}</div>
        <div class="stat-label">今日通过</div>
      </div>
      <div class="stat-card">
        <div class="stat-value bad-text">{{ stats.today_rejected }}</div>
        <div class="stat-label">今日驳回</div>
      </div>
      <div class="stats-tip">
        <el-icon><InfoFilled /></el-icon>
        <span>智能体安装新 Skill / 接入新 MCP 时须先经管理员审批（自动审批接口已预留，后续可在系统设置开启）</span>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-select v-model="query.state" placeholder="审批状态" clearable style="width: 140px" @change="handleSearch">
        <el-option label="待审批" value="pending" />
        <el-option label="已通过" value="approved" />
        <el-option label="已驳回" value="rejected" />
      </el-select>
      <el-select v-model="query.kind" placeholder="类型" clearable style="width: 130px" @change="handleSearch">
        <el-option label="Skill 安装" value="skill" />
        <el-option label="MCP 接入" value="mcp" />
      </el-select>
      <el-input
        v-model="query.keyword"
        placeholder="按申请名 / 来源 / 终端 / 理由搜索"
        clearable
        style="width: 260px"
        @keyup.enter="handleSearch"
        @clear="handleSearch"
      />
      <el-button type="primary" @click="handleSearch">查询</el-button>
      <el-button @click="handleReset">重置</el-button>
    </div>

    <el-table :data="approvals" v-loading="loading" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column label="类型" width="110">
        <template #default="{ row }">
          <el-tag v-if="row.kind === 'mcp'" type="success" effect="plain" size="small">MCP 接入</el-tag>
          <el-tag v-else effect="plain" size="small">Skill 安装</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="申请内容" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          <div class="cell-main">{{ row.name }}</div>
          <div v-if="row.source" class="cell-sub">{{ row.source }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="terminal_name" label="申请终端" width="150" show-overflow-tooltip>
        <template #default="{ row }">
          <span>{{ row.terminal_name || `#${row.terminal_id}` }}</span>
        </template>
      </el-table-column>
      <el-table-column label="申请理由" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">
          <span v-if="row.reason" class="cell-sub">{{ row.reason }}</span>
          <span v-else class="cell-sub">—</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="stateOf(row.state).type" size="small">{{ stateOf(row.state).text }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="审批方式" width="90">
        <template #default="{ row }">
          <span class="cell-sub">{{ row.approve_mode === 'auto' ? '自动' : '人工' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="审批备注" min-width="150" show-overflow-tooltip>
        <template #default="{ row }">
          <span v-if="row.state !== 'pending'" :class="{ 'bad-text': row.state === 'rejected' }">
            {{ row.review_note || '—' }}
          </span>
          <span v-else class="cell-sub">—</span>
        </template>
      </el-table-column>
      <el-table-column label="申请时间" width="160">
        <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button size="small" link @click="openDetail(row)">详情</el-button>
          <template v-if="row.state === 'pending'">
            <el-button type="success" size="small" link @click="handleApprove(row)">放行</el-button>
            <el-button type="danger" size="small" link @click="handleReject(row)">驳回</el-button>
          </template>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination-bar">
      <el-pagination
        background
        layout="total, prev, pager, next"
        :total="total"
        :page-size="pageSize"
        :current-page="page"
        @current-change="handlePageChange"
      />
    </div>

    <!-- 申请详情抽屉 -->
    <el-drawer v-model="detailVisible" :title="detailTitle" size="520px">
      <template v-if="detailRow">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="申请类型">
            {{ detailRow.kind === 'mcp' ? 'MCP 接入' : 'Skill 安装' }}
          </el-descriptions-item>
          <el-descriptions-item label="申请名">{{ detailRow.name }}</el-descriptions-item>
          <el-descriptions-item v-if="detailRow.source" label="来源">{{ detailRow.source }}</el-descriptions-item>
          <el-descriptions-item label="申请终端">
            {{ detailRow.terminal_name || `#${detailRow.terminal_id}` }}（终端 #{{ detailRow.terminal_id }}）
          </el-descriptions-item>
          <el-descriptions-item label="申请理由">{{ detailRow.reason || '—' }}</el-descriptions-item>
          <el-descriptions-item label="申请时间">{{ formatDate(detailRow.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="stateOf(detailRow.state).type" size="small">{{ stateOf(detailRow.state).text }}</el-tag>
            <span class="detail-mode">（{{ detailRow.approve_mode === 'auto' ? '自动审批' : '人工审批' }}）</span>
          </el-descriptions-item>
          <el-descriptions-item v-if="detailRow.state !== 'pending'" label="审批备注">
            {{ detailRow.review_note || '—' }}
          </el-descriptions-item>
        </el-descriptions>

        <div class="payload-title">申请明细（payload）</div>
        <pre class="payload-box">{{ prettyPayload }}</pre>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getExtensionApprovals,
  getExtensionApprovalStats,
  approveExtensionApproval,
  rejectExtensionApproval,
} from '@/api/admin'

const loading = ref(false)
const approvals = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20

const stats = reactive({ pending: 0, today_created: 0, today_approved: 0, today_rejected: 0 })
const query = reactive({ state: '', kind: '', keyword: '' })

const detailVisible = ref(false)
const detailRow = ref<any>(null)
const detailTitle = computed(() =>
  detailRow.value ? `${detailRow.value.kind === 'mcp' ? 'MCP 接入' : 'Skill 安装'}申请 #${detailRow.value.id}` : ''
)
const prettyPayload = computed(() => {
  const raw = detailRow.value?.payload
  if (!raw) return '{}'
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
})

// 轮询句柄：列表 30s 一次 + 概览 30s 一次（与列表同周期即可）
let pollTimer: number | undefined

const STATE_META: Record<string, { text: string; type: string }> = {
  pending: { text: '待审批', type: 'warning' },
  approved: { text: '已放行', type: 'success' },
  rejected: { text: '已驳回', type: 'danger' },
}
function stateOf(state: string) {
  return STATE_META[state] || { text: state, type: 'info' }
}

function formatDate(dateStr?: string) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN')
}

async function fetchStats() {
  try {
    const res = await getExtensionApprovalStats()
    const d = res.data?.data || {}
    stats.pending = d.pending || 0
    stats.today_created = d.today_created || 0
    stats.today_approved = d.today_approved || 0
    stats.today_rejected = d.today_rejected || 0
  } catch {
    /* 轮询失败静默，下次重试 */
  }
}

async function fetchList() {
  loading.value = true
  try {
    const res = await getExtensionApprovals({
      state: query.state || undefined,
      kind: query.kind || undefined,
      keyword: query.keyword || undefined,
      page: page.value,
      page_size: pageSize,
    })
    approvals.value = res.data.data || []
    total.value = res.data.total || 0
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error?.message || '加载审批单失败')
  } finally {
    loading.value = false
  }
}

function refresh() {
  fetchList()
  fetchStats()
}

function handleSearch() {
  page.value = 1
  refresh()
}

function handleReset() {
  query.state = ''
  query.kind = ''
  query.keyword = ''
  page.value = 1
  refresh()
}

function handlePageChange(p: number) {
  page.value = p
  fetchList()
}

function openDetail(row: any) {
  detailRow.value = row
  detailVisible.value = true
}

async function handleApprove(row: any) {
  try {
    await ElMessageBox.confirm(
      `将放行该申请，终端「${row.terminal_name || `#${row.terminal_id}`}」随后即可安装/接入「${row.name}」。`,
      '确认放行？',
      { type: 'warning', confirmButtonText: '放行', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    const res = await approveExtensionApproval(row.id)
    ElMessage.success('已放行')
    if (detailRow.value?.id === row.id) detailRow.value = res.data.data
    refresh()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error?.message || '操作失败')
  }
}

async function handleReject(row: any) {
  let note = ''
  try {
    const res = await ElMessageBox.prompt(
      '请填写驳回理由，终端侧将收到该理由以了解驳回原因。',
      '驳回申请',
      {
        confirmButtonText: '驳回',
        cancelButtonText: '取消',
        inputPlaceholder: '必填：驳回理由',
        inputValidator: (v: string) => (v && v.trim() ? true : '驳回必须填写理由'),
      }
    )
    note = (res.value || '').trim()
  } catch {
    return
  }
  try {
    await rejectExtensionApproval(row.id, note)
    ElMessage.success('已驳回')
    refresh()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error?.message || '操作失败')
  }
}

onMounted(() => {
  refresh()
  pollTimer = window.setInterval(refresh, 30000)
})
onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<style scoped lang="scss">
.stats-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.stat-card {
  min-width: 110px;
  padding: 10px 16px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  text-align: center;
}

.stat-value {
  font-size: 22px;
  font-weight: 600;
  color: #303133;
}

.stat-value.pending-text {
  color: #e6a23c;
}

.stat-value.ok-text {
  color: #67c23a;
}

.stat-value.bad-text {
  color: #f56c6c;
}

.stat-label {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

.stats-tip {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: 8px;
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}

.filter-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}

.cell-main {
  font-weight: 500;
  color: #303133;
}

.cell-sub {
  font-size: 12px;
  color: #909399;
}

.bad-text {
  color: #f56c6c;
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.detail-mode {
  font-size: 12px;
  color: #909399;
  margin-left: 6px;
}

.payload-title {
  margin: 18px 0 8px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.payload-box {
  margin: 0;
  padding: 12px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  font-family: 'SF Mono', Consolas, Menlo, monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 420px;
  overflow-y: auto;
}
</style>
