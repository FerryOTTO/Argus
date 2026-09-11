# Clawguard 版本一致性核查报告

- 起因:确认「Clawguard 有没有新版,有的话同步」
- 核查时间:2026-09-10
- 方法:盘点本机全部 Clawguard 载体 → 统一换行后做**内容级比对** → git 谱系与时间戳取证
- 结论:**没有更新的上游可拉;真正需要同步的是我们自己内部的一条线——`LLMGate/terminal` 落后于 `ClawguardV2.1`。**

---

## 一、先给结论

| 问题 | 结论 |
|---|---|
| 有没有更新的 Clawguard 版本? | **没有。** 本机最新的载体(`LLMGate-FULL.zip`,今天 15:11 打的)与我们的 `LLMGate/terminal` **内容零差异**,只是少了模型头——它是我们这条线的**下游产物**,不是新款 |
| 我们的发布包要动吗? | **不用。** `release/v1.0test` 已与最新的 `ClawguardV2.1` 一致 ✅ |
| 那要同步什么? | **`ClawguardV2.1` → `LLMGate/terminal`,共 9 个文件**。B 线仍停在"同步写 users.txt"的**旧架构**,而 A 线已是"users.txt 下线、等级存用户库、执法侧从 auth.db 动态回查"的**新架构** |
| 附加收获 | 找到同学报告里那条"高"问题(成品缺模型)的**真正根因**,且**不改打包方式每次都会复现** |

---

## 二、本机 Clawguard 载体盘点

| 载体 | 身份 | 文件数 | 快照时间 | 判定 |
|---|---|---|---|---|
| `ClawguardV2.1` | git 仓(remote `WT-ever/ClawguardV2.1`),HEAD `5c022e1` | 290 | 09-10 **09:30–09:37** | **A = 最新** ⭐ |
| `release/v1.0test/enterprise/terminal` | 我们的发布包 | 263 | 09-10 12:50 | **C = 与 A 一致** ✅ |
| `release/v1.0test/enterprise/desktop/ClawguardV2.1` | 我们的发布包(桌面) | 246 | 09-10 12:50 | 与 A 一致 ✅ |
| `LLMGate/terminal` | git 仓(`jingwenMC/LLMGate`)的子目录 | 273 | 09-07 ~ 09-10 03:06 | **B = 落后** ⚠️ |
| `LLMGate-FULL.zip`(Downloads) | 今天 15:11 打包,源自 LLMGate 提交 `7e768de`(15:10) | 264 | 09-10 15:11 | **= B,且少了模型头** |
| `clawguard-desktop/release*/win-unpacked/ClawguardV2.1` | 桌面端构建产物 | 246 | 09-10 12:55 | 与 A 一致 ✅ |
| `ClawguardV2.1-main` | 0.19 MB 残包 | 95 | 08-05 | 可忽略 |

> 注:zip 内所有条目时间戳都被归档器重置为 `09-10 00:10`,**不能用它判新旧**;判据用的是文件内容与本地 mtime。

---

## 三、内容级比对(已统一 CRLF/LF)

| 对比 | 共有文件 | 完全相同 | 仅换行不同 | **真实内容不同** |
|---|---|---|---|---|
| `LLMGate-FULL.zip` vs `LLMGate/terminal` | 264 | 43 | 221 | **0** |
| `ClawguardV2.1` vs `LLMGate/terminal` | 265 | 256 | 0 | **9** |
| `LLMGate/terminal` vs `release/v1.0test/terminal` | 257 | 248 | 0 | **9** |
| `zip` vs `ClawguardV2.1` | 260 | 40 | 211 | **9** |

**关键结论**

- zip 与 `LLMGate/terminal` **真实差异为 0** → 成品就是从 B 线打的,不是新版;zip 比 B 少的正好是 **5 个 io_guard 模型头文件**。
- A 与 B 之间有 **9 个真实分歧**,C(发布包)与 A 一致 → **只有 B 线落后**。
- 之前看到的"220 个文件大小不同"是**假象**:211/221 个只是 CRLF vs LF(例:`clawguard/__init__.py` 在 zip 里是 `\n`、本地是 `\r\n`)。

---

## 四、9 个分歧文件:差异性质

**不是零散改动,而是一次一致的架构迁移**(users.txt 存废):

| 文件 | A(V2.1) | B(LLMGate) | A 侧的新架构证据 |
|---|---|---|---|
| `clawguard/modules/access_control/original/auth_gateway.py` | 830 行 | 741 行 | A 多出 `self.bound` / `_load_bound_user()`(单用户绑定) |
| `clawguard/api/remote_sync.py` | 961 行 | 977 行 | A:`"users.txt 已下线:只写 access_local.json 的 bound_user"` |
| `clawguard/api/local_config_routes.py` | 228 行 | 228 行 | A:`pass  # users.txt 已下线:用户规则只保留在服务端` |
| `openguard/original/main.py` | 404 行 | 434 行 | A:`# users.txt 已下线:等级只存用户库,执法侧从 auth.db 动态回查` |
| `openguard/original/routes.py` | 657 行 | 702 行 | B 仍"同步写入 Access Control 规则表(users.txt)" |
| `openguard/original/auth.py` | 352 行 | 362 行 | B:`_sync_user_to_ac(...): 将用户同步写入 users.txt` |
| `openguard/original/templates/admin.html` | 873 行 | 873 行 | A:`等级以用户库为准(users.txt 已下线)` |
| `configs/modules.yaml` | 50 行 | 50 行 | **`tool_guard.block_threshold`:A=`0.87`、B=`0.4`** |
| `configs/modules.yaml.bak` | — | — | 同上 |

> `block_threshold` A=0.87 / B=0.4 值得注意:B 的判罚阈值明显更激进,可能对应同学报告里"工具安全 4 条正常样本被误拦(FPR 16.67%)"。

---

## 五、成品缺模型的根因(已定位)

两份 `.gitignore` 都有:

```
clawguard/modules/retrieval_guard/models/*          # PIGuard 被忽略
!clawguard/modules/retrieval_guard/models/.gitkeep
clawguard/modules/io_guard/original/models/
clawguard/modules/io_guard/original/model_heads/*/  # io_guard 模型头被忽略
```

`git ls-files` 实测:

| 仓库 | `model_heads` 是否被 git 跟踪 |
|---|---|
| `ClawguardV2.1` | ✅ 5 个文件全部已跟踪 |
| `LLMGate` | ❌ **未被跟踪**(输出为空) |

→ **只要从 git 打包/导出,io_guard 模型头与 PIGuard 必然丢失**,io_guard 三阶段静默降级为 `module_error → allow`。
这就是同学报告 §2.2 那条"高"问题的真因——**而且不修打包方式,每次打包都会复现**。

> 补充:`configs/modules.yaml` 里 `retrieval_guard.model_path` 指向 `models/PIGuard`,而 PIGuard 在**所有**本地载体里都不存在(713 MB 且被 gitignore),只有同学手动拷入后才测出检索安全 71.4%。

---

## 六、建议动作

| 优先级 | 动作 |
|---|---|
| P0 | **同步 A → B**:把上述 9 个文件从 `ClawguardV2.1` 同步到 `LLMGate/terminal`,让 LLMGate-FULL 产出用上新架构(users.txt 下线 + `block_threshold: 0.87`) |
| P0 | **修打包方式**:打包前把 `model_heads/` 与 `models/PIGuard` 显式纳入(或把 `.gitignore` 的这两条改成只忽略缓存),否则成品永远缺模型 |
| P1 | 统一"哪棵树是 master":现在 A/B/C 三份并存,C 已对、B 落后,建议以 `ClawguardV2.1` 为准,其余全部由它派生 |
| P2 | 把 `ClawguardV2.1-main`(0.19 MB 残包)标记为废弃,避免误用 |
| P2 | 核查后重新打包 LLMGate-FULL,复跑测试集验证 `tool_guard` FPR 与 `io_guard_content` 是否改善 |

---

## 七、附:未做的事

- **没有修改任何文件**(包括 `Downloads` 下的 zip 与报告,全程只读;所有比对在内存/临时脚本内完成)。
- **没有执行跨仓库同步**——涉及访问控制核心逻辑(users.txt 存废),等你确认方向后再做。
