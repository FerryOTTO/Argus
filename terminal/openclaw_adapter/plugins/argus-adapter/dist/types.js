export const DEFAULT_CONFIG = {
    argusUrl: "http://127.0.0.1:8000",
    apiTokenEnv: "ARGUS_API_TOKEN",
    timeoutMs: 30_000,
    failMode: "closed",
    humanReviewAutoAllowTools: [],
    protectedTools: [
        "web_fetch",
        "web_search",
        "read",
        "write",
        "edit",
        "memory_search",
        "memory_get",
    ],
    internalChannels: ["webchat", "control-ui"],
    ownerDataScopes: ["internal"],
    mediaRoot: "",
    enableMediaCheck: true,
    identityFile: "",
};
export function parseConfig(value) {
    const raw = typeof value === "object" && value !== null
        ? value
        : {};
    return {
        argusUrl: typeof raw.argusUrl === "string"
            ? raw.argusUrl.replace(/\/+$/, "")
            : DEFAULT_CONFIG.argusUrl,
        apiTokenEnv: typeof raw.apiTokenEnv === "string"
            ? raw.apiTokenEnv
            : DEFAULT_CONFIG.apiTokenEnv,
        timeoutMs: typeof raw.timeoutMs === "number"
            ? Math.min(60_000, Math.max(250, Math.trunc(raw.timeoutMs)))
            : DEFAULT_CONFIG.timeoutMs,
        failMode: raw.failMode === "open" ? "open" : "closed",
        humanReviewAutoAllowTools: Array.isArray(raw.humanReviewAutoAllowTools)
            ? raw.humanReviewAutoAllowTools.filter((item) => typeof item === "string")
            : DEFAULT_CONFIG.humanReviewAutoAllowTools,
        protectedTools: Array.isArray(raw.protectedTools)
            ? raw.protectedTools.filter((item) => typeof item === "string")
            : DEFAULT_CONFIG.protectedTools,
        internalChannels: Array.isArray(raw.internalChannels)
            ? raw.internalChannels.filter((item) => typeof item === "string")
            : DEFAULT_CONFIG.internalChannels,
        ownerDataScopes: Array.isArray(raw.ownerDataScopes)
            ? raw.ownerDataScopes.filter((item) => typeof item === "string")
            : DEFAULT_CONFIG.ownerDataScopes,
        mediaRoot: typeof raw.mediaRoot === "string"
            ? raw.mediaRoot
            : DEFAULT_CONFIG.mediaRoot,
        enableMediaCheck: typeof raw.enableMediaCheck === "boolean"
            ? raw.enableMediaCheck
            : DEFAULT_CONFIG.enableMediaCheck,
        identityFile: typeof raw.identityFile === "string"
            ? raw.identityFile
            : DEFAULT_CONFIG.identityFile,
    };
}
