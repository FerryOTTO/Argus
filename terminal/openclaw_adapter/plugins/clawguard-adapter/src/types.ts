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

export const DEFAULT_CONFIG: PluginConfig = {
  clawguardUrl: "http://127.0.0.1:8000",
  apiTokenEnv: "CLAWGUARD_API_TOKEN",
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

export function parseConfig(value: unknown): PluginConfig {
  const raw =
    typeof value === "object" && value !== null
      ? (value as Record<string, unknown>)
      : {};
  return {
    clawguardUrl:
      typeof raw.clawguardUrl === "string"
        ? raw.clawguardUrl.replace(/\/+$/, "")
        : DEFAULT_CONFIG.clawguardUrl,
    apiTokenEnv:
      typeof raw.apiTokenEnv === "string"
        ? raw.apiTokenEnv
        : DEFAULT_CONFIG.apiTokenEnv,
    timeoutMs:
      typeof raw.timeoutMs === "number"
        ? Math.min(60_000, Math.max(250, Math.trunc(raw.timeoutMs)))
        : DEFAULT_CONFIG.timeoutMs,
    failMode: raw.failMode === "open" ? "open" : "closed",
    humanReviewAutoAllowTools: Array.isArray(raw.humanReviewAutoAllowTools)
      ? raw.humanReviewAutoAllowTools.filter(
          (item): item is string => typeof item === "string",
        )
      : DEFAULT_CONFIG.humanReviewAutoAllowTools,
    protectedTools: Array.isArray(raw.protectedTools)
      ? raw.protectedTools.filter(
          (item): item is string => typeof item === "string",
        )
      : DEFAULT_CONFIG.protectedTools,
    internalChannels: Array.isArray(raw.internalChannels)
      ? raw.internalChannels.filter(
          (item): item is string => typeof item === "string",
        )
      : DEFAULT_CONFIG.internalChannels,
    ownerDataScopes: Array.isArray(raw.ownerDataScopes)
      ? raw.ownerDataScopes.filter(
          (item): item is string => typeof item === "string",
        )
      : DEFAULT_CONFIG.ownerDataScopes,
    mediaRoot:
      typeof raw.mediaRoot === "string"
        ? raw.mediaRoot
        : DEFAULT_CONFIG.mediaRoot,
    enableMediaCheck:
      typeof raw.enableMediaCheck === "boolean"
        ? raw.enableMediaCheck
        : DEFAULT_CONFIG.enableMediaCheck,
    identityFile:
      typeof raw.identityFile === "string"
        ? raw.identityFile
        : DEFAULT_CONFIG.identityFile,
  };
}
