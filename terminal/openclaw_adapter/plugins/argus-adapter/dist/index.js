import { randomUUID } from "node:crypto";
import { definePluginEntry, } from "openclaw/plugin-sdk/plugin-entry";
import { GuardClient } from "./guard-client.js";
import { SECURITY_LEVEL_NUMBERS, readLocalIdentity, } from "./local-identity.js";
import { attachmentsFromMetadata, parsePromptAttachments, resolveMediaRoot, resolveMediaUri, stripGatewayEnvelope, } from "./media-attachments.js";
import { replaceMessageText } from "./message-utils.js";
import { redactSensitiveValue, sensitiveTextReplacements, } from "./pii-redaction.js";
import { toolResultText } from "./tool-content.js";
import { normalizeToolName } from "./tool-names.js";
import { parseConfig, } from "./types.js";
const BLOCKED_INPUT_MESSAGE = "输入触发了安全策略，本次请求已阻止。";
const BLOCKED_OUTPUT_MESSAGE = "输出触发了安全策略，已停止发送原始内容。";
const BLOCKED_CONTEXT_MESSAGE = "[Argus 已隔离此工具结果：内容安全检查未通过。]";
const BLOCKED_TOOL_MESSAGE = "工具调用触发了安全策略，本次执行已阻止。";
const CONTENT_RESULT_TTL_MS = 60_000;
const RUNTIME_STATE_KEY = "__argusAdapterRuntimeStateV1";
function sharedRuntimeState() {
    // OpenClaw may lazily register the tool-result middleware separately from
    // gateway hooks. Both registrations must resolve the same real tool_call_id.
    const scope = globalThis;
    scope[RUNTIME_STATE_KEY] ??= {
        traceBySession: new Map(),
        identityBySession: new Map(),
        contentResultByCall: new Map(),
        contentCheckByCall: new Map(),
        blockedToolCalls: new Map(),
        contextByToolCall: new Map(),
        nextToolSequenceByTrace: new Map(),
        usageLedger: new Map(),
    };
    return scope[RUNTIME_STATE_KEY];
}
function numOrZero(value) {
    return typeof value === "number" && Number.isFinite(value) && value > 0
        ? value
        : 0;
}
function recordUsage(ledger, modelRef, usage) {
    const input = numOrZero(usage.input);
    const output = numOrZero(usage.output);
    const cacheRead = numOrZero(usage.cacheRead);
    const cacheWrite = numOrZero(usage.cacheWrite);
    const total = numOrZero(usage.total) || input + output + cacheRead + cacheWrite;
    if (total <= 0) {
        return;
    }
    const key = modelRef || "unknown";
    const list = ledger.get(key) ?? [];
    list.push({ input, output, cacheRead, cacheWrite, total, at: Date.now() });
    // 每个模型最多保留 500 条，防止内存膨胀；够首页画 30 天曲线。
    if (list.length > 500) {
        list.splice(0, list.length - 500);
    }
    ledger.set(key, list);
}
function mergeAttachments(primary, buffered, mediaRoot, enabled) {
    if (!enabled) {
        return [];
    }
    const seen = new Set();
    const merged = [];
    const push = (item) => {
        const key = item.url ?? item.path ?? item.name;
        if (seen.has(key)) {
            return;
        }
        seen.add(key);
        merged.push(item);
    };
    primary.forEach(push);
    buffered.forEach(push);
    const resolved = [];
    for (const item of merged) {
        if (item.url && /^media:\/\//.test(item.url)) {
            const resolvedPath = resolveMediaUri(item.url, mediaRoot);
            if (resolvedPath === null) {
                continue;
            }
            resolved.push({ ...item, path: resolvedPath, url: undefined });
        }
        else {
            resolved.push(item);
        }
    }
    return resolved;
}
function extractMarkerLines(prompt) {
    return prompt
        .split(/\r?\n/)
        .filter((line) => {
        return (/\[media attached:/i.test(line) ||
            /\[附件:/i.test(line) ||
            /-\s*图片:/i.test(line));
    });
}
function identityForRequest(input) {
    return {
        trace_id: input.traceId,
        session_id: input.sessionId || "default_session",
        user_id: input.profile.userId || "default_user",
    };
}
function defaultIdentityProfile() {
    return {
        principalType: "external_user",
        targetAudience: "external",
        channelClassification: "public",
        allowedDataScopes: [],
        userId: "",
        identitySource: "fallback",
        securityLevel: "public",
        roleLevel: SECURITY_LEVEL_NUMBERS.public,
    };
}
/**
 * 身份解析（Step 3：本地身份文件优先，fail-closed）。
 * - 企业版：桌面登录后写 ~/.openclaw/argus/identity.json（user_id/security_level/specials），
 *   读到即用，不再猜 owner/channel。
 * - 个人版：同一位置写死 desktop-local/internal（桌面端首次启动时写，见 §2.2）。
 * - 文件缺失/损坏 → 最低等级 public + identitySource=fallback，记 warn，不回落老猜测逻辑。
 */
function resolveIdentityProfile(input) {
    const identity = input.localIdentity;
    if (identity === null) {
        if (input.hadIdentityFileError) {
            input.logger.warn("[argus-identity] identity file unreadable; fail-closed to public");
        }
        return defaultIdentityProfile();
    }
    const isPrivileged = identity.securityLevel === "secret" ||
        identity.securityLevel === "top_secret";
    return {
        principalType: isPrivileged ? "privileged_employee" : "external_user",
        targetAudience: "internal",
        channelClassification: "internal",
        allowedDataScopes: isPrivileged ? input.ownerDataScopes : [],
        userId: identity.userId,
        identitySource: identity.source,
        securityLevel: identity.securityLevel,
        roleLevel: SECURITY_LEVEL_NUMBERS[identity.securityLevel],
    };
}
function contentResultKey(input) {
    return input.toolCallId
        ? `call:${input.toolCallId}`
        : `fallback:${input.sessionId}:${input.toolName}`;
}
function rewrittenContent(response, field) {
    if (typeof response.data !== "object" || response.data === null) {
        return undefined;
    }
    const value = response.data[field];
    return typeof value === "string" ? value : undefined;
}
function cacheContentResponse(cache, key, response) {
    cache.set(key, {
        action: response.action,
        content: response.action === "rewrite"
            ? rewrittenContent(response, "content")
            : undefined,
        reason: response.reason,
        expiresAt: Date.now() + CONTENT_RESULT_TTL_MS,
    });
}
function removeExpiredResults(cache) {
    const now = Date.now();
    for (const [key, result] of cache) {
        if (result.expiresAt <= now) {
            cache.delete(key);
        }
    }
}
const plugin = definePluginEntry({
    id: "argus-adapter",
    name: "Argus Adapter",
    description: "Connect OpenClaw security boundaries to the Argus API.",
    register(api) {
        // This layer runs on assistant stream events before the dashboard consumes
        // them.  The final asynchronous IO Guard checks below remain authoritative,
        // while this deterministic transform prevents PII from being visible only
        // until a transcript refresh applies before_message_write redaction.
        api.registerTextTransforms({
            output: sensitiveTextReplacements(),
        });
        const config = parseConfig(api.pluginConfig);
        const client = new GuardClient(config);
        const { traceBySession, identityBySession, contentResultByCall, contentCheckByCall, blockedToolCalls, contextByToolCall, nextToolSequenceByTrace, usageLedger, } = sharedRuntimeState();
        const mediaRoot = resolveMediaRoot(config);
        const attachmentsBySession = new Map();
        const allocateToolSequence = (traceId) => {
            const sequence = nextToolSequenceByTrace.get(traceId) ?? 0;
            nextToolSequenceByTrace.set(traceId, sequence + 1);
            return sequence;
        };
        const removeExpiredToolCallContexts = () => {
            const now = Date.now();
            for (const [toolCallId, context] of contextByToolCall) {
                if (context.expiresAt <= now) {
                    contextByToolCall.delete(toolCallId);
                }
            }
        };
        const rememberToolCallContext = (toolCallId, context) => {
            removeExpiredToolCallContexts();
            if (!toolCallId) {
                return;
            }
            contextByToolCall.set(toolCallId, {
                ...context,
                expiresAt: Date.now() + CONTENT_RESULT_TTL_MS,
            });
        };
        const toolCallContext = (toolCallId) => {
            removeExpiredToolCallContexts();
            return toolCallId ? contextByToolCall.get(toolCallId) : undefined;
        };
        const forgetToolCallContext = (toolCallId) => {
            if (toolCallId) {
                contextByToolCall.delete(toolCallId);
            }
        };
        const markToolCallBlocked = (toolCallId) => {
            if (toolCallId) {
                blockedToolCalls.set(toolCallId, Date.now() + CONTENT_RESULT_TTL_MS);
            }
        };
        const isToolCallBlocked = (toolCallId) => {
            const now = Date.now();
            for (const [id, expiresAt] of blockedToolCalls) {
                if (expiresAt <= now) {
                    blockedToolCalls.delete(id);
                }
            }
            return Boolean(toolCallId && blockedToolCalls.has(toolCallId));
        };
        const consumeBlockedToolCall = (toolCallId) => {
            if (!isToolCallBlocked(toolCallId)) {
                return false;
            }
            blockedToolCalls.delete(toolCallId);
            return true;
        };
        const removeExpiredContentChecks = () => {
            const now = Date.now();
            for (const [key, check] of contentCheckByCall) {
                if (check.expiresAt <= now) {
                    contentCheckByCall.delete(key);
                }
            }
        };
        const checkToolContent = async (input) => {
            const content = toolResultText(input.toolName, input.result);
            return client.checkContent(identityForRequest({
                traceId: input.traceId,
                sessionId: input.sessionId,
                profile: input.profile,
            }), {
                tool_name: input.toolName,
                tool_call_id: input.toolCallId,
                url: typeof input.args.url === "string" ? input.args.url : "",
                // IO Guard's content stage consumes `content`, while the existing
                // Retrieval Guard adapter consumes `text`. Send one normalized tool
                // result under both compatibility fields so neither module needs to
                // change its own interface.
                content,
                text: content,
                source: input.toolName,
                sequence: input.sequence,
                metadata: {
                    hook: input.hook,
                    ...input.metadata,
                },
                principal_type: input.profile.principalType,
                target_audience: input.profile.targetAudience,
                channel_classification: input.profile.channelClassification,
                allowed_data_scopes: input.profile.allowedDataScopes,
            });
        };
        const checkToolContentOnce = (input) => {
            // Middleware and after_tool_call may overlap. Reuse one request so the
            // Audit layer receives one decision for each real tool call.
            removeExpiredContentChecks();
            if (!input.toolCallId) {
                return checkToolContent(input);
            }
            const key = contentResultKey({
                toolCallId: input.toolCallId,
                sessionId: input.sessionId,
                toolName: input.toolName,
            });
            const existing = contentCheckByCall.get(key);
            if (existing) {
                return existing.promise;
            }
            const promise = checkToolContent(input);
            contentCheckByCall.set(key, {
                promise,
                expiresAt: Date.now() + CONTENT_RESULT_TTL_MS,
            });
            return promise;
        };
        // Backup capture: media metadata on inbound messages may not survive into
        // the agent prompt markers, so stash per-session attachments here and let
        // before_agent_run merge them with the markers it parsed from the prompt.
        api.on("message_received", (event, ctx) => {
            const sessionKey = event.sessionKey ?? ctx.sessionKey ?? "";
            if (!sessionKey) {
                return;
            }
            const descriptors = attachmentsFromMetadata(event.metadata);
            if (descriptors.length === 0) {
                return;
            }
            const existing = attachmentsBySession.get(sessionKey) ?? [];
            attachmentsBySession.set(sessionKey, [
                ...existing,
                ...descriptors,
            ]);
        }, { priority: 100 });
        api.on("before_agent_run", async (event, ctx) => {
            const originalPrompt = event.prompt;
            const traceId = ctx.runId ?? randomUUID();
            const sessionId = ctx.sessionKey ?? ctx.sessionId ?? "default_session";
            const channel = ctx.channel ?? event.channelId ?? "";
            // Step 3 身份来源：本地身份文件（企业登录写入 / 个人版默认），
            // 读不到按最低 public fail-closed，不再猜 owner/channel。
            const localIdentity = readLocalIdentity(config.identityFile);
            const profile = resolveIdentityProfile({
                localIdentity,
                hadIdentityFileError: localIdentity === null,
                ownerDataScopes: config.ownerDataScopes,
                logger: api.logger,
            });
            if (sessionId) {
                // Step 4 会话隔离：同一 session 绑定首次使用的 user，换人后旧会话拒绝。
                // userId 为空（fail-closed 回落）不占绑定，免得污染真用户会话。
                if (profile.userId) {
                    const bound = identityBySession.get(sessionId);
                    if (bound && bound.userId && bound.userId !== profile.userId) {
                        api.logger.warn(`[argus-session] owner mismatch session=${sessionId} ` +
                            `bound=${bound.userId} current=${profile.userId}; isolated`);
                        return {
                            outcome: "block",
                            reason: "session_owner_mismatch",
                            message: "当前会话属于其他用户，已隔离，请新建会话。",
                            category: "argus_session",
                        };
                    }
                    identityBySession.set(sessionId, profile);
                }
                traceBySession.set(sessionId, traceId);
            }
            nextToolSequenceByTrace.set(traceId, 0);
            const bufferedAttachments = attachmentsBySession.get(sessionId) ?? [];
            attachmentsBySession.delete(sessionId);
            const attachments = mergeAttachments(parsePromptAttachments(originalPrompt), bufferedAttachments, mediaRoot, config.enableMediaCheck);
            const checkText = stripGatewayEnvelope(event.prompt);
            try {
                const result = await client.checkInput(identityForRequest({ traceId, sessionId, profile }), {
                    text: checkText,
                    channel,
                    // 等级数字与 access_control 1-4 对齐（public1/internal2/secret3/top_secret4，
                    // io_guard CLASSIFICATION_LEVELS 0-4 的判定不受影响，见 local-identity.ts 注释）。
                    role_level: profile.roleLevel,
                    principal_type: profile.principalType,
                    target_audience: profile.targetAudience,
                    channel_classification: profile.channelClassification,
                    purpose: "agent_conversation",
                    allowed_data_scopes: profile.allowedDataScopes,
                    metadata: {
                        agent_id: ctx.agentId ?? "",
                        hook: "before_agent_run",
                        identity_source: profile.identitySource,
                        security_level: profile.securityLevel,
                    },
                    ...(attachments.length > 0 ? { attachments } : {}),
                });
                api.logger.info(`argus-result ${JSON.stringify(result)}`);
                if (result.action === "allow") {
                    await client.bindToolSessionPrompt({
                        session_id: sessionId,
                        prompt: originalPrompt,
                        trace_id: traceId,
                    });
                    return { outcome: "pass" };
                }
                if (result.action === "rewrite") {
                    const sanitizedPrompt = rewrittenContent(result, "text");
                    if (sanitizedPrompt !== undefined) {
                        // The compatibility patch consumes this sanitized prompt while
                        // preserving the original user message for audit purposes.
                        const markerLines = extractMarkerLines(originalPrompt);
                        event.prompt =
                            markerLines.length > 0
                                ? `${sanitizedPrompt}\n${markerLines.join("\n")}`
                                : sanitizedPrompt;
                        await client.bindToolSessionPrompt({
                            session_id: sessionId,
                            prompt: originalPrompt,
                            trace_id: traceId,
                        });
                        return { outcome: "pass" };
                    }
                }
                return {
                    outcome: "block",
                    reason: result.reason,
                    message: BLOCKED_INPUT_MESSAGE,
                    category: "argus_input",
                };
            }
            catch (error) {
                api.logger.error(`Argus input check failed: ${error instanceof Error ? error.message : String(error)}`);
                if (config.failMode === "open") {
                    return { outcome: "pass" };
                }
                return {
                    outcome: "block",
                    reason: "argus_service_unavailable",
                    message: "安全检查服务不可用，本次请求已按关闭失败策略阻止。",
                    category: "guard_unavailable",
                };
            }
        }, { priority: 100, timeoutMs: config.timeoutMs + 500 });
        api.on("before_tool_call", async (event, ctx) => {
            const toolCallId = event.toolCallId ?? ctx.toolCallId;
            const sessionId = ctx.sessionKey ?? ctx.sessionId ?? "default_session";
            const traceId = (sessionId && traceBySession.get(sessionId)) ||
                event.runId ||
                ctx.runId ||
                randomUUID();
            const profile = identityBySession.get(sessionId) ?? defaultIdentityProfile();
            const toolName = normalizeToolName(event.toolName);
            const sequence = allocateToolSequence(traceId);
            rememberToolCallContext(toolCallId, {
                traceId,
                sessionId,
                profile,
                sequence,
            });
            try {
                const result = await client.checkTool(identityForRequest({ traceId, sessionId, profile }), {
                    tool_name: toolName,
                    original_tool_name: event.toolName,
                    arguments: event.params,
                    tool_call_id: toolCallId ?? "",
                    sequence,
                    // Step 3：身份来自本地文件，不再是猜的 sender。
                    // enterprise/personal=文件身份可信，fallback=最低等级回落。
                    identity_correlation_quality: profile.identitySource === "fallback"
                        ? "fallback"
                        : "identity_file",
                });
                api.logger.info(`argus-result ${JSON.stringify(result)}`);
                if (result.action === "allow") {
                    return;
                }
                if (result.action === "block") {
                    markToolCallBlocked(toolCallId);
                    return {
                        block: true,
                        blockReason: result.reason || BLOCKED_TOOL_MESSAGE,
                    };
                }
                if (result.action === "human_review") {
                    if (config.humanReviewAutoAllowTools.includes(event.toolName)) {
                        api.logger.warn(`argus-human-review-auto-allowed ${JSON.stringify({
                            toolName: event.toolName,
                            toolCallId,
                            traceId,
                            reason: result.reason,
                        })}`);
                        return;
                    }
                    return {
                        requireApproval: {
                            title: `Argus 请求确认工具：${event.toolName}`,
                            description: result.reason || BLOCKED_TOOL_MESSAGE,
                            severity: "warning",
                            timeoutBehavior: "deny",
                            pluginId: "argus-adapter",
                            onResolution: (decision) => {
                                if (decision !== "allow-once" &&
                                    decision !== "allow-always") {
                                    markToolCallBlocked(toolCallId);
                                }
                            },
                        },
                    };
                }
                const data = result.data;
                const rewrittenArguments = typeof data === "object" && data !== null
                    ? data.arguments
                    : undefined;
                if (typeof rewrittenArguments === "object" &&
                    rewrittenArguments !== null &&
                    !Array.isArray(rewrittenArguments)) {
                    return { params: rewrittenArguments };
                }
                markToolCallBlocked(toolCallId);
                return {
                    block: true,
                    blockReason: "Argus 返回 rewrite，但未提供合法的新工具参数。",
                };
            }
            catch (error) {
                api.logger.error(`Argus tool pre-check failed: ${error instanceof Error ? error.message : String(error)}`);
                if (config.failMode === "open") {
                    return;
                }
                markToolCallBlocked(toolCallId);
                return {
                    block: true,
                    blockReason: "安全检查服务不可用，本次工具调用已阻止。",
                };
            }
        }, { priority: 100, timeoutMs: config.timeoutMs + 500 });
        api.registerAgentToolResultMiddleware(async (event, ctx) => {
            if (!config.protectedTools.includes(event.toolName)) {
                return;
            }
            if (isToolCallBlocked(event.toolCallId)) {
                return;
            }
            const callContext = toolCallContext(event.toolCallId);
            const sessionId = callContext?.sessionId ??
                ctx.sessionKey ??
                ctx.sessionId ??
                event.threadId ??
                "";
            const traceId = callContext?.traceId ||
                (sessionId && traceBySession.get(sessionId)) ||
                ctx.runId ||
                event.turnId ||
                randomUUID();
            const profile = callContext?.profile ??
                identityBySession.get(sessionId) ??
                defaultIdentityProfile();
            const sequence = callContext?.sequence ?? allocateToolSequence(traceId);
            if (!callContext) {
                rememberToolCallContext(event.toolCallId, {
                    traceId,
                    sessionId,
                    profile,
                    sequence,
                });
            }
            const key = contentResultKey({
                toolCallId: event.toolCallId,
                sessionId,
                toolName: event.toolName,
            });
            removeExpiredResults(contentResultByCall);
            try {
                const result = await checkToolContentOnce({
                    toolName: event.toolName,
                    toolCallId: event.toolCallId,
                    args: event.args,
                    result: event.result,
                    sessionId,
                    traceId,
                    profile,
                    sequence,
                    hook: "agent_tool_result_middleware",
                    metadata: { tool_error: event.isError },
                });
                cacheContentResponse(contentResultByCall, key, result);
                api.logger.info(`argus-result ${JSON.stringify(result)}`);
                if (result.action === "allow") {
                    return;
                }
                const rewritten = rewrittenContent(result, "content");
                const replacement = result.action === "rewrite" && rewritten !== undefined
                    ? rewritten
                    : typeof result.risk_score === "number"
                        ? `[Argus 已隔离此工具结果：内容安全检查未通过。score=${result.risk_score}]`
                        : BLOCKED_CONTEXT_MESSAGE;
                return {
                    result: replaceMessageText(event.result, replacement),
                };
            }
            catch (error) {
                api.logger.error(`Argus content middleware failed: ${error instanceof Error ? error.message : String(error)}`);
                const action = config.failMode === "open" ? "allow" : "block";
                cacheContentResponse(contentResultByCall, key, {
                    trace_id: traceId,
                    stage: "content",
                    action,
                    risk_score: action === "allow" ? 0 : 1,
                    reason: "argus_service_unavailable",
                    data: null,
                    module_results: [],
                });
                if (config.failMode === "open") {
                    return;
                }
                return {
                    result: replaceMessageText(event.result, BLOCKED_CONTEXT_MESSAGE),
                };
            }
        }, { runtimes: ["openclaw"] });
        api.on("after_tool_call", async (event, ctx) => {
            const toolCallId = event.toolCallId ?? ctx.toolCallId;
            if (consumeBlockedToolCall(toolCallId)) {
                forgetToolCallContext(toolCallId);
                return;
            }
            const callContext = toolCallContext(toolCallId);
            const sessionId = callContext?.sessionId ??
                ctx.sessionKey ??
                ctx.sessionId ??
                "default_session";
            const traceId = callContext?.traceId ||
                (sessionId && traceBySession.get(sessionId)) ||
                event.runId ||
                ctx.runId ||
                randomUUID();
            const profile = callContext?.profile ??
                identityBySession.get(sessionId) ??
                defaultIdentityProfile();
            const sequence = callContext?.sequence ?? allocateToolSequence(traceId);
            if (!callContext) {
                rememberToolCallContext(toolCallId, {
                    traceId,
                    sessionId,
                    profile,
                    sequence,
                });
            }
            try {
                try {
                    await client.recordToolSessionCall({
                        session_id: sessionId,
                        tool_name: normalizeToolName(event.toolName),
                        arguments: event.params,
                        trace_id: traceId,
                    });
                }
                catch (error) {
                    api.logger.error(`Argus tool session recording failed: ${error instanceof Error ? error.message : String(error)}`);
                }
                if (!config.protectedTools.includes(event.toolName)) {
                    return;
                }
                const key = contentResultKey({
                    toolCallId,
                    sessionId,
                    toolName: event.toolName,
                });
                removeExpiredResults(contentResultByCall);
                try {
                    const result = await checkToolContentOnce({
                        toolName: event.toolName,
                        toolCallId: toolCallId ?? "",
                        args: event.params,
                        result: event.result ?? event.error ?? "",
                        sessionId,
                        traceId,
                        profile,
                        sequence,
                        hook: "after_tool_call",
                        metadata: {
                            duration_ms: event.durationMs,
                            tool_error: event.error,
                        },
                    });
                    cacheContentResponse(contentResultByCall, key, result);
                    api.logger.info(`argus-result ${JSON.stringify(result)}`);
                }
                catch (error) {
                    api.logger.error(`Argus content check failed: ${error instanceof Error ? error.message : String(error)}`);
                    contentResultByCall.set(key, {
                        action: config.failMode === "open" ? "allow" : "block",
                        reason: "argus_service_unavailable",
                        expiresAt: Date.now() + CONTENT_RESULT_TTL_MS,
                    });
                }
            }
            finally {
                // Keep successful context until TTL expiry. Late or duplicate result
                // hooks must reuse the original trace and numeric sequence.
                removeExpiredToolCallContexts();
            }
        }, { priority: 100, timeoutMs: config.timeoutMs + 500 });
        api.on("tool_result_persist", (event, ctx) => {
            const toolName = event.toolName ?? ctx.toolName ?? "";
            if (!config.protectedTools.includes(toolName)) {
                return;
            }
            const sessionId = ctx.sessionKey ?? "";
            const key = contentResultKey({
                toolCallId: event.toolCallId ?? ctx.toolCallId,
                sessionId,
                toolName,
            });
            removeExpiredResults(contentResultByCall);
            const result = contentResultByCall.get(key);
            contentResultByCall.delete(key);
            if (!result) {
                api.logger.warn(`Argus content result missing at persistence: tool=${toolName} key=${key}; applying failMode=${config.failMode}`);
                if (config.failMode === "open") {
                    return;
                }
                return {
                    message: replaceMessageText(event.message, BLOCKED_CONTEXT_MESSAGE),
                };
            }
            if (result.action === "allow") {
                return;
            }
            const replacement = result.action === "rewrite" && result.content !== undefined
                ? result.content
                : BLOCKED_CONTEXT_MESSAGE;
            return {
                message: replaceMessageText(event.message, replacement),
            };
        }, { priority: 100 });
        api.on("before_message_write", (event) => {
            const role = typeof event.message === "object" && event.message !== null
                ? event.message.role
                : undefined;
            if (role === "user") {
                return;
            }
            const message = redactSensitiveValue(event.message);
            if (message === event.message) {
                return;
            }
            return { message: message };
        }, { priority: 200 });
        api.on("message_sending", async (event, ctx) => {
            const sessionId = ctx.sessionKey ?? "";
            const traceId = (sessionId && traceBySession.get(sessionId)) ||
                ctx.runId ||
                ctx.traceId ||
                randomUUID();
            const profile = identityBySession.get(sessionId) ?? defaultIdentityProfile();
            try {
                const result = await client.checkOutput(identityForRequest({ traceId, sessionId, profile }), {
                    text: event.content,
                    channel: ctx.channelId ?? "",
                    principal_type: profile.principalType,
                    target_audience: profile.targetAudience,
                    channel_classification: profile.channelClassification,
                    purpose: "channel_delivery",
                    allowed_data_scopes: profile.allowedDataScopes,
                    metadata: {
                        destination: event.to,
                        hook: "message_sending",
                    },
                });
                api.logger.info(`argus-result ${JSON.stringify(result)}`);
                if (result.action === "allow") {
                    return;
                }
                const safeText = rewrittenContent(result, "text");
                if (safeText !== undefined &&
                    result.action === "rewrite") {
                    return {
                        content: safeText,
                        metadata: {
                            ...(event.metadata ?? {}),
                            argusAction: result.action,
                            argusReason: result.reason,
                        },
                    };
                }
                return {
                    content: BLOCKED_OUTPUT_MESSAGE,
                    metadata: {
                        ...(event.metadata ?? {}),
                        argusAction: result.action,
                        argusReason: result.reason,
                    },
                };
            }
            catch (error) {
                api.logger.error(`Argus output check failed: ${error instanceof Error ? error.message : String(error)}`);
                if (config.failMode === "open") {
                    return;
                }
                return {
                    content: "安全检查服务不可用，原始输出未发送。",
                    metadata: {
                        ...(event.metadata ?? {}),
                        argusAction: "service_unavailable",
                    },
                };
            }
        }, { priority: 100, timeoutMs: config.timeoutMs + 500 });
        api.on("reply_payload_sending", async (event, ctx) => {
            const text = event.payload.text;
            if (typeof text !== "string" || !text) {
                return;
            }
            const sessionId = event.sessionKey ?? ctx.sessionKey ?? "";
            const traceId = (sessionId && traceBySession.get(sessionId)) ||
                event.runId ||
                ctx.runId ||
                randomUUID();
            const profile = identityBySession.get(sessionId) ?? defaultIdentityProfile();
            try {
                const result = await client.checkOutput(identityForRequest({ traceId, sessionId, profile }), {
                    text,
                    channel: event.channel ?? ctx.channelId ?? "",
                    principal_type: profile.principalType,
                    target_audience: profile.targetAudience,
                    channel_classification: profile.channelClassification,
                    purpose: "reply_payload_delivery",
                    allowed_data_scopes: profile.allowedDataScopes,
                    metadata: {
                        reply_kind: event.kind,
                        hook: "reply_payload_sending",
                    },
                });
                api.logger.info(`argus-result ${JSON.stringify(result)}`);
                if (result.action === "allow") {
                    return;
                }
                const safeText = rewrittenContent(result, "text");
                if (safeText !== undefined &&
                    result.action === "rewrite") {
                    return { payload: { ...event.payload, text: safeText } };
                }
                return {
                    payload: { ...event.payload, text: BLOCKED_OUTPUT_MESSAGE },
                    reason: result.reason,
                };
            }
            catch (error) {
                api.logger.error(`Argus reply payload check failed: ${error instanceof Error ? error.message : String(error)}`);
                if (config.failMode === "open") {
                    return;
                }
                return {
                    payload: {
                        ...event.payload,
                        text: "安全检查服务不可用，原始输出未发送。",
                    },
                    reason: "argus_service_unavailable",
                };
            }
        }, { priority: 100, timeoutMs: config.timeoutMs + 500 });
        api.on("agent_end", (_event, ctx) => {
            const sessionId = ctx.sessionKey ?? ctx.sessionId ?? "";
            if (sessionId) {
                const traceId = traceBySession.get(sessionId);
                if (traceId) {
                    nextToolSequenceByTrace.delete(traceId);
                }
                identityBySession.delete(sessionId);
                traceBySession.delete(sessionId);
                attachmentsBySession.delete(sessionId);
            }
            removeExpiredResults(contentResultByCall);
            removeExpiredContentChecks();
            removeExpiredToolCallContexts();
        });
        api.on("gateway_start", async () => {
            const healthy = await client.health();
            if (healthy) {
                api.logger.info("Argus API is healthy");
            }
            else {
                api.logger.warn("Argus API is unavailable; failMode applies");
            }
        });
        // token 消耗记账：每次模型输出后，把 usage 写进账本。
        // llm_output 带 usage{input,output,cacheRead,cacheWrite,total} + provider/model，
        // 无 usage 的调用直接跳过（不估算、不编数）。
        // 每次模型输出后立即向 :8000 上报（fire-and-forget），避免首页长期显示 0。
        // 不用 setInterval：node --test 下未退出的 timer 会卡住测试进程。
        const flushUsageLedger = () => {
            try {
                const records = [];
                for (const [model, list] of usageLedger) {
                    for (const r of list.splice(0, list.length)) {
                        records.push({ model, ...r });
                    }
                    if (usageLedger.get(model)?.length === 0) {
                        usageLedger.delete(model);
                    }
                }
                if (records.length === 0) {
                    return;
                }
                void client
                    .reportUsage(records)
                    .catch(() => {
                    // 上报失败直接丢弃：用量是观测数据，不值得为它阻塞或堆积内存。
                });
            }
            catch {
                // 记账永不抛错，不影响主链路。
            }
        };
        api.on("llm_output", (event) => {
            try {
                const ev = event;
                if (!ev.usage || typeof ev.usage !== "object") {
                    return;
                }
                const ref = (typeof ev.resolvedRef === "string" && ev.resolvedRef) ||
                    (typeof ev.provider === "string" && typeof ev.model === "string"
                        ? `${ev.provider}/${ev.model}`
                        : typeof ev.model === "string" ? ev.model : "unknown");
                recordUsage(usageLedger, ref, ev.usage);
                flushUsageLedger();
            }
            catch {
                // 记账永不抛错，不影响主链路。
            }
        });
        api.on("gateway_stop", () => {
            contentResultByCall.clear();
            contentCheckByCall.clear();
            blockedToolCalls.clear();
            contextByToolCall.clear();
            nextToolSequenceByTrace.clear();
            identityBySession.clear();
            traceBySession.clear();
            attachmentsBySession.clear();
            flushUsageLedger();
            // usageLedger 不清：网关重启后首页仍能看到历史消耗。
        });
    },
});
export default plugin;
