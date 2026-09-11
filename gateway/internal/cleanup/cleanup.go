package cleanup

import (
	"log/slog"
	"time"

	"github.com/llmgate/llmgate/internal/store"
)

// Worker runs periodic cleanup of old audit logs, conversation logs, agent audit events, and usage records
type Worker struct {
	auditStore           *store.AuditStore
	convStore            *store.ConversationStore
	agentAuditEventStore *store.AgentAuditEventStore
	retentionDays        int
	stopCh               chan struct{}
}

// NewWorker creates a new cleanup Worker
func NewWorker(auditStore *store.AuditStore, convStore *store.ConversationStore, agentAuditEventStore *store.AgentAuditEventStore, retentionDays int) *Worker {
	if retentionDays <= 0 {
		retentionDays = 90
	}
	return &Worker{
		auditStore:           auditStore,
		convStore:            convStore,
		agentAuditEventStore: agentAuditEventStore,
		retentionDays:        retentionDays,
		stopCh:               make(chan struct{}),
	}
}

// Start begins the periodic cleanup goroutine
func (w *Worker) Start() {
	go w.run()
	slog.Info("cleanup worker started", "retention_days", w.retentionDays)
}

// Stop signals the cleanup worker to stop
func (w *Worker) Stop() {
	close(w.stopCh)
}

func (w *Worker) run() {
	// Run cleanup immediately on start
	w.doCleanup()

	ticker := time.NewTicker(24 * time.Hour)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			w.doCleanup()
		case <-w.stopCh:
			slog.Info("cleanup worker stopped")
			return
		}
	}
}

func (w *Worker) doCleanup() {
	auditDeleted, usageDeleted, err := w.auditStore.CleanupOldLogs(w.retentionDays)
	if err != nil {
		slog.Error("cleanup failed for audit logs", "error", err)
	} else if auditDeleted > 0 || usageDeleted > 0 {
		slog.Info("cleanup completed",
			"audit_logs_deleted", auditDeleted,
			"usage_records_deleted", usageDeleted,
			"retention_days", w.retentionDays,
		)
	}

	if w.convStore != nil {
		convDeleted, err := w.convStore.CleanupOldLogs(w.retentionDays)
		if err != nil {
			slog.Error("cleanup failed for conversation logs", "error", err)
		} else if convDeleted > 0 {
			slog.Info("conversation logs cleanup completed",
				"conversation_logs_deleted", convDeleted,
				"retention_days", w.retentionDays,
			)
		}
	}

	if w.agentAuditEventStore != nil {
		eventDeleted, err := w.agentAuditEventStore.CleanupOldEvents(w.retentionDays)
		if err != nil {
			slog.Error("cleanup failed for agent audit events", "error", err)
		} else if eventDeleted > 0 {
			slog.Info("agent audit events cleanup completed",
				"agent_audit_events_deleted", eventDeleted,
				"retention_days", w.retentionDays,
			)
		}
	}
}
