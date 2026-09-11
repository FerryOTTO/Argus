export function replaceMessageText(value, text) {
    if (typeof value !== "object" || value === null) {
        return value;
    }
    const message = value;
    if (typeof message.content === "string") {
        return { ...message, content: text };
    }
    if (Array.isArray(message.content)) {
        let replaced = false;
        const content = message.content.map((part) => {
            if (!replaced &&
                typeof part === "object" &&
                part !== null &&
                part.type === "text") {
                replaced = true;
                return { ...part, text };
            }
            if (typeof part === "object" &&
                part !== null &&
                part.type === "text") {
                return { ...part, text: "" };
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
