# OpenGuard — 多用户认证网关

为 OpenClaw 提供 JWT 多用户认证 + Agent 隔离 + Web 聊天界面。

## 在 Clawguard 中的位置

用户 → OpenGuard (:3000) → OpenClaw (:18789) → Clawguard (:8000)

OpenGuard 在代理请求时注入 X-Clawguard-* 身份头（对接方案 7.7 节）。

## 快速启动

### 1. 生成 RSA 密钥

```bash
cd openguard/original
mkdir -p keys
openssl genrsa -out keys/private.pem 2048
openssl rsa -in keys/private.pem -pubout -out keys/public.pem
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
npm install ws
```

### 4. 启动（3 个终端）

| 顺序 | 命令 | 端口 |
|------|------|------|
| 1 | openclaw gateway run | 18789 |
| 2 | node bridge.js | 18080 |
| 3 | python main.py | 3000 |

访问 http://localhost:3000

### 5. 演示用测试用户

```bash
python seed.py -n 10 --admin adminuser
# 所有用户密码: test12345
```

## 注入的身份头

| Header | 说明 |
|--------|------|
| X-Clawguard-User-Id | 用户 ID |
| X-Clawguard-Session-Id | 会话 ID |
| X-Clawguard-Trace-Id | 链路追踪 ID |
| X-Clawguard-Role | 角色 |
| X-Clawguard-Security-Level | 安全级别 |

## 运行测试

```bash
python test_clawguard_integration.py
```
