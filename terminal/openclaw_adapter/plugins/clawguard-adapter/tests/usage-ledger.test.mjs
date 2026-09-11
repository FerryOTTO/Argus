import assert from "node:assert/strict";
import test from "node:test";

import plugin from "../dist/index.js";

function registerPlugin(config = {}) {
  const handlers = new Map();
  const logs = [];
  plugin.register({
    pluginConfig: {
      clawguardUrl: "http://127.0.0.1:8000",
      timeoutMs: 10000,
      failMode: "closed",
      protectedTools: ["web_search", "web_fetch"],
      identityFile: "/nonexistent-clawguard-identity-xyz.json",
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

test("llm_output without usage is ignored", async () => {
  const { handlers } = registerPlugin();
  assert.ok(handlers.has("llm_output"));
  // 无 usage：直接返回，不抛错。
  await handlers.get("llm_output")(
    { runId: "r1", sessionId: "s1", provider: "p", model: "m" },
    {},
  );
});

test("llm_output with zero usage is ignored", async () => {
  const { handlers } = registerPlugin();
  await handlers.get("llm_output")(
    { runId: "r1", sessionId: "s1", provider: "p", model: "m", usage: { input: 0, output: 0 } },
    {},
  );
});
