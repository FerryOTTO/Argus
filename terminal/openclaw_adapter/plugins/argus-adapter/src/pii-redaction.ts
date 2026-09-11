const SENSITIVE_TEXT_PATTERNS: ReadonlyArray<readonly [RegExp, string]> = [
  [/(?<!\d)1[3-9]\d{9}(?!\d)/g, "[PHONE]"],
  [/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g, "[EMAIL]"],
  [
    /((?:(?:facebook|meta)\s+)?(?:one[-\s]?time\s+)?(?:verification|security|login)\s+code\s*(?:is|:|：)?\s*)\d{4,8}/gi,
    "$1[OTP]",
  ],
  [
    /((?:短信|登录|一次性|动态)?(?:验证码|校验码|验证代码)\s*(?:是|为|:|：)?\s*)\d{4,8}/g,
    "$1[OTP]",
  ],
  [/(?<!\d)\d{17}[\dXx](?!\d)/g, "[ID_CARD]"],
  [/\b(?:sk|pk|ak)-[A-Za-z0-9_-]{16,}\b/g, "[API_KEY]"],
  [
    /\b[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{20,}\b/g,
    "[TOKEN]",
  ],
  [
    /(system prompt|developer message|hidden instruction)\s*[:：]/gi,
    "[HIDDEN_PROMPT]",
  ],
  [/(系统提示|系统指令|开发者消息|隐藏指令)\s*[:：]/g, "[HIDDEN_PROMPT]"],
];

export type SensitiveTextReplacement = {
  from: RegExp;
  to: string;
};

/**
 * Return fresh replacements for OpenClaw's model-stream transform layer.
 * Fresh RegExp objects avoid sharing mutable ``lastIndex`` state between
 * concurrent streams.
 */
export function sensitiveTextReplacements(): SensitiveTextReplacement[] {
  return SENSITIVE_TEXT_PATTERNS.map(([from, to]) => ({
    from: new RegExp(from.source, from.flags),
    to,
  }));
}

export function redactSensitiveText(text: string): string {
  return SENSITIVE_TEXT_PATTERNS.reduce(
    (current, [pattern, replacement]) => current.replace(pattern, replacement),
    text,
  );
}

function isPlainObject(value: object): value is Record<string, unknown> {
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

/**
 * Redact JSON-like message values without mutating the live OpenClaw event.
 * Non-plain runtime objects are intentionally kept intact.
 */
export function redactSensitiveValue(value: unknown): unknown {
  if (typeof value === "string") {
    return redactSensitiveText(value);
  }
  if (Array.isArray(value)) {
    let changed = false;
    const redacted = value.map((item) => {
      const next = redactSensitiveValue(item);
      changed ||= next !== item;
      return next;
    });
    return changed ? redacted : value;
  }
  if (typeof value !== "object" || value === null || !isPlainObject(value)) {
    return value;
  }

  let changed = false;
  const redacted: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    const next = redactSensitiveValue(item);
    changed ||= next !== item;
    redacted[key] = next;
  }
  return changed ? redacted : value;
}
