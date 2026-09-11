import assert from "node:assert/strict";
import test from "node:test";
import * as os from "node:os";
import * as path from "node:path";

import {
  attachmentsFromMetadata,
  mimeFromName,
  parsePromptAttachments,
  resolveMediaRoot,
  resolveMediaUri,
  stripGatewayEnvelope,
} from "../dist/media-attachments.js";

test("parses webchat and QQ markers into descriptors", () => {
  const prompt = [
    "看这张图 [media attached: media://inbound/abc.png]",
    "[附件: C:\\tmp\\report.pdf]",
    "- 图片: C:\\tmp\\shot.png",
  ].join("\n");
  const parsed = parsePromptAttachments(prompt);
  assert.equal(parsed.length, 3);
  assert.equal(parsed[0].url, "media://inbound/abc.png");
  assert.equal(parsed[0].name, "abc.png");
  assert.equal(parsed[0].mime_type, "image/png");
  assert.equal(parsed[1].path, "C:\\tmp\\report.pdf");
  assert.equal(parsed[1].name, "report.pdf");
  assert.equal(parsed[1].mime_type, "application/pdf");
  assert.equal(parsed[2].path, "C:\\tmp\\shot.png");
  assert.equal(parsed[2].mime_type, "image/png");
});

test("deduplicates repeated markers", () => {
  const prompt =
    "[media attached: media://inbound/a.png] [media attached: media://inbound/a.png]";
  assert.equal(parsePromptAttachments(prompt).length, 1);
});

test("resolveMediaUri only allows inbound ids inside the media root", () => {
  const root = "C:\\media";
  assert.equal(
    resolveMediaUri("media://inbound/abc.png", root),
    "C:\\media\\inbound\\abc.png",
  );
  assert.equal(resolveMediaUri("media://inbound/..", root), null);
  assert.equal(resolveMediaUri("media://inbound/../x.png", root), null);
  assert.equal(resolveMediaUri("http://evil/x.png", root), null);
  assert.equal(resolveMediaUri("not-a-uri", root), null);
});

test("resolveMediaRoot honours config then falls back to the home media dir", () => {
  assert.equal(resolveMediaRoot({ mediaRoot: "C:\\custom" }), "C:\\custom");
  assert.equal(resolveMediaRoot({ mediaRoot: "" }), path.join(os.homedir(), ".openclaw", "media"));
  assert.equal(resolveMediaRoot({}), path.join(os.homedir(), ".openclaw", "media"));
});

test("attachmentsFromMetadata reads mediaPaths/mediaTypes", () => {
  const found = attachmentsFromMetadata({
    mediaPaths: ["C:\\a.png", "C:\\b.pdf"],
    mediaTypes: ["image/png", "application/pdf"],
  });
  assert.equal(found.length, 2);
  assert.equal(found[0].path, "C:\\a.png");
  assert.equal(found[0].mime_type, "image/png");
  assert.equal(found[1].path, "C:\\b.pdf");
  assert.equal(found[1].mime_type, "application/pdf");
});

test("attachmentsFromMetadata reads mediaUrl media:// URIs", () => {
  const found = attachmentsFromMetadata({
    mediaUrl: "media://inbound/photo.png",
  });
  assert.equal(found.length, 1);
  assert.equal(found[0].url, "media://inbound/photo.png");
  assert.equal(found[0].mime_type, "image/png");
});

test("mimeFromName maps common extensions", () => {
  assert.equal(mimeFromName("a.PDF"), "application/pdf");
  assert.equal(mimeFromName("b.xlsx"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  assert.equal(mimeFromName("c.unknown"), undefined);
});

test("stripGatewayEnvelope removes untrusted-metadata envelope, keeps markers and caption", () => {
  const prompt = [
    "Conversation info (untrusted metadata):",
    "```json",
    '{ "source_modality": "image" }',
    "```",
    "",
    "[media attached: media://inbound/abc.png (image/png)]",
    "[User sent media without caption]",
  ].join("\n");
  const stripped = stripGatewayEnvelope(prompt);
  assert.ok(!stripped.includes("untrusted metadata"));
  assert.ok(!stripped.includes("source_modality"));
  assert.ok(!stripped.includes("User sent media without caption"));
  assert.ok(stripped.includes("media://inbound/abc.png"));
});

test("stripGatewayEnvelope keeps real user caption next to markers", () => {
  const prompt = [
    "Conversation info (untrusted metadata):",
    "```json",
    '{ "source_modality": "document" }',
    "```",
    "",
    "[media attached: media://inbound/note.docx (application/vnd.openxmlformats-officedocument.wordprocessingml.document)]",
    "请总结今天的会议纪要",
  ].join("\n");
  const stripped = stripGatewayEnvelope(prompt);
  assert.ok(!stripped.includes("untrusted metadata"));
  assert.ok(stripped.includes("media://inbound/note.docx"));
  assert.ok(stripped.includes("请总结今天的会议纪要"));
});

test("stripGatewayEnvelope leaves plain text prompts untouched", () => {
  assert.equal(stripGatewayEnvelope("hello world"), "hello world");
  assert.equal(stripGatewayEnvelope("看这张图"), "看这张图");
});
