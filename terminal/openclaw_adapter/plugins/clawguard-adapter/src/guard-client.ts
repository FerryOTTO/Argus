import type {
  PluginConfig,
  RequestIdentity,
  SecurityAction,
  SecurityRequest,
  SecurityResponse,
  SecurityStage,
} from "./types.js";

export class GuardServiceError extends Error {}

const ACTIONS = new Set<SecurityAction>([
  "allow",
  "rewrite",
  "block",
  "human_review",
]);

export class GuardClient {
  constructor(private readonly config: PluginConfig) {}

  async health(): Promise<boolean> {
    try {
      const response = await this.request("/health", undefined, "GET");
      return response.ok;
    } catch {
      return false;
    }
  }

  checkInput(
    identity: RequestIdentity,
    payload: Record<string, unknown>,
  ): Promise<SecurityResponse> {
    return this.check("input", "/v1/input/check", identity, payload);
  }

  checkContent(
    identity: RequestIdentity,
    payload: Record<string, unknown>,
  ): Promise<SecurityResponse> {
    return this.check("content", "/v1/content/check", identity, payload);
  }

  checkTool(
    identity: RequestIdentity,
    payload: Record<string, unknown>,
  ): Promise<SecurityResponse> {
    return this.check("tool_pre", "/v1/tool/pre_check", identity, payload);
  }

  async bindToolSessionPrompt(input: {
    session_id: string;
    prompt: string;
    trace_id: string;
  }): Promise<void> {
    await this.postSession("/v1/tool/session/prompt", input);
  }

  async recordToolSessionCall(input: {
    session_id: string;
    tool_name: string;
    arguments: Record<string, unknown>;
    trace_id: string;
  }): Promise<void> {
    await this.postSession("/v1/tool/session/call", input);
  }

  async reportUsage(
    records: Array<Record<string, unknown>>,
  ): Promise<void> {
    const response = await this.request(
      "/v1/local/usage/ingest",
      JSON.stringify({ records }),
      "POST",
    );
    if (!response.ok) {
      throw new GuardServiceError(
        `Clawguard returned HTTP ${response.status} for /v1/local/usage/ingest`,
      );
    }
  }

  checkOutput(
    identity: RequestIdentity,
    payload: Record<string, unknown>,
  ): Promise<SecurityResponse> {
    return this.check("output", "/v1/output/check", identity, payload);
  }

  private async check(
    stage: SecurityStage,
    path: string,
    identity: RequestIdentity,
    payload: Record<string, unknown>,
  ): Promise<SecurityResponse> {
    const request: SecurityRequest = {
      context: {
        ...identity,
        stage,
        timestamp: new Date().toISOString(),
      },
      payload,
    };
    const response = await this.request(path, JSON.stringify(request), "POST");
    if (!response.ok) {
      throw new GuardServiceError(
        `Clawguard returned HTTP ${response.status} for ${path}`,
      );
    }
    const value = (await response.json()) as Partial<SecurityResponse>;
    if (!this.isSecurityResponse(value, stage)) {
      throw new GuardServiceError(
        `Clawguard returned an invalid response for ${path}`,
      );
    }
    return value;
  }

  private isSecurityResponse(
    value: Partial<SecurityResponse>,
    expectedStage: SecurityStage,
  ): value is SecurityResponse {
    if (
      typeof value.trace_id !== "string" ||
      value.stage !== expectedStage ||
      typeof value.action !== "string" ||
      !ACTIONS.has(value.action as SecurityAction) ||
      typeof value.risk_score !== "number" ||
      typeof value.reason !== "string" ||
      !Array.isArray(value.module_results)
    ) {
      return false;
    }
    if (value.action !== "rewrite") {
      return true;
    }
    if (typeof value.data !== "object" || value.data === null) {
      return false;
    }
    if (expectedStage === "tool_pre") {
      const argumentsValue = (value.data as Record<string, unknown>).arguments;
      return (
        typeof argumentsValue === "object" &&
        argumentsValue !== null &&
        !Array.isArray(argumentsValue)
      );
    }
    const field = expectedStage === "content" ? "content" : "text";
    return typeof (value.data as Record<string, unknown>)[field] === "string";
  }

  private async postSession(
    path: string,
    payload: Record<string, unknown>,
  ): Promise<void> {
    const response = await this.request(path, JSON.stringify(payload), "POST");
    if (!response.ok) {
      throw new GuardServiceError(
        `Clawguard returned HTTP ${response.status} for ${path}`,
      );
    }
    const value = (await response.json()) as { status?: unknown };
    if (value.status !== "ok") {
      throw new GuardServiceError(
        `Clawguard returned an invalid response for ${path}`,
      );
    }
  }

  private async request(
    path: string,
    body: string | undefined,
    method: "GET" | "POST",
  ): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.config.timeoutMs);
    const token = process.env[this.config.apiTokenEnv] ?? "";
    try {
      return await fetch(`${this.config.clawguardUrl}${path}`, {
        method,
        body,
        signal: controller.signal,
        headers: {
          ...(body ? { "Content-Type": "application/json" } : {}),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
    } catch (error) {
      throw new GuardServiceError(
        error instanceof Error ? error.message : String(error),
      );
    } finally {
      clearTimeout(timer);
    }
  }
}
