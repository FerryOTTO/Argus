import assert from "node:assert/strict";
import test from "node:test";

import { normalizeToolName } from "../dist/tool-names.js";

test("maps only the explicitly supported OpenClaw tool names", () => {
  assert.equal(normalizeToolName("read"), "read_file");
  assert.equal(normalizeToolName("write"), "write_file");
  assert.equal(normalizeToolName("edit"), "write_file");
  assert.equal(normalizeToolName("exec"), "execute_bash");
  assert.equal(normalizeToolName("web_fetch"), "http_request");
  assert.equal(normalizeToolName("web_search"), "web_search");
  assert.equal(normalizeToolName("unknown_custom_tool"), "unknown_custom_tool");
  assert.equal(normalizeToolName("apply_patch"), "apply_patch");
});
