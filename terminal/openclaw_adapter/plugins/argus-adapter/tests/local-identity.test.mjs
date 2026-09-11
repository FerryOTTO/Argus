import assert from "node:assert/strict";
import test from "node:test";

import {
  PERSONAL_IDENTITY,
  SECURITY_LEVEL_NUMBERS,
  identityFileCandidates,
  normalizeSecurityLevel,
  normalizeSpecials,
  readLocalIdentity,
} from "../dist/local-identity.js";

test("normalizeSecurityLevel covers rbac aliases and falls back to public", () => {
  assert.equal(normalizeSecurityLevel("top_secret"), "top_secret");
  assert.equal(normalizeSecurityLevel("SECRET"), "secret");
  assert.equal(normalizeSecurityLevel("2"), "internal");
  assert.equal(normalizeSecurityLevel("b"), "internal");
  assert.equal(normalizeSecurityLevel("nonsense"), "public");
  assert.equal(normalizeSecurityLevel(undefined), "public");
});

test("level numbers align with access_control 1-4", () => {
  assert.deepEqual(SECURITY_LEVEL_NUMBERS, {
    public: 1,
    internal: 2,
    secret: 3,
    top_secret: 4,
  });
});

test("normalizeSpecials splits comma text and string arrays", () => {
  assert.deepEqual(normalizeSpecials("*,!tool:write_file"), ["*", "!tool:write_file"]);
  assert.deepEqual(normalizeSpecials(["a", " b ", ""]), ["a", "b"]);
  assert.deepEqual(normalizeSpecials(undefined), []);
});

test("missing identity file returns null (fail-closed to public by caller)", () => {
  assert.equal(
    readLocalIdentity("/nonexistent-argus-identity-xyz.json"),
    null,
  );
});

test("explicit path wins over default candidates", () => {
  assert.deepEqual(
    identityFileCandidates("/tmp/x.json"),
    ["/tmp/x.json"],
  );
});

test("personal identity matches users.txt desktop-local row", () => {
  assert.equal(PERSONAL_IDENTITY.userId, "desktop-local");
  assert.equal(PERSONAL_IDENTITY.securityLevel, "internal");
  assert.equal(PERSONAL_IDENTITY.source, "personal");
});
