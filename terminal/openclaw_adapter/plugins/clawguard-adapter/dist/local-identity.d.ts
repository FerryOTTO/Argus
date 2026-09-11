export type SecurityLevel = "public" | "internal" | "secret" | "top_secret";
export type LocalIdentity = {
    userId: string;
    securityLevel: SecurityLevel;
    specials: string[];
    /** 身份来源：enterprise=企业登录写入，personal=个人版默认 */
    source: "enterprise" | "personal";
};
export declare const IDENTITY_FILE_NAME = "identity.json";
export declare const PERSONAL_IDENTITY: LocalIdentity;
/** 等级数字：给 io_guard role_level 用（与 CLASSIFICATION_LEVELS 0-4 对齐）。 */
export declare const SECURITY_LEVEL_NUMBERS: Record<SecurityLevel, number>;
export declare function normalizeSecurityLevel(raw: unknown): SecurityLevel;
export declare function normalizeSpecials(raw: unknown): string[];
export declare function identityFileCandidates(explicitPath?: string): string[];
/**
 * 读取本地身份文件。fail-closed：
 * 文件缺失/损坏/无 user_id → 返回 null，调用方按最低等级 public 处理，
 * 不回落 owner/channel 猜测逻辑。
 */
export declare function readLocalIdentity(explicitPath?: string): LocalIdentity | null;
