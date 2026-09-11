import assert from "node:assert/strict";
import test from "node:test";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import plugin from "../dist/index.js";

const FIXTURES_DIR = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "fixtures",
);
const fixtureIdentity = (name) => path.join(FIXTURES_DIR, name);

function securityResponse(stage, action, data = null) {
  return {
    trace_id: "trace-1",
    stage,
    action,
    risk_score: action === "allow" ? 0 : 0.95,
    reason: `${stage}_${action}`,
    data,
    module_results: [],
  };
}

function jsonResponse(value) {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function sessionResponse() {
  return jsonResponse({ status: "ok", session: {} });
}

function registerPlugin(config = {}) {
  const handlers = new Map();
  const logs = [];
  plugin.register({
    pluginConfig: {
      argusUrl: "http://127.0.0.1:8000",
      timeoutMs: 10000,
      failMode: "closed",
      protectedTools: ["web_search", "web_fetch"],
      ...config,
    },
    logger: {
      info: (message) => logs.push(["info", message]),
      warn: (message) => logs.push(["warn", message]),
      error: (message) => logs.push(["error", message]),
    },
    on(name, handler) {
      handlers.set(name, handler);
    },
    registerAgentToolResultMiddleware() {},
    registerTextTransforms() {},
  });
  return { handlers, logs };
}

function mockFetchAllow(t) {
  t.mock.method(globalThis, "fetch", async (url) =>
    url.includes("/tool/session/")
      ? sessionResponse()
      : jsonResponse(securityResponse("input", "allow")),
  );
}

function writeIdentityFile(dir, payload) {
  const file = path.join(dir, `identity-${Date.now()}-${Math.random().toString(16).slice(2)}.json`);
  fs.writeFileSync(file, JSON.stringify(payload));
  return file;
}

test("same user reuses a session without isolation", async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cg-ident-"));
  const identityFile = writeIdentityFile(dir, {
    user_id: "alice",
    security_level: "internal",
    specials: "",
  });
  const { handlers } = registerPlugin({ identityFile });
  mockFetchAllow(t);

  const first = await handlers.get("before_agent_run")(
    { prompt: "hello" },
    { sessionKey: "sess-alice", runId: "trace-1" },
  );
  assert.deepEqual(first, { outcome: "pass" });

  const second = await handlers.get("before_agent_run")(
    { prompt: "again" },
    { sessionKey: "sess-alice", runId: "trace-2" },
  );
  assert.deepEqual(second, { outcome: "pass" });

  fs.rmSync(dir, { recursive: true, force: true });
});

test("a different user on the same session is isolated", async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cg-ident-"));
  const identityFile = path.join(dir, "identity.json");
  fs.writeFileSync(
    identityFile,
    JSON.stringify({ user_id: "alice", security_level: "internal", specials: "" }),
  );
  const { handlers } = registerPlugin({ identityFile });
  mockFetchAllow(t);

  const first = await handlers.get("before_agent_run")(
    { prompt: "alice msg" },
    { sessionKey: "sess-shared", runId: "trace-1" },
  );
  assert.deepEqual(first, { outcome: "pass" });

  // 切用户：桌面端重写身份文件（Step 4 约定动作）
  fs.writeFileSync(
    identityFile,
    JSON.stringify({ user_id: "bob", security_level: "secret", specials: "" }),
  );

  const blocked = await handlers.get("before_agent_run")(
    { prompt: "bob msg" },
    { sessionKey: "sess-shared", runId: "trace-2" },
  );
  assert.equal(blocked.outcome, "block");
  assert.equal(blocked.reason, "session_owner_mismatch");
  assert.equal(blocked.category, "argus_session");

  fs.rmSync(dir, { recursive: true, force: true });
});

test("a different session for the new user passes", async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cg-ident-"));
  const identityFile = path.join(dir, "identity.json");
  fs.writeFileSync(
    identityFile,
    JSON.stringify({ user_id: "alice", security_level: "internal", specials: "" }),
  );
  const { handlers } = registerPlugin({ identityFile });
  mockFetchAllow(t);

  const first = await handlers.get("before_agent_run")(
    { prompt: "alice msg" },
    { sessionKey: "sess-a", runId: "trace-1" },
  );
  assert.deepEqual(first, { outcome: "pass" });

  fs.writeFileSync(
    identityFile,
    JSON.stringify({ user_id: "bob", security_level: "internal", specials: "" }),
  );

  const fresh = await handlers.get("before_agent_run")(
    { prompt: "bob msg" },
    { sessionKey: "sess-b", runId: "trace-2" },
  );
  assert.deepEqual(fresh, { outcome: "pass" });

  fs.rmSync(dir, { recursive: true, force: true });
});

test("fallback identity without user id never occupies a binding", async (t) => {
  const { handlers } = registerPlugin({
    identityFile: "/nonexistent-argus-identity-xyz.json",
  });
  mockFetchAllow(t);

  const first = await handlers.get("before_agent_run")(
    { prompt: "anon msg" },
    { sessionKey: "sess-anon", runId: "trace-1" },
  );
  assert.deepEqual(first, { outcome: "pass" });

  const second = await handlers.get("before_agent_run")(
    { prompt: "anon again" },
    { sessionKey: "sess-anon", runId: "trace-2" },
  );
  assert.deepEqual(second, { outcome: "pass" });
});
