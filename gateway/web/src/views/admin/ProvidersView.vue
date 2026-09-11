<template>
  <div class="providers-page">
    <div class="page-header">
      <h2 class="page-title">供应商管理</h2>
      <el-button type="primary" @click="openDialog()">
        <el-icon><Plus /></el-icon>添加供应商
      </el-button>
    </div>

    <el-table :data="providers" v-loading="loading" stripe>
      <el-table-column type="expand">
        <template #default="{ row }">
          <div style="padding: 0 20px 10px">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px">
              <span style="font-weight: 600">模型列表</span>
              <el-button size="small" @click="openModelDialog(row)">
                <el-icon><Plus /></el-icon>添加模型
              </el-button>
            </div>
            <el-table :data="row.models || []" size="small" border>
              <el-table-column prop="model_id" label="模型名称" />
              <el-table-column prop="display_name" label="显示名称" />
              <el-table-column label="操作" width="100">
                <template #default="{ row: model }">
                  <el-popconfirm title="确定删除此模型？" @confirm="handleDeleteModel(model.id)">
                    <template #reference>
                      <el-button type="danger" size="small" link>删除</el-button>
                    </template>
                  </el-popconfirm>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="display_name" label="显示名称" />
      <el-table-column prop="provider_type" label="类型" width="120" />
      <el-table-column prop="api_base_url" label="API 地址" show-overflow-tooltip />
      <el-table-column prop="is_active" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.is_active === true ? 'success' : 'info'" size="small">
            {{ row.is_active === true ? '启用' : '禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" size="small" link @click="openDialog(row)">编辑</el-button>
          <el-popconfirm title="确定删除此供应商？" @confirm="handleDelete(row.id)">
            <template #reference>
              <el-button type="danger" size="small" link>删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <!-- Provider Dialog -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingProvider ? '编辑供应商' : '添加供应商'"
      width="500px"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="唯一标识名" />
        </el-form-item>
        <el-form-item label="显示名称" prop="display_name">
          <el-input v-model="form.display_name" placeholder="界面显示名称" />
        </el-form-item>
        <el-form-item label="类型" prop="provider_type">
          <el-select v-model="form.provider_type" placeholder="选择类型">
            <el-option label="OpenAI" value="openai" />
            <el-option label="Anthropic" value="anthropic" />
          </el-select>
        </el-form-item>
        <el-form-item label="API 地址" prop="api_base_url">
          <el-input v-model="form.api_base_url" placeholder="https://api.openai.com" />
        </el-form-item>
        <el-form-item label="API Key" prop="api_key">
          <el-input v-model="form.api_key" type="password" show-password placeholder="供应商 API 密钥" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>

    <!-- Model Dialog: pick from upstream /v1/models -->
<el-dialog v-model="modelDialogVisible" title="添加模型" width="540px">
  <div style="margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center">
    <span style="color: #909399; font-size: 13px">从上游 /v1/models 实时拉取，勾选后批量入库</span>
    <el-button size="small" link type="primary" :loading="upstreamLoading" @click="fetchUpstreamModels(currentProviderId)">重新拉取</el-button>
  </div>
  <el-alert v-if="upstreamError" :title="upstreamError" type="warning" show-icon :closable="false" style="margin-bottom: 10px" />
  <div v-loading="upstreamLoading" style="min-height: 80px">
    <el-checkbox-group v-model="selectedModels" v-if="upstreamModels.length">
      <div style="max-height: 300px; overflow-y: auto">
        <el-checkbox v-for="m in upstreamModels" :key="m.id" :label="m.id" :disabled="m.added" style="display: block; margin-bottom: 4px">
          {{ m.id }}
          <el-tag v-if="m.added" size="small" type="info" style="margin-left: 6px">已添加</el-tag>
        </el-checkbox>
      </div>
    </el-checkbox-group>
    <el-empty v-else-if="!upstreamLoading" description="暂无上游模型，可手动输入" />
  </div>
  <div style="margin-top: 6px">
    <el-button link type="primary" size="small" @click="manualInput = !manualInput">{{ manualInput ? "收起手动输入" : "上游没有？手动输入" }}</el-button>
  </div>
  <el-form v-if="manualInput" ref="modelFormRef" :model="modelForm" :rules="modelRules" label-width="100px" style="margin-top: 8px">
    <el-form-item label="模型名称" prop="model_id">
      <el-input v-model="modelForm.model_id" placeholder="如 gpt-4o" />
    </el-form-item>
    <el-form-item label="显示名称" prop="display_name">
      <el-input v-model="modelForm.display_name" placeholder="可选，界面显示名称" />
    </el-form-item>
  </el-form>
  <template #footer>
    <el-button @click="modelDialogVisible = false">取消</el-button>
    <el-button type="primary" :loading="submitting" @click="handleAddModel">确定</el-button>
  </template>
</el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance } from 'element-plus'
import { getProviders, createProvider, updateProvider, deleteProvider, createModel, deleteModel, getUpstreamModels } from '@/api/admin'

const loading = ref(false)
const submitting = ref(false)
const providers = ref<any[]>([])
const dialogVisible = ref(false)
const modelDialogVisible = ref(false)
const editingProvider = ref<any>(null)
const currentProviderId = ref<number>(0)
const upstreamModels = ref<{ id: string; added: boolean }[]>([])
const upstreamAdded = ref<Set<string>>(new Set())
const selectedModels = ref<string[]>([])
const upstreamLoading = ref(false)
const upstreamError = ref('')
const manualInput = ref(false)
const formRef = ref<FormInstance>()
const modelFormRef = ref<FormInstance>()

const form = reactive({
  name: '',
  display_name: '',
  provider_type: 'openai',
  api_base_url: '',
  api_key: '',
})

const rules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  provider_type: [{ required: true, message: '请选择类型', trigger: 'change' }],
  api_base_url: [{ required: true, message: '请输入 API 地址', trigger: 'blur' }],
  api_key: [{ required: true, message: '请输入 API Key', trigger: 'blur' }],
}

const modelForm = reactive({
  model_id: '',
  display_name: '',
})

const modelRules = {
  model_id: [{ required: true, message: '请输入模型名称', trigger: 'blur' }],
}

async function fetchProviders() {
  loading.value = true
  try {
    const res = await getProviders()
    providers.value = res.data || []
  } catch {
    ElMessage.error('获取供应商列表失败')
  } finally {
    loading.value = false
  }
}

function openDialog(provider?: any) {
  editingProvider.value = provider || null
  if (provider) {
    Object.assign(form, {
      name: provider.name,
      display_name: provider.display_name || '',
      provider_type: provider.provider_type,
      api_base_url: provider.api_base_url,
      api_key: '',
    })
  } else {
    Object.assign(form, {
      name: '',
      display_name: '',
      provider_type: 'openai',
      api_base_url: '',
      api_key: '',
    })
  }
  dialogVisible.value = true
}

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    if (editingProvider.value) {
      await updateProvider(editingProvider.value.id, form)
      ElMessage.success('更新成功')
    } else {
      await createProvider(form)
      ElMessage.success('创建成功')
    }
    dialogVisible.value = false
    fetchProviders()
  } catch {
    ElMessage.error('操作失败')
  } finally {
    submitting.value = false
  }
}

async function handleDelete(id: number) {
  try {
    await deleteProvider(id)
    ElMessage.success('删除成功')
    fetchProviders()
  } catch {
    ElMessage.error('删除失败')
  }
}

function openModelDialog(provider: any) {
  currentProviderId.value = provider.id
  upstreamAdded.value = new Set((provider.models || []).map((m: any) => m.model_id))
  modelForm.model_id = ''
  modelForm.display_name = ''
  manualInput.value = false
  modelDialogVisible.value = true
  fetchUpstreamModels(provider.id)
}

async function fetchUpstreamModels(providerId: number) {
  upstreamLoading.value = true
  upstreamError.value = ''
  upstreamModels.value = []
  selectedModels.value = []
  try {
    const res = await getUpstreamModels(providerId)
    const list: string[] = res.data || []
    upstreamModels.value = list.map((id) => ({ id, added: upstreamAdded.value.has(id) }))
    if (list.length === 0) upstreamError.value = '上游返回了空列表，可手动输入添加'
  } catch (e: any) {
    const msg = e?.response?.data?.error?.message
    upstreamError.value = msg ? `拉取上游模型失败：${msg}` : '拉取上游模型失败，请检查供应商地址与密钥，或手动输入添加'
  } finally {
    upstreamLoading.value = false
  }
}

async function handleAddModel() {
  const selected = selectedModels.value.filter((id) => !upstreamAdded.value.has(id))
  let manualId = ''
  if (manualInput.value && modelForm.model_id.trim()) {
    const valid = await modelFormRef.value?.validate().catch(() => false)
    if (!valid) return
    manualId = modelForm.model_id.trim()
  }
  if (selected.length === 0 && !manualId) {
    ElMessage.warning('请先勾选上游模型，或手动输入一个模型')
    return
  }

  submitting.value = true
  try {
    const tasks: Promise<unknown>[] = selected.map((id) =>
      createModel({ provider_id: currentProviderId.value, model_id: id })
    )
    if (manualId) {
      tasks.push(
        createModel({
          provider_id: currentProviderId.value,
          model_id: manualId,
          display_name: modelForm.display_name || undefined,
        })
      )
    }
    const results = await Promise.allSettled(tasks)
    const failed = results.filter((r) => r.status === 'rejected').length
    if (failed === 0) {
      ElMessage.success(`成功添加 ${tasks.length} 个模型`)
    } else {
      ElMessage.warning(`添加完成，成功 ${tasks.length - failed} 个，失败 ${failed} 个（可能已存在）`)
    }
    modelDialogVisible.value = false
    fetchProviders()
  } catch {
    ElMessage.error('添加模型失败')
  } finally {
    submitting.value = false
  }
}
async function handleDeleteModel(id: number) {
  try {
    await deleteModel(id)
    ElMessage.success('模型删除成功')
    fetchProviders()
  } catch {
    ElMessage.error('删除模型失败')
  }
}

onMounted(fetchProviders)
</script>

<style scoped lang="scss">
.providers-page {
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
</style>
