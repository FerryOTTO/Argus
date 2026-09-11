// bridge.js — 持久连接 OpenClaw WebSocket 桥接（agentClaw 风格）
// 启动时完成 Ed25519 握手，保持长连接，所有客户端复用同一条 WS。
//
// 特性（学习 agentClaw 后新增）：
//   1. 事件按 session 前缀过滤：chat.* / agent 事件只发给对应 agent 的客户端，防止多用户串消息
//   2. 客户端连接需 HMAC 签名（sig = HMAC(bridgeToken, "openguard:<agentId>:<ts>")[:16]），防未授权接入
//   3. HTTP API：POST /api/agents（注册即建 agent）、GET /health

const http = require("http");
const WebSocket = require("ws");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const os = require("os");

const OPENCLAW_WS = "ws://localhost:18789/ws";
const LISTEN_PORT = parseInt(process.argv[2]) || 18080;
const LISTEN_HOST = process.env.BRIDGE_HOST || "127.0.0.1"; // 仅本机暴露，防止远程未授权接入
const SIG_SKEW_MS = 600_000; // 签名时间戳允许偏移（放宽到 10min 防时钟漂移）

// --------------- 配置读取 ---------------

function readEnvValue(filePath, key) {
  try {
    const content = fs.readFileSync(filePath, "utf8");
    for (const line of content.split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
      if (m && m[1] === key) {
        let v = m[2].trim();
        if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
          v = v.slice(1, -1);
        }
        return v;
      }
    }
  } catch {}
  return "";
}

// Gateway token（OpenClaw 网关 token 认证）
let GATEWAY_TOKEN = "";
try {
  const openclawStateDir = process.env.OPENCLAW_STATE_DIR
    || process.env.OPENCLAW_HOME
    || path.join(os.homedir(), ".openclaw");
  const cfg = JSON.parse(fs.readFileSync(
    path.join(openclawStateDir, "openclaw.json"), "utf8"
  ));
  GATEWAY_TOKEN = cfg?.gateway?.auth?.token || "";
  console.log(`[bridge] Gateway token: ${GATEWAY_TOKEN ? GATEWAY_TOKEN.slice(0, 10) + "..." : "NOT FOUND"}`);
} catch (e) { console.log("[bridge] Could not read gateway token"); }

// Bridge token（与 OpenGuard 共享的 HMAC 密钥，用于客户端接入认证）
const BRIDGE_TOKEN = process.env.BRIDGE_TOKEN
  || readEnvValue(path.join(__dirname, ".env"), "BRIDGE_TOKEN")
  || "";
if (!BRIDGE_TOKEN) {
  console.error("[bridge] BRIDGE_TOKEN not found in .env — client auth disabled (loopback only)");
}

// --------------- Ed25519 device auth ---------------
const ED25519_SPKI_PREFIX = Buffer.from("302a300506032b6570032100", "hex");
function b64url(b) { return b.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); }

const DEVICE_KEY_FILE = path.join(__dirname, "data", "bridge_device.json");

async function getOrCreateDevice() {
  try {
    const saved = JSON.parse(fs.readFileSync(DEVICE_KEY_FILE, "utf8"));
    const subtleKey = await crypto.subtle.importKey("jwk", saved.jwk, "Ed25519", false, ["sign"]);
    console.log(`[bridge] Loaded device: ${saved.deviceId.slice(0, 16)}...`);
    return { deviceId: saved.deviceId, pubB64: saved.pubB64, subtleKey };
  } catch {}
  const { publicKey, privateKey } = crypto.generateKeyPairSync("ed25519");
  const pubDer = publicKey.export({ type: "spki", format: "der" });
  const pubRaw = pubDer.subarray(ED25519_SPKI_PREFIX.length);
  const deviceId = crypto.createHash("sha256").update(pubRaw).digest("hex");
  const pubB64 = b64url(pubRaw);
  const privDer = privateKey.export({ type: "pkcs8", format: "der" });
  const subtleKey = await crypto.subtle.importKey("pkcs8", privDer, "Ed25519", true, ["sign"]);
  const jwk = await crypto.subtle.exportKey("jwk", subtleKey);
  fs.mkdirSync(path.dirname(DEVICE_KEY_FILE), { recursive: true });
  fs.writeFileSync(DEVICE_KEY_FILE, JSON.stringify({ deviceId, pubB64, jwk }));
  console.log(`[bridge] New device: ${deviceId.slice(0, 16)}...`);
  return { deviceId, pubB64, subtleKey };
}

// --------------- Persistent OpenClaw connection ---------------
let openclawWs = null;
let handshakeDone = false;
let device = null;
const clients = new Set();
const pending = new Map(); // reqId -> {resolve, reject, timer}

function rpcRequest(method, params, timeoutMs = 60_000) {
  return new Promise((resolve, reject) => {
    if (!openclawWs || openclawWs.readyState !== WebSocket.OPEN || !handshakeDone) {
      reject(new Error("OpenClaw not connected"));
      return;
    }
    const id = crypto.randomUUID();
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`RPC timeout: ${method}`));
    }, timeoutMs);
    pending.set(id, { resolve, reject, timer });
    openclawWs.send(JSON.stringify({ type: "req", id, method, params }));
  });
}

async function connectToOpenclaw() {
  device = device || await getOrCreateDevice();
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(OPENCLAW_WS);
    openclawWs = ws;
    handshakeDone = false;

    ws.on("open", () => console.log("[bridge] OpenClaw WS open"));

    ws.on("message", async (data) => {
      let msg;
      try {
        msg = JSON.parse(data.toString());
      } catch {
        return;
      }

      // Connect handshake: shared token + Ed25519 device identity. OpenClaw >= 2026.4.x
      // clears unbound scopes for token-only connections (no device identity), which
      // caused "missing scope: operator.write/read" on agent calls. The device
      // signature payload (v3) must include the gateway token in field 8.
      if (msg.type === "event" && msg.event === "connect.challenge") {
        const platform = process.platform;
        const nonce = msg.payload.nonce;
        const nowMs = Date.now();
        // v3: deviceId|clientId|clientMode|role|scopes|signedAt|token|nonce|platform|deviceFamily
        const authPayload = [
          "v3", device.deviceId, "gateway-client", "backend",
          "operator", "operator.admin", String(nowMs),
          GATEWAY_TOKEN, nonce, platform, platform,
        ].join("|");
        const sig = await crypto.subtle.sign("Ed25519", device.subtleKey, Buffer.from(authPayload, "utf8"));
        ws.send(JSON.stringify({
          type: "req", id: crypto.randomUUID(), method: "connect",
          params: {
            minProtocol: 3, maxProtocol: 10, role: "operator", scopes: ["operator.admin"],
            auth: { token: GATEWAY_TOKEN },
            client: { id: "gateway-client", displayName: "OpenGuard Bridge", version: "1.0.0", platform, mode: "backend", deviceFamily: platform },
            device: { id: device.deviceId, publicKey: device.pubB64, signature: b64url(Buffer.from(sig)), signedAt: nowMs, nonce },
          },
        }));
        return;
      }

      // Handshake result
      if (!handshakeDone && msg.type === "res") {
        if (msg.ok) {
          handshakeDone = true;
          console.log("[bridge] Handshake OK - persistent connection established");
          resolve();
          for (const c of clients) {
            if (c.readyState === WebSocket.OPEN) {
              c.send(JSON.stringify({ type: "event", event: "bridge.ready", payload: {} }));
            }
          }
        } else {
          const err = msg.error?.message || "unknown";
          const protoInfo = `(payload protoInfo: ${JSON.stringify(msg.error?.payload || msg.payload || {})})`;
          console.log(`[bridge] Handshake FAILED: ${err} ${protoInfo}`);
          reject(new Error(err + " " + protoInfo));
        }
        return;
      }

      // RPC 响应：按 id 匹配 pending 请求
      if (msg.type === "res" && msg.id && pending.has(msg.id)) {
        const p = pending.get(msg.id);
        pending.delete(msg.id);
        clearTimeout(p.timer);
        if (msg.ok) p.resolve(msg.payload ?? {});
        else p.reject(new Error(msg.error?.message || "RPC failed"));
        return;
      }

      // 事件转发：按 session 前缀过滤，防止多用户串消息
      if (handshakeDone) {
        const raw = data.toString();
        for (const c of clients) {
          if (c.readyState !== WebSocket.OPEN) continue;
          if (shouldDeliverToClient(c, msg)) c.send(raw);
        }
      }
    });

    ws.on("close", (code) => {
      console.log(`[bridge] OpenClaw disconnected (code=${code})`);
      handshakeDone = false;
      for (const [id, p] of pending) {
        clearTimeout(p.timer);
        p.reject(new Error("OpenClaw disconnected"));
      }
      pending.clear();
      for (const c of clients) {
        if (c.readyState === WebSocket.OPEN) {
          c.send(JSON.stringify({ type: "event", event: "bridge.disconnected", payload: { code } }));
        }
      }
      setTimeout(() => {
        console.log("[bridge] Reconnecting...");
        connectToOpenclaw().catch(() => {});
      }, 2000);
    });

    ws.on("error", (err) => {
      console.log(`[bridge] OpenClaw error: ${err.message}`);
      if (!handshakeDone) reject(err);
    });
  });
}

// --------------- 事件过滤（agentClaw 风格：session 前缀隔离） ---------------

function eventSessionKey(msg) {
  const p = msg.payload || {};
  if (typeof p.sessionKey === "string" && p.sessionKey) return p.sessionKey;
  const d = p.data || {};
  if (typeof d.sessionKey === "string" && d.sessionKey) return d.sessionKey;
  if (typeof d.session === "string" && d.session) return d.session;
  if (typeof d.key === "string" && d.key) return d.key;
  return "";
}

function shouldDeliverToClient(client, msg) {
  const evt = msg.event || "";
  // chat.* 与 agent 事件按 sessionKey 前缀过滤
  if (evt.startsWith("chat.") || evt === "agent") {
    const sk = eventSessionKey(msg);
    if (sk.startsWith("agent:")) {
      // 网关会将 sessionKey 中的 agent id 归一化为小写，这里必须大小写不敏感比较
      return Boolean(client.agentId) && sk.toLowerCase().startsWith(`agent:${client.agentId.toLowerCase()}:`);
    }
    if (evt === "agent") {
      // agent 流式事件（数据在 payload.data 下，sessionKey 通常不在 payload 顶层）：
      // 无法定位归属时绝不广播给所有人，仅当报文内出现该客户端的 agentId 时才投递（fail-closed）。
      if (!client.agentId) return false;
      return JSON.stringify(msg).includes(client.agentId);
    }
    // 无 agent: 前缀的 legacy 会话照发
    return true;
  }
  // 非聊天事件全量广播
  return true;
}

// --------------- 客户端接入认证（HMAC 防篡改） ---------------

function verifyClientSig(agentId, ts, sig) {
  if (!BRIDGE_TOKEN) return false; // 未配置 token：拒绝所有接入（fail-closed，禁止无认证开放）
  if (!agentId || !ts || !sig) return false;
  const tsNum = parseInt(ts, 10);
  if (!Number.isFinite(tsNum)) return false;
  if (Math.abs(Date.now() - tsNum) > SIG_SKEW_MS) return false;
  const expected = crypto
    .createHmac("sha256", BRIDGE_TOKEN)
    .update(`openguard:${agentId}:${tsNum}`)
    .digest("hex")
    .slice(0, 16);
  const ok = crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(sig.slice(0, 16)));
  return ok;
}

// --------------- HTTP API + WS 客户端服务 ---------------

// 解析 agent 工作区目录：main → ~/.openclaw/workspace，其他 → ~/.openclaw/workspace-<agentId>
function getAgentWorkspacePath(agentId) {
  const home = require("os").homedir();
  if (!agentId || agentId === "main") {
    return path.join(home, ".openclaw", "workspace");
  }
  return path.join(home, ".openclaw", `workspace-${agentId}`);
}

// 防路径穿越：relPath 必须严格落在 rootDir 之内
function sanitizePath(relPath, rootDir) {
  const root = path.resolve(rootDir);
  const abs = path.resolve(root, relPath);
  if (abs === root || !abs.startsWith(root + path.sep)) return null;
  return abs;
}

// 技能文件落地：PUT /api/agents/:agentId/files/:path 写文件，DELETE 删文件/目录
function handleAgentFile(req, res, agentId, relPath) {
  // 认证：仅 OpenGuard（loopback + X-Bridge-Token）；无 token 时拒绝
  if (!BRIDGE_TOKEN || req.headers["x-bridge-token"] !== BRIDGE_TOKEN) {
    res.writeHead(403, { "content-type": "application/json" });
    res.end(JSON.stringify({ detail: "invalid bridge token" }));
    return;
  }
  // agentId 必须是安全目录名，防注入
  if (!/^[A-Za-z0-9_-]+$/.test(agentId)) {
    res.writeHead(400, { "content-type": "application/json" });
    res.end(JSON.stringify({ detail: "invalid agentId" }));
    return;
  }
  const rootDir = getAgentWorkspacePath(agentId);
  const absPath = sanitizePath(relPath, rootDir);
  if (!absPath) {
    res.writeHead(400, { "content-type": "application/json" });
    res.end(JSON.stringify({ detail: "invalid path" }));
    return;
  }

  if (req.method === "DELETE") {
    try {
      if (!fs.existsSync(absPath)) {
        res.writeHead(404, { "content-type": "application/json" });
        res.end(JSON.stringify({ detail: "not found" }));
        return;
      }
      fs.rmSync(absPath, { recursive: true, force: true });
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ ok: true }));
    } catch (err) {
      res.writeHead(500, { "content-type": "application/json" });
      res.end(JSON.stringify({ detail: err.message }));
    }
    return;
  }

  // PUT
  let body = "";
  req.on("data", (chunk) => {
    body += chunk;
    if (body.length > 1024 * 1024) req.destroy();
  });
  req.on("end", () => {
    try {
      const payload = JSON.parse(body || "{}");
      if (typeof payload.content !== "string") {
        res.writeHead(400, { "content-type": "application/json" });
        res.end(JSON.stringify({ detail: "content must be a string" }));
        return;
      }
      fs.mkdirSync(path.dirname(absPath), { recursive: true });
      fs.writeFileSync(absPath, payload.content, "utf-8");
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ ok: true, path: relPath }));
    } catch (err) {
      res.writeHead(500, { "content-type": "application/json" });
      res.end(JSON.stringify({ detail: err.message }));
    }
  });
}

function handleHttp(req, res) {
  const url = new URL(req.url, `http://127.0.0.1:${LISTEN_PORT}`);

  if (req.method === "GET" && url.pathname === "/health") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ status: handshakeDone ? "ok" : "connecting", clients: clients.size }));
    return;
  }

  if (req.method === "POST" && url.pathname === "/api/agents") {
    // 注册即建 agent：由 OpenGuard 调用，凭 X-Bridge-Token 认证（无 token 时拒绝）
    if (!BRIDGE_TOKEN || req.headers["x-bridge-token"] !== BRIDGE_TOKEN) {
      res.writeHead(403, { "content-type": "application/json" });
      res.end(JSON.stringify({ detail: "invalid bridge token" }));
      return;
    }
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > 1024 * 1024) req.destroy();
    });
    req.on("end", async () => {
      try {
        const payload = JSON.parse(body || "{}");
        const agentId = String(payload.agentId || "").trim();
        const name = String(payload.name || agentId).trim();
        if (!agentId) {
          res.writeHead(400, { "content-type": "application/json" });
          res.end(JSON.stringify({ detail: "agentId is required" }));
          return;
        }
        // OpenClaw 的 agents.create 以 name 作为 agent id
        const params = {
          name: agentId,
          workspace: payload.workspace
            || path.join(require("os").homedir(), ".openclaw", `workspace-${agentId}`),
        };
        const result = await rpcRequest("agents.create", params, 30_000);
        console.log(`[bridge] agent created: ${agentId}`);
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ ok: true, agentId, result }));
      } catch (err) {
        console.error(`[bridge] agents.create failed: ${err.message}`);
        res.writeHead(500, { "content-type": "application/json" });
        res.end(JSON.stringify({ ok: false, detail: err.message }));
      }
    });
    return;
  }

  // 技能文件落地端点：PUT/DELETE /api/agents/:agentId/files/:path
  const fileMatch = url.pathname.match(/^\/api\/agents\/([^/]+)\/files\/(.+)$/);
  if (fileMatch && (req.method === "PUT" || req.method === "DELETE")) {
    handleAgentFile(req, res, decodeURIComponent(fileMatch[1]), decodeURIComponent(fileMatch[2]));
    return;
  }

  res.writeHead(404, { "content-type": "application/json" });
  res.end(JSON.stringify({ detail: "not found" }));
}

const server = http.createServer(handleHttp);
const wss = new WebSocket.Server({ server });

server.listen(LISTEN_PORT, LISTEN_HOST, () => {
  console.log(`[bridge] Listening on http+ws://${LISTEN_HOST}:${LISTEN_PORT}`);
});

wss.on("connection", (clientWs, req) => {
  // 解析连接参数：agentId、ts、sig（HMAC 防篡改）
  let agentId = "";
  try {
    const url = new URL(req.url, `http://127.0.0.1:${LISTEN_PORT}`);
    agentId = url.searchParams.get("agentId") || "";
    const ts = url.searchParams.get("ts") || "";
    const sig = url.searchParams.get("sig") || "";
    if (!verifyClientSig(agentId, ts, sig)) {
      console.log(`[bridge] Rejected client (bad sig): agent=${agentId || "?"}`);
      clientWs.close(4003, "Invalid openguard signature");
      return;
    }
  } catch {
    clientWs.close(4003, "Invalid openguard signature");
    return;
  }

  clientWs.agentId = agentId;
  clients.add(clientWs);
  console.log(`[bridge] Client connected (agent=${agentId || "?"}, ${clients.size} total)`);

  if (handshakeDone) {
    clientWs.send(JSON.stringify({ type: "event", event: "bridge.ready", payload: {} }));
  }

  // Forward client messages to OpenClaw
  clientWs.on("message", (data) => {
    if (openclawWs && openclawWs.readyState === WebSocket.OPEN && handshakeDone) {
      openclawWs.send(data.toString());
    }
  });

  clientWs.on("close", () => {
    clients.delete(clientWs);
    console.log(`[bridge] Client disconnected (${clients.size} total)`);
  });
});

// --------------- Start ---------------
(async () => {
  try {
    await connectToOpenclaw();
    console.log("[bridge] Ready - persistent connection active");
  } catch (e) {
    console.error(`[bridge] Startup failed: ${e.message}`);
    process.exit(1);
  }
})();
