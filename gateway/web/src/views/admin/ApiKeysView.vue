<template>
  <div class="apikeys-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">密钥管理</h2>
        <p class="page-subtitle">
          管理访问模型所需的密钥：终端注册时平台自动签发，也可手动创建；密钥可归属用户，用于配额与审计统计
        </p>
      </div>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>添加密钥
      </el-button>
    </div>

    <el-table :data="apiKeys" v-loading="loading" stripe>
      <el-table-column label="名称" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">
          <div class="cell-main">{{ row.name }}</div>
          <div class="cell-sub" v-if="row.terminal_name">{{ row.terminal_name }}</div>
        </template>
      </el-table-column>
      <el-table-column label="所属用户" width="140">
        <template #default="{ row }">
          <el-tag v-if="row.owner_username" type="primary" size="small" effect="plain">
            {{ row.owner_username }}
          </el-tag>
          <el-tag v-else size="small" type="info" effect="plain">无主</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="来源" width="110">
        <template #default="{ row }">
          <el-tag v-if="row.terminal_id" type="success" size="small">终端下发</el-tag>
          <span v-else style="color: #909399; font-size: 12px">手动创建</span>
        </template>
      </el-table-column>
      <el-table-column prop="key_prefix" label="密钥前缀" width="130" />
      <el-table-column label="权限模型" min-width="150" show-overflow-tooltip>
        <template #default="{ row }">
          <template v-if="permissionModels(row.permissions)?.length">
            <el-tag v-for="m in permissionModels(row.permissions)" :key="m" size="small" style="margin-right: 4px">
              {{ m }}
            </el-tag>
          </template>
          <span v-else class="cell-sub">全部模型</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '有效' : '已停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="过期时间" width="170">
        <template #default="{ row }">
          {{ row.expires_at ? formatDate(row.expires_at) : '永不过期' }}
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="170">
        <template #default="{ row }">
          {{ formatDate(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="170" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" size="small" link @click="openEdit(row)">编辑</el-button>
          <el-popconfirm
            v-if="row.is_active"
            title="停用后该密钥将无法访问模型，且终端将解除此密钥关联？"
            confirm-button-text="停用"
            @confirm="handleDeactivate(row)"
          >
            <template #reference>
              <el-button type="warning" size="small" link>停用</el-button>
            </template>
          </el-popconfirm>
          <el-popconfirm
            title="删除后密钥将永久移除且无法恢复；若终端正使用此密钥，其 LLM 凭据将立即失效（需重新注册获取新 key）？"
            confirm-button-text="删除"
            @confirm="handleDelete(row)"
          >
            <template #reference>
              <el-button type="danger" size="small" link>删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <!-- 编辑密钥 Dialog：名称 + 权限模型白名单（明文密钥不存储、不可回显） -->
    <el-dialog v-model="editVisible" title="编辑密钥" width="540px">
      <el-form label-width="90px">
        <el-form-item label="名称" required>
          <el-input v-model="editForm.name" maxlength="100" placeholder="如：终端 LLM 凭据 - dev-test-01" />
        </el-form-item>
        <el-form-item label="权限模型">
          <el-select
            v-model="editForm.permissions"
            multiple
            filterable
            allow-create
            default-first-option
            clearable
            style="width: 100%"
            placeholder="留空 = 开放全部模型"
          >
            <el-option-group v-for="g in providerModelGroups" :key="g.label" :label="g.label">
              <el-option v-for="m in g.models" :key="m" :label="m" :value="m" />
            </el-option-group>
          </el-select>
          <div class="form-tip">密钥级白名单，仅允许访问所选模型（可直接手输模型名）；留空表示全部模型，保存后即时生效。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleUpdate">保存</el-button>
      </template>
    </el-dialog>

    <!-- 添加密钥 Dialog（手动创建：名称 + 可选绑定用户 + 权限模型） -->
    <el-dialog v-model="createVisible" title="添加密钥" width="540px">
      <el-form label-width="90px">
        <el-form-item label="名称" required>
          <el-input v-model="createForm.name" maxlength="100" placeholder="如：CI 流水线访问凭据" />
        </el-form-item>
        <el-form-item label="绑定用户">
          <el-select
            v-model="createForm.user_id"
            clearable
            filterable
            placeholder="可留空（无主密钥）"
            style="width: 100%"
          >
            <el-option v-for="u in userOptions" :key="u.id" :label="u.username" :value="u.id" />
          </el-select>
          <div class="form-tip">绑定后，该密钥的用量与审计记录归属此用户；不绑定则创建为无主密钥（列表“所属用户”显示无主）</div>
        </el-form-item>
        <el-form-item label="权限模型">
          <el-select
            v-model="createForm.permissions"
            multiple
            filterable
            allow-create
            default-first-option
            clearable
            style="width: 100%"
            placeholder="留空 = 开放全部模型"
          >
            <el-option-group v-for="g in providerModelGroups" :key="g.label" :label="g.label">
              <el-option v-for="m in g.models" :key="m" :label="m" :value="m" />
            </el-option-group>
          </el-select>
          <div class="form-tip">密钥级白名单，仅允许访问所选模型（可直接手输模型名）；留空表示全部模型</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 新密钥明文一次性展示 Dialog（仅此一次，不可找回） -->
    <el-dialog v-model="showKeyVisible" title="密钥创建成功（仅显示一次）" width="580px">
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="请立即复制并妥善保存；关闭后无法再次查看明文，只能删除后重新创建。"
      />
      <div class="key-name">{{ createdKeyName }}</div>
      <el-input :model-value="createdApiKey" readonly>
        <template #append>
          <el-button @click="copyCreatedKey">复制</el-button>
        </template>
      </el-input>
      <div class="code-tip">
        用法与终端下发的 key 一致：以 <code>Bearer {{ createdApiKeyPrefix }}</code> 访问 OpenAI 兼容端点
        <code>{系统根地址}/v1</code>（如 <code>/v1/models</code>、<code>/v1/chat/completions</code>）
      </div>
      <template #footer>
        <el-button type="primary" @click="showKeyVisible = false">我已保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getApiKeys, createApiKey, deactivateApiKey, updateApiKey, deleteApiKey, getAdminModels, getProviders, getUsers } from '@/api/admin'

const loading = ref(false)
const apiKeys = ref<any[]>([])
// 可选模型列表（来自上游 provider 的 /v1/models；空时仍可手输模型名）
const modelOptions = ref<string[]>([])
const providerModelGroups = ref<{ label: string; models: string[] }[]>([])
// 绑定用户候选（手动创建 key 可选归属）
const userOptions = ref<any[]>([])

// 编辑弹窗状态
const editVisible = ref(false)
const saving = ref(false)
const editingKeyId = ref<number | null>(null)
const editForm = reactive({ name: '', permissions: [] as string[] })

// 创建弹窗状态
const createVisible = ref(false)
const creating = ref(false)
const createForm = reactive({ name: '', user_id: null as number | null, permissions: [] as string[] })

// 创建成功后的一次性明文展示
const showKeyVisible = ref(false)
const createdKeyName = ref('')
const createdApiKey = ref('')
const createdKeyPrefix = ref('')

function formatDate(dateStr: string) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN')
}

// permissions 为 JSON 字符串（"[]" / "["m1","m2"]" / "["*"]"）；空或全通配视为不限
function permissionModels(permissions: string | undefined): string[] | null {
  if (!permissions) return null
  try {
    const list = JSON.parse(permissions)
    if (Array.isArray(list) && list.length > 0 && !list.includes('*')) {
      return list
    }
  } catch {
    // ignore
  }
  return null
}

// 编辑回显：将 JSON 白名单转为选中数组（"*" / 空 => 不选任何项 = 全部模型）
function permissionList(permissions: string | undefined): string[] {
  if (!permissions) return []
  try {
    const list = JSON.parse(permissions)
    if (Array.isArray(list)) {
      return list.filter((m: string) => m !== '*')
    }
  } catch {
    // ignore
  }
  return []
}

async function fetchApiKeys() {
  loading.value = true
  try {
    const res = await getApiKeys()
    apiKeys.value = res.data.data || []
  } catch {
    ElMessage.error('获取密钥列表失败')
  } finally {
    loading.value = false
  }
}

async function fetchModels() {
  try {
    const res = await getProviders()
    const providers = res.data || []
    const groups: { label: string; models: string[] }[] = []
    const flat: string[] = []
    for (const pv of providers) {
      const label = pv.display_name ? pv.display_name + " (" + pv.name + ")" : pv.name
      const models = (pv.models || []).map((m: any) => m.model_id).filter(Boolean)
      if (models.length) { groups.push({ label, models }); flat.push(...models) }
    }
    providerModelGroups.value = groups
    modelOptions.value = flat
    if (flat.length) return
  } catch {
  }
  try {
    const res2 = await getAdminModels()
    modelOptions.value = (res2.data.data || []).map((m: any) => m.id)
  } catch {
    // 模型列表不可用不阻塞编辑（支持手输模型名）
  }
}

async function fetchUsers() {
  try {
    const res = await getUsers()
    userOptions.value = res.data.data || []
  } catch {
    // 用户列表不可用不阻塞创建（可留空创建无主 key）
  }
}

function openCreate() {
  createForm.name = ''
  createForm.user_id = null
  createForm.permissions = []
  createVisible.value = true
}

async function handleCreate() {
  const name = createForm.name.trim()
  if (!name) {
    ElMessage.warning('名称不能为空')
    return
  }
  creating.value = true
  try {
    const res = await createApiKey({
      name,
      user_id: createForm.user_id,
      permissions: createForm.permissions,
    })
    const created = res.data.data
    createdKeyName.value = name
    createdApiKey.value = created.api_key || ''
    createdKeyPrefix.value = created.api_key ? created.api_key.slice(0, 10) : ''
    createVisible.value = false
    showKeyVisible.value = true
    fetchApiKeys()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error?.message || '创建密钥失败')
  } finally {
    creating.value = false
  }
}

async function copyCreatedKey() {
  try {
    await navigator.clipboard.writeText(createdApiKey.value)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败，请手动选择复制')
  }
}

function openEdit(row: any) {
  editingKeyId.value = row.id
  editForm.name = row.name || ''
  editForm.permissions = permissionList(row.permissions)
  editVisible.value = true
}

async function handleUpdate() {
  const name = editForm.name.trim()
  if (!name) {
    ElMessage.warning('名称不能为空')
    return
  }
  if (editingKeyId.value == null) return
  saving.value = true
  try {
    await updateApiKey(editingKeyId.value, { name, permissions: editForm.permissions })
    ElMessage.success('密钥已更新')
    editVisible.value = false
    fetchApiKeys()
  } catch {
    ElMessage.error('更新密钥失败')
  } finally {
    saving.value = false
  }
}

async function handleDeactivate(row: any) {
  try {
    await deactivateApiKey(row.id)
    ElMessage.success('密钥已停用')
    fetchApiKeys()
  } catch {
    ElMessage.error('停用密钥失败')
  }
}

async function handleDelete(row: any) {
  try {
    await deleteApiKey(row.id)
    ElMessage.success('密钥已删除')
    fetchApiKeys()
  } catch {
    ElMessage.error('删除密钥失败')
  }
}

onMounted(() => {
  fetchApiKeys()
  fetchModels()
  fetchUsers()
})
</script>

<style scoped lang="scss">
.apikeys-page {
  padding: 0;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;

  .page-title {
    font-size: 20px;
    font-weight: 600;
    color: #303133;
    margin: 0 0 4px;
  }

  .page-subtitle {
    color: #909399;
    font-size: 13px;
    margin: 0;
  }
}

.cell-main {
  font-weight: 500;
}

.cell-sub {
  color: #909399;
  font-size: 12px;
  margin-top: 2px;
}

.form-tip {
  color: #909399;
  font-size: 12px;
  line-height: 1.5;
  margin-top: 4px;
}

.key-name {
  font-weight: 500;
  color: #303133;
  margin: 14px 0 8px;
}

.code-tip {
  color: #909399;
  font-size: 12px;
  line-height: 1.7;
  margin-top: 10px;

  code {
    background: #f5f7fa;
    padding: 1px 5px;
    border-radius: 3px;
    color: #606266;
  }
}
</style>
