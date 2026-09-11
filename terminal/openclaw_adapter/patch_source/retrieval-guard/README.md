# Retrieval Guard 补丁说明

> ⚠️ **已废弃（2026-08-20）**：content 检查改由 `clawguard-adapter` 插件（`agentToolResultMiddleware`）
> 转发到服务端 Retrieval Guard adapter，**不再需要 bundle 补丁**。OpenClaw 端当前无需打任何补丁
> （仅需安装插件 + 服务端运行）。本目录保留作为回退方案（bundle 还原 + 打补丁 = 旧方案复活）。
>
> **现行方案（新思路）**：
> 1. OpenClaw 端装 `clawguard-adapter` 插件（compat 已适配 6.11），middleware 转发 `/v1/content/check`
> 2. 服务端 `/v1/content/check` 只跑 Retrieval Guard adapter（PIGuard，`io_guard_context` 已 disabled）
> 3. 契约统一 `content/tool_name/source`（adapter 双兼容 `text/tool`）
> 4. 插件与 6.11 适配说明见 `openclaw_adapter/patch_source/clawguard-adapter/README.md`

OpenClaw 端改动的**差异文件**与**源文件**分两处存放（patch_source 为团队共用目录，每个模块一个子文件夹）：

| 位置 | 内容 |
|---|---|
| `patches/openclaw-2026.6.11-retrieval-guard.patch` | 差异文件（`.patch`，供 `patch -p1` 应用） |
| `patches/scripts/apply-patch.ps1` | 一键应用脚本（自动检测已应用 → 应用 → 验证） |
| `patch_source/retrieval-guard/proxy-CoylXPU6.js` | **修改后的完整源文件** |
| `patch_source/retrieval-guard/proxy-CoylXPU6.js.orig` | **未修改的原始源文件**（对照用） |

改源文件时必须**同时**更新三处：`patches/` 的 `.patch` 差异、本目录的修改后源文件、以及原始源文件（如基础版本变化）。

## 文件详解

### 三件套的关系

```
proxy-CoylXPU6.js.orig（原始源）  +  补丁配方（.patch）  =  proxy-CoylXPU6.js（补丁后源）
                                   ↑ apply-patch.ps1 自动完成
```

### 每个文件是啥

| 文件 | 是什么 | 为什么存在 | 什么时候用 |
|---|---|---|---|
| `proxy-CoylXPU6.js` | **补丁后的完整源文件**（= 原始 + 补丁的结果） | 升级后 bundle 结构变化时，patch 打不上——手工对照它迁移改动 | 手工迁移/对照 |
| `proxy-CoylXPU6.js.orig` | **未修改的原始源文件**（`.orig` = original，patch 工具的备份惯例） | ① 验证补丁内容：`diff .orig 补丁版` = 补丁本身 ② 回退时还原原始 ③ 升级时确认"干净源"长什么样 | 对照/回退/验证 |
| `openclaw-2026.6.11-retrieval-guard.patch` | 差异文件（unified diff 格式）——补丁的"配方" | patch 命令按它把原始源变成补丁版 | `patch -p1 < ...patch` 自动应用 |
| `apply-patch.ps1` | 一键应用脚本（定位 bundle → 检测已应用 → 备份 → 应用 → node 验证） | 免手工 patch，幂等可重复 | 升级后重放补丁 |

### 通俗类比

```
.patch  = 菜谱（只记录"怎么改"）
.orig   = 没做菜之前的原料（原始干净版）
补丁版 js = 按菜谱做完的成品菜（修改后的完整文件）
apply 脚本 = 自动按菜谱做菜的厨师
```

> 注意：本目录方案已**废弃**（2026-08-20 起走插件方案），以上文件仅作为回退/对照保留。

## 补丁内容

**目标文件**：`node_modules/openclaw/dist/proxy-CoylXPU6.js`（2026.6.11 版 agent-loop 编译产物）

**唯一改动位置**：`executePreparedToolCall` 函数内（工具执行后、结果进 AI 上下文前）

**改动内容**（+51 行，无其他修改）：
1. 工具名为 `web_search` / `web_fetch` 且结果非空时，提取 `content[0].text`
2. POST `http://127.0.0.1:8000/v1/content/check`（Clawguard 统一检索安全检查）
3. 返回 `block` → 工具结果替换为拦截错误消息（AI 读到拦截信息，看不到原始内容）
4. 返回 `rewrite` → `result.content[0].text` 写回 C 层包装文本
5. 失败/超时 → fail-open（原样放行，不阻塞主流程）

**开关**：`SAFEGUARD_ENABLED = true/false`（补丁内常量，改后重启 gateway 生效）

## 如何应用

```powershell
# 一键脚本（推荐）
cd openclaw_adapter\patches\scripts
powershell -ExecutionPolicy Bypass -File .\apply-patch.ps1
```

```bash
# 手工（必须在 openclaw 包根目录运行，-p1 匹配 dist/ 相对路径）
cd "e:/OpenClaw/npm-global/node_modules/openclaw"
patch -p1 < "e:/OpenClaw/ClawguardV2.1/openclaw_adapter/patches/openclaw-2026.6.11-retrieval-guard.patch"
grep -c SafeGuard dist/proxy-CoylXPU6.js   # 应为 7
node --check dist/proxy-CoylXPU6.js         # 语法检查
```

## 回退

```bash
cd "e:/OpenClaw/npm-global/node_modules/openclaw"
patch -p1 -R < "e:/OpenClaw/ClawguardV2.1/openclaw_adapter/patches/openclaw-2026.6.11-retrieval-guard.patch"
```

## 升级后重放

OpenClaw 升级会覆盖 dist，补丁丢失。重放步骤：
1. 新版本后先确认 `executePreparedToolCall` 仍存在（`grep -n "executePreparedToolCall" dist/proxy-*.js`）——函数没了说明结构大改，需手工对照 `patch_source/proxy-CoylXPU6.js` 迁移
2. 行号变化通常无碍（`patch` 的 fuzz 容忍小幅偏移）
3. 应用后 `node --check` 验证语法
4. 重启 gateway，实测一次 web_fetch 确认拦截生效

## 方案演进记录（为什么从补丁改回插件）

2026.6.11 的插件 hook 体系验证历程：

| 方案 | 结论 |
|---|---|
| `after_tool_call` + 缓存 | ❌ fire-and-forget，检测结果来不及写入（实测） |
| `tool_result_persist` | ❌ 只修改持久化记录，AI 上下文用的是另一份（实测） |
| `registerAgentToolResultMiddleware` | ✅ **2026-08-20 实测可用**：主会话触发（runtime=openclaw）+ 替换生效（模型读到替换后内容）。8/4 曾误判"只作用于 embedded/codex"——原因是测试时 gateway 为旧进程未加载插件。**现行方案即基于它** |
| `before_agent_run` | ⚠️ 能 block；prompt 改写需补丁消费（6.11 等价补丁已移植，见 `patch_source/clawguard-adapter/`） |
| `before_prompt_build` | ⚠️ 只能注入提示（软防护），不能替换工具结果 |
| bundle 源码补丁（本目录） | ✅ 曾实测有效（拦截 + 包装），**2026-08-20 起废弃**（改走插件方案），保留为回退 |

**演进结论**：8/4 因测试环境问题误判 middleware 不可用，选择了 bundle 补丁；8/20 实测纠正误判后，回归官方 API（middleware）方案——**零源码修改、升级无忧**。

## 前置依赖

- Clawguard 服务运行在 `127.0.0.1:8000`（`cd ClawguardV2.1 && python -m uvicorn clawguard.api.main:app --port 8000`）
- Clawguard 不可达时补丁 fail-open，OpenClaw 正常运作但不检测
