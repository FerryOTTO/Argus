<template>
  <div class="packages-tab">
    <!-- 新终端自动分发横幅 -->
    <div class="default-banner">
      <div class="banner-main">
        <div class="banner-title">
          <span>新终端自动分发</span>
          <el-switch
            :model-value="defaults.enabled"
            :loading="savingDefaults"
            @change="handleToggleDefault"
          />
        </div>
        <div class="banner-desc">
          开启后，此后新注册接入的终端将自动获得所选 Skill 包；已有终端不受影响，可在各包的「分发」中单独配置
        </div>
      </div>
      <div class="banner-right">
        <el-tag v-if="defaults.enabled" type="success" size="small" effect="plain">
          已选择 {{ defaults.package_ids.length }} 个默认包
        </el-tag>
        <el-tag v-else type="info" size="small" effect="plain">未启用</el-tag>
        <el-button size="small" @click="openDefaultsDialog">选择默认包</el-button>
      </div>
    </div>

    <!-- 工具栏 -->
    <div class="filter-bar">
      <el-input
        v-model="query.keyword"
        placeholder="按 Skill 名称搜索"
        clearable
        style="width: 240px"
        @keyup.enter="handleSearch"
        @clear="handleSearch"
      />
      <el-button type="primary" @click="handleSearch">查询</el-button>
      <el-button @click="handleReset">重置</el-button>
      <div class="filter-spacer" />
      <el-button type="primary" @click="openUpload()">
        <el-icon><Upload /></el-icon>上传 Skill 包
      </el-button>
    </div>

    <el-table :data="packages" v-loading="loading" stripe>
      <el-table-column label="Skill" min-width="220" show-overflow-tooltip>
        <template #default="{ row }">
          <div class="cell-main">{{ row.name }}</div>
          <div class="cell-sub">{{ row.description || '（无描述）' }}</div>
        </template>
      </el-table-column>
      <el-table-column label="版本" width="80">
        <template #default="{ row }">
          <el-tag size="small" effect="plain">v{{ row.version }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="文件" min-width="170">
        <template #default="{ row }">
          <div class="cell-sub">{{ row.zip_name }}</div>
          <div class="cell-sub file-size">{{ formatSize(row.zip_size) }}</div>
        </template>
      </el-table-column>
      <el-table-column label="内容预览" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">
          <span v-if="row.preview" class="cell-sub">{{ row.preview }}</span>
          <span v-else class="cell-sub">—</span>
        </template>
      </el-table-column>
      <el-table-column label="分发情况" width="120">
        <template #default="{ row }">
          <el-tag type="info" size="small" effect="plain">
            {{ row.assigned_count > 0 ? `已分发 ${row.assigned_count} 台` : '未分发' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="更新时间" width="160">
        <template #default="{ row }">{{ formatDate(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="230" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" size="small" link @click="openAssign(row)">分发</el-button>
          <el-button size="small" link @click="openUpload(row)">更新包</el-button>
          <el-button size="small" link @click="openEditDesc(row)">编辑描述</el-button>
          <el-popconfirm
            title="删除后所有终端将不再收到该 Skill；已安装的不受影响。确定删除？"
            @confirm="handleDelete(row)"
          >
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

    <!-- 上传 / 更新 Skill 包 Dialog -->
    <el-dialog
      v-model="uploadVisible"
      :title="uploadRow ? `更新 Skill 包：${uploadRow.name}` : '上传 Skill 包'"
      width="560px"
      @closed="resetUpload"
    >
      <el-alert
        :type="uploadRow ? 'info' : 'warning'"
        :closable="false"
        show-icon
        :title="
          uploadRow
            ? `将替换当前内容并升级至 v${uploadRow.version + 1}，已分发的终端会按版本差自动重新拉取`
            : '压缩包要求：zip 格式 ≤ 2MB，内含 SKILL.md（须带 frontmatter name），目录或文件命名与 skill 名一致'
        "
      />
      <div class="upload-area">
        <el-upload
          drag
          accept=".zip"
          :auto-upload="false"
          :limit="1"
          :on-change="handleFileChange"
          :on-remove="() => (rawFile = null)"
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">将 zip 文件拖到此处，或<em>点击选择</em></div>
          <template #tip>
            <div class="el-upload__tip">仅支持 .zip（校验包内 SKILL.md 与命名规则，同名覆盖视为更新版本）</div>
          </template>
        </el-upload>
      </div>
      <el-form label-width="70px">
        <el-form-item label="说明">
          <el-input
            v-model="uploadDescription"
            type="textarea"
            :rows="2"
            maxlength="500"
            show-word-limit
            placeholder="可选：覆盖包说明，不填则使用 SKILL.md frontmatter 中的 description"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" :disabled="!rawFile" @click="handleUpload">
          确定上传
        </el-button>
      </template>
    </el-dialog>

    <!-- 分发终端 Dialog（全量覆盖目标集合） -->
    <el-dialog v-model="assignVisible" :title="`分发 Skill：${assignRow?.name || ''}`" width="560px">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="勾选即为最终分发目标（全量保存）；被分发终端将按需拉取并安装，解除后不再下发更新"
      />
      <div class="assign-select">
        <el-select
          v-model="assignTerminalIds"
          multiple
          filterable
          collapse-tags
          collapse-tags-tooltip
          placeholder="选择要分发的终端（可搜索）"
          style="width: 100%"
          :loading="optionsLoading"
        >
          <el-option
            v-for="t in terminalOptions"
            :key="t.id"
            :label="terminalLabel(t)"
            :value="t.id"
          >
            <span>{{ t.name }}</span>
            <span class="option-sub">
              {{ t.hostname || t.agent_type }} · {{ terminalStatusText(t.status) }}
            </span>
          </el-option>
        </el-select>
      </div>
      <template #footer>
        <el-button @click="assignVisible = false">取消</el-button>
        <el-button type="primary" :loading="assigning" @click="handleSaveAssign">保存分发</el-button>
      </template>
    </el-dialog>

    <!-- 默认包选择 Dialog -->
    <el-dialog v-model="defaultsVisible" title="新终端自动分发的默认 Skill 包" width="560px">
      <el-form label-width="90px">
        <el-form-item label="启用分发">
          <el-switch v-model="defaultsDraft.enabled" />
          <span class="form-tip-inline">开启后，新注册终端自动获得下方所选包</span>
        </el-form-item>
        <el-form-item label="默认包">
          <el-select
            v-model="defaultsDraft.package_ids"
            multiple
            filterable
            placeholder="选择 Skill 包（可搜索，留空 = 不自动分发）"
            style="width: 100%"
            :loading="allPackagesLoading"
          >
            <el-option
              v-for="p in allPackages"
              :key="p.id"
              :label="`${p.name}（v${p.version}）`"
              :value="p.id"
            />
          </el-select>
          <div class="form-tip">仅作用于之后新注册的终端；存量终端请在其对应包的「分发」中单独添加</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="defaultsVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingDefaults" @click="handleSaveDefaults">保存</el-button>
      </template>
    </el-dialog>

    <!-- 编辑描述 Dialog -->
    <el-dialog v-model="descVisible" :title="`编辑描述：${descRow?.name || ''}`" width="520px">
      <el-input
        v-model="descText"
        type="textarea"
        :rows="4"
        maxlength="500"
        show-word-limit
        placeholder="包的说明文字（终端侧展示）"
      />
      <template #footer>
        <el-button @click="descVisible = false">取消</el-button>
        <el-button type="primary" :loading="descSaving" @click="handleSaveDesc">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { UploadFile } from 'element-plus'
import {
  getSkillPackages,
  uploadSkillPackage,
  updateSkillPackage,
  deleteSkillPackage,
  getSkillPackageAssignments,
  setSkillPackageAssignments,
  getExtensionTerminalOptions,
  getDefaultSkillPackages,
  setDefaultSkillPackages,
} from '@/api/admin'

const loading = ref(false)
const packages = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const query = reactive({ keyword: '' })

// ── 上传 / 更新 ──
const uploadVisible = ref(false)
const uploadRow = ref<any>(null) // 非空 = 更新场景
const uploadDescription = ref('')
const rawFile = ref<File | null>(null)
const uploading = ref(false)

// ── 分发 ──
const assignVisible = ref(false)
const assignRow = ref<any>(null)
const assignTerminalIds = ref<number[]>([])
const terminalOptions = ref<any[]>([])
const optionsLoading = ref(false)
const assigning = ref(false)

// ── 默认包 ──
const defaultsVisible = ref(false)
const defaults = ref<{ enabled: boolean; package_ids: number[] }>({ enabled: false, package_ids: [] })
const defaultsDraft = reactive<{ enabled: boolean; package_ids: number[] }>({ enabled: false, package_ids: [] })
const savingDefaults = ref(false)
const allPackages = ref<any[]>([])
const allPackagesLoading = ref(false)

// ── 编辑描述 ──
const descVisible = ref(false)
const descRow = ref<any>(null)
const descText = ref('')
const descSaving = ref(false)

function formatDate(dateStr?: string) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN')
}

function formatSize(bytes: number) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

function terminalLabel(t: any) {
  return t.hostname ? `${t.name}（${t.hostname}）` : t.name
}

function terminalStatusText(status: string) {
  return status === 'online' ? '在线' : status === 'offline' ? '离线' : '未激活'
}

async function fetchList() {
  loading.value = true
  try {
    const res = await getSkillPackages({
      keyword: query.keyword || undefined,
      page: page.value,
      page_size: pageSize,
    })
    packages.value = res.data.data || []
    total.value = res.data.total || 0
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error?.message || '加载 Skill 包失败')
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  page.value = 1
  fetchList()
}

function handleReset() {
  query.keyword = ''
  page.value = 1
  fetchList()
}

function handlePageChange(p: number) {
  page.value = p
  fetchList()
}

// ── 上传 / 更新 ──
function openUpload(row?: any) {
  uploadRow.value = row || null
  uploadDescription.value = row?.description || ''
  uploadVisible.value = true
}

function resetUpload() {
  rawFile.value = null
  uploadRow.value = null
  uploadDescription.value = ''
}

function handleFileChange(file: UploadFile) {
  // 限定 zip + 大小（服务端同样校验，这里提前提示）
  if (!file.name.toLowerCase().endsWith('.zip')) {
    ElMessage.warning('仅支持 .zip 压缩包')
    return
  }
  if (file.size > 2 * 1024 * 1024) {
    ElMessage.warning('压缩包不能超过 2MB')
    return
  }
  rawFile.value = (file.raw as File) || null
}

async function handleUpload() {
  if (!rawFile.value) return
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', rawFile.value)
    fd.append('description', uploadDescription.value)
    const res = await uploadSkillPackage(fd)
    const pkg = res.data.data || {}
    ElMessage.success(
      res.data.is_new
        ? `「${pkg.name}」已发布（v${pkg.version}）`
        : `「${pkg.name}」已更新至 v${pkg.version}，已分发终端将自动重拉`
    )
    uploadVisible.value = false
    fetchList()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error?.message || '上传失败')
  } finally {
    uploading.value = false
  }
}

// ── 分发 ──
async function fetchTerminalOptions() {
  optionsLoading.value = true
  try {
    const res = await getExtensionTerminalOptions()
    terminalOptions.value = res.data.data || []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error?.message || '加载终端列表失败')
  } finally {
    optionsLoading.value = false
  }
}

async function openAssign(row: any) {
  assignRow.value = row
  assignTerminalIds.value = []
  assignVisible.value = true
  if (terminalOptions.value.length === 0) {
    await fetchTerminalOptions()
  }
  try {
    const res = await getSkillPackageAssignments(row.id)
    assignTerminalIds.value = res.data.data?.terminal_ids || []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error?.message || '加载分发状态失败')
  }
}

async function handleSaveAssign() {
  const row = assignRow.value
  if (!row) return
  assigning.value = true
  try {
    await setSkillPackageAssignments(row.id, assignTerminalIds.value)
    ElMessage.success('分发已保存，终端将按需拉取安装')
    assignVisible.value = false
    fetchList()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error?.message || '保存失败')
  } finally {
    assigning.value = false
  }
}

// ── 默认包 ──
async function fetchDefaultPackages() {
  try {
    const res = await getDefaultSkillPackages()
    const d = res.data.data || {}
    defaults.value = { enabled: !!d.enabled, package_ids: d.package_ids || [] }
  } catch {
    /* 静默：沿用当前值 */
  }
}

async function loadAllPackages() {
  if (allPackages.value.length > 0) return
  allPackagesLoading.value = true
  try {
    const collected: any[] = []
    let p = 1
    const ps = 100
    for (;;) {
      const res = await getSkillPackages({ page: p, page_size: ps })
      collected.push(...(res.data.data || []))
      if (collected.length >= (res.data.total || 0) || (res.data.data || []).length === 0) break
      p++
    }
    allPackages.value = collected
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error?.message || '加载 Skill 包失败')
  } finally {
    allPackagesLoading.value = false
  }
}

async function openDefaultsDialog() {
  defaultsDraft.enabled = defaults.value.enabled
  defaultsDraft.package_ids = [...defaults.value.package_ids]
  await loadAllPackages()
  defaultsVisible.value = true
}

async function handleToggleDefault(val: boolean) {
  // 打开开关但还没有选择任何包 → 引导先选包
  if (val && defaults.value.package_ids.length === 0) {
    ElMessage.warning('请先选择要自动分发的默认 Skill 包')
    openDefaultsDialog()
    fetchDefaultPackages() // 回滚开关展示
    return
  }
  savingDefaults.value = true
  try {
    await setDefaultSkillPackages({ enabled: val, package_ids: defaults.value.package_ids })
    ElMessage.success(val ? '已开启新终端自动分发' : '已关闭新终端自动分发')
    fetchDefaultPackages()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error?.message || '保存失败')
    fetchDefaultPackages()
  } finally {
    savingDefaults.value = false
  }
}

async function handleSaveDefaults() {
  savingDefaults.value = true
  try {
    await setDefaultSkillPackages({
      enabled: defaultsDraft.enabled,
      package_ids: defaultsDraft.package_ids,
    })
    ElMessage.success('默认包设置已保存')
    defaultsVisible.value = false
    fetchDefaultPackages()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error?.message || '保存失败')
  } finally {
    savingDefaults.value = false
  }
}

// ── 描述 / 删除 ──
function openEditDesc(row: any) {
  descRow.value = row
  descText.value = row.description || ''
  descVisible.value = true
}

async function handleSaveDesc() {
  const row = descRow.value
  if (!row) return
  descSaving.value = true
  try {
    await updateSkillPackage(row.id, descText.value)
    ElMessage.success('描述已更新')
    descVisible.value = false
    fetchList()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error?.message || '保存失败')
  } finally {
    descSaving.value = false
  }
}

async function handleDelete(row: any) {
  try {
    await deleteSkillPackage(row.id)
    ElMessage.success('已删除')
    fetchList()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error?.message || '删除失败')
  }
}

onMounted(() => {
  fetchList()
  fetchDefaultPackages()
})
</script>

<style scoped lang="scss">
.default-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  padding: 12px 16px;
  background: #ecf5ff;
  border: 1px solid #d9ecff;
  border-radius: 6px;
}

.banner-main {
  flex: 1;
}

.banner-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.banner-desc {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}

.banner-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}

.filter-spacer {
  flex: 1;
}

.cell-main {
  font-weight: 500;
  color: #303133;
}

.cell-sub {
  font-size: 12px;
  color: #909399;
}

.file-size {
  font-size: 11px;
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.upload-area {
  margin: 14px 0;
}

.assign-select {
  margin-top: 14px;
}

.option-sub {
  float: right;
  font-size: 12px;
  color: #909399;
}

.form-tip-inline {
  font-size: 12px;
  color: #909399;
  margin-left: 10px;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
  margin-top: 4px;
  width: 100%;
}
</style>
