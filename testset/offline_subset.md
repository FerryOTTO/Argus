# 离线可跑子集清单

以下样本**不依赖 torch / PIGuard 模型 / 网络 / Docker / 真实 LLM**，在只装了基础依赖
（`requirements.txt` + `argus/modules/io_guard/requirements.txt`，其中 io_guard 模型头已随仓库提交）后即可离线评测：

## 完全离线（无任何外部依赖）

| 数据集 | 可离线样本 | 说明 |
|---|---|---|
| `access_control_matrix.jsonl` | 全部 | 纯规则判定（auth_gateway + 静态规则），评测前先在 `rules/users.txt` 配好 `u_public/u_internal/u_secret/u_admin` 等级；`risk_escalation` 类由评测脚本自动写临时审计事件触发联动，仍离线 |
| `sandbox_harm_detector.jsonl` | 全部 | 纯正则扫描 `harm_detector.py`，无需 Docker/torch/网络 |
| `audit_events.synthetic.jsonl` | 全部 | 离线：验证事件写入/查询/图构建/风险联动升级（需 networkx，见 `argus/modules/audit/requirements.txt`） |
| `io_guard_input.jsonl` | 全部 | 输入分类头 `input_char.joblib` 已提交，可离线加载 |
| `io_guard_output.jsonl` | 全部 | 输出分类头 `output_char.joblib` 已提交 |
| `retrieval_guard.jsonl` | 仅 A/C 层 + `empty_or_error` | 关掉 B 层（guards.B=false）后 A 白名单 + C 包装 + cleaner 清洗可离线；`prompt_injection` 类需要 PIGuard |

## 需真实 LLM（Tool Guard）

`tool_guard_intent.jsonl` 全部样本依赖 LLM 意图裁判，需配置 `TOOL_GUARD_LLM_*`
（或注入 `IntentMatchDetector` 假客户端）。不配置时只对 `expected_action=block`
的样本命中（返回 `llm_unconfigured`）。

## 需模型 / 外部环境

| 数据集 | 依赖 |
|---|---|
| `retrieval_guard.jsonl` 的 `prompt_injection` 类 | torch + PIGuard 模型（`argus/modules/retrieval_guard/models/PIGuard`） |
| `media_input.jsonl` | PDF 抽取需 pymupdf，图片 OCR 需 RapidOCR；评测脚本按 `attachment.content` 自动生成文件 |
| `io_guard_content.jsonl` | content 分类头 `content_char.joblib` 已提交，可离线；但走 `/v1/content/check` 时会先过 Retrieval Guard（B 层需模型） |

## 建议离线评测顺序（从简到繁）

1. `sandbox_harm_detector`（纯正则，零依赖，最快）
2. `access_control_matrix`（纯规则）
3. `io_guard_input` / `io_guard_output`（本地模型头）
4. `io_guard_content`（内容头，注意走 content 接口会先过 Retrieval Guard）
5. `retrieval_guard`（先只测 A/C/清洗，再加 B）
6. `tool_guard_intent`（配 LLM 后）
7. `media_input`（附件抽取）
