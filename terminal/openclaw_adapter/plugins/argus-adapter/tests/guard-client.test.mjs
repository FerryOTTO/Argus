import assert from "node:assert/strict";
import test from "node:test";

import { GuardClient, GuardServiceError } from "../dist/guard-client.js";

const config = {
  argusUrl: "http://127.0.0.1:8000",
  apiTokenEnv: "ARGUS_TEST_TOKEN",
  timeoutMs: 500,
  failMode: "closed",
  protectedTools: ["web_fetch"],
  internalChannels: [],
  ownerDataScopes: [],
};

const identity = {
  trace_id: "trace-test",
  session_id: "session-test",
  user_id: "user-test",
};

function response(stage, action = "allow", data = null) {
  return {
    trace_id: identity.trace_id,
    stage,
    action,
    risk_score: 0,
    reason: "passed",
    data,
    module_results: [],
  };
}

test("uses unified checks and existing Tool Guard session endpoints", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init, body: init?.body ? JSON.parse(init.body) : null });
    if (url.includes("/tool/session/")) {
      return new Response(JSON.stringify({ status: "ok", session: {} }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    const stage = url.includes("/input/")
      ? "input"
      : url.includes("/tool/pre_check")
        ? "tool_pre"
      : url.includes("/content/")
        ? "content"
        : "output";
    return new Response(JSON.stringify(response(stage)), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  try {
    const client = new GuardClient(config);
    await client.checkInput(identity, { text: "hello" });
    await client.bindToolSessionPrompt({
      session_id: "session-test",
      prompt: "hello",
      trace_id: "trace-test",
    });
    await client.checkTool(identity, {
      tool_name: "read_file",
      arguments: { path: "README.md" },
    });
    await client.recordToolSessionCall({
      session_id: "session-test",
      tool_name: "read_file",
      arguments: { path: "README.md" },
      trace_id: "trace-test",
    });
    await client.checkContent(identity, { content: "tool result" });
    await client.checkOutput(identity, { text: "answer" });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(
    calls.map((call) => call.url),
    [
      "http://127.0.0.1:8000/v1/input/check",
      "http://127.0.0.1:8000/v1/tool/session/prompt",
      "http://127.0.0.1:8000/v1/tool/pre_check",
      "http://127.0.0.1:8000/v1/tool/session/call",
      "http://127.0.0.1:8000/v1/content/check",
      "http://127.0.0.1:8000/v1/output/check",
    ],
  );
  assert.deepEqual(
    calls.filter((call) => call.body.context).map((call) => call.body.context.stage),
    ["input", "tool_pre", "content", "output"],
  );
  assert.equal(calls[0].body.payload.text, "hello");
  assert.deepEqual(calls[1].body, {
    session_id: "session-test",
    prompt: "hello",
    trace_id: "trace-test",
  });
  assert.equal(calls[2].body.payload.tool_name, "read_file");
  assert.equal(calls[3].body.tool_name, "read_file");
  assert.equal(calls[4].body.payload.content, "tool result");
  assert.equal(calls[5].body.payload.text, "answer");
});

test("accepts tool rewrite only with explicit object arguments", async () => {
  const originalFetch = globalThis.fetch;
  const responses = [
    response("tool_pre", "rewrite", { arguments: { path: "safe.txt" } }),
    response("tool_pre", "rewrite", { arguments: ["not", "an", "object"] }),
  ];
  globalThis.fetch = async () =>
    new Response(JSON.stringify(responses.shift()), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  try {
    const client = new GuardClient(config);
    const valid = await client.checkTool(identity, { tool_name: "read_file" });
    assert.deepEqual(valid.data, { arguments: { path: "safe.txt" } });
    await assert.rejects(
      () => client.checkTool(identity, { tool_name: "read_file" }),
      GuardServiceError,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("accepts rewrite only when the stage-specific data field exists", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify(response("output", "rewrite", { text: "redacted" })),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  try {
    const result = await new GuardClient(config).checkOutput(identity, {
      text: "secret",
    });
    assert.equal(result.action, "rewrite");
    assert.deepEqual(result.data, { text: "redacted" });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("rejects the legacy sidecar response shape", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        decision: "allow",
        sanitized_content: "legacy",
        event_id: "event-1",
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  try {
    await assert.rejects(
      () => new GuardClient(config).checkInput(identity, { text: "hello" }),
      GuardServiceError,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
