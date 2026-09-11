<template>
  <div class="cfg-editor">
    <!-- 模式切换条 -->
    <div class="ed-head">
      <el-radio-group v-model="mode" size="small">
        <el-radio-button value="visual">可视化编辑</el-radio-button>
        <el-radio-button value="json">配置包 JSON</el-radio-button>
      </el-radio-group>
      <span class="ed-hint">
        {{ mode === 'visual' ? '修改后保存：仅被改动过的项会下发给终端，未涉及的项终端保持自身默认' : '即保存后将实际下发给终端的内容，请谨慎修改' }}
      </span>
      <el-button v-if="mode === 'visual'" size="small" text @click="handleResetAll">
        <el-icon><RefreshLeft /></el-icon>全部恢复默认
      </el-button>
    </div>

    <!-- 可视化模式：左分组导航 + 右表单 -->
    <template v-if="mode === 'visual'">
      <div class="ed-body">
        <div class="group-nav">
          <div
            v-for="g in groups"
            :key="g.id"
            class="group-item"
            :class="{ active: activeGroup === g.id }"
            @click="activeGroup = g.id"
          >
            <div class="group-label">{{ g.label }}</div>
            <div class="group-desc">{{ g.desc }}</div>
          </div>
        </div>
        <div class="group-panel">
          <template v-for="section in activeGroupDef.sections" :key="section.title || 's'">
            <div v-if="section.title" class="section-title">{{ section.title }}</div>
            <div class="field-grid">
              <div v-for="f in section.fields" :key="f.key" class="field-cell" :class="{ wide: isWide(f) }">
                <template v-if="f.type === 'bool'">
                  <div class="bool-row">
                    <span class="field-label">{{ f.label }}</span>
                    <el-switch :model-value="val(f) as boolean" @update:model-value="set(f, $event)" />
                  </div>
                  <div v-if="f.desc" class="field-desc">{{ f.desc }}</div>
                </template>

                <template v-else>
                  <div class="field-label">{{ f.label }}</div>
                  <template v-if="f.type === 'number'">
                    <el-input-number
                      :model-value="val(f) as number"
                      :min="f.min" :max="f.max" :step="f.step || 1" :precision="precisionOf(f)"
                      controls-position="right" style="width: 100%"
                      @update:model-value="set(f, $event)"
                    />
                    <span v-if="f.unit" class="unit-tip">{{ f.unit }}</span>
                  </template>
                  <el-input
                    v-else-if="f.type === 'text'"
                    :model-value="val(f) as string"
                    :placeholder="f.placeholder || '留空 = 使用终端本地默认'"
                    @update:model-value="set(f, $event)"
                  />
                  <el-input
                    v-else-if="f.type === 'secret'"
                    :model-value="val(f) as string"
                    :placeholder="f.placeholder || '留空 = 使用终端本地默认'"
                    type="password" show-password
                    @update:model-value="set(f, $event)"
                  />
                  <template v-else-if="f.type === 'llm_preset'">
                    <el-select
                      v-if="allocatedLlm"
                      :model-value="presetMode(f)"
                      style="width: 100%"
                      placeholder="请选择"
                      @update:model-value="onPresetModeChange(f, $event)"
                    >
                      <el-option :label="presetAllocatedLabel(f)" value="__allocated__" />
                      <el-option label="＋ 自定义…" value="__custom__" />
                    </el-select>
                    <div v-if="allocatedLlm" class="preset-hint">{{ presetHint(f) }}</div>
                    <el-select
                      v-if="allocatedLlm && presetMode(f) === '__allocated__' && f.preset === 'model' && allocatedLlm.models.length > 1"
                      :model-value="String(val(f) ?? '')"
                      style="width: 100%; margin-top: 8px"
                      @update:model-value="set(f, $event)"
                    >
                      <el-option v-for="m in allocatedLlm.models" :key="m" :label="m" :value="m" />
                    </el-select>
                    <el-input
                      v-if="!allocatedLlm || presetMode(f) === '__custom__'"
                      :model-value="String(val(f) ?? '')"
                      :type="f.preset === 'api_key' ? 'password' : 'text'"
                      :show-password="f.preset === 'api_key'"
                      :placeholder="f.placeholder || '手动输入自定义值'"
                      style="margin-top: 8px"
                      @update:model-value="set(f, $event)"
                    />
                  </template>
                  <el-select
                    v-else-if="f.type === 'select'"
                    :model-value="val(f) as string" style="width: 100%"
                    :clearable="f.def === ''"
                    :placeholder="f.placeholder || '请选择'"
                    @update:model-value="set(f, $event)"
                  >
                    <el-option v-for="o in f.options" :key="o.value" :label="o.label" :value="o.value" />
                  </el-select>
                  <el-select
                    v-else-if="f.type === 'tags'"
                    :model-value="val(f) as string[]"
                    multiple filterable allow-create default-first-option
                    :clearable="f.clearableTags !== false"
                    :placeholder="f.placeholder || '输入后按回车添加'"
                    style="width: 100%"
                    @update:model-value="set(f, $event)"
                  >
                    <el-option v-for="t in (val(f) as string[])" :key="t" :label="t" :value="t" />
                  </el-select>
                  <el-input
                    v-else-if="f.type === 'textarea'"
                    :model-value="val(f) as string"
                    type="textarea" :rows="f.rows || 4"
                    :placeholder="f.placeholder"
                    @update:model-value="set(f, $event)"
                  />
                  <RulesTableEditor
                    v-else-if="f.type === 'rules_table'"
                    :field="f"
                    :model-value="val(f) as string"
                    @update:model-value="set(f, $event)"
                  />
                  <div v-if="f.desc" class="field-desc">{{ f.desc }}</div>
                </template>
              </div>
            </div>
          </template>
          <div v-if="!activeGroupDef" class="empty-tip">选择左侧分组进行配置</div>
        </div>
      </div>
    </template>

    <!-- JSON 模式：最终下发包预览/编辑 -->
    <template v-else>
      <div class="json-panel">
        <el-alert type="info" :closable="false" show-icon class="json-alert"
          title="此内容即保存后将下发给终端的配置。只需填写要修改的项：未列出的配置项，终端会继续使用自身默认，无需写全。" />
        <el-input
          v-model="jsonText"
          type="textarea"
          :rows="20"
          spellcheck="false"
          class="json-editor"
          placeholder='{}'
        />
      </div>
    </template>

    <div class="ed-footer">
      <el-button @click="$emit('cancel')">取消</el-button>
      <el-button type="primary" :loading="saving" @click="handleSave">保存配置</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, reactive } from 'vue'
import RulesTableEditor from '@/components/terminal/RulesTableEditor.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FieldDef } from '@/config/terminalConfigSchema'
import {
  CONFIG_GROUPS,
  CONFIG_SCHEMA_VERSION,
  buildDefaultTree,
  deepMerge,
  diffToPartial,
  getByPath,
  setByPath,
} from '@/config/terminalConfigSchema'

export interface AllocatedLlm {
  keyId: number
  keyName: string
  keyPrefix: string
  models: string[]
  gatewayBaseUrl: string
}

const props = defineProps<{
  /** 服务端当前下发的配置包原文（'' = 从未下发） */
  initialConfig: string
  /** 保存请求进行中（父组件控制） */
  saving: boolean
  allocatedLlm?: AllocatedLlm | null
}>()

const emit = defineEmits<{
  (e: 'save', configText: string): void
  (e: 'cancel'): void
}>()

const mode = ref<'visual' | 'json'>('visual')
const activeGroup = ref(CONFIG_GROUPS[0].id)
const groups = CONFIG_GROUPS

// 当前编辑树 = 默认树 merged 已下发 partial（含未知扩展键）
const model = ref<Record<string, unknown>>({})
const jsonText = ref('')

const activeGroupDef = computed(() => groups.find((g) => g.id === activeGroup.value))

// 字段类型工具
function isWide(f: FieldDef): boolean {
  return f.type === 'textarea' || f.type === 'tags' || f.type === 'rules_table'
}
function precisionOf(f: FieldDef): number {
  const s = String(f.step || 1)
  const dot = s.indexOf('.')
  return dot >= 0 ? s.length - dot - 1 : 0
}

function val(f: FieldDef): unknown {
  return getByPath(model.value, f.path)
}
function set(f: FieldDef, v: unknown) {
  setByPath(model.value, f.path, v)
}
const presetCustom = reactive(new Set<string>())
function allocatedVal(f: FieldDef): string {
  if (!props.allocatedLlm) return String(f.def ?? '')
  if (f.preset === 'base_url') return props.allocatedLlm.gatewayBaseUrl
  if (f.preset === 'api_key') return ''
  const ms = props.allocatedLlm.models
  if (ms.length === 1) return ms[0]
  return String(f.def ?? '')
}
function presetMode(f: FieldDef): string {
  if (presetCustom.has(f.key)) return '__custom__'
  const cur = String(val(f) ?? '')
  if (f.preset === 'model' && props.allocatedLlm && props.allocatedLlm.models.length > 1) {
    return props.allocatedLlm.models.includes(cur) ? '__allocated__' : '__custom__'
  }
  return cur === allocatedVal(f) ? '__allocated__' : '__custom__'
}
function presetAllocatedLabel(f: FieldDef): string {
  const a = props.allocatedLlm
  if (!a) return '使用分配的'
  if (f.preset === 'base_url') return '使用分配的（网关地址）'
  if (f.preset === 'api_key') return '使用已分配密钥（#' + a.keyId + ' ' + a.keyName + '）'
  if (a.models.length === 1) return '使用分配的模型（' + a.models[0] + '）'
  if (a.models.length > 1) return '使用分配的（' + a.models.length + ' 个模型中选一个）'
  return '不限模型（用终端本地默认）'
}
function presetHint(f: FieldDef): string {
  const a = props.allocatedLlm
  if (!a) return ''
  if (f.preset === 'base_url') return '将下发网关地址：' + a.gatewayBaseUrl
  if (f.preset === 'api_key') return a.keyPrefix + '…。选此项 = 下发包留空，终端沿用本地已保存的分配密钥'
  if (a.models.length === 1) return '与该终端绑定密钥的权限模型一致'
  if (a.models.length > 1) return '仅列出该终端绑定密钥允许的模型'
  return '该密钥不限模型，此项不下发，终端用本地默认'
}

function onPresetModeChange(f: FieldDef, m: string) {
  if (m === '__allocated__') {
    presetCustom.delete(f.key)
    set(f, allocatedVal(f))
  } else {
    presetCustom.add(f.key)
  }
}

/** 初始化：解析已下发配置包并合并到默认树 */
function parseStored(text: string): Record<string, unknown> {
  const t = text.trim()
  if (!t) return {}
  try {
    const obj = JSON.parse(t)
    return typeof obj === 'object' && obj !== null && !Array.isArray(obj) ? (obj as Record<string, unknown>) : {}
  } catch {
    // 历史遗留的非 JSON 原文（或旧版文本下发）：无法并入可视化，仅保留供 JSON 模式兜底
    return { __raw_legacy__: t }
  }
}

function toPackageText(): string {
  const partial = diffToPartial(defaultTree(), model.value)
  const keys = Object.keys(partial)
  if (keys.length === 0) return ''
  return JSON.stringify({ schema_version: CONFIG_SCHEMA_VERSION, ...partial }, null, 2)
}

// 默认树构建一次（所有字段）
let _defaultTree: Record<string, unknown> | null = null
function defaultTree(): Record<string, unknown> {
  if (!_defaultTree) {
    _defaultTree = buildDefaultTree(CONFIG_GROUPS.flatMap((g) => g.sections.flatMap((s) => s.fields)))
  }
  return _defaultTree
}

function syncJsonFromModel() {
  jsonText.value = toPackageText()
}

// JSON → 可视化：合并手改内容
function applyJsonToModel(text: string): boolean {
  const t = text.trim()
  if (!t) {
    model.value = deepMerge(defaultTree(), {})
    return true
  }
  try {
    const obj = JSON.parse(t)
    if (typeof obj !== 'object' || obj === null || Array.isArray(obj)) {
      ElMessage.error('配置包必须是 JSON 对象')
      return false
    }
    model.value = deepMerge(defaultTree(), obj)
    return true
  } catch (e) {
    ElMessage.error('JSON 解析失败：' + (e as Error).message)
    return false
  }
}

watch(mode, (m, old) => {
  if (m === old) return
  if (m === 'json') {
    syncJsonFromModel()
  } else {
    applyJsonToModel(jsonText.value)
  }
})

function handleResetAll() {
  model.value = deepMerge(defaultTree(), {})
  ElMessage.success('已全部恢复终端本地默认（本组改动将被忽略）')
}

function handleSave() {
  let text: string
  if (mode.value === 'visual') {
    text = toPackageText()
    if (text === '') {
      ElMessageBox.confirm('当前未包含任何修改项，保存将“收回”下发配置（终端回退本地默认）。继续？', '提示', {
        type: 'warning',
        confirmButtonText: '收回配置',
        cancelButtonText: '取消',
      })
        .then(() => emit('save', ''))
        .catch(() => {})
      return
    }
  } else {
    if (!jsonText.value.trim()) {
      ElMessageBox.confirm('配置包为空，保存将“收回”下发配置（终端回退本地默认）。继续？', '提示', {
        type: 'warning',
        confirmButtonText: '收回配置',
        cancelButtonText: '取消',
      })
        .then(() => emit('save', ''))
        .catch(() => {})
      return
    }
    try {
      const obj = JSON.parse(jsonText.value)
      if (typeof obj !== 'object' || obj === null || Array.isArray(obj)) {
        ElMessage.error('配置包必须是 JSON 对象')
        return
      }
      const withVer = { schema_version: CONFIG_SCHEMA_VERSION, ...(obj as Record<string, unknown>) }
      text = JSON.stringify(withVer, null, 2)
    } catch (e) {
      ElMessage.error('JSON 解析失败：' + (e as Error).message)
      return
    }
  }
  emit('save', text)
}

// 组件挂载时初始化（父组件以 v-if 保证数据就绪后渲染）
model.value = deepMerge(defaultTree(), parseStored(props.initialConfig))
</script>

<style scoped lang="scss">
.cfg-editor {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.ed-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid #ebeef5;
}

.ed-hint {
  flex: 1;
  font-size: 12px;
  color: #909399;
}

.ed-body {
  display: flex;
  gap: 16px;
  margin-top: 12px;
  min-height: 420px;
  max-height: 56vh;
}

.group-nav {
  width: 168px;
  flex-shrink: 0;
  border-right: 1px solid #ebeef5;
  padding-right: 12px;
  overflow-y: auto;
}

.group-item {
  padding: 9px 10px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 2px;
  transition: background 0.15s;

  &:hover {
    background: #f5f7fa;
  }
  &.active {
    background: #ecf5ff;

    .group-label {
      color: #409eff;
      font-weight: 600;
    }
  }
}

.group-label {
  font-size: 13px;
  color: #303133;
}

.group-desc {
  font-size: 11px;
  color: #a8abb2;
  margin-top: 3px;
  line-height: 1.4;
}

.group-panel {
  flex: 1;
  overflow-y: auto;
  padding-right: 6px;
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  margin: 14px 0 10px;
  padding-bottom: 6px;
  border-bottom: 1px dashed #e4e7ed;

  &:first-child {
    margin-top: 2px;
  }
}

.field-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 20px;
}

.field-cell {
  padding: 8px 0;
  min-width: 0;

  &.wide {
    grid-column: 1 / -1;
  }
}

.field-label {
  font-size: 13px;
  color: #303133;
  margin-bottom: 4px;
  font-weight: 500;
}

.bool-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.field-desc {
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
  margin-top: 5px;
}

.unit-tip {
  margin-left: 8px;
  font-size: 12px;
  color: #909399;
}

.json-panel {
  margin-top: 12px;
}

.json-alert {
  margin-bottom: 10px;
}

.json-editor {
  :deep(textarea) {
    font-family: 'SF Mono', Consolas, Menlo, monospace;
    font-size: 13px;
    line-height: 1.6;
  }
}

.ed-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 14px;
  margin-top: 14px;
  border-top: 1px solid #ebeef5;
}

.empty-tip {
  color: #909399;
  font-size: 13px;
  padding: 40px 0;
  text-align: center;
}
.preset-hint {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
  word-break: break-all;
}

</style>
