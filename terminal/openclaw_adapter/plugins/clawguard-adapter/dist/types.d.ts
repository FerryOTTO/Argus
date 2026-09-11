export type SecurityStage = "input" | "tool_pre" | "content" | "output";
export type SecurityAction = "allow" | "rewrite" | "block" | "human_review";
export type RequestContext = {
    trace_id: string;
    session_id: string;
    user_id: string;
    stage: SecurityStage;
    timestamp: string;
};
export type SecurityRequest = {
    context: RequestContext;
    payload: Record<string, unknown>;
};
export type ModuleResult = {
    module: string;
    success: boolean;
    action: SecurityAction;
    risk_score: number;
    reason: string;
    modified_data: unknown | null;
    details: Record<string, unknown>;
    latency_ms: number;
    error: string | null;
};
export type SecurityResponse = {
    trace_id: string;
    stage: string;
    action: SecurityAction;
    risk_score: number;
    reason: string;
    data: unknown | null;
    module_results: ModuleResult[];
};
export type RequestIdentity = Omit<RequestContext, "stage" | "timestamp">;
export type PluginConfig = {
    clawguardUrl: string;
    apiTokenEnv: string;
    timeoutMs: number;
    failMode: "closed" | "open";
    humanReviewAutoAllowTools: string[];
    protectedTools: string[];
    internalChannels: string[];
    ownerDataScopes: string[];
    mediaRoot: string;
    enableMediaCheck: boolean;
    /** 本地身份文件路径（Step 3）。空=按约定位置 ~/.openclaw/clawguard/identity.json；也可用 CLAWGUARD_IDENTITY_FILE 环境变量覆盖。 */
    identityFile: string;
};
export declare const DEFAULT_CONFIG: PluginConfig;
export declare function parseConfig(value: unknown): PluginConfig;
