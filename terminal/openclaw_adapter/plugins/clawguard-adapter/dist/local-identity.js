import { existsSync, readFileSync } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
export const IDENTITY_FILE_NAME = "identity.json";
export const PERSONAL_IDENTITY = {
    userId: "desktop-local",
    securityLevel: "internal",
    specials: [],
    source: "personal",
};
const LEVEL_ALIASES = {
    "1": "public",
    a: "public",
    public: "public",
    "2": "internal",
    b: "internal",
    internal: "internal",
    "3": "secret",
    c: "secret",
    secret: "secret",
    "4": "top_secret",
    d: "top_secret",
    top_secret: "top_secret",
    topsecret: "top_secret",
};
/** 等级数字：给 io_guard role_level 用（与 CLASSIFICATION_LEVELS 0-4 对齐）。 */
export const SECURITY_LEVEL_NUMBERS = {
    public: 1,
    internal: 2,
    secret: 3,
    top_secret: 4,
};
export function normalizeSecurityLevel(raw) {
    if (typeof raw !== "string") {
        return "public";
    }
    return LEVEL_ALIASES[raw.trim().toLowerCase()] ?? "public";
}
export function normalizeSpecials(raw) {
    if (Array.isArray(raw)) {
        return raw
            .filter((item) => typeof item === "string")
            .map((item) => item.trim())
            .filter((item) => item.length > 0);
    }
    if (typeof raw === "string") {
        return raw
            .split(",")
            .map((item) => item.trim())
            .filter((item) => item.length > 0);
    }
    return [];
}
function parseIdentityFile(content) {
    let raw;
    try {
        raw = JSON.parse(content);
    }
    catch {
        return null;
    }
    if (typeof raw !== "object" || raw === null) {
        return null;
    }
    const record = raw;
    const userId = record["user_id"];
    if (typeof userId !== "string" || !userId.trim()) {
        return null;
    }
    return {
        userId: userId.trim(),
        securityLevel: normalizeSecurityLevel(record["security_level"]),
        specials: normalizeSpecials(record["specials"]),
        source: "enterprise",
    };
}
export function identityFileCandidates(explicitPath) {
    if (explicitPath && explicitPath.trim()) {
        return [explicitPath];
    }
    const fromEnv = process.env["CLAWGUARD_IDENTITY_FILE"];
    if (fromEnv && fromEnv.trim()) {
        return [fromEnv];
    }
    // 约定位置：网关数据目录，与 mediaRoot（~/.openclaw/media）同一父目录。
    return [path.join(os.homedir(), ".openclaw", "clawguard", IDENTITY_FILE_NAME)];
}
/**
 * 读取本地身份文件。fail-closed：
 * 文件缺失/损坏/无 user_id → 返回 null，调用方按最低等级 public 处理，
 * 不回落 owner/channel 猜测逻辑。
 */
export function readLocalIdentity(explicitPath) {
    for (const candidate of identityFileCandidates(explicitPath)) {
        if (!existsSync(candidate)) {
            continue;
        }
        let content;
        try {
            content = readFileSync(candidate, "utf-8");
        }
        catch {
            return null;
        }
        const parsed = parseIdentityFile(content);
        if (parsed === null) {
            return null;
        }
        return parsed;
    }
    return null;
}
