import * as os from "node:os";
import * as path from "node:path";
const MEDIA_ATTACHED_RE = /\[media attached:\s*(media:\/\/[^\]]+)\]/gi;
const QQ_ATTACH_RE = /\[附件:\s*([^\]]+)\]/gi;
const QQ_IMAGE_RE = /-\s*图片:\s*(\S+)/gi;
const EXT_MIME = {
    png: "image/png",
    jpg: "image/jpeg",
    jpeg: "image/jpeg",
    gif: "image/gif",
    bmp: "image/bmp",
    webp: "image/webp",
    pdf: "application/pdf",
    docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    csv: "text/csv",
    txt: "text/plain",
};
const MEDIA_INBOUND_RE = /^media:\/\/inbound\/([A-Za-z0-9._-]+)$/;
export function basename(value) {
    const normalized = value.replace(/[\\/]+/g, "/");
    return normalized.split("/").pop() || "attachment";
}
export function mimeFromName(name) {
    const extension = path.extname(name).slice(1).toLowerCase();
    return EXT_MIME[extension];
}
export function mediaUriName(uri) {
    return basename(uri);
}
/** Parse webchat / QQ media markers out of the user prompt. */
export function parsePromptAttachments(prompt) {
    const found = [];
    const seen = new Set();
    const push = (value) => {
        const isUri = /^media:\/\//.test(value);
        if (seen.has(value)) {
            return;
        }
        seen.add(value);
        const name = isUri ? mediaUriName(value) : basename(value);
        const descriptor = { name };
        const mime = mimeFromName(name);
        if (mime) {
            descriptor.mime_type = mime;
        }
        if (isUri) {
            descriptor.url = value;
        }
        else {
            descriptor.path = value;
        }
        found.push(descriptor);
    };
    for (const match of prompt.matchAll(MEDIA_ATTACHED_RE)) {
        const value = match[1];
        if (typeof value === "string") {
            push(value.trim());
        }
    }
    for (const match of prompt.matchAll(QQ_ATTACH_RE)) {
        const value = match[1];
        if (typeof value === "string") {
            push(value.trim());
        }
    }
    for (const match of prompt.matchAll(QQ_IMAGE_RE)) {
        const value = match[1];
        if (typeof value === "string") {
            push(value.trim());
        }
    }
    return found;
}
export function resolveMediaRoot(cfg) {
    const configured = cfg.mediaRoot;
    if (typeof configured === "string" && configured.trim()) {
        return configured;
    }
    return path.join(os.homedir(), ".openclaw", "media");
}
/** Resolve a media://inbound/<id> URI to a local path inside mediaRoot. */
export function resolveMediaUri(uri, mediaRoot) {
    const match = MEDIA_INBOUND_RE.exec(uri.trim());
    const id = match?.[1];
    if (!id || id.includes("..")) {
        return null;
    }
    const root = path.resolve(mediaRoot);
    const candidate = path.resolve(root, "inbound", id);
    if (candidate !== root && !candidate.startsWith(root + path.sep)) {
        return null;
    }
    return candidate;
}
/**
 * OpenClaw wraps media-bearing prompts in a transport envelope
 * ("Conversation info (untrusted metadata):" + a ```json block + a
 * "[User sent media without caption]" line). It is gateway scaffolding,
 * not user input, but the semantic classifier flags the "untrusted
 * metadata" phrase as prompt injection. Strip it before checking while
 * keeping real user text and media marker lines.
 */
export function stripGatewayEnvelope(prompt) {
    return prompt
        .replace(/Conversation info\s*\(?untrusted metadata\)?:[\s\S]*?```[\s\S]*?```/gi, "")
        .replace(/Conversation info\s*\(untrusted metadata\)?:\s*/gi, "")
        .replace(/\[User sent media without caption\][^\n]*/gi, "")
        .trim();
}
/** Extract attachments captured on message_received from event.metadata. */
export function attachmentsFromMetadata(meta) {
    if (typeof meta !== "object" || meta === null) {
        return [];
    }
    const record = meta;
    const collected = [];
    const collect = (valueKey, typeKey) => {
        const raw = record[valueKey];
        const types = record[typeKey];
        const pickType = (index) => {
            const value = Array.isArray(types) ? types[index] : types;
            return typeof value === "string" ? value : undefined;
        };
        if (Array.isArray(raw)) {
            raw.forEach((item, index) => {
                if (typeof item === "string" && item.trim()) {
                    collected.push({ value: item.trim(), type: pickType(index) });
                }
            });
        }
        else if (typeof raw === "string" && raw.trim()) {
            collected.push({ value: raw.trim(), type: pickType(0) });
        }
    };
    collect("mediaPath", "mediaType");
    collect("mediaPaths", "mediaTypes");
    collect("mediaUrl", "mediaType");
    collect("mediaUrls", "mediaTypes");
    const found = [];
    const seen = new Set();
    for (const { value, type } of collected) {
        if (seen.has(value)) {
            continue;
        }
        seen.add(value);
        const isUri = /^media:\/\//.test(value);
        const name = isUri ? mediaUriName(value) : basename(value);
        const descriptor = { name };
        const mime = type || mimeFromName(name);
        if (mime) {
            descriptor.mime_type = mime;
        }
        if (isUri) {
            descriptor.url = value;
        }
        else {
            descriptor.path = value;
        }
        found.push(descriptor);
    }
    return found;
}
