export class GuardServiceError extends Error {
}
const ACTIONS = new Set([
    "allow",
    "rewrite",
    "block",
    "human_review",
]);
export class GuardClient {
    config;
    constructor(config) {
        this.config = config;
    }
    async health() {
        try {
            const response = await this.request("/health", undefined, "GET");
            return response.ok;
        }
        catch {
            return false;
        }
    }
    checkInput(identity, payload) {
        return this.check("input", "/v1/input/check", identity, payload);
    }
    checkContent(identity, payload) {
        return this.check("content", "/v1/content/check", identity, payload);
    }
    checkTool(identity, payload) {
        return this.check("tool_pre", "/v1/tool/pre_check", identity, payload);
    }
    async bindToolSessionPrompt(input) {
        await this.postSession("/v1/tool/session/prompt", input);
    }
    async recordToolSessionCall(input) {
        await this.postSession("/v1/tool/session/call", input);
    }
    async reportUsage(records) {
        const response = await this.request("/v1/local/usage/ingest", JSON.stringify({ records }), "POST");
        if (!response.ok) {
            throw new GuardServiceError(`Clawguard returned HTTP ${response.status} for /v1/local/usage/ingest`);
        }
    }
    checkOutput(identity, payload) {
        return this.check("output", "/v1/output/check", identity, payload);
    }
    async check(stage, path, identity, payload) {
        const request = {
            context: {
                ...identity,
                stage,
                timestamp: new Date().toISOString(),
            },
            payload,
        };
        const response = await this.request(path, JSON.stringify(request), "POST");
        if (!response.ok) {
            throw new GuardServiceError(`Clawguard returned HTTP ${response.status} for ${path}`);
        }
        const value = (await response.json());
        if (!this.isSecurityResponse(value, stage)) {
            throw new GuardServiceError(`Clawguard returned an invalid response for ${path}`);
        }
        return value;
    }
    isSecurityResponse(value, expectedStage) {
        if (typeof value.trace_id !== "string" ||
            value.stage !== expectedStage ||
            typeof value.action !== "string" ||
            !ACTIONS.has(value.action) ||
            typeof value.risk_score !== "number" ||
            typeof value.reason !== "string" ||
            !Array.isArray(value.module_results)) {
            return false;
        }
        if (value.action !== "rewrite") {
            return true;
        }
        if (typeof value.data !== "object" || value.data === null) {
            return false;
        }
        if (expectedStage === "tool_pre") {
            const argumentsValue = value.data.arguments;
            return (typeof argumentsValue === "object" &&
                argumentsValue !== null &&
                !Array.isArray(argumentsValue));
        }
        const field = expectedStage === "content" ? "content" : "text";
        return typeof value.data[field] === "string";
    }
    async postSession(path, payload) {
        const response = await this.request(path, JSON.stringify(payload), "POST");
        if (!response.ok) {
            throw new GuardServiceError(`Clawguard returned HTTP ${response.status} for ${path}`);
        }
        const value = (await response.json());
        if (value.status !== "ok") {
            throw new GuardServiceError(`Clawguard returned an invalid response for ${path}`);
        }
    }
    async request(path, body, method) {
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
        }
        catch (error) {
            throw new GuardServiceError(error instanceof Error ? error.message : String(error));
        }
        finally {
            clearTimeout(timer);
        }
    }
}
