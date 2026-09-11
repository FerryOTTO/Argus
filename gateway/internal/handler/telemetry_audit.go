package handler

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/model"
)

// 审计事件批量上传的约束上限（与 REMOTE.md §4.7 契约一致）
const (
	maxAuditEventsPerBatch = 500
	maxAuditEventIDLen     = 128
	maxAuditTraceLen       = 128
	maxAuditUserIDLen      = 64
	maxAuditModuleLen      = 64
	maxAuditStageLen       = 32
	maxAuditReasonBytes    = 4096
	maxAuditObjectBytes    = 64 << 10 // content/metadata JSON 序列化后单对象上限 64KB
)

// agentAuditActions 是 Argus AuditEvent.action 的合法取值（与客户端契约一致）
var agentAuditActions = map[string]bool{
	"allow": true, "block": true, "rewrite": true, "human_review": true,
}

// telemetryAuditEventRequest 对应 Argus 本地 audit-events.jsonl 的一条 AuditEvent。
// 字段名与客户端契约（REMOTE.md §4.7）一致。
type telemetryAuditEventRequest struct {
	EventID      string         `json:"event_id" binding:"required"`
	TraceID      string         `json:"trace_id"`
	SessionID    string         `json:"session_id"`
	UserID       string         `json:"user_id"`
	Timestamp    string         `json:"timestamp" binding:"required"`
	Stage        string         `json:"stage" binding:"required"`
	SourceModule string         `json:"source_module" binding:"required"`
	Action       string         `json:"action" binding:"required"`
	RiskScore    float64        `json:"risk_score"`
	Reason       string         `json:"reason"`
	Content      map[string]any `json:"content"`
	Metadata     map[string]any `json:"metadata"`
}

type telemetryAuditUploadRequest struct {
	Events []telemetryAuditEventRequest `json:"events" binding:"required"`
}

// UploadAuditEvents handles POST /telemetry/v1/audit/events.
// 客户端周期批量上传 Argus 审计事件（全量，含 allow）；服务端按
// (terminal_id, event_id) 幂等去重，客户端以 200 为准推进本地"已上传游标"。
// 整批全有或全无：任一条非法即 400 且整批不落库（message 携带 events[i] 索引定位），
// 防止客户端缺陷导致事件静默丢失。
func (h *TelemetryHandler) UploadAuditEvents(c *gin.Context) {
	if h.auditEventStore == nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "audit events store not available", "type": "internal_error"},
		})
		return
	}

	var req telemetryAuditUploadRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}
	if len(req.Events) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "events must not be empty", "type": "invalid_request_error"},
		})
		return
	}
	if len(req.Events) > maxAuditEventsPerBatch {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{
				"message": fmt.Sprintf("too many events in one batch: %d (max %d)", len(req.Events), maxAuditEventsPerBatch),
				"type":    "invalid_request_error",
				"code":    "batch_too_large",
			},
		})
		return
	}

	id := terminalID(c)
	name := c.GetString("terminal_name")

	rows := make([]model.AgentAuditEvent, 0, len(req.Events))
	seen := make(map[string]struct{}, len(req.Events))
	duplicates := int64(0)
	for i, ev := range req.Events {
		row, err := normalizeAuditEvent(id, name, ev)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{
				"error": gin.H{
					"message": fmt.Sprintf("events[%d]: %v", i, err),
					"type":    "invalid_request_error",
					"code":    "invalid_event",
				},
			})
			return
		}
		if _, dup := seen[row.EventID]; dup {
			duplicates++
			continue // 批内重复事件忽略，不落库
		}
		seen[row.EventID] = struct{}{}
		rows = append(rows, row)
	}

	accepted, err := h.auditEventStore.InsertBatch(rows)
	if err != nil {
		slog.Error("failed to insert agent audit events", "error", err, "terminal_id", id, "batch", len(rows))
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	duplicates += int64(len(rows)) - accepted

	slog.Info("terminal audit events uploaded",
		"terminal_id", id, "terminal_name", name,
		"events", len(rows), "accepted", accepted, "duplicates", duplicates)
	c.JSON(http.StatusOK, gin.H{
		"data": gin.H{
			"status":     "ok",
			"accepted":   accepted,
			"duplicates": duplicates,
		},
	})
}

// normalizeAuditEvent 校验并归一化一条上报事件为落库行：
// 时间归一化为 UTC RFC3339 秒级定宽（model.AuditEventTimeLayout）；
// content/metadata 为 nil 时落库 "{}"。
func normalizeAuditEvent(terminalID int64, terminalName string, ev telemetryAuditEventRequest) (model.AgentAuditEvent, error) {
	row := model.AgentAuditEvent{
		TerminalID:   terminalID,
		TerminalName: terminalName,
		EventID:      strings.TrimSpace(ev.EventID),
		TraceID:      strings.TrimSpace(ev.TraceID),
		SessionID:    strings.TrimSpace(ev.SessionID),
		UserID:       strings.TrimSpace(ev.UserID),
		Stage:        strings.TrimSpace(ev.Stage),
		SourceModule: strings.TrimSpace(ev.SourceModule),
		Action:       strings.TrimSpace(ev.Action),
		RiskScore:    ev.RiskScore,
		Reason:       strings.TrimSpace(ev.Reason),
	}

	if row.EventID == "" || len(row.EventID) > maxAuditEventIDLen {
		return row, fmt.Errorf("event_id is required and must be <= %d chars", maxAuditEventIDLen)
	}
	if len(row.TraceID) > maxAuditTraceLen {
		return row, fmt.Errorf("trace_id must be <= %d chars", maxAuditTraceLen)
	}
	if len(row.SessionID) > maxAuditTraceLen {
		return row, fmt.Errorf("session_id must be <= %d chars", maxAuditTraceLen)
	}
	if len(row.UserID) > maxAuditUserIDLen {
		return row, fmt.Errorf("user_id must be <= %d chars", maxAuditUserIDLen)
	}
	if row.Stage == "" || len(row.Stage) > maxAuditStageLen {
		return row, fmt.Errorf("stage is required and must be <= %d chars", maxAuditStageLen)
	}
	if row.SourceModule == "" || len(row.SourceModule) > maxAuditModuleLen {
		return row, fmt.Errorf("source_module is required and must be <= %d chars", maxAuditModuleLen)
	}
	if !agentAuditActions[row.Action] {
		return row, fmt.Errorf("action must be one of allow/block/rewrite/human_review (got %q)", row.Action)
	}
	if row.RiskScore < 0 || row.RiskScore > 1 {
		return row, fmt.Errorf("risk_score must be within [0, 1] (got %v)", row.RiskScore)
	}
	if len(row.Reason) > maxAuditReasonBytes {
		return row, fmt.Errorf("reason must be <= %d bytes", maxAuditReasonBytes)
	}

	ts, err := normalizeAuditTimestamp(ev.Timestamp)
	if err != nil {
		return row, err
	}
	row.EventTime = ts

	if row.Content, err = marshalAuditObject("content", ev.Content); err != nil {
		return row, err
	}
	if row.Metadata, err = marshalAuditObject("metadata", ev.Metadata); err != nil {
		return row, err
	}
	return row, nil
}

// normalizeAuditTimestamp 将客户端时间解析并归一化为 UTC RFC3339 秒级定宽文本。
// 接受 RFC3339(Nano) 与无时区时间（按 UTC 解释，契约要求客户端报 UTC）。
func normalizeAuditTimestamp(raw string) (string, error) {
	s := strings.TrimSpace(raw)
	for _, layout := range []string{time.RFC3339Nano, time.RFC3339, "2006-01-02T15:04:05", "2006-01-02 15:04:05"} {
		if t, err := time.Parse(layout, s); err == nil {
			return t.UTC().Format(model.AuditEventTimeLayout), nil
		}
	}
	return "", fmt.Errorf("timestamp must be ISO 8601 (got %q)", raw)
}

// marshalAuditObject 序列化 content/metadata（nil → "{}"），并施加单对象大小上限。
func marshalAuditObject(label string, m map[string]any) (string, error) {
	if m == nil {
		return "{}", nil
	}
	b, err := json.Marshal(m)
	if err != nil {
		return "", fmt.Errorf("%s is not valid JSON: %w", label, err)
	}
	if len(b) > maxAuditObjectBytes {
		return "", fmt.Errorf("%s must be <= %d bytes after serialization", label, maxAuditObjectBytes)
	}
	return string(b), nil
}
