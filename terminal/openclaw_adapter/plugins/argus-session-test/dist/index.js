/**
 * Argus 全链路安全与访问控制拦截插件（OpenClaw 适配层）。
 * 
 * 功能：
 *   1. 输入阶段 (message_received)：绑定原始 Prompt 到 Tool Guard 意图会话，并上报审计事件；
 *   2. 工具前置 (before_tool_call)：同步请求 Argus /v1/tool/pre_check 进行 RBAC/MAC 鉴权与审计风险联动：
 *      - 若 action === "block"：物理阻断工具执行，向 Agent 返回结构化拦截原因；
 *      - 若 action === "human_review"：防线升级拦截，提示需人工二次审批；
 *      - 若 action === "allow"：放行执行真实工具；
 *   3. 输出阶段 (reply_payload_sending)：上报最终回复审计事件。
 */
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const ARGUS_URL = "http://127.0.0.1:8000";

// 从 hook 的 (event, ctx) 提取 Argus 审计/上下文通用字段
function extractAuditFields(stage, event, ctx) {
  const sessionId = ctx.sessionKey ?? ctx.sessionId ?? "default_session";
  const traceId = ctx.runId ?? event.messageId ?? ctx.messageId ?? crypto.randomUUID();
  const userId = ctx.userId ?? ctx.customHeaders?.["x-argus-user-id"] ?? ctx.headers?.["x-argus-user-id"] ?? "user_01";

  return {
    event_id: crypto.randomUUID(),
    trace_id: traceId,
    session_id: sessionId,
    user_id: userId,
    stage,
    source_module: "openclaw",
    action: stage === "input" ? "received" : stage === "output" ? "sent" : "tool_call",
    risk_score: 0.0,
    reason: "",
    content: {
      tool: event.toolName ?? null,
      tool_call_id: event.toolCallId ?? null,
      message_id: event.messageId ?? ctx.messageId ?? null,
      session_key: ctx.sessionKey ?? null,
      run_id: ctx.runId ?? null,
      arguments: event.params ?? event.arguments ?? null,
    },
    metadata: {
      channel: ctx.channelId ?? null,
      agent: ctx.agentId ?? null,
    },
  };
}

// 异步上报审计日志（fail-open：上报异常不影响主流程）
async function postAudit(audit) {
  try {
    await fetch(`${ARGUS_URL}/v1/audit/event`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(audit),
      signal: AbortSignal.timeout(3000),
    });
  } catch {
    /* 审计上报失败静默 */
  }
}

// 同步绑定 Prompt 到 Tool Guard
async function bindPrompt(sessionId, prompt, traceId) {
  try {
    await fetch(`${ARGUS_URL}/v1/tool/session/prompt`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, prompt, trace_id: traceId }),
      signal: AbortSignal.timeout(2000),
    });
  } catch {
    /* 忽略错误 */
  }
}

export default definePluginEntry({
  id: "argus-session-test",
  name: "Argus Access Control & Audit Plugin",
  description: "全流程拦截与鉴权插件：before_tool_call 访问控制卡点阻断 + 全链路会话审计",
  register(api) {
    // ① 输入阶段：记录意图锚点 + 上报审计
    api.on("message_received", async (event, ctx) => {
      const sessionId = ctx.sessionKey ?? ctx.sessionId ?? "default_session";
      const traceId = ctx.runId ?? event.messageId ?? ctx.messageId ?? "";
      const text = event.text ?? event.content ?? "";
      
      if (text) {
        void bindPrompt(sessionId, text, traceId);
      }
      void postAudit(extractAuditFields("input", event, ctx));
    });

    // ② 工具调用前：同步调用 Argus /v1/tool/pre_check 进行访问控制与防线升级判定
    api.on("before_tool_call", async (event, ctx) => {
      const toolName = event.toolName ?? "";
      const args = event.params ?? event.arguments ?? {};
      const sessionId = ctx.sessionKey ?? ctx.sessionId ?? "default_session";
      const traceId = ctx.runId ?? event.messageId ?? ctx.messageId ?? crypto.randomUUID();
      const userId = ctx.userId ?? ctx.customHeaders?.["x-argus-user-id"] ?? ctx.headers?.["x-argus-user-id"] ?? "user_01";

      try {
        const resp = await fetch(`${ARGUS_URL}/v1/tool/pre_check`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            context: {
              trace_id: traceId,
              session_id: sessionId,
              user_id: userId,
              stage: "tool_pre",
              timestamp: new Date().toISOString(),
            },
            payload: {
              tool_name: toolName,
              tool_call_id: event.toolCallId ?? "",
              arguments: args,
              database: "",
            },
          }),
          signal: AbortSignal.timeout(3000),
        });

        if (resp.ok) {
          const res = await resp.json();
          const action = res.action;
          const reason = res.reason || "";
          const riskScore = res.risk_score || 0.0;

          // 1. 访问控制拦截 (BLOCK)
          if (action === "block") {
            void postAudit({
              event_id: crypto.randomUUID(),
              trace_id: traceId,
              session_id: sessionId,
              user_id: userId,
              timestamp: new Date().toISOString(),
              stage: "tool_pre",
              source_module: "access_control",
              action: "block",
              risk_score: riskScore,
              reason: reason,
              content: { tool: toolName, arguments: args },
              metadata: { channel: ctx.channelId ?? null },
            });

            return {
              block: true,
              blockReason: `[Argus 安全拦截] 访问控制拒绝执行工具 "${toolName}": ${reason}`,
            };
          }

          // 2. 二次审批 (human_review)
          if (action === "human_review") {
            void postAudit({
              event_id: crypto.randomUUID(),
              trace_id: traceId,
              session_id: sessionId,
              user_id: userId,
              timestamp: new Date().toISOString(),
              stage: "tool_pre",
              source_module: "access_control",
              action: "human_review",
              risk_score: riskScore,
              reason: reason,
              content: { tool: toolName, arguments: args },
              metadata: { channel: ctx.channelId ?? null },
            });

            return {
              block: true,
              blockReason: `[Argus 二次审批] 触发防线升级二次审批: ${reason}`,
            };
          }

          // 3. 放行 (ALLOW)
          void postAudit(extractAuditFields("tool", event, ctx));
          return { block: false };
        }
      } catch (err) {
        console.error("[Argus Plugin] pre_check error:", err.message);
        // Fail-open: 安全网关异常时不阻断正常业务
      }

      return { block: false };
    });

    // ③ 输出阶段：上报最终回复审计
    api.on("reply_payload_sending", (event, ctx) => {
      void postAudit(extractAuditFields("output", event, ctx));
    });
  },
});
