// ============================================================================
// 访问控制规则文件（users.txt / resources.txt）文本 ↔ 可视化表格行互转
//
// 文本格式（Clawguard auth_gateway 解析规则，CONFIGS.md §4.1）：
//   users.txt:     用户名或ID | 默认等级 | 特例(逗号分隔,可选)
//   resources.txt: 路径模式 | 所需等级 | 继承模式(flat/inherit/override)
// 解析行为与后端一致：整行以 '#' 开头或空行跳过；'|' 切列并剥行内注释；
// 等级别名（数字/字母）统一归一为标准名；tags 列按 ',' 拆子项。
//
// 序列化规则：仅输出数据行（跳过首列为空的行）；有任何数据行时自动带
// 文件头注释（风格同后端 save_users / save_resources）；空 → ''（不覆盖）。
// ============================================================================

import type { FieldDef, RulesColumn } from './terminalConfigSchema'

/** 表格数据行（cells 键 = RulesColumn.key；text/select 为 string，tags 为 string[]） */
export interface RuleRow {
  id: number
  cells: Record<string, string | string[]>
}

/** 后端 _normalize_level 的等级别名 → 标准名（未知值原样保留，不做有损归一） */
const LEVEL_ALIASES: Record<string, string> = {
  '1': 'public', '2': 'internal', '3': 'secret', '4': 'top_secret',
  a: 'public', b: 'internal', c: 'secret', d: 'top_secret',
  public: 'public', internal: 'internal', secret: 'secret',
  top_secret: 'top_secret', topsecret: 'top_secret',
}

export function normalizeLevel(raw: string): string {
  // 与后端一致：先 trim + lower 再查别名表（'B'/'SECRET' 等大小写均可识别）
  const s = raw.trim().toLowerCase()
  return LEVEL_ALIASES[s] ?? s
}

/** 剥行内注释（与后端 _split_line 的 re.sub(r"\s+#.*$", "") 一致） */
function stripInlineComment(s: string): string {
  return s.replace(/\s+#.*$/, '')
}

/** 文件头注释（按字段 key 定位目标文件；风格与 Clawguard 后端保存一致） */
const FILE_HEADERS: Record<string, string[]> = {
  users: ['# Clawguard 用户规则', '# 格式: 用户名或ID | 默认等级 | 特例(逗号分隔,可选)'],
  resources: ['# Clawguard 资源规则', '# 格式: 路径模式 | 所需等级 | 继承模式(flat/inherit/override)'],
}

/** 解析规则文件文本为表格行（过滤空行/注释行，等级别名归一） */
export function parseRulesText(text: string, cols: RulesColumn[]): RuleRow[] {
  const rows: RuleRow[] = []
  let seq = 0
  const lines = String(text ?? '').split(/\r?\n/)
  for (const raw of lines) {
    const line = stripInlineComment(raw.trim())
    if (!line || line.startsWith('#')) continue
    const segs = line.split('|')
    const cells: Record<string, string | string[]> = {}
    for (let i = 0; i < cols.length; i++) {
      const col = cols[i]
      const seg = (segs[i] ?? '').trim()
      if (col.type === 'tags') {
        cells[col.key] = seg ? seg.split(',').map((s) => s.trim()).filter(Boolean) : []
      } else if (col.type === 'select') {
        cells[col.key] = normalizeLevel(seg)
      } else {
        cells[col.key] = seg
      }
    }
    rows.push({ id: ++seq, cells })
  }
  return rows
}

/** 序列化表格行为规则文件文本；全空 → ''（不覆盖终端本地文件） */
export function serializeRulesText(rows: RuleRow[], field: FieldDef, cols: RulesColumn[]): string {
  const lines: string[] = []
  for (const row of rows) {
    const parts = cols.map((col) => {
      const v = row.cells[col.key]
      if (col.type === 'tags') return Array.isArray(v) ? v.join(',') : ''
      return String(v ?? '').trim()
    })
    if (!parts[0]) continue // 主列（首列）为空的行视为无效行，不输出
    lines.push(parts.join(' | '))
  }
  if (lines.length === 0) return ''
  const header = FILE_HEADERS[field.key]
  return (header ? header.join('\n') + '\n\n' : '') + lines.join('\n')
}
