<template>
  <div class="terminals-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">终端管理</h2>
        <p class="page-subtitle">登记并管理接入平台的智能体终端（OpenClaw）：查看运行数据，远程下发 Clawguard 安全配置</p>
      </div>
      <el-button type="primary" @click="openDialog()">
        <el-icon><Plus /></el-icon>添加终端
      </el-button>
    </div>

    <!-- 搜索栏 -->
    <div class="filter-bar">
      <el-input
        v-model="query.keyword"
        placeholder="按名称 / 计算机名搜索"
        clearable
        style="width: 240px"
        @keyup.enter="handleSearch"
        @clear="handleSearch"
      />
      <el-select v-model="query.agent_type" placeholder="Agent 类型" clearable style="width: 160px" @change="handleSearch">
        <el-option label="OpenClaw" value="openclaw" />
      </el-select>
      <el-button @click="handleSearch">查询</el-button>
      <el-button @click="handleReset">重置</el-button>
    </div>

    <el-table :data="terminals" v-loading="loading" stripe>
      <el-table-column prop="name" label="终端名称" min-width="140" show-overflow-tooltip>
        <template #default="{ row }">
          <div class="cell-main">{{ row.name }}</div>
          <div v-if="row.description" class="cell-sub">{{ row.description }}</div>
        </template>
      </el-table-column>
      <el-table-column label="Agent 类型 / 版本" width="160">
        <template #default="{ row }">
          <el-tag type="primary" size="small" effect="plain">{{ agentLabel(row.agent_type) }}</el-tag>
          <el-tag v-if="row.agent_version" size="small" class="ver-tag">{{ row.agent_version }}</el-tag>
          <span v-else class="cell-sub">未上报</span>
        </template>
      </el-table-column>
      <el-table-column label="Clawguard 版本" width="130">
        <template #default="{ row }">
          <el-tag v-if="row.clawguard_version" size="small" type="info">{{ row.clawguard_version }}</el-tag>
          <span v-else class="cell-sub">未上报</span>
        </template>
      </el-table-column>
      <el-table-column label="绑定用户" width="110">
        <template #default="{ row }">
          <span>{{ row.bound_username || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="LLM 密钥" width="120">
        <template #default="{ row }">
          <el-tag v-if="row.llm_api_key_id" type="success" size="small" effect="plain">#{{ row.llm_api_key_id }}</el-tag>
          <span v-else class="cell-sub">未签发</span>
        </template>
      </el-table-column>
      <el-table-column prop="hostname" label="终端计算机名" min-width="130" show-overflow-tooltip>
        <template #default="{ row }">
          <span v-if="row.hostname">{{ row.hostname }}</span>
          <span v-else class="cell-sub">-</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="statusOf(row).type" size="small">{{ statusOf(row).text }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="Token 消耗数" width="120" align="right">
        <template #default="{ row }">
          <span>{{ formatNumber(row.token_usage_total) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="安全预警次数" width="120" align="right">
        <template #default="{ row }">
          <span :class="{ 'alert-count': row.alert_count_total > 0 }">
            {{ formatNumber(row.alert_count_total) }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="最近心跳" width="170">
        <template #default="{ row }">
          {{ formatDate(row.last_seen_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="300" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" size="small" link @click="openConfigDialog(row)">修改配置</el-button>
          <el-button size="small" link @click="openDialog(row)">编辑</el-button>
          <el-button type="warning" size="small" link @click="handleRegenerateCode(row)">重置注册码</el-button>
          <el-popconfirm title="吊销后终端将断开与平台的连接，如需重新接入，请重新生成注册码？" @confirm="handleRevoke(row)">
            <template #reference>
              <el-button type="danger" size="small" link>吊销</el-button>
            </template>
          </el-popconfirm>
          <el-popconfirm title="确定删除此终端？其审计记录、LLM 密钥及相关运行数据将一并删除" @confirm="handleDelete(row)">
            <template #reference>
              <el-button type="danger" size="small" link>删除</el-button>
            </template>
          </el-popconfirm>
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

    <!-- 添加 / 编辑终端 Dialog -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingTerminal ? '编辑终端' : '添加终端'"
      width="520px"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="终端名称" prop="name">
          <el-input v-model="form.name" placeholder="如：研发-张三的MacBook" />
        </el-form-item>
        <el-form-item label="Agent 类型" prop="agent_type">
          <el-select v-model="form.agent_type" :disabled="!!editingTerminal" style="width: 100%">
            <el-option label="OpenClaw" value="openclaw" />
          </el-select>
          <div class="form-tip">更多 Agent 类型（Claude Code 等）将在后续版本开放</div>
        </el-form-item>
        <el-form-item label="绑定用户" prop="bound_user_id">
          <el-select
            v-model="form.bound_user_id"
            placeholder="选择 Clawguard 控制台用户（可留空）"
            clearable
            style="width: 100%"
          >
            <el-option v-for="u in userOptions" :key="u.id" :label="u.username" :value="u.id" />
          </el-select>
          <div class="form-tip">终端注册时自动签发的密钥将归属此用户；变更绑定用户时密钥归属同步更新（解绑后变为无主）</div>
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="可选：用途 / 位置 / 备注" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>

    <!-- 注册码一次性展示 Dialog -->
    <el-dialog v-model="codeDialogVisible" title="终端接入信息（仅显示一次）" width="560px">
      <el-alert type="warning" :closable="false" show-icon
        title="请立即复制注册码并交给终端侧配置；关闭后无法再次查看，只能重新生成。" />
      <div class="code-box">
        <div class="code-label">Registration Code（注册码）</div>
        <div class="code-value">{{ registrationCode }}</div>
        <el-button type="primary" size="small" @click="copyCode">复制注册码</el-button>
      </div>
      <div class="code-tip">
        接入方式：将「系统设置 → 系统根地址」与本注册码填入终端客户端的接入配置，客户端将自动完成注册；
        成功后平台会一次性下发该终端的 LLM 密钥与接入信息（密钥进入「密钥管理」，归属随终端的绑定用户）。
      </div>
      <template #footer>
        <el-button type="primary" @click="codeDialogVisible = false">我已保存</el-button>
      </template>
    </el-dialog>

    <!-- 修改配置 Dialog（可视化编辑器，schema 见 config/terminalConfigSchema.ts） -->
    <el-dialog
      v-model="configDialogVisible"
      title="修改终端 Clawguard 配置"
      width="960px"
      top="4vh"
    >
      <template v-if="configState">
        <div class="config-meta">
          <span>下发版本：<b>v{{ configState.config_version }}</b></span>
          <span class="meta-sep">|</span>
          <span>终端已应用：<b>v{{ configState.config_applied_version }}</b></span>
          <span class="meta-sep">|</span>
          <el-tag :type="configState.config_pending ? 'warning' : 'success'" size="small">
            {{ configState.config_pending ? '等待终端拉取' : '终端已同步' }}
          </el-tag>
          <span class="meta-sep">|</span>
          <span>绑定用户：<b>{{ activeConfigRow?.bound_username || '-' }}</b><span class="cell-sub">（仅改此用户等级）</span></span>
          <span v-if="configState.config_version === 0 && !configState.has_live" class="cell-sub">（尚未下发过配置，终端使用本地配置）</span>
          <span v-if="editorFromLive" class="cell-sub">（已预填该绑定用户当前等级与实时资源规则，改等级后保存即可）</span>
          <span v-else-if="configState.has_live && configState.live_updated_at" class="cell-sub">（终端实时文件 {{ configState.live_updated_at }} 已上报）</span>
        </div>
        <TerminalConfigEditor
          v-if="configReady"
          :initial-config="editorInitialConfig"
          :saving="savingConfig"
          :allocated-llm="allocatedLlm"
          @save="handleEditorSave"
          @cancel="configDialogVisible = false"
        />
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance } from 'element-plus'
import {
  getTerminals,
  createTerminal,
  updateTerminal,
  deleteTerminal,
  regenerateTerminalCode,
  revokeTerminal,
  getTerminalConfig,
  updateTerminalConfig,
  getUsers,
  getApiKeys,
  getSettings,
} from '@/api/admin'
import TerminalConfigEditor from '@/components/terminal/TerminalConfigEditor.vue'
import type { AllocatedLlm } from '@/components/terminal/TerminalConfigEditor.vue'

const loading = ref(false)
const submitting = ref(false)
const savingConfig = ref(false)
const terminals = ref<any[]>([])
const userOptions = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20

const query = reactive({ keyword: '', agent_type: '' })

const dialogVisible = ref(false)
const editingTerminal = ref<any>(null)
const formRef = ref<FormInstance>()
const form = reactive({
  name: '',
  agent_type: 'openclaw',
  bound_user_id: undefined as number | undefined,
  description: '',
})

const rules = {
  name: [{ required: true, message: '请输入终端名称', trigger: 'blur' }],
  agent_type: [{ required: true, message: '请选择 Agent 类型', trigger: 'change' }],
}

const codeDialogVisible = ref(false)
const registrationCode = ref('')

const configDialogVisible = ref(false)
const configState = ref<any>(null)
const activeConfigRow = ref<any>(null)
// 可视化配置编辑器（见 components/terminal/TerminalConfigEditor.vue）
const configReady = ref(false) // 服务端配置拉取完成后渲染编辑器（保证初始数据就绪）
const editorInitialConfig = ref('')
const editorFromLive = ref(false)
const allocatedLlm = ref<AllocatedLlm | null>(null)

function parseKeyModels(permissions: string | undefined): string[] {
  if (!permissions) return []
  try {
    const list = JSON.parse(permissions)
    if (Array.isArray(list)) return list.filter((m: unknown) => typeof m === 'string' && m !== '*')
  } catch { }
  return []
}

async function resolveAllocatedLlm(row: any): Promise<AllocatedLlm | null> {
  if (!row || row.llm_api_key_id === null || row.llm_api_key_id === undefined) return null
  try {
    const [keysRes, settingsRes] = await Promise.all([getApiKeys(), getSettings()])
    const keys = keysRes.data?.data || []
    const k = keys.find((x: any) => x.id === row.llm_api_key_id)
    if (!k) return null
    let base = String(settingsRes.data?.data?.system_base_url || '').trim()
    if (!base && typeof window !== 'undefined') base = window.location.origin
    base = base.replace(/\/+$/, '') + '/v1'
    return { keyId: k.id, keyName: k.name || '', keyPrefix: k.key_prefix || '', models: parseKeyModels(k.permissions), gatewayBaseUrl: base }
  } catch {
    return null
  }
}

// 终端类型展示名映射（新增类型时在此扩展）
const AGENT_LABELS: Record<string, string> = { openclaw: 'OpenClaw' }
function agentLabel(type: string) {
  return AGENT_LABELS[type] || type
}

function statusOf(row: any) {
  if (row.status !== 'active') return { type: 'warning' as const, text: '未注册' }
  if (row.online) return { type: 'success' as const, text: '在线' }
  return { type: 'info' as const, text: '离线' }
}

function formatNumber(n: number) {
  return (n || 0).toLocaleString('zh-CN')
}

function formatDate(dateStr?: string) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN')
}

async function fetchTerminals() {
  loading.value = true
  try {
    const res = await getTerminals({
      page: page.value,
      page_size: pageSize,
      keyword: query.keyword || undefined,
      agent_type: query.agent_type || undefined,
    })
    terminals.value = res.data.data || []
    total.value = res.data.total || 0
  } catch {
    ElMessage.error('获取终端列表失败')
  } finally {
    loading.value = false
  }
}

async function fetchUserOptions() {
  try {
    const res = await getUsers({ page: 1, page_size: 100 } as any)
    userOptions.value = res.data.data || []
  } catch {
    // 用户列表拉取失败不阻塞终端页
  }
}

function handleSearch() {
  page.value = 1
  fetchTerminals()
}

function handleReset() {
  query.keyword = ''
  query.agent_type = ''
  page.value = 1
  fetchTerminals()
}

function handlePageChange(p: number) {
  page.value = p
  fetchTerminals()
}

function openDialog(terminal?: any) {
  editingTerminal.value = terminal || null
  Object.assign(form, {
    name: terminal?.name || '',
    agent_type: terminal?.agent_type || 'openclaw',
    bound_user_id: terminal?.bound_user_id || undefined,
    description: terminal?.description || '',
  })
  dialogVisible.value = true
}

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    const payload = {
      name: form.name.trim(),
      agent_type: form.agent_type,
      bound_user_id: form.bound_user_id ?? null,
      description: form.description,
    }
    if (editingTerminal.value) {
      await updateTerminal(editingTerminal.value.id, payload)
      ElMessage.success('终端已更新')
      dialogVisible.value = false
      fetchTerminals()
    } else {
      const res = await createTerminal(payload)
      dialogVisible.value = false
      fetchTerminals()
      registrationCode.value = res.data?.data?.registration_code || ''
      codeDialogVisible.value = true
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error?.message || '操作失败')
  } finally {
    submitting.value = false
  }
}

async function handleDelete(row: any) {
  try {
    await deleteTerminal(row.id)
    ElMessage.success('终端已删除')
    fetchTerminals()
  } catch {
    ElMessage.error('删除失败')
  }
}

async function handleRegenerateCode(row: any) {
  try {
    const res = await regenerateTerminalCode(row.id)
    registrationCode.value = res.data?.data?.registration_code || ''
    codeDialogVisible.value = true
  } catch {
    ElMessage.error('重新生成注册码失败')
  }
}

async function handleRevoke(row: any) {
  try {
    await revokeTerminal(row.id)
    ElMessage.success('终端已吊销')
    fetchTerminals()
  } catch {
    ElMessage.error('吊销失败')
  }
}

async function openConfigDialog(row: any) {
  activeConfigRow.value = row
  configReady.value = false
  configState.value = null
  configDialogVisible.value = true
  allocatedLlm.value = null
  try {
    const res = await getTerminalConfig(row.id)
    configState.value = res.data.data || {}
    if (configState.value.config) {
      editorInitialConfig.value = configState.value.config
      editorFromLive.value = false
    } else if (configState.value.live_config) {
      editorInitialConfig.value = configState.value.live_config
      editorFromLive.value = true
    } else {
      editorInitialConfig.value = ''
      editorFromLive.value = false
    }
    configReady.value = true
    resolveAllocatedLlm(row).then((v) => { allocatedLlm.value = v })
  } catch {
    ElMessage.error('加载终端配置失败')
    configDialogVisible.value = false
  }
}

// 编辑器保存（configText: 可视化/JSON 模式生成的配置包原文；'' = 收回下发）
async function handleEditorSave(configText: string) {
  if (!activeConfigRow.value) return
  if (configText) {
    try {
      const pkg = JSON.parse(configText) as Record<string, unknown>
      const au = pkg.access_user as Record<string, unknown> | undefined
      if (au && typeof au === 'object' && !Array.isArray(au)) {
        if (!String(au.username ?? '').trim() && activeConfigRow.value.bound_username) {
          au.username = activeConfigRow.value.bound_username
          configText = JSON.stringify(pkg, null, 2)
        }
      }
    } catch { /* JSON 包原样下发 */ }
  }
  savingConfig.value = true
  try {
    const res = await updateTerminalConfig(activeConfigRow.value.id, configText)
    const version = res.data?.data?.config_version
    configState.value = {
      ...configState.value,
      config: configText,
      config_version: version,
      config_pending: true,
    }
    ElMessage.success(version > 0
      ? `配置已保存（v${version}），终端将在下次心跳时拉取应用`
      : '已收回下发配置，终端下次心跳后将回退本地默认')
    fetchTerminals()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error?.message || '保存配置失败')
  } finally {
    savingConfig.value = false
  }
}

async function copyCode() {
  try {
    await navigator.clipboard.writeText(registrationCode.value)
    ElMessage.success('注册码已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}

onMounted(() => {
  fetchTerminals()
  fetchUserOptions()
})
</script>

<style scoped lang="scss">
.terminals-page {
  padding: 0;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}

.page-title {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
  margin: 0;
}

.page-subtitle {
  margin: 6px 0 0;
  font-size: 13px;
  color: #909399;
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

.ver-tag {
  margin-left: 6px;
}

.alert-count {
  color: #f56c6c;
  font-weight: 600;
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
  margin-top: 4px;
}

.code-box {
  margin: 16px 0;
  padding: 16px;
  background: #f5f7fa;
  border-radius: 6px;
  border: 1px dashed #dcdfe6;
}

.code-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
}

.code-value {
  font-family: 'SF Mono', Consolas, Menlo, monospace;
  font-size: 16px;
  color: #303133;
  word-break: break-all;
  margin-bottom: 12px;
}

.code-tip {
  font-size: 13px;
  color: #606266;
  line-height: 1.7;
}

.code-tip code {
  background: #f0f2f5;
  padding: 1px 5px;
  border-radius: 3px;
  font-family: 'SF Mono', Consolas, Menlo, monospace;
  font-size: 12px;
}

.config-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 13px;
  color: #606266;
}

.meta-sep {
  color: #dcdfe6;
}
</style>
