const EXTERNAL_WRAPPER_RE =
  /<<<(?:END_)?EXTERNAL_UNTRUSTED_CONTENT\b[^>]*>>>/gi;
const EXTERNAL_BLOCK_RE =
  /<<<EXTERNAL_UNTRUSTED_CONTENT\b[^>]*>>>\s*(?:Source:\s*Web (?:Search|Fetch)\s*)?(?:---\s*)?([\s\S]*?)\s*<<<END_EXTERNAL_UNTRUSTED_CONTENT\b[^>]*>>>/gi;
const EXTERNAL_SOURCE_RE = /^Source:\s*Web (?:Search|Fetch)\s*$/gim;
const EXTERNAL_SEPARATOR_RE = /^---\s*$/gm;
const ERROR_STATUSES = new Set(["error", "failed", "failure"]);
const EXTERNAL_TOOLS = new Set(["web_fetch", "web_search"]);

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : undefined;
}

function decodeTransportNewlines(value: string): string {
  if (!value.includes("EXTERNAL_UNTRUSTED_CONTENT")) {
    return value;
  }
  return value
    .replace(/\\r\\n/g, "\n")
    .replace(/\\n/g, "\n")
    .replace(/\\r/g, "\n")
    .replace(/\\t/g, "\t");
}

function unwrapExternalContent(value: string): string {
  const decoded = decodeTransportNewlines(value);
  const blocks = [...decoded.matchAll(EXTERNAL_BLOCK_RE)]
    .map((match) => match[1]?.trim() ?? "")
    .filter(Boolean);
  if (blocks.length > 0) {
    return blocks.join("\n");
  }
  return decoded
    .replace(EXTERNAL_WRAPPER_RE, "")
    .replace(EXTERNAL_SOURCE_RE, "")
    .replace(EXTERNAL_SEPARATOR_RE, "")
    .trim();
}

function parseStructuredValue(value: unknown): unknown {
  let current = value;
  for (let round = 0; round < 3 && typeof current === "string"; round += 1) {
    const text = current.trim();
    if (!text) {
      break;
    }
    try {
      const parsed = JSON.parse(text) as unknown;
      if (parsed === current) {
        break;
      }
      current = parsed;
    } catch {
      break;
    }
  }
  return current;
}

function externalBlocks(value: unknown): string[] {
  if (typeof value === "string") {
    const decoded = decodeTransportNewlines(value);
    const blocks = [...decoded.matchAll(EXTERNAL_BLOCK_RE)]
      .map((match) => match[1]?.trim() ?? "")
      .filter(Boolean);
    if (blocks.length > 0) {
      return blocks;
    }
    const parsed = parseStructuredValue(value);
    return parsed === value ? [] : externalBlocks(parsed);
  }
  if (Array.isArray(value)) {
    return value.flatMap(externalBlocks);
  }
  const record = asRecord(value);
  return record ? Object.values(record).flatMap(externalBlocks) : [];
}

function isTransportError(
  value: unknown,
  allowUntypedError = false,
): boolean {
  const parsed = parseStructuredValue(value);
  if (parsed !== value) {
    return isTransportError(parsed, allowUntypedError);
  }
  if (Array.isArray(parsed)) {
    return parsed.some((item) => isTransportError(item));
  }
  const record = asRecord(parsed);
  if (!record) {
    return false;
  }
  const status =
    typeof record.status === "string" ? record.status.toLowerCase() : "";
  const tool =
    typeof record.tool === "string" ? record.tool.toLowerCase() : "";
  const isExternalTool = EXTERNAL_TOOLS.has(tool);
  if (ERROR_STATUSES.has(status) && (allowUntypedError || isExternalTool)) {
    return true;
  }
  if (
    isExternalTool &&
    record.error !== undefined &&
    record.error !== null &&
    record.error !== ""
  ) {
    return true;
  }
  return Object.values(record).some((item) => isTransportError(item));
}

function resultText(value: unknown): string {
  const result = asRecord(value);
  if (!result) {
    return "";
  }
  const fields = ["title", "description", "excerpt", "content"] as const;
  const lines = fields
    .map((field) => result[field])
    .filter((item): item is string => typeof item === "string")
    .map(unwrapExternalContent)
    .filter(Boolean);
  if (typeof result.url === "string" && result.url) {
    lines.push(`URL: ${result.url}`);
  }
  return lines.join("\n");
}

function webSearchText(value: unknown): string | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }
  const details = asRecord(record.details);
  const results = Array.isArray(record.results)
    ? record.results
    : details && Array.isArray(details.results)
      ? details.results
      : undefined;
  if (!results) {
    return undefined;
  }
  const text = results.map(resultText).filter(Boolean).join("\n\n");
  return text || undefined;
}

function webFetchText(value: unknown): string | undefined {
  const blocks = externalBlocks(value);
  if (blocks.length > 0) {
    return [...new Set(blocks)].join("\n");
  }
  if (isTransportError(value, true)) {
    return "";
  }
  const text = genericToolResultText(value);
  const cleaned = unwrapExternalContent(text);
  return cleaned === text ? undefined : cleaned;
}

function genericToolResultText(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  const record = asRecord(value);
  if (record) {
    if (typeof record.text === "string") {
      return record.text;
    }
    if (typeof record.content === "string") {
      return record.content;
    }
    if (Array.isArray(record.content)) {
      const text = record.content
        .map((item) => {
          if (typeof item === "string") {
            return item;
          }
          const block = asRecord(item);
          return block && typeof block.text === "string" ? block.text : "";
        })
        .filter(Boolean)
        .join("\n");
      if (text) {
        return text;
      }
    }
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function toolResultText(toolName: string, value: unknown): string {
  if (toolName === "web_search") {
    const structured = webSearchText(value);
    if (structured) {
      return structured;
    }
  }
  if (toolName === "web_fetch") {
    const structured = webFetchText(value);
    if (structured !== undefined) {
      return structured;
    }
  }
  return genericToolResultText(value);
}
