<template>
  <div class="rules-editor">
    <div class="rules-scroll">
      <table v-if="rows.length > 0" class="rules-table">
        <thead>
          <tr>
            <th v-for="col in field.columns" :key="col.key" :style="colStyle(col)">{{ col.label }}</th>
            <th class="op-col"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td v-for="col in field.columns" :key="col.key" :style="colStyle(col)">
              <el-input
                v-if="(col.type || 'text') === 'text'"
                v-model="row.cells[col.key]"
                :placeholder="col.placeholder"
                size="small"
                @change="commit()"
              />
              <el-select
                v-else-if="col.type === 'select'"
                :model-value="cellValue(row, col) as string"
                :placeholder="col.placeholder"
                size="small"
                style="width: 100%"
                @update:model-value="setCell(row, col, $event)"
              >
                <el-option v-for="o in selectOptions(col)" :key="o.value" :label="o.label" :value="o.value" />
              </el-select>
              <el-select
                v-else-if="col.type === 'tags'"
                :model-value="cellTags(row, col)"
                multiple filterable allow-create default-first-option
                :placeholder="col.placeholder || '回车添加'"
                size="small"
                style="width: 100%"
                @update:model-value="setCell(row, col, $event)"
              >
                <el-option v-for="t in cellTags(row, col)" :key="t" :label="t" :value="t" />
              </el-select>
            </td>
            <td class="op-col">
              <el-button link type="danger" size="small" title="删除该行" @click="removeRow(row)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="rules-empty">
        当前无任何规则行 —— 留空保存 = 不覆盖终端本地文件；点击下方「添加一行」开始编辑
      </div>
    </div>
    <el-button size="small" class="add-row-btn" @click="addRow">
      <el-icon><Plus /></el-icon>添加一行
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { FieldDef, RulesColumn } from '@/config/terminalConfigSchema'
import { parseRulesText, serializeRulesText, type RuleRow } from '@/config/rulesText'

const props = defineProps<{
  /** 规则表字段（type 应为 rules_table，值 = 规则文件文本原文） */
  field: FieldDef
  modelValue: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: string): void
}>()

const cols = computed(() => props.field.columns || [])
const rows = ref<RuleRow[]>([])

let uidSeq = 0
function withId(r: Omit<RuleRow, 'id'>): RuleRow {
  return { ...r, id: ++uidSeq }
}

function reload(text: string) {
  rows.value = parseRulesText(text, cols.value).map(withId)
}

// 外部值变化（初始化 / JSON→可视化 / 恢复默认）时重新解析；
// 若新值与当前行的序列化结果一致（即刚由自身 commit 写回）则跳过，避免重建行打断编辑
watch(
  () => props.modelValue,
  (v) => {
    const t = String(v ?? '')
    if (serializeRulesText(rows.value, props.field, cols.value) === t) return
    reload(t)
  },
  { immediate: true },
)

function commit() {
  const t = serializeRulesText(rows.value, props.field, cols.value)
  if (t !== props.modelValue) emit('update:modelValue', t)
}

function cellValue(row: RuleRow, col: RulesColumn): string {
  return (row.cells[col.key] as string) ?? ''
}
function cellTags(row: RuleRow, col: RulesColumn): string[] {
  return Array.isArray(row.cells[col.key]) ? (row.cells[col.key] as string[]) : []
}
function setCell(row: RuleRow, col: RulesColumn, v: unknown) {
  row.cells[col.key] = col.type === 'tags' ? (v as string[]) : String(v ?? '')
  commit()
}

function addRow() {
  const cells: Record<string, string | string[]> = {}
  for (const col of cols.value) {
    cells[col.key] = col.type === 'tags' ? [] : ''
  }
  rows.value.push(withId({ cells }))
  commit()
}

function removeRow(row: RuleRow) {
  rows.value = rows.value.filter((r) => r.id !== row.id)
  commit()
}

function colStyle(col: RulesColumn) {
  return col.width ? { width: col.width } : undefined
}

/** select 列下拉：标准选项 + 行内已存在的非标值（如历史文本中的别名残留，保证可见可改） */
function selectOptions(col: RulesColumn) {
  const opts = col.options || []
  const known = new Set(opts.map((o) => o.value))
  const extra = new Set<string>()
  for (const row of rows.value) {
    const v = row.cells[col.key]
    if (typeof v === 'string' && v && !known.has(v)) extra.add(v)
  }
  return extra.size === 0 ? opts : [...opts, ...[...extra].map((v) => ({ label: v, value: v }))]
}
</script>

<style scoped lang="scss">
.rules-editor {
  display: flex;
  flex-direction: column;
}

.rules-scroll {
  max-height: 300px;
  overflow: auto;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
}

.rules-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;

  th,
  td {
    padding: 4px 8px;
    border-bottom: 1px solid #f0f2f5;
    text-align: left;
    vertical-align: middle;
  }

  thead th {
    position: sticky;
    top: 0;
    z-index: 1;
    background: #f5f7fa;
    color: #606266;
    font-weight: 600;
    font-size: 12px;
    white-space: nowrap;
  }

  tbody tr {
    &:hover {
      background: #fafafa;
    }
    &:last-child td {
      border-bottom: none;
    }
  }
}

.op-col {
  width: 40px;
  text-align: center;
}

.rules-empty {
  padding: 22px 14px;
  font-size: 12px;
  color: #a8abb2;
  text-align: center;
  line-height: 1.6;
}

.add-row-btn {
  align-self: flex-start;
  margin-top: 8px;
}
</style>
