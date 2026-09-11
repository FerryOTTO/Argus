// ============================================================================
// Clawguard 集控配置包 schema v1（终端"修改配置"可视化编辑器的唯一数据源）
//
// 设计依据：ClawguardV2.1/CONFIGS.md（2026-09 实测结论）
//  - 仅收录"已生效"配置项；CONFIGS.md 中标注 ⚠️ 的声明未接线项一律不收
//  - 键路径收敛命名：modules.* / io_guard_policy.* / access.* /
//    access_rules.* / retrieval.* / integration.*
//  - 下发语义 = partial 增量合并（客户端 deep-merge 本地配置，见 REMOTE.md）
//
// 分组方式：按**模块**组织（导航分组 = CONFIGS.md 模块边界）——
//   IO Guard 检测 / Tool Guard / Retrieval Guard / 访问控制 / 审计 /
//   沙箱 / 人工复核 / OpenClaw 集成；每个模块的"启停+异常兜底"开关
//   与其参数放在同一分组，不再集中到"链路编排"总览。
//
// 新增配置项时：在对应模块的字段数组中追加一条 FieldDef 即可，
// UI（分组导航 + 表单控件）与默认树均由本 schema 自动推导。
// ============================================================================

export type FieldType = 'bool' | 'number' | 'text' | 'secret' | 'select' | 'tags' | 'textarea' | 'rules_table' | 'llm_preset'

export type RulesColumnType = 'text' | 'select' | 'tags'

/** 规则表（rules_table）的列定义：value 即文本行按 '|' 分隔的列；tags 列内部再按 ',' 拆分子项 */
export interface RulesColumn {
  key: string // 列键（路径语义见 rulesText.ts 解析器）
  label: string // 表头
  type?: RulesColumnType // 默认 text
  width?: string // 列宽（CSS），如 '26%'
  options?: SelectOption[] // select 列选项
  placeholder?: string
}


export interface SelectOption {
  label: string
  value: string
}

export interface FieldDef {
  key: string // 字段名（path 末级）
  path: string[] // 完整 JSON 路径，如 ['modules', 'io_guard_input', 'enabled']
  label: string
  type: FieldType
  desc?: string // 展示说明（来源 CONFIGS.md）
  def: unknown // 默认值（diff 基准；def==未修改 → 不出现在配置包中）
  options?: SelectOption[]
  min?: number
  max?: number
  step?: number
  unit?: string // number 单位后缀
  placeholder?: string
  rows?: number
  clearableTags?: boolean
  preset?: 'base_url' | 'api_key' | 'model'
  columns?: RulesColumn[] // 仅 type === 'rules_table' 使用：可视化规则表列定义
}

export interface SchemaSection {
  title?: string
  fields: FieldDef[]
}

export interface ConfigGroup {
  id: string
  label: string
  desc?: string
  sections: SchemaSection[]
}

// 数值常量：字节换算（1MB = 1048576）
const MB = 1048576

// 通用兜底选项（allow/block/ignore）
const ON_ERROR_OPTIONS: SelectOption[] = [
  { label: 'allow 放行', value: 'allow' },
  { label: 'block 拦截', value: 'block' },
  { label: 'ignore 忽略', value: 'ignore' },
]
const BLOCK_ALLOW_OPTIONS: SelectOption[] = [
  { label: 'block 拦截', value: 'block' },
  { label: 'allow 放行', value: 'allow' },
]

// ---------------------------------------------------------------------------
// 模块 1：IO Guard 检测（io_guard_input / io_guard_context + 检测策略）
//  - 模块开关/兜底：原 modules.yaml，CONFIGS.md §2.1
//  - 检测策略：原 default_policy.json，CONFIGS.md §3
// ---------------------------------------------------------------------------
const ioInputModuleFields: FieldDef[] = [
  // io_guard_input（输入防护：媒体抽取 + 文本检测）
  { key: 'io_guard_input_enabled', path: ['modules', 'io_guard_input', 'enabled'], label: '启用输入检测', type: 'bool', def: true, desc: '模块启停；关闭时路由跳过输入阶段检测' },
  { key: 'io_guard_input_on_error', path: ['modules', 'io_guard_input', 'on_error'], label: '检测异常兜底', type: 'select', def: 'allow', options: ON_ERROR_OPTIONS, desc: '模块抛异常时的兜底动作（IO Guard 默认 allow）' },
  { key: 'io_guard_input_media', path: ['modules', 'io_guard_input', 'media_extraction'], label: '附件媒体抽取', type: 'bool', def: true, desc: '图片/文档附件先抽取文本再走输入检测' },
]

const ioContextModuleFields: FieldDef[] = [
  // io_guard_context（上下文复检）
  { key: 'io_guard_context_enabled', path: ['modules', 'io_guard_context', 'enabled'], label: '启用上下文复检', type: 'bool', def: true, desc: '检索/工具结果净化后执行上下文复检' },
  { key: 'io_guard_context_on_error', path: ['modules', 'io_guard_context', 'on_error'], label: '复检异常兜底', type: 'select', def: 'allow', options: ON_ERROR_OPTIONS },
]

const decisionThresholdFields: FieldDef[] = [
  { key: 'dt_rewrite', path: ['io_guard_policy', 'decision_thresholds', 'rewrite'], label: 'rewrite 阈值', type: 'number', def: 0.55, min: 0, max: 1, step: 0.05, desc: '证据风险分低于此值 → allow' },
  { key: 'dt_block', path: ['io_guard_policy', 'decision_thresholds', 'block'], label: 'block 阈值', type: 'number', def: 0.85, min: 0, max: 1, step: 0.05, desc: '证据风险分高于此值 → block' },
]

const questionDecompFields: FieldDef[] = [
  // 长问题分解
  { key: 'qd_enabled', path: ['io_guard_policy', 'question_decomposition', 'enabled'], label: '启用长问题分解', type: 'bool', def: true, desc: '长问题拆分子查询分别送检' },
  { key: 'qd_min_chars', path: ['io_guard_policy', 'question_decomposition', 'min_chars'], label: '触发分解最小长度', type: 'number', def: 60, min: 10, max: 10000, step: 10, unit: '字符' },
  { key: 'qd_max_parts', path: ['io_guard_policy', 'question_decomposition', 'max_parts'], label: '最大拆分数量', type: 'number', def: 8, min: 1, max: 32 },
  { key: 'qd_strategy', path: ['io_guard_policy', 'question_decomposition', 'strategy'], label: '分解策略', type: 'text', def: 'lossless_heuristic_v1' },
]

const semanticDetectFields: FieldDef[] = [
  // 语义检测
  { key: 'sd_enabled', path: ['io_guard_policy', 'semantic_detection', 'enabled'], label: '启用语义模型检测', type: 'bool', def: true },
  { key: 'sd_backend', path: ['io_guard_policy', 'semantic_detection', 'backend'], label: '检测后端', type: 'text', def: 'stage_char_classifier' },
  { key: 'sd_model_dir', path: ['io_guard_policy', 'semantic_detection', 'model_dir'], label: '模型目录', type: 'text', def: '', placeholder: '如 ../model_heads/io-guard-stage-char-v3', desc: '相对 policy 文件所在目录；留空 = 使用终端本地默认' },
  { key: 'sd_policy_score', path: ['io_guard_policy', 'semantic_detection', 'policy_score'], label: '语义证据计入总分权重', type: 'number', def: 0.9, min: 0, max: 1, step: 0.05 },
  { key: 'sd_threshold', path: ['io_guard_policy', 'semantic_detection', 'detector_threshold'], label: '通用命中阈值', type: 'number', def: 0.55, min: 0, max: 1, step: 0.05 },
  { key: 'sd_thr_input', path: ['io_guard_policy', 'semantic_detection', 'threshold_overrides', 'input'], label: 'input 阶段阈值覆盖', type: 'number', def: 0.6825, min: 0, max: 1, step: 0.0025 },
  { key: 'sd_thr_output', path: ['io_guard_policy', 'semantic_detection', 'threshold_overrides', 'output'], label: 'output 阶段阈值覆盖', type: 'number', def: 0.3, min: 0, max: 1, step: 0.0025 },
  { key: 'sd_thr_content', path: ['io_guard_policy', 'semantic_detection', 'threshold_overrides', 'content'], label: 'content 阶段阈值覆盖', type: 'number', def: 0.7, min: 0, max: 1, step: 0.0025 },
]

const mediaExtractFields: FieldDef[] = [
  // 媒体抽取
  { key: 'me_enabled', path: ['io_guard_policy', 'media_extraction', 'enabled'], label: '附件抽取总开关', type: 'bool', def: true },
  { key: 'me_max_file', path: ['io_guard_policy', 'media_extraction', 'max_file_bytes'], label: '单附件大小上限', type: 'number', def: 15 * MB, min: MB, max: 1024 * MB, step: MB, unit: '字节', desc: '15 MB = 15728640；步进 1 MB' },
  { key: 'me_max_text', path: ['io_guard_policy', 'media_extraction', 'max_text_chars'], label: '抽取文本送检上限', type: 'number', def: 50000, min: 1000, max: 1000000, step: 1000, unit: '字符' },
  { key: 'me_max_attach', path: ['io_guard_policy', 'media_extraction', 'max_attachments'], label: '单请求附件上限', type: 'number', def: 5, min: 1, max: 20 },
  { key: 'me_remote_max', path: ['io_guard_policy', 'media_extraction', 'remote', 'max_bytes'], label: '远程 URL 附件上限', type: 'number', def: 5 * MB, min: MB, max: 512 * MB, step: MB, unit: '字节', desc: '5 MB = 5242880' },
  { key: 'me_remote_timeout', path: ['io_guard_policy', 'media_extraction', 'remote', 'timeout_ms'], label: '远程附件下载超时', type: 'number', def: 8000, min: 500, max: 60000, step: 500, unit: '毫秒' },
  { key: 'me_ocr_enabled', path: ['io_guard_policy', 'media_extraction', 'ocr', 'enabled'], label: '启用 OCR', type: 'bool', def: true },
  { key: 'me_ocr_lang', path: ['io_guard_policy', 'media_extraction', 'ocr', 'lang'], label: 'OCR 语言', type: 'text', def: 'ch' },
  { key: 'me_ocr_device', path: ['io_guard_policy', 'media_extraction', 'ocr', 'device'], label: 'OCR 推理设备', type: 'select', def: 'cpu', options: [{ label: 'CPU', value: 'cpu' }, { label: 'CUDA', value: 'cuda' }] },
  { key: 'me_ocr_max', path: ['io_guard_policy', 'media_extraction', 'ocr', 'max_images'], label: '单请求 OCR 图片上限', type: 'number', def: 4, min: 1, max: 16 },
]

// ---------------------------------------------------------------------------
// 模块 2：Tool Guard（modules.tool_guard 段 + TOOL_GUARD_* env，CONFIGS.md §2.1/§6）
//  api_key 为空时仅允许 localhost 本地端点
// ---------------------------------------------------------------------------
const toolModuleFields: FieldDef[] = [
  { key: 'tool_guard_enabled', path: ['modules', 'tool_guard', 'enabled'], label: '启用 Tool Guard', type: 'bool', def: true, desc: 'LLM 意图匹配裁判 + fetch_guard 抓取前置判定' },
  { key: 'tool_guard_on_error', path: ['modules', 'tool_guard', 'on_error'], label: 'LLM 异常兜底', type: 'select', def: 'block', options: ON_ERROR_OPTIONS, desc: 'LLM 未配置/调用异常时的兜底（默认 block 拦截）' },
]

const judgeLLMFields: FieldDef[] = [
  { key: 'base_url', path: ['modules', 'tool_guard', 'base_url'], label: 'LLM Base URL', type: 'llm_preset', preset: 'base_url', def: 'https://api.deepseek.com/v1', desc: 'OpenAI 兼容端点' },
  { key: 'api_key', path: ['modules', 'tool_guard', 'api_key'], label: 'LLM API Key', type: 'llm_preset', preset: 'api_key', def: '', placeholder: '手动输入要下发的密钥明文(有泄露风险)', desc: '密钥下发有泄露风险；留空 = 不覆盖终端已有密钥。空密钥时仅允许 localhost 本地端点' },
  { key: 'model', path: ['modules', 'tool_guard', 'model'], label: '模型名', type: 'llm_preset', preset: 'model', def: 'deepseek-chat', placeholder: '手动输入自定义模型名', desc: '选分配 = 使用该终端绑定密钥允许的模型' },
  { key: 'timeout_seconds', path: ['modules', 'tool_guard', 'timeout_seconds'], label: '调用超时', type: 'number', def: 30, min: 1, max: 600, unit: '秒', desc: 'LLM 裁判调用超时' },
  { key: 'block_threshold', path: ['modules', 'tool_guard', 'block_threshold'], label: 'block 阈值', type: 'number', def: 0.4, min: 0, max: 1, step: 0.05, desc: '意图匹配分 < 0.4 → block' },
  { key: 'review_threshold', path: ['modules', 'tool_guard', 'review_threshold'], label: 'review 阈值', type: 'number', def: 0.7, min: 0, max: 1, step: 0.05, desc: '0.4 ~ 0.7 → human_review；≥ 0.7 → allow' },
]

const fetchGuardFields: FieldDef[] = [
  { key: 'fetch_enabled', path: ['modules', 'tool_guard', 'fetch_guard', 'enabled'], label: '启用 fetch_guard', type: 'bool', def: true, desc: 'shell/浏览器绕行抓取的前置判定（命中不走 LLM，交 Retrieval Guard 补充判定）' },
  { key: 'shell_tools', path: ['modules', 'tool_guard', 'fetch_guard', 'shell_tools'], label: 'shell 工具名单', type: 'tags', def: ['execute_bash', 'exec', 'bash', 'shell', 'sh', 'terminal', 'cmd', 'powershell'], desc: 'curl/wget 命令扫描范围；可增删工具名' },
  { key: 'url_tools', path: ['modules', 'tool_guard', 'fetch_guard', 'url_tools'], label: 'URL 导航工具', type: 'tags', def: ['browser'], desc: 'URL 导航工具名单' },
]

// ---------------------------------------------------------------------------
// 模块 3：Retrieval Guard（modules.retrieval_guard 段 + retrieval.* 参数，
//  CONFIGS.md §2.1/§5：URL 白名单 + B 层注入 + C 层包装）
// ---------------------------------------------------------------------------
const retrievalModuleFields: FieldDef[] = [
  { key: 'retrieval_enabled', path: ['modules', 'retrieval_guard', 'enabled'], label: '启用 Retrieval Guard', type: 'bool', def: true, desc: 'URL 白名单 + 注入检测 + 提示词包装总开关' },
  { key: 'retrieval_on_error', path: ['modules', 'retrieval_guard', 'on_error'], label: '异常兜底', type: 'select', def: 'allow', options: ON_ERROR_OPTIONS },
  { key: 'retrieval_model_path', path: ['modules', 'retrieval_guard', 'model_path'], label: 'PIGuard 模型目录', type: 'text', def: '', placeholder: '如 clawguard/modules/retrieval_guard/models/PIGuard', desc: '相对 Clawguard 项目根；留空 = 使用客户端本地默认（不写入配置包）' },
  { key: 'guard_a', path: ['modules', 'retrieval_guard', 'guards', 'A'], label: 'A 层 URL 白名单', type: 'bool', def: true },
  { key: 'guard_b', path: ['modules', 'retrieval_guard', 'guards', 'B'], label: 'B 层 PIGuard 注入检测', type: 'bool', def: true },
  { key: 'guard_c', path: ['modules', 'retrieval_guard', 'guards', 'C'], label: 'C 层提示词包装', type: 'bool', def: true },
]

const retrievalWhitelistFields: FieldDef[] = [
  // A 层
  { key: 'wl_trusted', path: ['retrieval', 'whitelist', 'trusted'], label: '白名单（trusted）', type: 'tags', def: [], clearableTags: true, placeholder: '如 *.wikipedia.org', desc: 'fnmatch 通配，按回车添加；白名单外一律 block。列表为空 = 不覆盖终端本地白名单' },
  { key: 'wl_blocked', path: ['retrieval', 'whitelist', 'blocked'], label: '黑名单（blocked）', type: 'tags', def: [], clearableTags: true, placeholder: '如 pastebin.com', desc: '显式黑名单补充记录；列表为空 = 不覆盖' },
]

const retrievalInjectionFields: FieldDef[] = [
  // B 层
  { key: 'inj_threshold', path: ['retrieval', 'injection', 'threshold'], label: '注入拦截阈值', type: 'number', def: 0.95, min: 0, max: 1, step: 0.01, desc: 'PIGuard 注入概率阈值（越高越严格）' },
  { key: 'inj_window', path: ['retrieval', 'injection', 'window_size'], label: '滑窗大小', type: 'number', def: 400, min: 50, max: 512, step: 10, unit: 'token', desc: '≤ 模型 512 限制' },
  { key: 'inj_step', path: ['retrieval', 'injection', 'step'], label: '滑窗步长', type: 'number', def: 200, min: 10, max: 512, step: 10, unit: 'token' },
]

const retrievalPromptWrapFields: FieldDef[] = [
  // C 层
  { key: 'pw_random', path: ['retrieval', 'prompt_wrap', 'random_length'], label: '随机序列长度', type: 'number', def: 10, min: 1, max: 64, desc: 'Spotlighting 随机序列长度' },
  { key: 'pw_self_reminder', path: ['retrieval', 'prompt_wrap', 'self_reminder'], label: '行为契约文案', type: 'textarea', def: '', rows: 5, placeholder: '数据前植入的行为契约文案（英文段落）', desc: '留空 = 不覆盖终端本地文案' },
  { key: 'pw_post', path: ['retrieval', 'prompt_wrap', 'post_prompting'], label: '后置指令文案', type: 'textarea', def: '', rows: 5, placeholder: '数据后的 recency-bias 指令', desc: '留空 = 不覆盖终端本地文案' },
]

// ---------------------------------------------------------------------------
// 模块 4：访问控制（modules.access_control 段 + CLAWGUARD_* env + 规则文件，
//  CONFIGS.md §2.1/§4：users.txt / resources.txt / 风险联动与隔离）
// ---------------------------------------------------------------------------
const accessModuleFields: FieldDef[] = [
  { key: 'access_enabled', path: ['modules', 'access_control', 'enabled'], label: '启用访问控制', type: 'bool', def: true, desc: 'RBAC/MAC + 风险联动 + 隔离' },
  { key: 'access_on_error', path: ['modules', 'access_control', 'on_error'], label: '异常兜底', type: 'select', def: 'block', options: ON_ERROR_OPTIONS },
]

const accessPolicyFields: FieldDef[] = [
  { key: 'mode', path: ['access', 'mode'], label: '策略模型', type: 'select', def: 'rbac', options: [
    { label: 'RBAC 角色访问', value: 'rbac' },
    { label: 'MAC 强制访问', value: 'mac' },
    { label: 'Hybrid 混合', value: 'hybrid' },
  ], desc: '对应 CLAWGUARD_MODE' },
  { key: 'block_unknown', path: ['access', 'block_unknown_users'], label: '拦截未知用户', type: 'bool', def: false, desc: '未在规则文件中的用户是否直接拦截' },
  { key: 'risk_link', path: ['access', 'risk_link_enabled'], label: '审计风险联动', type: 'bool', def: true, desc: '关闭则退化为纯 RBAC 判定（对应 CLAWGUARD_AC_RISK_LINK）' },
  { key: 'risk_window', path: ['access', 'risk_window_seconds'], label: '风险滑窗时长', type: 'number', def: 300, min: 30, max: 86400, step: 30, unit: '秒' },
  { key: 'risk_threshold', path: ['access', 'risk_threshold'], label: '高风险事件阈值', type: 'number', def: 0.6, min: 0, max: 1, step: 0.05, desc: '单事件风险分 ≥ 此值计为高风险事件' },
  { key: 'probe_count', path: ['access', 'risk_probe_block_count'], label: '试探标记拦截数', type: 'number', def: 3, min: 1, max: 100, desc: '窗内拦截 ≥ 此数 → probe_likely 试探标记' },
  { key: 'escalation', path: ['access', 'risk_escalation_threshold'], label: '防线升级阈值', type: 'number', def: 0.5, min: 0, max: 1, step: 0.05, desc: '综合风险 ≥ 此值开始动态提升所需等级' },
]

const accessQuarantineFields: FieldDef[] = [
  { key: 'quarantine', path: ['access', 'quarantine_enabled'], label: '启用隔离', type: 'bool', def: true },
  { key: 'q_block_count', path: ['access', 'quarantine_block_count'], label: '隔离触发拦截数', type: 'number', def: 8, min: 1, max: 500, desc: '5 分钟窗内拦截 ≥ 此值 → 隔离' },
  { key: 'q_risk', path: ['access', 'quarantine_risk_threshold'], label: '隔离风险阈值', type: 'number', def: 0.85, min: 0, max: 1, step: 0.05, desc: 'probe 标记且风险 ≥ 此值 → 隔离' },
  { key: 'q_long_window', path: ['access', 'quarantine_long_window_seconds'], label: '长窗时长', type: 'number', def: 3600, min: 60, max: 604800, step: 60, unit: '秒', desc: '1 小时长窗评估' },
  { key: 'q_long_count', path: ['access', 'quarantine_long_window_count'], label: '长窗触发拦截数', type: 'number', def: 15, min: 1, max: 1000, desc: '长窗内拦截 ≥ 此值 → 隔离' },
]

// 规则文件（users.txt / resources.txt，CONFIGS.md §4.1）；类型 rules_table：可视化表格行编辑，
// 底层值仍是文本原文（空串 = 不覆盖终端本地文件），行文本 ↔ 表格互转见 rulesText.ts
const LEVEL_OPTIONS: SelectOption[] = [
  { label: 'public 公开', value: 'public' },
  { label: 'internal 内部', value: 'internal' },
  { label: 'secret 机密', value: 'secret' },
  { label: 'top_secret 绝密', value: 'top_secret' },
]
const INHERIT_OPTIONS: SelectOption[] = [
  { label: 'flat 平铺', value: 'flat' },
  { label: 'inherit 继承', value: 'inherit' },
  { label: 'override 覆盖', value: 'override' },
]

const accessRulesFields: FieldDef[] = [
  {
    key: 'user_level', path: ['access_user', 'level'], label: '绑定用户默认等级（仅改本终端用户）', type: 'select', def: '',
    options: LEVEL_OPTIONS, placeholder: '不修改（保持终端现状）',
    desc: '只修改本终端绑定用户的默认等级（四档：公开 / 内部 / 机密 / 绝密），不触碰 users.txt 其他用户与其他行；留空 = 不修改，特例列原样保留。',
  },
  {
    key: 'resources', path: ['access_rules', 'resources'], label: '资源规则（resources.txt）', type: 'rules_table', def: '',
    desc: '可视化编辑：每行 = 路径模式 | 所需等级 | 继承模式。模式前缀三类：tool: 工具、db: 数据库、裸路径为文件系统（Windows/Linux fnmatch 通配）。删除全部行 = 不覆盖终端本地 resources.txt',
    columns: [
      { key: 'pattern', label: '路径 / 资源模式', type: 'text', width: '36%', placeholder: '如 tool:web_fetch、db:secret_db、C:\\Users\\*、/etc/*' },
      { key: 'level', label: '所需等级', type: 'select', width: '14%', options: LEVEL_OPTIONS, placeholder: '选择等级' },
      { key: 'inherit', label: '继承模式', type: 'select', width: '18%', options: INHERIT_OPTIONS, placeholder: 'flat（默认）' },
    ],
  },
]

// ---------------------------------------------------------------------------
// 模块 5：审计（modules.audit 段 + 审计存储策略，CONFIGS.md §2.1/§3）
//  audit.content_storage 等策略键位于 io_guard_policy.audit.*（default_policy.json）
// ---------------------------------------------------------------------------
const auditModuleFields: FieldDef[] = [
  { key: 'audit_enabled', path: ['modules', 'audit', 'enabled'], label: '启用审计', type: 'bool', def: true },
  { key: 'audit_on_error', path: ['modules', 'audit', 'on_error'], label: '审计异常处理', type: 'select', def: 'ignore', options: ON_ERROR_OPTIONS, desc: '审计异常不阻断业务（ignore）' },
]

const auditStorageFields: FieldDef[] = [
  { key: 'audit_storage', path: ['io_guard_policy', 'audit', 'content_storage'], label: '审计正文存储', type: 'text', def: 'sanitized', desc: '审计正文存储策略（默认净化后存储）' },
  { key: 'audit_chars', path: ['io_guard_policy', 'audit', 'max_content_chars'], label: '审计正文截断上限', type: 'number', def: 2000, min: 100, max: 100000, step: 100, unit: '字符' },
]

// ---------------------------------------------------------------------------
// 模块 6：沙箱（modules.yaml sandbox 段）
// ---------------------------------------------------------------------------
const sandboxModuleFields: FieldDef[] = [
  { key: 'sandbox_enabled', path: ['modules', 'sandbox', 'enabled'], label: '启用沙箱', type: 'bool', def: true },
  { key: 'sandbox_mode', path: ['modules', 'sandbox', 'mode'], label: '接入方式', type: 'select', def: 'mcp', options: [{ label: 'MCP', value: 'mcp' }] },
  { key: 'sandbox_url', path: ['modules', 'sandbox', 'url'], label: 'Sandbox MCP 地址', type: 'text', def: 'http://127.0.0.1:9876', desc: '与沙箱服务端口约定一致（默认 9876）' },
]

// ---------------------------------------------------------------------------
// 模块 7：人工复核（modules.yaml human_review 段）
// ---------------------------------------------------------------------------
const humanReviewModuleFields: FieldDef[] = [
  { key: 'unsupported_action', path: ['modules', 'human_review', 'unsupported_action'], label: '复核不支持动作的兜底', type: 'select', def: 'block', options: BLOCK_ALLOW_OPTIONS, desc: '收到不支持的人工复核动作时的兜底' },
]

// ---------------------------------------------------------------------------
// 模块 8：OpenClaw 接入集成（原 openclaw.config 插件段，CONFIGS.md §9）
// ---------------------------------------------------------------------------
const integrationFields: FieldDef[] = [
  { key: 'clawguard_url', path: ['integration', 'clawguard_url'], label: 'Clawguard API 地址', type: 'text', def: 'http://127.0.0.1:8000', desc: 'OpenClaw 插件访问本机 Clawguard 服务的地址' },
  { key: 'api_token_env', path: ['integration', 'api_token_env'], label: 'API 令牌环境变量名', type: 'text', def: 'CLAWGUARD_API_TOKEN', desc: '令牌本身不进配置文件，仅指定读取的环境变量名' },
  { key: 'timeout_ms', path: ['integration', 'timeout_ms'], label: 'HTTP 调用超时', type: 'number', def: 30000, min: 1000, max: 300000, step: 1000, unit: '毫秒' },
  { key: 'fail_mode', path: ['integration', 'fail_mode'], label: '插件故障模式', type: 'select', def: 'closed', options: [
    { label: 'closed 故障即拦截', value: 'closed' },
    { label: 'open 故障即放行', value: 'open' },
  ], desc: '插件自身故障时的安全策略' },
  { key: 'media_check', path: ['integration', 'enable_media_check'], label: '附件送检', type: 'bool', def: true, desc: '是否启用附件送 Clawguard 检测' },
  { key: 'media_root', path: ['integration', 'media_root'], label: '附件根目录', type: 'text', def: '', placeholder: '空 = 按协议字段', desc: '留空 = 使用协议默认（不写入配置包）' },
  { key: 'protected_tools', path: ['integration', 'protected_tools'], label: '回检保护工具', type: 'tags', def: ['web_fetch', 'web_search'], desc: '内容回检保护的工具名单，按回车添加' },
]

// ---------------------------------------------------------------------------
// 导出：分组定义 + 默认树 + schema_version
//  分组 = 模块边界；模块的"启停/异常兜底"开关与其参数同组
// ---------------------------------------------------------------------------
export const CONFIG_GROUPS: ConfigGroup[] = [
  {
    id: 'io_guard', label: 'IO Guard 检测', desc: '输入/上下文检测模块 · 检测策略',
    sections: [
      { title: '输入检测模块', fields: ioInputModuleFields },
      { title: '上下文复检模块', fields: ioContextModuleFields },
      { title: '决策阈值', fields: decisionThresholdFields },
      { title: '长问题分解', fields: questionDecompFields },
      { title: '语义模型检测', fields: semanticDetectFields },
      { title: '附件媒体抽取', fields: mediaExtractFields },
    ],
  },
  {
    id: 'tool_guard', label: 'Tool Guard', desc: '模块启停 · LLM 意图裁判 · fetch_guard',
    sections: [
      { title: '模块启停与异常兜底', fields: toolModuleFields },
      { title: '裁判 LLM 与判定阈值', fields: judgeLLMFields },
      { title: 'fetch_guard 抓取前置判定', fields: fetchGuardFields },
    ],
  },
  {
    id: 'retrieval_guard', label: 'Retrieval Guard', desc: '模块开关 · A/B/C 层参数',
    sections: [
      { title: '模块启停与层开关', fields: retrievalModuleFields },
      { title: 'A 层 URL 白/黑名单', fields: retrievalWhitelistFields },
      { title: 'B 层注入检测', fields: retrievalInjectionFields },
      { title: 'C 层提示词包装', fields: retrievalPromptWrapFields },
    ],
  },
  {
    id: 'access_control', label: '访问控制', desc: '模块开关 · 策略与风险 · 规则文件',
    sections: [
      { title: '模块启停与异常兜底', fields: accessModuleFields },
      { title: '策略模型与风险联动', fields: accessPolicyFields },
      { title: '隔离', fields: accessQuarantineFields },
      { title: '绑定用户等级 / 资源规则（resources.txt）', fields: accessRulesFields },
    ],
  },
  {
    id: 'audit', label: '审计', desc: '审计模块开关 · 审计存储策略',
    sections: [
      { title: '模块启停与异常兜底', fields: auditModuleFields },
      { title: '审计存储策略', fields: auditStorageFields },
    ],
  },
  {
    id: 'sandbox', label: '沙箱', desc: '沙箱接入',
    sections: [{ title: '沙箱接入', fields: sandboxModuleFields }],
  },
  {
    id: 'human_review', label: '人工复核', desc: '复核兜底策略',
    sections: [{ title: '兜底动作', fields: humanReviewModuleFields }],
  },
  {
    id: 'integration', label: 'OpenClaw 集成', desc: 'Clawguard 接入插件参数',
    sections: [{ title: '插件接入', fields: integrationFields }],
  },
]

/** 配置包版本号（客户端据此识别 schema，未知版本应拒绝应用） */
export const CONFIG_SCHEMA_VERSION = 1

/** 由字段定义自动构建的默认树（diff 基准：与默认相同的不写入配置包） */
export function buildDefaultTree(fields: FieldDef[]): Record<string, unknown> {
  const tree: Record<string, unknown> = {}
  for (const f of fields) {
    setByPath(tree, f.path, f.def)
  }
  return tree
}

/** 全部字段拍平（含所属分组信息，供"恢复默认/仅含修改项统计"使用） */
export function flattenFields(): { group: ConfigGroup; field: FieldDef }[] {
  const out: { group: ConfigGroup; field: FieldDef }[] = []
  for (const g of CONFIG_GROUPS) {
    for (const s of g.sections) {
      for (const f of s.fields) out.push({ group: g, field: f })
    }
  }
  return out
}

export const ALL_FIELDS = flattenFields()

// ---------------------------------------------------------------------------
// 通用路径工具（编辑/合并/diff 共用）
// ---------------------------------------------------------------------------
export function getByPath(obj: unknown, path: string[]): unknown {
  let cur: unknown = obj
  for (const seg of path) {
    if (cur === null || typeof cur !== 'object') return undefined
    cur = (cur as Record<string, unknown>)[seg]
  }
  return cur
}

export function setByPath(obj: Record<string, unknown>, path: string[], value: unknown): void {
  let cur = obj
  for (let i = 0; i < path.length - 1; i++) {
    const seg = path[i]
    if (typeof cur[seg] !== 'object' || cur[seg] === null) cur[seg] = {}
    cur = cur[seg] as Record<string, unknown>
  }
  cur[path[path.length - 1]] = value
}

export function unsetByPath(obj: Record<string, unknown>, path: string[]): void {
  let cur = obj
  for (let i = 0; i < path.length - 1; i++) {
    const seg = path[i]
    if (typeof cur[seg] !== 'object' || cur[seg] === null) return
    cur = cur[seg] as Record<string, unknown>
  }
  delete cur[path[path.length - 1]]
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** 深拷贝普通对象/数组/标量（剥离 reactive 代理与共享引用） */
function deepClone(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(deepClone)
  if (isPlainObject(v)) {
    const out: Record<string, unknown> = {}
    for (const [k, val] of Object.entries(v)) out[k] = deepClone(val)
    return out
  }
  return v
}

/** 递归深合并：先深拷贝 dst（绝不共享/修改入参），再对象逐键合并；标量/数组以 src 覆盖（dst 保留 src 未含的键，用于保留未知扩展字段） */
export function deepMerge(dst: Record<string, unknown>, src: unknown): Record<string, unknown> {
  const out = deepClone(dst) as Record<string, unknown>
  if (!isPlainObject(src)) return out
  for (const [k, v] of Object.entries(src)) {
    if (isPlainObject(v) && isPlainObject(out[k])) {
      out[k] = deepMerge(out[k] as Record<string, unknown>, v)
    } else {
      out[k] = deepClone(v)
    }
  }
  return out
}

/** 与默认树对比，产出 partial 配置包（对象逐层递归；仅保留 != 默认的键；默认树没有的扩展键原样保留） */
export function diffToPartial(defaults: Record<string, unknown>, model: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(model)) {
    const dv = defaults[k]
    if (dv === undefined) {
      out[k] = v // 未知扩展字段：保留
      continue
    }
    if (isPlainObject(v) && isPlainObject(dv)) {
      const sub = diffToPartial(dv, v)
      if (Object.keys(sub).length > 0) out[k] = sub
      continue
    }
    if (!deepEqual(v, dv)) out[k] = v
  }
  return out
}

export function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false
    return a.every((x, i) => deepEqual(x, b[i]))
  }
  if (isPlainObject(a) && isPlainObject(b)) {
    const ka = Object.keys(a)
    const kb = Object.keys(b)
    if (ka.length !== kb.length) return false
    return ka.every((k) => deepEqual(a[k], b[k]))
  }
  return false
}
