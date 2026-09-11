# Clawguard Desktop 桌面客户端 (MiMo Code 1:1 高保真版)

Clawguard 智能安全智能体桌面守护客户端，采用 **Electron + Vite + Vue 3 + Tailwind CSS + Lucide Icons** 构建，深度复刻小米 **MiMo Code** 官方（`mimo.xiaomi.com/zh/mimocode`）的设计美学与核心交互特效。

---

## 一、MiMo Code 核心设计与交互亮点

1. **鼠标擦除露图动效 (Mouse Scratch Reveal Background)**：
   - 英雄区采用双层渲染技术，上层覆盖暗色微距网格遮罩，底层潜伏发光赛博电路拓扑图；
   - 鼠标滑过时触发高科技径向粒子擦除，随光标动态露出底层发光线路与节点，并在鼠标移开后自然衰减回填。
2. **打字机字幕动效 (Typewriter Hero)**：
   - 实时字符级打字循环滚动显示核心安全使命，配合发光橙色光标动效。
3. **Bento 栅格卡片系统 (`coder-card-grid`)**：
   - 1:1 复刻 `coder-card` 视觉结构，具备 16px 圆角、微距边框光晕（`hover:border-[#FF6900]/45`）、毛玻璃暗夜质感与呼吸微阴影。
4. **单机无缝守护与双版本切换**：
   - **个人版**：极简开箱即用，提供核心防御总开关与 4 项核心资产（`~/.gitconfig`、`.env`、SSH 密钥、高危 Shell）快速勾选拦截；
   - **企业版**：开放标准 OpenTelemetry (OTLP) 遥测配置与近永久隔离区工单人工复核解封流转。

---

## 二、架构全景图

```
clawguard-desktop/
├── DESIGN.md                 # MiMo Code 官方设计系统规范（参照 Google Labs 规范）
├── package.json              # 项目依赖与启动脚本
├── vite.config.js            # Vite 配置文件
├── tailwind.config.js        # MiMo 色彩与发光样式扩展
├── postcss.config.js         # Tailwind CSS 处理器
├── index.html                # 桌面端主入口
├── scripts/
│   └── dev.js                # 一键联动启动 Vite 与 Electron
└── src/
    ├── main/
    │   ├── index.js          # Electron 主进程：无边框窗口、原生拖拽、IPC 通信
    │   └── daemon.js         # DaemonManager：静默拉起与托管 FastAPI/Bridge/OpenClaw
    ├── preload/
    │   └── index.js          # 安全上下文桥接脚本 (window.electronAPI)
    └── renderer/
        ├── main.js           # Vue 3 入口
        ├── App.vue           # 根组件与顶部标签页路由
        ├── assets/
        │   ├── style.css     # 全局样式、coder-card 样式与平滑滚动条
        │   ├── logo.svg      # 小米橙风格发光盾牌徽章
        │   └── cyber_bg.svg  # 底层发光赛博拓扑图
        └── components/
            ├── MimoHeader.vue        # 顶部栏（品牌 Logo、窗口控制、版本切换）
            ├── MimoHero.vue          # 英雄区（Canvas 鼠标擦除露图 + 打字机）
            ├── BentoCards.vue        # 核心防御卡片与个人快速勾选屏障
            ├── SecurityRules.vue     # 四级密级 (L1-L4) 与访问控制规则矩阵
            ├── TelemetryView.vue     # 企业级 OTLP 遥测与近永久隔离区工单审批
            └── DaemonConsole.vue     # 后台守护进程集群实时日志流控制台
```

---

## 三、快速开始

### 1. 安装依赖
由于国内网络环境对 Electron 二进制下载有特殊要求，项目已内置国内镜像源 `.npmrc`：
```bash
npm install
```

### 2. 开发模式（浏览器调试）
启动 Vite 开发服务器：
```bash
npm run dev
```
访问 `http://localhost:5173` 即可实时热重载调试。

### 3. 桌面客户端模式（Electron 运行）
启动 Vite 并自动拉起 Electron 桌面无边框窗口：
```bash
npm run app:dev
```
或者若已构建产物，可直接运行：
```bash
npm start
```

### 4. 前端生产打包
编译打包静态资源至 `dist/`：
```bash
npm run build
```

---

## 四、守护进程管理说明

桌面端主进程内置 `DaemonManager`，在客户端启动时会自动探测并启动后台三大守护核心：
1. **Clawguard API**：`py -m uvicorn clawguard.api.main:app --port 8000`
2. **OpenGuard Bridge**：`node openguard/original/bridge.js` (:18080)
3. **OpenClaw Gateway**：`openclaw gateway run` (:18789)

当用户退出桌面应用时，主进程将通过操作系统进程树管理自动回收所有后台子进程，确保零资源占用与无孤儿幽灵进程滞留。
