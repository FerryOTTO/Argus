# IO Guard 0.2（九类风险自动处置版）

IO Guard 是 Argus V2.1 的输入、外部内容和输出安全模块。0.2 版保留统一接口和 Adapter 契约，将检测范围收敛到九类目标风险，并把 IO Guard 的动作限定为 `allow`、`rewrite`、`block`。

完整实现说明、检测器细节和已知边界见 [IO_GUARD_MODULE.md](original/IO_GUARD_MODULE.md)。

## 检测范围

风险来源：

1. `malicious_user_instruction_or_jailbreak`：恶意用户指令或越狱；
2. `direct_prompt_injection`：直接提示注入；
3. `indirect_prompt_injection`：网页、检索、工具结果或记忆中的间接提示注入；
4. `unreliable_or_misinformation`：被显式标为虚假、不可信、过时或未经验证的环境内容。

输出失败模式：

1. `harmful_or_offensive_content`：有害、仇恨或攻击性内容；
2. `harmful_or_illegal_guidance`：可操作的有害或非法指导；
3. `malicious_executable_generation`：恶意可执行代码或脚本；
4. `unauthorized_information_disclosure`：个人信息、凭据、内部提示或越权密级信息泄露；
5. `inaccurate_misleading_or_unverified_information`：被显式标为不准确、误导或未经核实的模型输出。

长度、Token、时长和工具调用预算由网关、限流器或 Tool Guard 负责，不再由 IO Guard 重复判断。

## 三阶段与统一接口

| 阶段 | Argus 路径 | 文本字段 | 模块结果名 |
|---|---|---|---|
| 输入 | `POST /v1/input/check` | `payload.text` | `io_guard.input` |
| 外部内容 | `POST /v1/content/check` | `payload.content` | `io_guard.context` |
| 输出 | `POST /v1/output/check` | `payload.text` | `io_guard.output` |

`/v1/content/check` 先运行 Retrieval Guard。若其返回 `block`，请求立即终止；若返回 `rewrite`，IO Guard Context 接收净化后的 `content`，不会重新处理原始脏内容。

原 IO Guard Sidecar 的兼容路径仍保留：`/v1/check/input`、`/v1/check/context`、`/v1/check/output`，请求文本字段为 `content`。

## 动作和响应契约

IO Guard 只返回：

- `allow`：未发现九类目标风险；
- `rewrite`：风险可通过过滤、警示或脱敏修复，调用方必须使用响应中的 `data`；
- `block`：风险不可安全修复，调用方必须停止当前阶段。

公共 `Action` 类型仍为其他模块保留 `human_review`，但 IO Guard 本身不会返回该动作。

统一响应继续使用 Argus `SecurityResponse` / `ModuleResult`。IO Guard 的 `details` 还会提供 `verdict`、`primary_label`、`dimension`、`mitigated`、`evidence` 和 `processing_metadata.trajectory`。

## 图片和文档输入

输入接口可在 `payload.attachments` 中附带图片或文档。外层 Adapter 抽取文本后，将每个附件分别送入同一输入检测管线，再与主文本结果取最严格动作。

```json
{
  "context": {
    "stage": "input",
    "user_id": "user-001",
    "session_id": "session-001"
  },
  "payload": {
    "text": "请检查附件",
    "attachments": [
      {
        "name": "report.pdf",
        "path": "C:\\OpenClaw\\media\\inbound\\report.pdf",
        "mime_type": "application/pdf"
      }
    ]
  }
}
```

附件描述需要 `name`，并提供 `path` 或 `url`；`mime_type` 可选。`path` 应仅由受信任的 OpenClaw 网关生成，远程附件只接受 HTTP/HTTPS。支持 PDF、DOCX、XLSX、CSV、TXT/Markdown、PNG、JPEG、GIF、BMP 和 WebP。

默认限制：单文件 15 MB、远程文件 5 MB、抽取文本 50,000 字符、每次 5 个附件、其中最多 4 张图片。OCR 使用 CPU 版 RapidOCR。单个附件解析失败会记录在 `details.attachment_verdicts`，不会掩盖其他附件的检测结果。

OpenClaw Plugin 会从 `media://inbound/...`、QQ 附件标记或消息元数据提取附件，并在调用 `/v1/input/check` 时传入。默认超时为 30 秒，可通过 Plugin 的 `mediaRoot`、`enableMediaCheck` 和 `timeoutMs` 配置覆盖。

## 安装

使用 Python 3.11，在仓库根目录执行：

```powershell
python -m pip install -r requirements.txt
python -m pip install -r argus\modules\io_guard\requirements.txt
```

第二条命令会以 editable 模式安装 `original/`，并安装字符分类器、PDF/DOCX/XLSX 解析和 OCR 依赖。阶段感知模型位于 `original/model_heads/io-guard-stage-char-v3/`，已随仓库提交，可离线加载。

## 配置

`configs/modules.yaml` 中三个阶段应启用；媒体抽取仅作用于输入阶段：

```yaml
modules:
  io_guard_input:
    enabled: true
    mode: import
    on_error: allow
    media_extraction: true

  io_guard_context:
    enabled: true
    mode: import
    on_error: allow

  io_guard_output:
    enabled: true
    mode: import
    on_error: allow
```

策略文件默认为 `original/configs/default_policy.json`。可用以下环境变量覆盖：

- `IO_GUARD_POLICY`：IO Guard 主策略；
- `IO_GUARD_MEDIA_POLICY`：媒体抽取策略；
- `IO_GUARD_AUDIT_PATH`：JSONL 审计日志路径。

当前 IO Guard 异常策略为开发联调所需的 fail-open；生产部署前应根据业务风险决定是否切换为 fail-closed。

## 启动与验证

```powershell
python -m uvicorn argus.api.main:app --host 127.0.0.1 --port 8000
```

模块、接口和媒体测试：

```powershell
python -m pytest `
  argus\modules\io_guard\original\tests `
  tests\test_io_guard_adapter.py `
  tests\test_media_input_api.py -q
```

OpenClaw Plugin 测试：

```powershell
Set-Location openclaw_adapter\plugins\argus-adapter
npm ci
npm run check
npm test
```

## 代码入口

- 九类枚举：`original/src/io_guard/taxonomy.py`
- 三阶段管线：`original/src/io_guard/pipeline.py`
- 自动处置：`original/src/io_guard/policy.py`
- 内层契约 Adapter：`original/src/io_guard/adapters/argus_adapter.py`
- Argus Adapter：`../../adapters/io_guard_adapter.py`
- 媒体抽取：`../media_input/`
- 默认策略：`original/configs/default_policy.json`

不要提交虚拟环境、缓存、运行日志、临时附件、`*.egg-info` 或任何密钥。
