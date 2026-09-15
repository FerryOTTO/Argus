# Argus Desktop (Electron + Vue 3 + MiMo Code UI) 实施方案

本方案旨在响应用户指示，在独立目录 `desktop` 下完整构建基于 **Electron + Vite + Vue 3 + Tailwind CSS + Lucide 图标** 的 Argus 桌面客户端。同时深入参考 CSDN 教程《小米MiMoCode官网颜值高？Codex：拿来吧，您嘞！1:1完美复刻～》，实现 MiMo Code（`mimo.xiaomi.com/zh/mimocode`）的 1:1 高保真设计语言，包含**鼠标擦除露图背景特效**、**打字机动效**、**Bento 卡片栅格系统**及**守护进程静默管理**。

---

## 1. 核心架构与目录规划

为保持根目录整洁，所有桌面端代码、配置文件与辅助脚本均收拢在 `argus-desktop/` 目录中：

desktop/

├── DESIGN.md                     # 参考 Google Labs 规范的 MiMo Code 设计系统文档

├── package.json                  # Electron, Vite, Vue 3, Tailwind, Lucide 依赖与启动脚本

├── vite.config.js                # Vite 打包配置，支持 Electron 渲染进程

├── tailwind.config.js            # MiMo Code 色彩 Token (#FF6900 等) 与组件扩展

├── postcss.config.js             # Tailwind CSS 处理器

├── index.html                    # 桌面端主入口

├── src/

│   ├── main/

│   │   ├── index.js              # Electron 主进程：无边框窗口、系统托盘、IPC 通信

│   │   └── daemon.js             # DaemonManager：管理 FastAPI(:8000)、Bridge(:18080)、OpenClaw(:18789)

│   ├── preload/

│   │   └── index.js              # 安全 ContextBridge 预加载脚本，暴露 window.electronAPI

│   └── renderer/

│       ├── main.js               # Vue 3 入口

│       ├── App.vue               # 顶层布局容器

│       ├── assets/

│       │   ├── style.css         # Tailwind 全局样式与 MiMo Code 专用渐变与卡片样式

│       │   └── mimo_pattern.svg  # 鼠标擦除特效底层高科技电路与矩阵纹理

│       └── components/

│           ├── MimoHeader.vue    # MiMo 风格顶部栏（拖拽区、小米橙 Logo、窗口缩放关闭控制）

│           ├── MimoHero.vue      # 英雄区（打字机字幕动效、鼠标移动擦除露出高科技背景特效）

│           ├── BentoCards.vue    # Coder-card 栅格（核心防御总开关、个人常用隐私勾选、实时阻断指标）

│           ├── SecurityRules.vue # 四级密级分配与用户/资源访问控制规则在线可视化

│           ├── TelemetryView.vue # 企业级遥测配置（OTLP/Prometheus）与永久隔离区工单审批

│           └── DaemonConsole.vue # 后台守护进程控制台（实时日志流、启动/停止/重启子进程）

---

## 2. MiMo Code 1:1 视觉复刻要点（基于 CSDN 教程与官网萃取）

1. **DESIGN.md 设计规范规范化**：
   - 主题底色：极客暗黑 `#0B0E14`、卡片背景 `#121824`、面板高亮 `#1A2234`。
   - 品牌主色：小米橙 `#FF6900`（高亮 `#FF8533`，呼吸光晕 `rgba(255, 105, 0, 0.35)`）。
   - 辅助安全色：翡翠绿 `#10B981`（安全运行）、电光青 `#00F2FE`（密级/Token）、警示红 `#EF4444`（高危阻断）。
2. **鼠标擦除露图特效（Mouse Scratch / Eraser Canvas Effect）**：
   - 采用 HTML5 Canvas 绘制遮罩层，侦测光标坐标与滑动速度，动态以径向渐变擦除上层遮罩，暴露出底层的发光赛博网格与安全拓扑线路图，带有平滑衰减淡出恢复动效。
3. **打字机字幕特效（Typewriter Effect）**：
   - 英雄区实时打字循环滚动显示：“全模态 AI 智能体安全守护”、“一键阻断 .gitconfig / .env / 私钥外泄”、“四级动态密级与安全隔离区”等高光特性。
4. **Bento 栅格卡片系统（`coder-card-grid`）**：
   - 1:1 还原 `coder-card` 结构：微距边框光晕（`hover:border-[#FF6900]/50`）、毛玻璃背景（`backdrop-blur-md`）、交互悬停浮起动画与极具质感的开关组件。

---

## 3. 守护进程协同体系（Daemon Architecture）

- **双击即用**：Electron 启动后，主进程 `DaemonManager` 检测后台服务健康状态（`http://127.0.0.1:8000/health` 等）；若未运行，则利用 `child_process.spawn` 静默启动 FastAPI、Bridge 与 OpenClaw。
- **IPC 双向桥接**：
  - `start-all-services` / `stop-all-services` / `restart-service`
  - `get-service-status` (获取 PID、内存与运行状态)
  - `on-daemon-log` (实时推送进程日志到前端控制台)
- **安全生命周期**：在 Electron `before-quit` 事件中，主进程向子进程发送终止信号（Windows 平台采用 `taskkill /pid ... /T /F`），确保无孤儿幽灵进程滞留。

---

## 4. 实施阶段计划

- **第一阶段：独立目录创建与设计系统建立**
  - 创建 `desktop`。
  - 编写 `DESIGN.md`，定义 MiMo Code 调色板、圆角、阴影、光晕与动画 Token。
- **第二阶段：工程脚手架配置**
  - 安装并配置 `package.json`、`vite.config.js`、`tailwind.config.js`、`postcss.config.js`。
  - 配置 Electron 主进程与预加载脚本。
- **第三阶段：1:1 MiMo Code 前端核心组件开发**
  - 实现 Canvas 鼠标擦除露图特效与 Typewriter 打字机组件。
  - 实现 Bento 栅格防御卡片与个人版快速勾选框。
  - 整合四级密级与隔离区、遥测配置视图。
- **第四阶段：Electron 守护联动与运行验证**
  - 联调主进程子进程守护逻辑。
  - 启动应用并验证界面渲染与交互功能。

---

## 5. 验证计划

1. **构建与启动验证**：
   - 在 `argus-desktop` 目录下运行 `npm install` 与 `npm run build` / `npm run dev`，确保无报错。
2. **视觉保真验证**：
   - 验证无边框窗口渲染、MiMo Code 小米橙色调、打字机动效、鼠标移动擦除露图特效及 Bento 卡片 hover 光晕。
3. **功能验证**：
   - 测试防御总开关与快速隐私保护勾选项的切换。
   - 测试子进程状态检测与控制台日志输出。
