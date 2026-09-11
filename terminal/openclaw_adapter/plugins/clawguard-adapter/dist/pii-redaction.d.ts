export type SensitiveTextReplacement = {
    from: RegExp;
    to: string;
};
/**
 * Return fresh replacements for OpenClaw's model-stream transform layer.
 * Fresh RegExp objects avoid sharing mutable ``lastIndex`` state between
 * concurrent streams.
 */
export declare function sensitiveTextReplacements(): SensitiveTextReplacement[];
export declare function redactSensitiveText(text: string): string;
/**
 * Redact JSON-like message values without mutating the live OpenClaw event.
 * Non-plain runtime objects are intentionally kept intact.
 */
export declare function redactSensitiveValue(value: unknown): unknown;
