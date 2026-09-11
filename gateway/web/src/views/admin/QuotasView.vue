<template>
  <div class="quotas-page">
    <div class="page-header">
      <h2 class="page-title">配额管理</h2>
      <el-button type="primary" @click="openDialog">
        <el-icon><Plus /></el-icon>添加配额
      </el-button>
    </div>

    <!-- 用户筛选 -->
    <div class="filter-bar">
      <el-select
        v-model="selectedUserId"
        placeholder="选择用户查看配额"
        clearable
        filterable
        style="width: 260px"
        @change="fetchQuotas"
      >
        <el-option
          v-for="u in users"
          :key="u.id"
          :label="u.username"
          :value="u.id"
        />
      </el-select>
    </div>

    <!-- 配额列表 -->
    <el-table :data="quotas" v-loading="loading" stripe style="width: 100%">
      <el-table-column label="用户" width="160">
        <template #default="{ row }">
          {{ getUserLabel(row.user_id) }}
        </template>
      </el-table-column>
      <el-table-column prop="model_id" label="模型" width="180">
        <template #default="{ row }">
          <el-tag v-if="row.model_id === '*'" type="info" size="small">全部模型</el-tag>
          <span v-else>{{ row.model_id }}</span>
        </template>
      </el-table-column>
      <el-table-column label="配额类型" width="140">
        <template #default="{ row }">
          <el-tag :type="quotaTypeTag(row.quota_type)" size="small">
            {{ quotaTypeLabel(row.quota_type) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="limit_value" label="限制值" width="120" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
            {{ row.is_active ? '启用' : '禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="180">
        <template #default="{ row }">
          {{ formatDate(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" fixed="right" width="100">
        <template #default="{ row }">
          <el-popconfirm title="确定删除此配额？" @confirm="handleDelete(row.id)">
            <template #reference>
              <el-button type="danger" size="small" link>删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="selectedUserId && !loading && quotas.length === 0" class="empty-tip">
      <el-empty description="该用户暂无配额记录" />
    </div>
    <div v-if="!selectedUserId" class="empty-tip">
      <el-empty description="请选择一个用户以查看其配额" />
    </div>

    <!-- 添加配额对话框 -->
    <el-dialog v-model="dialogVisible" title="添加配额" width="480px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="用户" prop="user_id">
          <el-select v-model="form.user_id" placeholder="选择用户" filterable style="width: 100%">
            <el-option
              v-for="u in users"
              :key="u.id"
              :label="u.username"
              :value="u.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="模型 ID" prop="model_id">
          <el-input v-model="form.model_id" placeholder='输入模型名称，* 表示全部' />
        </el-form-item>
        <el-form-item label="配额类型" prop="quota_type">
          <el-select v-model="form.quota_type" placeholder="选择配额类型" style="width: 100%">
            <el-option label="RPM（每分钟请求数）" value="rpm" />
            <el-option label="RPD（每日请求数）" value="rpd" />
            <el-option label="TPM（每分钟 Token 数）" value="tpm" />
            <el-option label="TPD（每日 Token 数）" value="tpd" />
          </el-select>
        </el-form-item>
        <el-form-item label="限制值" prop="limit_value">
          <el-input-number v-model="form.limit_value" :min="1" :step="1" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance } from 'element-plus'
import { getQuotas, createQuota, deleteQuota, getUsers } from '@/api/admin'

const loading = ref(false)
const submitting = ref(false)
const quotas = ref<any[]>([])
const users = ref<any[]>([])
const selectedUserId = ref<number | null>(null)
const dialogVisible = ref(false)
const formRef = ref<FormInstance>()

const form = reactive({
  user_id: null as number | null,
  model_id: '*',
  quota_type: '',
  limit_value: 100,
})

const rules = {
  user_id: [{ required: true, message: '请选择用户', trigger: 'change' }],
  quota_type: [{ required: true, message: '请选择配额类型', trigger: 'change' }],
  limit_value: [{ required: true, message: '请输入限制值', trigger: 'blur' }],
}

function formatDate(dateStr: string) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN')
}

function quotaTypeLabel(type: string) {
  const map: Record<string, string> = {
    rpm: 'RPM',
    rpd: 'RPD',
    tpm: 'TPM',
    tpd: 'TPD',
  }
  return map[type] || type
}

function quotaTypeTag(type: string) {
  const map: Record<string, string> = {
    rpm: '',
    rpd: 'success',
    tpm: 'warning',
    tpd: 'info',
  }
  return map[type] || ''
}

function getUserLabel(userId: number) {
  const u = users.value.find((u: any) => u.id === userId)
  return u ? u.username : `用户 #${userId}`
}

async function fetchUsers() {
  try {
    const res = await getUsers()
    users.value = res.data || []
  } catch {
    ElMessage.error('获取用户列表失败')
  }
}

async function fetchQuotas() {
  if (!selectedUserId.value) {
    quotas.value = []
    return
  }
  loading.value = true
  try {
    const res = await getQuotas({ user_id: selectedUserId.value })
    quotas.value = res.data?.data || res.data || []
  } catch {
    ElMessage.error('获取配额列表失败')
  } finally {
    loading.value = false
  }
}

function openDialog() {
  Object.assign(form, {
    user_id: selectedUserId.value || null,
    model_id: '*',
    quota_type: '',
    limit_value: 100,
  })
  dialogVisible.value = true
}

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    await createQuota({
      user_id: form.user_id!,
      model_id: form.model_id || '*',
      quota_type: form.quota_type,
      limit_value: form.limit_value,
    })
    ElMessage.success('配额添加成功')
    dialogVisible.value = false
    // 如果当前已选中该用户，刷新列表
    if (selectedUserId.value === form.user_id) {
      fetchQuotas()
    }
  } catch (e: any) {
    const msg = e?.response?.data?.error?.message || '添加配额失败'
    ElMessage.error(msg)
  } finally {
    submitting.value = false
  }
}

async function handleDelete(id: number) {
  try {
    await deleteQuota(id)
    ElMessage.success('删除成功')
    fetchQuotas()
  } catch {
    ElMessage.error('删除失败')
  }
}

onMounted(() => {
  fetchUsers()
})
</script>

<style scoped lang="scss">
.quotas-page {
  padding: 0;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-title {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.filter-bar {
  margin-bottom: 16px;
}

.empty-tip {
  margin-top: 24px;
}
</style>
