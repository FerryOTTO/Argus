export type TextPart = {
  type: "text";
  text: string;
  [key: string]: unknown;
};

export type MessageLike = {
  content?: unknown;
};

export function replaceMessageText(value: unknown, text: string): unknown {
  if (typeof value !== "object" || value === null) {
    return value;
  }
  const message = value as MessageLike;
  if (typeof message.content === "string") {
    return { ...message, content: text };
  }
  if (Array.isArray(message.content)) {
    let replaced = false;
    const content = message.content.map((part) => {
      if (
        !replaced &&
        typeof part === "object" &&
        part !== null &&
        (part as TextPart).type === "text"
      ) {
        replaced = true;
        return { ...(part as TextPart), text };
      }
      if (
        typeof part === "object" &&
        part !== null &&
        (part as TextPart).type === "text"
      ) {
        return { ...(part as TextPart), text: "" };
      }
      return part;
    });
    if (!replaced) {
      content.unshift({ type: "text", text });
    }
    return { ...message, content };
  }
  return { ...message, content: [{ type: "text", text }] };
}
