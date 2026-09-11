import type { PluginConfig, RequestIdentity, SecurityResponse } from "./types.js";
export declare class GuardServiceError extends Error {
}
export declare class GuardClient {
    private readonly config;
    constructor(config: PluginConfig);
    health(): Promise<boolean>;
    checkInput(identity: RequestIdentity, payload: Record<string, unknown>): Promise<SecurityResponse>;
    checkContent(identity: RequestIdentity, payload: Record<string, unknown>): Promise<SecurityResponse>;
    checkTool(identity: RequestIdentity, payload: Record<string, unknown>): Promise<SecurityResponse>;
    bindToolSessionPrompt(input: {
        session_id: string;
        prompt: string;
        trace_id: string;
    }): Promise<void>;
    recordToolSessionCall(input: {
        session_id: string;
        tool_name: string;
        arguments: Record<string, unknown>;
        trace_id: string;
    }): Promise<void>;
    reportUsage(records: Array<Record<string, unknown>>): Promise<void>;
    checkOutput(identity: RequestIdentity, payload: Record<string, unknown>): Promise<SecurityResponse>;
    private check;
    private isSecurityResponse;
    private postSession;
    private request;
}
