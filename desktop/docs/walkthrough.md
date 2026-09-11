# Argus Desktop 桌面客户端实施与验证记录

依据您的要求，所有桌面端代码与辅助脚本均收拢在全新的独立目录 `e:/tiaozhanbei/MAC/argus-desktop` 中，未在父工作区根目录中遗留任何杂乱脚本。同时，深入汲取 CSDN 教程《小米MiMoCode官网颜值高？Codex：拿来吧，您嘞！1:1完美复刻～》的设计精髓，完成了小米 **MiMo Code**（`mimo.xiaomi.com/zh/mimocode`）1:1 高保真设计与守护体系的工程构建。

---

## 1. 核心成果概览

### 1.1 独立整洁的目录工程结构

所有构建脚本、配置文件、设计规范与源码均独立闭环在 `argus-desktop/` 内：

- **`DESIGN.md`**：参照 Google Labs 规范建立的 MiMo Code 设计规范文档，固化小米橙色彩 Token（`#FF6900`）、极客深空灰阶（`#0B0E14` / `#121824`）与 `coder-card` 交互标准。
- **`src/main/`**：Electron 主进程无边框窗口、系统原生拖拽、IPC 通信与后台 `DaemonManager`。
- **`src/preload/`**：安全预加载脚本，向渲染层暴露标准的 `window.electronAPI` 上下文桥。
- **`src/renderer/`**：基于 **Vue 3 + Tailwind CSS + Lucide Icons** 的高保真组件体系。

---

## 2. MiMo Code 1:1 标志性视觉与交互还原

### 2.1 极简防护与鼠标擦除露图主控台

- **鼠标擦除露图动效 (Mouse Scratch Reveal)**：英雄区 Canvas 覆盖层在光标滑过时实时擦除，随动呈现底层潜伏的发光赛博电路拓扑图，并辅以自然渐变回填。
- **打字机字幕动效 (Typewriter)**：实时滚动播放核心防护使命。
- **Bento 栅格卡片 (`coder-card`)**：零信任主动防御总开关、个人极简隐私勾选（`.gitconfig`/`.env`/SSH密钥/高危命令）、集群健康指示与审计小流。

---

### 2.2 密级与访问控制规则矩阵

- **四级安全密级总览卡**：L1 公开、L2 内部、L3 机密、L4 绝密。
- **规则在线编辑**：提供搜索、新建规则弹窗、匹配模式与生效动作配置。

---

### 2.3 企业遥测与近永久隔离区工单流

- **企业级 OTLP 遥测**：支持 OTLP Collector 终结点、Prometheus 拉取路径与自适应采样率。
- **近永久隔离区 (Quarantine Vault)**：对高危涉密文件进行物理隔离，提供管理员工单审批解封与深层覆写永久粉碎操作。

---

### 2.4 后台守护进程集群实时控制台

- **守护集群双向掌控**：可视化监控与一键重启 FastAPI (:8000)、Bridge (:18080) 与 OpenClaw (:18789)。
- **实时日志流水**：支持高亮阻断告警、进程启动事件与滚动展示。

---

## 3. 运行与验证指令

在 `e:/tiaozhanbei/MAC/argus-desktop` 目录下：

bash

# 启动 Vite 并自动拉起 Electron 桌面无边框应用

npm run app:dev

# 或直接运行独立桌面客户端

npm start

# 构建前端静态产物

npm run build
