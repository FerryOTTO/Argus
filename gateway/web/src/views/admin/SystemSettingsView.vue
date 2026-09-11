<template>
  <div class="settings-page">
    <div class="page-header">
      <h2 class="page-title">系统设置</h2>
      <p class="page-subtitle">企业名称 / 系统根地址 / 开放模型 —— 新终端接入平台时自动应用</p>
    </div>

    <el-card shadow="never" v-loading="loading">
      <el-form label-width="130px" style="max-width: 720px">
        <el-form-item label="企业名称">
          <el-input
            v-model="form.enterprise_name"
            placeholder="如：XX 科技有限公司"
            maxlength="64"
            clearable
          />
          <div class="form-tip">
            企业名称会显示在登录页标题，并随新终端注册自动下发（留空时终端使用默认名称）
          </div>
        </el-form-item>

        <el-form-item label="系统根地址">
          <el-input
            v-model="form.system_base_url"
            placeholder="如：http://10.0.0.5:8080（不要带 /v1 后缀）"
            clearable
          />
          <div class="form-tip">
            新注册终端将凭此地址访问平台提供的模型服务（平台会自动拼接 <code>/v1</code>，此处只填根地址即可）；
            留空则不下发该地址
          </div>
        </el-form-item>

        <el-form-item label="开放模型">
          <el-select
            v-model="form.open_models"
            multiple
            filterable
            clearable
            placeholder="不选择 = 开放全部模型"
            style="width: 100%"
          >
            <el-option v-for="m in modelOptions" :key="m" :label="m" :value="m" />
          </el-select>
          <div class="form-tip">
            新注册终端的密钥只能访问这里勾选的模型；不勾选表示不限制。
            已注册终端的密钥不受此次修改影响
          </div>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="saving" @click="handleSave">保存设置</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getSettings, updateSettings, getAdminModels } from '@/api/admin'

const loading = ref(false)
const saving = ref(false)
const modelOptions = ref<string[]>([])

const form = reactive({
  enterprise_name: '',
  system_base_url: '',
  open_models: [] as string[],
})

async function fetchSettings() {
  try {
    const res = await getSettings()
    const data = res.data?.data || {}
    form.enterprise_name = data.enterprise_name || ''
    form.system_base_url = data.system_base_url || ''
    form.open_models = Array.isArray(data.open_models) ? data.open_models : []
  } catch {
    ElMessage.error('获取系统设置失败')
  }
}

async function fetchModels() {
  try {
    const res = await getAdminModels()
    const list: any[] = res.data?.data || []
    modelOptions.value = list.map((m: any) => m.id).filter(Boolean)
  } catch {
    // 模型拉取失败不阻塞设置页
  }
}

async function handleSave() {
  saving.value = true
  try {
    await updateSettings({
      enterprise_name: form.enterprise_name.trim(),
      system_base_url: form.system_base_url.trim(),
      open_models: form.open_models,
    })
    ElMessage.success('系统设置已保存（对新注册终端生效）')
  } catch (err: any) {
    ElMessage.error(err.response?.data?.error?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loading.value = true
  Promise.all([fetchSettings(), fetchModels()]).finally(() => {
    loading.value = false
  })
})
</script>

<style scoped lang="scss">
.settings-page {
  padding: 0;
}

.page-header {
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

.form-tip {
  color: #909399;
  font-size: 12px;
  line-height: 1.6;
  margin-top: 4px;
}
</style>
