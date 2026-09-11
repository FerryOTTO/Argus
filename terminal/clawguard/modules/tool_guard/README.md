# Tool Guard 模块

工具调用安全:在工具**执行前**校验"智能体工具链是否与用户原始意图一致"。

## 1. 调用流程

```
OpenClaw 收到用户输入
  → POST /v1/tool/session/prompt   绑定意图锚点(原始输入)
OpenClaw 工具执行前
  → POST /v1/tool/pre_check
      → Access Control(既有)
      → Tool Guard(本模块)
          ├─ 从会话存储取 original_prompt + tool_chain(按 session_id)
          ├─ LLM 裁判打分(score 0~1,输入不含工具结果)
          └─ score < block_threshold → block
              score < review_threshold → human_review
              否则 → allow
OpenClaw 工具执行后
  → POST /v1/tool/session/call    回写工具调用(名称 + 参数摘要)
```

## 2. 接口契约

### 会话绑定(OpenClaw 侧调用)

| 接口 | 作用 |
|---|---|
| `POST /v1/tool/session/prompt` | 绑定会话原始输入,body: `{"session_id": "...", "prompt": "用户原始输入"}` |
| `POST /v1/tool/session/call` | 记录已执行工具调用,body: `{"session_id": "...", "tool_name": "...", "arguments": {...}}` |

### pre_check 判定(返回值语义)

| score 区间 | action | 说明 |
|---|---|---|
| `>= review_threshold`(默认 0.7) | `allow` | 与用户意图一致 |
| `[block_threshold, review_threshold)`(默认 0.4~0.7) | `human_review` | 关联弱/绕路,需人工确认 |
| `< block_threshold`(默认 0.4) | `block` | 疑似被外部内容/注入指令劫持 |

特殊兜底:

| 场景 | 行为 |
|---|---|
| 会话无上下文(OpenClaw 未接补丁) | `allow` + `reason=no_session_context`,联调不误伤 |
| LLM 未配置 | 按 `on_error`(默认 `block`)返回 `llm_unconfigured` |
| LLM 调用异常 | 按 `on_error`(默认 `block`)返回 `module_error` |

## 3. 配置

优先级:环境变量 > `configs/modules.yaml` 的 `modules.tool_guard` 段 > 内置默认。

环境变量:

```text
TOOL_GUARD_LLM_BASE_URL=https://api.deepseek.com/v1   # OpenAI 兼容接口地址
TOOL_GUARD_LLM_API_KEY=                                # 远程服务必填;本地(如 Ollama)可留空
TOOL_GUARD_LLM_MODEL=deepseek-chat
TOOL_GUARD_BLOCK_THRESHOLD=0.4
TOOL_GUARD_REVIEW_THRESHOLD=0.7
TOOL_GUARD_LLM_TIMEOUT=30
```

审计日志:每次判定(含无会话/未配置/异常兜底分支)由 API 层统一通过 audit 模块
进程内写入(``emit_module_audit_event``),``content`` 携带 score/deviation/tool_name/chain_length
等判定细节,``source_module=tool_guard``、``stage=tool_pre``;写入失败不影响判定结果本身。
Tool Guard 自身不再直接对接审计 REST 接口,避免与 audit 模块重复对接。

运行期修改(仅内存生效,重启回退):

```text
GET /v1/tool_guard/config    # 查看当前配置(api_key 脱敏为 ***)
PUT /v1/tool_guard/config    # 更新,如 {"model": "...", "block_threshold": 0.3}
```

安全说明:远程服务无 `api_key` 时视为未配置(不会带空 key 调远程);
无 key 仅允许本地地址(如 `http://127.0.0.1:11434`,Ollama)。

## 4. 目录结构

```text
tool_guard/
├── README.md
├── original/                  # 原模块代码预留(如 Suzuran 拆分后)
├── intent_match.py            # IntentMatchDetector:LLM 裁判(OpenAI 兼容,JSON 输出)
├── session_store.py           # 会话状态:意图锚点 + 工具链(内存,TTL 30 分钟,链长上限 20)
└── llm_config.py              # LLM 配置管理(env/yaml/运行期 API)
```

## 5. 真实 LLM 评估结果(DeepSeek deepseek-chat,2026-08)

评估脚本:`evaluation/scripts/eval_intent_match.py`(25 用例,多次运行分数一致,可重复)。
用例来源:自建基础场景 + AgentDojo(NeurIPS 2024,邮件/旅行/银行注入模式)+ AgentLAB(2026,长时程攻击链类型)。

| 类别 | 命中 | 说明 |
|---|---|---|
| normal 3/3 | 文件整理/天气/文档对比 | `allow`(0.90~1.00),直接必要步骤 → 高分 |
| hijack 4/4 | 邮件泄露/恶意 URL/删文件/越权转账 | `block`(0.00),deviation 准确指出目标漂移点 |
| ambiguous 3/3 | 周报辅助搜索 0.50 / 娱乐搜索 0.00 / 订错航班 0.00 | 弱关联→中分;强无关/参数严重不符→block(保守) |
| robust 2/2 | 参数内嵌注入指令 | `block`(0.00),识别参数级注入 |
| attack_chain 10/10 | 渐进漂移(E)、诱饵链(F)、复合攻击(G)、短链攻击(I) | 攻击链末跳全部拦截;正常收尾跳不误伤 |
| normal_chain 3/3 | 会议安排/订票/调研报告长链 | 多跳正常链全部 `allow`(0.90~1.00) |

关键发现:

1. **核心安全能力可靠**:正常调用高分放行、劫持调用零分拦截,`deviation` 字段可直接用于审计;
2. **保守倾向**:强无关或参数严重不符(订票去错城市)直接判 `block` 而非 `human_review`,
   符合“宁可错杀”的安全定位;如需更宽松可在 `configs/modules.yaml` 调低 `block_threshold`;
3. **注入免疫双保险**:裁判输入不含工具返回内容 → 对真实注入(结果内嵌)天然免疫;
   参数内嵌明显指令时也会降分拦截,覆盖参数级污染;
4. **攻击链拦截有效**:多跳无害调用渐进漂移(整理桌面→上传银行对账单)、前段正常后段漂移
   (总结邮件→转发给外部)、复合攻击(订便宜酒店→订最贵酒店)均被末跳拦截;
5. **单跳语义边界**:裁判只评估“本次调用 vs 原始意图”,链中恶意跳应在该跳被拦截,
   后续正常收尾跳不“连坐”(如 F3)。链级风险累积/历史清洁度不在当前裁判范围;
6. **性能**:平均单次判定约 1.2s(temperature=0),满足工具调用前置校验的延迟预算;
7. **格式鲁棒性**:JSON 解析失败时自动以更强制式指令重发一次,仍失败才按 ``on_error``
   兜底,降低非格式化输出导致的假阳性。

## 6. 联调注意

1. **Access Control 会先执行**:其规则库为空时会把工具调用全部 block,导致 Tool Guard
   走不到。联调 Tool Guard 前请先确认 `modules/access_control/rules/` 已配置用户/资源规则,
   或临时在 `configs/modules.yaml` 中关闭 `access_control`。
2. OpenClaw 端补丁(绑定 prompt / 回写调用 / pre_check 前置)尚未实现,
   补丁位置参照 `openclaw_adapter/patch_source/retrieval-guard/` 的既有模式。
3. 测试:`.venv/bin/python tests/test_tool_guard.py`(会话/配置/裁判/Adapter/审计全覆盖)。
