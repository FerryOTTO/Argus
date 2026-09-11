# Skill 压缩包制作规范（SKILL_CREATION）

> **读者**：在 LLMGate「扩展管理 → Skill 分发」上传 skill 包的管理员 / skill 制作者。
> 本文说明 skill 压缩包（zip）的格式要求与制作步骤；服务端按本规范严格校验，
> 不合规的包会被拒绝上传。
> 客户端（终端侧）如何接收安装见 [CLIENT.md](./CLIENT.md)。

---

## 1. 什么是“Skill 包”

一个 Skill 包 = 一个 **zip 压缩包**，内含：

- `SKILL.md` —— **必须**。技能说明正文，须带 YAML frontmatter；
- 其余资源（脚本/模板/参考文档）—— 可选，与 SKILL.md 放在同一 skill 目录下。

格式对齐 OpenClaw / 通用 Agent Skill 约定：一个目录 = 一个 skill，
`SKILL.md` 的 frontmatter 声明 `name` 与 `description`。

> 服务端把 zip **原样存储、整包下传**，只解压 `SKILL.md` 用于校验与生成内容预览
> （详情抽屉/列表里看到的前 N 字符即正文摘要）；安装动作发生在终端侧。

## 2. 允许的两种 zip 布局

### 布局 B（推荐）：单目录 = skill 名

```
my-skill.zip
└── pdf-briefing/            ← 目录名即 skill 名（与 frontmatter name 一致）
    ├── SKILL.md
    ├── scripts/
    │   └── parse.py
    └── assets/template.md
```

### 布局 A：顶层仅一个 SKILL.md

```
my-skill.zip
└── SKILL.md                 ← frontmatter name 声明 skill 名（必填）
```

规则速查：

| 规则 | 要求 |
|------|------|
| 顶层结构 | **单目录**（目录名 = skill 名），**或**仅一个 SKILL.md 直接放在顶层 |
| 目录/文件混放 | 不允许：SKILL.md 在顶层时不能再有其它文件/目录；反之顶层不能散落文件 |
| 打包垃圾 | `__MACOSX/`、`.DS_Store`、`Thumbs.db` 会被自动忽略（可不清除，但建议清理） |
| frontmatter name | 与目录名**一致**时合法；不一致 → 拒绝；布局 A 时必须声明且合法 |

## 3. SKILL.md frontmatter

文件开头必须是 `---` 分隔的 YAML frontmatter：

```markdown
---
name: pdf-briefing
description: 将 PDF 文档转成结构化简报，供后续问答使用
---

<!-- 这里是给智能体看的技能说明正文：何时使用、如何调用、注意事项 -->
```

| 字段 | 必填 | 约束 |
|------|------|------|
| `name` | 布局 A 必填；布局 B 强烈建议 | 命名规则：字母/数字开头，仅含 `[A-Za-z0-9_-]`（如 `pdf-briefing`、`chart2png`）；与服务端目录/上传键一致则视为“同名更新” |
| `description` | 否 | 一句话能力描述；不写则上传时可在控制台“说明”里补充，列表用控制台说明 |

命名规则与 OpenClaw 技能目录安全命名一致：

```
^[A-Za-z0-9][A-Za-z0-9_-]*$
✓ 合法：pdf-briefing、chart2png、io_guard_demo、v1
✗ 非法：中文名、带空格/点号（a.b）、带斜杠、以 - 或 _ 开头、. 开头（隐藏目录）
```

`description` 建议一句话 ≤ 200 字符，避免把整份说明塞进 frontmatter。

## 4. 大小与数量上限（服务端校验）

| 项 | 上限 | 说明 |
|----|------|------|
| zip 文件大小 | **2 MB** | 超出拒绝上传（前端会先提示） |
| 包内条目数 | **200 个** | 文件 + 目录合计 |
| 解压后总大小 | **16 MB** | 防止 zip bomb；按 zip 声明的解压大小累计 |
| SKILL.md 大小 | **512 KB** | 服务端只读取它做摘要 |

技能依赖的大模型权重/语料等大文件**不适合**走此通道——服务端存储 + 终端整包
拉取，请保持轻量（多数 skill < 200KB）。

## 5. 制作示例

### 目录准备（布局 B）

```bash
# 1. 建目录（目录名 = skill 名）
mkdir -p pdf-briefing/scripts

# 2. 写 SKILL.md（frontmatter 见 §3）
cat > pdf-briefing/SKILL.md <<'EOF'
---
name: pdf-briefing
description: 将 PDF 文档转成结构化简报，供后续问答使用
---
# PDF Briefing
在用户给出 PDF 文件路径时：
1. 用 scripts/parse.py 提取文本与页码；
2. 生成 {章节, 要点, 风险} 结构的简报；
3. 简报中引用页码时给出原文上下文。
EOF

# 3. 放脚本资源
cat > pdf-briefing/scripts/parse.py <<'EOF'
#!/usr/bin/env python3
print("parser stub")
EOF

# 4. 打包（务必在父目录执行，使包内首层是 pdf-briefing/）
cd .. && zip -r pdf-briefing.zip pdf-briefing
unzip -l pdf-briefing.zip   # 自查：首层应为 pdf-briefing/ 目录
```

### 布局 A（单文件 skill）

```bash
cat > SKILL.md <<'EOF'
---
name: date-utils
description: 日期计算小工具集
---
当用户询问日期差、工作日推算时给出 Python 代码片段……
EOF
zip date-utils.zip SKILL.md
```

## 6. 上传、发布与分发

1. 控制台 → **扩展管理 → Skill 分发** → 右上「上传 Skill 包」，选择 zip，
   可填写“说明”（覆盖展示文案；留空则用 frontmatter description）。
2. 服务端即时校验（布局/命名/大小/frontmatter 一致性），失败会给出原因提示
   （见 §7），修正后重传即可。
3. 发布后点包的「**分发**」勾选目标终端 → 保存；终端在下次心跳感知后拉取安装。
4. **同名再上传 = 发布新版本**：内容替换、`version +1`，已分发终端保持分发，
   自动按版本差增量更新；列表“更新包”按钮即此操作。
5. 「**新终端自动分发**」横幅（页面顶部）：开关 + 选择默认包，保存后**之后新注册**
   的终端自动获得分配；存量终端不受影响。
6. 删除包会连带解除全部分发；已安装到终端的本地副本服务端不回收。

## 7. 上传被拒的常见原因对照

| 错误提示 | 原因与修正 |
|----------|-----------|
| 顶层须为单个目录…或仅一个 SKILL.md | 包内顶层有多目录/散落文件；把内容统一收进一个目录（目录名 = skill 名） |
| 顶层直接放置 SKILL.md 时不能附带其它文件或目录 | 布局 A 混入布局 B；二选一：全收进目录，或只留 SKILL.md 在顶层 |
| 目录名不合法：须以字母/数字开头 | 目录名含中文/空格/点/连字符开头等；按 §3 命名规则重命名目录 |
| frontmatter name 与目录名不一致 | 修 `SKILL.md` 的 `name:` 与目录名一致（或反过来） |
| 未找到 SKILL.md | 包内必须有 SKILL.md（顶层或单目录内） |
| 压缩包/解压总量/条目数/SKILL.md 超限 | 精简内容或拆分多个 skill 包（§4） |
| 无法解析 zip | 文件损坏或非 zip；重新打包（`zip -r` 而非 store/rar） |
