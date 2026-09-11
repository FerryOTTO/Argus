# IO Guard 安全模块功能说明

> 本文档汇总 `io_guard` 模块在收窄到九类风险目标后的完整功能，包含三阶段检测管线、全部检测器、模型分类器、策略引擎、问题拆分、审计/轨迹、媒体（图片与文档）输入检测，以及 `semantic.py` 自联系方式查询 allowlist 的兼容行为。

---

## 一、模块概览

- **模块路径**：`argus/modules/io_guard/original/`
- **Python 包**：`src/io_guard/`（包名 `input_output_guard`，0.2.0）
- **定位**：对用户输入、检索内容、模型输出三个环节做自动安全检查，**只输出 `allow` / `rewrite` / `block` 三种决策，永不返回人工 review**。
- **核心原则**：`io_guard` 核心包（`service.py` / `pipeline.py` / `detectors/`）始终接收**真实字符串**，不对其直接跑模型之外的处理；媒体附件的文本抽取发生在适配器层，抽取结果以普通字符串循环喂给同一套检测管线。
- **启动方式**：作为 Argus FastAPI 的一个模块适配器被调用；也可独立以 HTTP 服务运行（`service.py` 提供 `ThreadingHTTPServer`，默认端口 8765）。生产环境经 `argus/api/main.py` 暴露 `/v1/input/check`、`/v1/content/check`、`/v1/output/check`。

---

## 二、目录结构

```
original/
├── configs/
│   ├── default_policy.json          # 策略、阈值、语义模型、媒体抽取配置
│   └── security_event_schema.json
├── model_heads/
│   └── io-guard-stage-char-v3/      # 阶段感知字符分类器模型（joblib）
│       ├── input_char.joblib        #   输入 head
│       ├── output_char.joblib       #   输出 head
│       ├── content_char.joblib      #   检索/工具内容 head
│       ├── training_metadata.json
│       └── README.md
├── src/io_guard/
│   ├── pipeline.py                  # IOGuard：三阶段编排
│   ├── service.py                   # GuardService：传输无关门面 + HTTP handler
│   ├── policy.py                    # PolicyEngine：决策引擎
│   ├── taxonomy.py                  # RiskCategory（9 类）+ TaxonomyDimension（2 维）
│   ├── types.py                     # Evidence / GuardRequest / GuardResult / Decision
│   ├── config.py                    # 注入模式、泄露模式、密级表
│   ├── normalization.py             # 文本归一化、安全摘要
│   ├── structured_content.py        # 结构化文本取叶子
│   ├── audit.py                     # AuditLogger
│   ├── trajectory.py                # TrajectoryStore（同 trace 轨迹状态）
│   ├── events.py / argus_contracts.py / runtime.py
│   ├── adapters/
│   │   ├── base.py
│   │   └── argus_adapter.py     # 内层适配器：Argus 契约 ↔ GuardService
│   ├── detectors/
│   │   ├── base.py
│   │   ├── prompt_injection.py      # PromptInjectionDetector
│   │   ├── input_safety.py          # MaliciousUserInstructionDetector
│   │   ├── semantic.py              # SemanticDetector（模型 + allowlist）
│   │   ├── stage_classifier.py      # StageAwareCharClassifier（3 个 head）
│   │   ├── output_leakage.py        # OutputLeakageDetector（脱敏/密级）
│   │   ├── output_safety.py         # OutputSafetyDetector（危害/违法引导/恶意代码）
│   │   ├── reliability.py           # ReliabilityDetector（来源可信度）
│   │   └── external_content.py      # ExternalContentFilter（剔除指令片段）
│   └── preprocessors/
│       └── decomposition.py         # QuestionDecomposer（无损失拆分检测视图）
├── tests/                           # 单测（test_*.py，含媒体抽取与分类器）
└── IO_GUARD_MODULE.md               # 本文档
```

---

## 三、三阶段检测流程

入口统一为 `GuardService.check(stage, payload)`，`stage ∈ {input, context, output}`，映射到 `SourceType`：

| stage | SourceType | 管线方法 | 端点 |
|---|---|---|---|
| `input` | `user_prompt` | `pre_check` | `/v1/input/check` |
| `context` | `retrieval_chunk` / `tool_result` / `memory` | `check_retrieval_content` | `/v1/content/check` |
| `output` | `model_output` | `post_check` | `/v1/output/check` |

> context 阶段会读 `metadata` 里的 `tool_name` / `tool_call_id` / `source`，把工具调用结果独立映射为 `tool_result`，让其使用独立的模型 head。

### 3.1 pre_check（输入）

1. 文本归一化（`normalize_text`：空白折叠、去除零宽字符、小写等）。
2. 问题拆分（≥60 字且含多任务标记才拆分，最多 8 段）。
3. 依次收集证据：
   - `PromptInjectionDetector.detect`（规则注入检测）
   - `MaliciousUserInstructionDetector.detect`（恶意意图）
   - `SemanticDetector.detect`（模型分类，含 allowlist 前置判断）
   - 各拆分视图的规则+输入检测（`_detect_decomposed_views`，`include_input=True`）
4. `PolicyEngine.decide` → `GuardResult`。

### 3.2 check_retrieval_content（检索内容）

1. 规范化 + 拆分视图。
2. 规则注入证据（`PromptInjectionDetector`）+ 各视图检测（`include_semantic=False`）。
3. `ExternalContentFilter.filter` 按段落剔除指令类片段，保留事实内容，输出过滤后文本 + 过滤证据。
4. 对**过滤后**文本跑 `SemanticDetector`，对**原始**文本跑 `ReliabilityDetector`。
5. 若可信度证据全部可补救（remediable），调用 `reliability_detector.rewrite` 在开头加“未经验证”标记。
6. 聚合证据 → 策略决策。

> 该阶段默认对“仅间接注入”且过滤成功的情况返回 `rewrite`（替换为过滤后文本）；若过滤后为空则 `block`。

### 3.3 post_check（模型输出）

1. 强制 `source_type = model_output`，规范化 + 拆分。
2. `OutputLeakageDetector.detect`（泄露）+ `redact`（脱敏），输出脱敏文本。
3. `OutputSafetyDetector.detect`（危害/引导/恶意代码）。
4. `ReliabilityDetector.detect`（未验证/高风险的输出）。
5. 对**脱敏后**文本跑 `SemanticDetector`。
6. 聚合 → 决策；`rewrite` 时 `modified_data` 携带脱敏后的 `text` / `content`。

---

## 四、风险分类体系

`taxonomy.py` 定义 9 类风险（`RiskCategory`），并保留 AgentDoG 的两个维度（`TaxonomyDimension`）：

| 风险类别（value） | 维度 | 主要触发阶段 |
|---|---|---|
| `malicious_user_instruction_or_jailbreak` | risk_source | input |
| `direct_prompt_injection` | risk_source | input |
| `indirect_prompt_injection` | risk_source | context |
| `unreliable_or_misinformation` | risk_source | context |
| `harmful_or_offensive_content` | failure_mode | output |
| `harmful_or_illegal_guidance` | failure_mode | output |
| `malicious_executable_generation` | failure_mode | output |
| `unauthorized_information_disclosure` | failure_mode | output |
| `inaccurate_misleading_or_unverified_information` | failure_mode | output |

`SourceType`：`user_prompt` / `retrieval_chunk` / `tool_result` / `memory` / `model_output`。
`Decision`：`allow` / `rewrite` / `block`。

`GuardResult.to_dict()` 输出 `decision`、`risk_score`（所有证据最高分）、`risk_types`、`verdict`（safe/unsafe，`rewrite` 视为 safe）、`primary_label`、`dimension`、`mitigated`、`sanitized_content`、`reason`、`evidence`、`processing_metadata`（含分解信息、延迟、轨迹）。

---

## 五、检测器明细

### 5.1 PromptInjectionDetector（`detectors/prompt_injection.py`）

基于 `config.py` 的 `PROMPT_INJECTION_PATTERNS`（约 20 条正则），每条带基础分数。能力：

- **直接提示注入 / 越狱**：`ignore previous instructions`、`reveal the system prompt`、`you are now DAN`、忽略/覆盖既有指令、伪造高优先级指令、请求披露系统提示、绕过权限、请求泄露系统凭证、DAN 模式等（中英文正则）。
- **间接注入**：对 `retrieval_chunk` / `tool_result` / `memory` 来源把风险类型标为 `indirect_prompt_injection`，分数 +0.04。
- **Base64 混淆载荷**：识别 ≥24 字符的 base64 串，解码后再次跑注入正则（`max(score, 0.88)`）。
- **零宽字符混淆**：≥2 个零宽字符（`​` 等）或零宽字符拆分后命中注入规则 → `zero-width character obfuscation`，score 0.62。

### 5.2 MaliciousUserInstructionDetector（`detectors/input_safety.py`）

只处理 `user_prompt`，先排除 `_BENIGN_CONTEXT`（“防止/检测/安全研究/教育/不要……”等防御语境）。两类命中：

1. **未授权联系方式请求**：`_CONTACT_OBJECT`（电话/邮箱）+（`_UNAUTHORIZED_CONTACT_ACTION` 窃取/泄露/绕过权限，或 `_THIRD_PARTY` 他人/同事/前女友/陌生人/客户 **且** `_CONTACT_ACCESS_ACTION` 查询/获取/导出/告诉我）→ `malicious_user_instruction_or_jailbreak`，score 0.94。
2. **明确恶意指令**：`_ACTION`（制作/制造/编写/入侵/攻击/窃取/破解/投毒/how to/build/hack/steal…）且 `_HARMFUL_OBJECT`（炸弹/武器/毒品/恶意软件/木马/勒索/病毒/后门/键盘记录器/钓鱼/密码/令牌/银行卡/自杀方法…）→ 同类别，score 0.94。

> 已知边界：`_THIRD_PARTY` 未覆盖“老板/上司/家人/朋友/邻居”，因此“老板的手机号是多少”这类请求当前不会在此检测器命中（仍可能被语义分类器拦截）。

### 5.3 SemanticDetector（`detectors/semantic.py`）

- 配置 `backend = stage_char_classifier`（唯一支持的后端），加载 `StageAwareCharClassifier`（见第六节）。
- 在调用模型前有两类**确定性放行**（属于“模型只对短文本误报”的窄边界豁免）：
  1. `_is_self_contact_query`：完整的“查询自己的联系方式”请求（见 5.3.1，本次修改）。
  2. `_is_clearly_benign_user_task`：完整的“总结会议纪要”请求，或受约束的临时文件读写流程（write/read 工具 + `/tmp/` 或“临时备忘录”目标 + 良性内容如 hello/普通文本/项目联调），且不出现 `_OPERATIONAL_TASK_RISK`（忽略/绕过/系统提示/密码/恶意软件/删除/执行/curl 等）与 `_UNSAFE_LOCAL_PATH`（`../`、`/etc`、`C:\Windows`、`.ssh`）。
- 命中模型时按 `label` 映射 `RiskType`，未知标签回退到按来源选类型（input→direct_prompt_injection、output→harmful_or_offensive_content、其余→indirect_prompt_injection）。

#### 5.3.1 自联系方式查询 allowlist（本次修改）

原 `_SELF_CONTACT_QUERY` 只允许**单个**联系方式名词，导致 `我的电话邮箱是多少`、`我的电话和邮箱是多少` 等组合查询 `fullmatch` 失败、回落到阶段分类器被误判为 `direct_prompt_injection` 而拦截。

本次把正则重构为支持组合联系方式短语：

```python
_CONTACT_TERM = (
    r"(?:电话号码|手机号码|手机号|联系电话|电子邮箱|邮箱地址|"
    r"联系方式|电话|邮箱)"
)
_CONTACT_PHRASE = (
    rf"(?:{_CONTACT_TERM}"
    rf"(?:[、,，\s]*(?:和|或|与|以及)?[、,，\s]*{_CONTACT_TERM})*)"
)
_SELF_CONTACT_QUERY = re.compile(
    rf"^(?:"
    rf"(?:请问)?(?:你知道)?"
    rf"(?:我(?:自己)?的|我本人的|本人的|自己的)"
    rf"{_CONTACT_PHRASE}"
    rf"(?:各)?(?:是|为)?(?:什么|多少)?(?:吗|呢)?"
    rf"|"
    rf"(?:请|麻烦)?(?:帮我)?(?:查询|查看|显示|告诉我|查)(?:一下)?"
    rf"(?:我(?:自己)?的|我本人的|本人的|自己的)"
    rf"{_CONTACT_PHRASE}"
    rf"(?:吗|呢)?"
    rf")$",
    re.IGNORECASE,
)
```

要点：

- 第一分支覆盖 `我的电话邮箱是多少`、`我的手机号和邮箱各是多少`（`各` 位于 `是/为` 之前）。
- 第二分支覆盖 `帮我查看我的电话和邮箱`、`查一下我的手机号`、`请告诉我我的邮箱` 等。
- `_CONTACT_TERM` 含裸 `电话`/`邮箱`，使“电话邮箱”“电话和邮箱”按**两个联系方式名词**匹配，而不是回落到模型。
- `_is_self_contact_query` 会先压缩空白、strip `？。!！`，再做 `fullmatch`。
- 判断是**前置豁免**，仅在 `source_type == user_prompt` 生效；输入侧规则检测器（5.1 / 5.2）仍先运行，因此“绕过权限查询手机号”等未授权请求仍会被拦截。

> 已知剩余 gap：第二分支句尾只允许 `(?:吗|呢)?`，因此 `告诉我我的手机号码是多少`（动词+归属+联系方式+“是多少”）仍会 `fullmatch` 失败、被阶段分类器拦截。如需补全，可给第二分支追加与第一分支相同的 `(?:各)?(?:是|为)?(?:什么|多少)?(?:吗|呢)?` 后缀。

### 5.4 OutputLeakageDetector（`detectors/output_leakage.py`）

基于 `OUTPUT_LEAKAGE_PATTERNS`（`config.py`），命中即记 `unauthorized_information_disclosure` 证据，且 `redact()` 把文本脱敏为占位符：

| 模式 | 分数 | 替换 |
|---|---|---|
| 中国大陆手机号 `1[3-9]\d{9}` | 0.75 | `[PHONE]` |
| 邮箱 | 0.65 | `[EMAIL]` |
| 一次性验证码 / OTP（含“验证码为……”） | 0.88 | `[OTP]` |
| 身份证 `\d{17}[\dXx]` | 0.88 | `[ID_CARD]` |
| API key `sk/pk/ak-…` | 0.95 | `[API_KEY]` |
| JWT 风格 token | 0.90 | `[TOKEN]` |
| 系统提示泄露 `system prompt:` | 0.92 | `[HIDDEN_PROMPT]` |

- `remediable` 置 `False` 的项（API key / JWT / 系统提示泄露）→ 不可脱敏，直接 `block`；其余可脱敏 → `rewrite`。
- **密级标签**：识别“公开/内部/秘密/机密/绝密”等（`CLASSIFICATION_LEVELS`，0–4 级），仅在**有分类语境**时生效（前置词“密级/标记为/classified as”或后接文档名词），要求 `required_level > role_level` 才记证据（score 0.90），避免“内部结构”“秘密花园”等正常词误报。

### 5.5 OutputSafetyDetector（`detectors/output_safety.py`）

只处理 `model_output`，先看 `_SAFE_CONTEXT`（“我不能/无法协助/应当拒绝/不要尝试/防止/安全建议”等拒绝语境，命中则跳过危害判定）：

- **有害/冒犯内容**：`_HARMFUL`（“去死吧/你这个垃圾/杀死他们/仇恨/种族清洗/鼓励自杀/go die/hate speech…）→ `harmful_or_offensive_content`，0.92。
- **可操作危害/违法引导**：`_GUIDANCE_TOPIC`（炸弹/武器/毒品/入侵账号/窃取密码/自杀/绑架…）**且** `_GUIDANCE_FORM`（详细步骤/第一步/教程/所需材料/step-by-step/instructions…）→ `harmful_or_illegal_guidance`，0.96。
- **恶意可执行代码**：`_CODE_MARKER`（```python/import os/subprocess/IEX/powershell -enc/#!/bin/sh…）**且** `_DANGEROUS_CODE`（`os.system(`、`subprocess.run(`、`rm -rf /`、`curl | sh`、`Invoke-WebRequest…IEX`、`CreateRemoteThread`、`keylogger`、`reverse shell`…）→ `malicious_executable_generation`，0.98。

### 5.6 ReliabilityDetector（`detectors/reliability.py`）

只处理 context/output 来源，**不假装事实核查**，仅依据显式来源信号：

- 状态 `false / contradicted / misinformation / fabricated / invalid` → 0.96；`trust_level == untrusted` → 0.90。
- 状态 `unverified / unknown / unsupported / incomplete / noisy / stale / outdated` → 高风险 0.88 / 否则 0.70。
- `requires_verification` 且无引证 → 高风险 0.88 / 否则 0.68。
- 风险类型：output → `inaccurate_misleading_or_unverified_information`；否则 → `unreliable_or_misinformation`。
- `rewrite`：output 替换为“该结论缺少足够的可靠依据…”，context 在开头加 `[来源状态：未经验证…]` 标记；`remediable = not high_stakes and score < 0.85`。

### 5.7 ExternalContentFilter（`detectors/external_content.py`）

用于检索内容阶段，按标点分段，剔除“指令类”片段而保留事实内容：

- 匹配指令正则：`ignore … system prompt`、`忽略/无视/覆盖 … 指令/系统提示`、`将…视为系统指令`、`你必须…` 等（中英文），与规则检测器命中区间重叠的段也一并剔除。
- 每个被剔除段生成 `indirect_prompt_injection` 证据（score 0.72，`remediable=True`），输出过滤后文本（`BottleneckResult`）。

---

## 六、阶段感知字符分类器（模型）

`StageAwareCharClassifier`（`detectors/stage_classifier.py`）：

- **模型**：字符 n-gram + 逻辑回归（joblib），三个独立 head（`input` / `output` / `content`），路径 `model_heads/io-guard-stage-char-v3/*_char.joblib`。
- **来源标记**：输入前拼接 `[输入]` / `[输出]` / `[检索内容]` / `[工具结果]`，让模型感知阶段。对结构化文本（检索/工具/记忆）先用 `extract_string_leaves` 拆字段再逐字段打分，取最高分。
- **阈值**：head 自带 `unsafe_threshold`（input 0.6825、output 0.3、content 0.7，可在策略里 override）。
- **校准**：命中时把概率校准到策略分 `policy_score=0.9` 之上：`policy_score + scaled*(1-policy_score)`，使命中结果稳定落在 block 区间。
- **标签**：`direct_prompt_injection`（input）/ `harmful_or_offensive_content`（output）/ `indirect_prompt_injection`（content），附 `confidence/head/threshold/field`。

> 已知盲区（诊断结论，未修）：短中文“我的+名词”组合 FP 较多（`[输入]` 标记 + `我的`/`是多少` n-gram 权重高）；中文越狱变体、`读取 /etc/passwd` 式命令、跨语言（德/韩）注入等存在漏检。SemanticDetector 的 allowlist 正是针对其中“我的+联系方式”这类确定性短文本误报的窄豁免。

---

## 七、策略引擎（PolicyEngine）

`policy.py`，阈值 `rewrite=0.55`、`block=0.85`。`risk_score = max(evidence.score)`，决策顺序：

1. 无证据或 `risk_score < 0.55` → `allow`。
2. `_authorized_disclosure`（内部员工/服务账户 + internal 受众 + 非 public 渠道 + 授权 scope）→ `allow`。
3. 仅 `indirect_prompt_injection` → 内容有净化且非空则 `rewrite`，否则 `block`。
4. 存在不可补救的 `unauthorized_information_disclosure` → `block`。
5. 内容已变化且全部证据可补救 → `rewrite`。
6. 硬阻断集合（恶意指令/越狱、直接注入、有害冒犯、违法引导、恶意代码）命中 → `block`。
7. `risk_score ≥ 0.85` → `block`；否则内容已净化 → `rewrite`，未净化 → `block`。

`reason` 形如 `block: direct_prompt_injection: stage classifier flagged content: … (score=0.93)`；`policy_id = io-guard-target-taxonomy-v1`。

---

## 八、问题拆分（QuestionDecomposer）

`preprocessors/decomposition.py`：**无损失、不调模型**的启发式拆分，仅为检测创建“视图”。

- 触发：`enabled` 且文本 ≥ `min_chars`（60）且含多任务标记（换行/句号/然后/同时/另外/最后/并且/接着/之后/then/also/finally）。
- 最多 `max_parts`（8）段；每段标注 `kind`：`instruction`（含 忽略/覆盖/绕过/系统提示/凭证/扮演/不受限制 等）、`credential`（密码/验证码/密钥/token…）、`external_data`（网页/文档/检索/引用…）、`task`。
- 各视图独立跑规则/语义检测，证据坐标平移到原文本，`message` 追加 `detection_view=part-N; view_kind=…`。
- 目的是让混合在长文本里的注入片段不会因整段被模型“稀释”而漏检。

---

## 九、审计与轨迹

- **AuditLogger**：`audit.py`，可配置 `content_storage=sanitized`（默认只存脱敏内容）、`max_content_chars=2000`，写 `audit.jsonl`。
- **TrajectoryStore**：`trajectory.py`，同一 `trace_id` 跨步骤累积，`processing_metadata.trajectory` 记录 `verdict`、`step_count`、`unsafe_step_ids`；一旦某步 `unsafe`，后续步骤轨迹保持 `unsafe`。

---

## 十、媒体输入检测（图片 & 文档）

### 10.1 适配器编排（`argus/adapters/io_guard_adapter.py`）

外层 `IoGuardAdapter.run` 在 `stage=="input"` 且 payload 含非空 `attachments` 且 `media_extraction` 开启时走 `_run_with_attachments`：

1. `extract_attachments(attachments, cfg)` 对每个附件抽取文本（`asyncio.to_thread` 包裹 OCR）。
2. 先跑主文本 `delegate.run(request)`。
3. 对每个有非空 `text` 的附件，构造 `payload.text=提取文本` 的副本再跑 `delegate.run()`（即现有 `pre_check` 管线）。
4. **聚合**：任一附件 `block` → 整体 `block`；否则取最严结果。`details.attachment_verdicts` 逐个标注 `{name, path, url, mime_type, action, risk_score, primary_label, reason, error}`；block 来自附件时 `reason` 前缀 `附件 <name> 命中安全策略:`。
5. 无附件/未启用时行为与纯文本完全一致；任何解析失败按文件隔离为 `error`，不使整体降级成 `module_error/allow`。

内层 `io_guard/adapters/argus_adapter.py` 与 `service.py` 保持不动，仅做契约转换（`payload.text|content` → `GuardRequest`）。

### 10.2 格式与提取器（`argus/modules/media_input/`）

- **`mime.py`**：magic bytes 嗅探（PNG/JPEG/PDF/ZIP）；ZIP 再读 `[Content_Types].xml` 区分 docx/xlsx；扩展名兜底。支持 `pdf / docx / xlsx / csv / txt / md(按txt) / png / jpeg / gif / bmp / webp`。
- **`extractors.py`**：
  - `extract_pdf`：PyMuPDF（`fitz`）逐页取文本。
  - `extract_docx`：python-docx，段落 + 表格（单元格按行 `\t` 拼接）。
  - `extract_xlsx`：openpyxl `read_only + data_only`，逐 sheet 逐行取非空单元格。
  - `extract_csv`：`utf-8-sig → gbk → utf-8` 解码后按行取非空单元格。
  - `extract_text`：`utf-8 → utf-8-sig → gbk → utf-16 → latin-1` 多编码回退。
  - `extract_image`：OCR。
  - 统一限制：文件 > `max_file_bytes`（15MB）报错；文本截断到 `max_text_chars`（50000）。
- **`ocr.py`**：懒加载单例 **RapidOCR**（`rapidocr_onnxruntime`，CPU），`threading.Lock` 保护；初始化失败缓存 `_INIT_ERROR`，并作为当前附件的独立错误返回；未识别到文字时返回空串。
- **`download.py`**：`fetch_remote` 仅接受 HTTP/HTTPS，用 `httpx` 流式下载远程附件（QQ 远程图片），硬性上限 `remote.max_bytes`（5MB）、超时 `remote.timeout_ms`（8000）。异常时立即清理临时文件，成功抽取后也由附件调度层清理。
- **`__init__.py`**：`extract_attachments` 调度；`max_attachments`（5）截断；图片受 `ocr.max_images`（4）与 `ocr.enabled` 约束；**每个文件 try/except 隔离错误**。

### 10.3 配置开关

- 模块级：`configs/modules.yaml` → `io_guard_input.media_extraction: true`（三个 `io_guard_*` 共享同一适配器实例，仅 `input` 阶段分支，不碰 content/output）。
- 策略级：`default_policy.json` 顶层 `media_extraction` 块（见第十一节）。
- env 覆盖：`IO_GUARD_MEDIA_POLICY` 指定策略路径。

---

## 十一、配置（default_policy.json）

```jsonc
{
  "policy_id": "io-guard-target-taxonomy-v1",
  "target_taxonomy": { "risk_source": [...4项], "failure_mode": [...5项] },
  "decision_thresholds": { "rewrite": 0.55, "block": 0.85 },
  "audit": { "content_storage": "sanitized", "max_content_chars": 2000 },
  "disclosure": { "authorized_scopes": ["pii","customer_support","hr","finance"] },
  "question_decomposition": { "enabled": true, "min_chars": 60, "max_parts": 8 },
  "semantic_detection": {
    "enabled": true,
    "backend": "stage_char_classifier",
    "model_dir": "../model_heads/io-guard-stage-char-v3",
    "policy_score": 0.9,
    "detector_threshold": 0.55,
    "threshold_overrides": { "input": 0.6825, "output": 0.3, "content": 0.7 }
  },
  "media_extraction": {
    "enabled": true, "max_file_bytes": 15000000, "max_text_chars": 50000,
    "max_attachments": 5,
    "remote": { "max_bytes": 5000000, "timeout_ms": 8000 },
    "ocr": { "enabled": true, "lang": "ch", "device": "cpu", "max_images": 4 }
  }
}
```

`IOGuard.from_policy_file` 只读取它关心的键，其余键（如 `media_extraction`）由媒体模块自行读取，互不影响。

---

## 十二、测试

`original/tests/`（pytest，与 API 集成测试 `tests/test_media_input_api.py` 配合）：

- `test_target_taxonomy.py`：九类风险、三种决策、三阶段行为；**自联系方式组合查询 allowlist**（`我的电话邮箱是多少` 等 5 条 + 追加指令仍 block + 未授权联系仍 block）；良性临时文件/总结任务绕过模型误报；风险近邻仍 block；检索内容过滤 rewrite；来源可信度 rewrite/block；输出脱敏/密级/恶意代码/不可补救泄露 block；轨迹保持 unsafe。
- `test_argus_adapter.py`、`test_service.py`：适配器契约与 HTTP 门面。
- `test_media_extraction.py`：mime 嗅探、各格式提取、OCR monkeypatch（不跑真 OCR）、大小超限置 error、错误隔离。
- `test_stage_char_classifier.py`：模型 head 加载与打分。

---

## 十三、已知边界与后续建议

1. **`_SELF_CONTACT_QUERY` 剩余 gap**：`告诉我我的手机号码是多少` 仍会被阶段分类器拦截（第二分支缺少“是多少”后缀）。
2. **`_THIRD_PARTY` 缺口**：未含“老板/上司/家人/朋友/邻居”，`老板的手机号是多少` 可能漏检。
3. **阶段分类器盲区**：中文“我的+名词”短文本 FP；命令型指令（`读取 /etc/passwd`）、中文越狱变体、跨语言注入等 FN。
4. **OCR 延迟**：单 worker 串行 OCR，CPU 约 2.2s/图；`max_images=4`、`max_attachments=5` 已限流；hook 超时需 ≥ 31000ms 与之匹配。
5. **Editable 安装路径**：切换工作副本后应在当前仓库根目录重新执行 `python -m pip install -r argus\modules\io_guard\requirements.txt`，避免 Python 环境继续加载其他 checkout 中的旧 `io_guard` 包。
