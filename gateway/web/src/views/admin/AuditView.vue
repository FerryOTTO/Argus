<template>
  <div class="audit-page">
    <h2 class="page-title">审计日志</h2>

    <el-tabs v-model="activeTab" @tab-change="handleTabChange">
      <!-- LLM 用量 Tab -->
      <el-tab-pane label="LLM 用量" name="usage">
        <div class="filter-bar">
          <el-date-picker
            v-model="usageDateRange"
            type="datetimerange"
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            value-format="YYYY-MM-DDTHH:mm:ss"
            style="width: 380px"
            @change="fetchUsageLogs"
          />
          <el-select
            v-model="usageUserId"
            placeholder="全部用户"
            clearable
            filterable
            style="width: 160px; margin-left: 12px"
            @change="fetchUsageLogs"
          >
            <el-option v-for="u in users" :key="u.id" :label="u.username" :value="u.id" />
          </el-select>
          <el-input
            v-model="usageModel"
            placeholder="模型名称"
            clearable
            style="width: 160px; margin-left: 12px"
            @clear="fetchUsageLogs"
            @keyup.enter="fetchUsageLogs"
          />
          <el-button
            type="primary"
            plain
            style="margin-left: 12px"
            :loading="exporting"
            @click="handleExportUsage"
          >
            <el-icon><Download /></el-icon>导出 CSV
          </el-button>
        </div>

        <el-table :data="usageLogs" v-loading="usageLoading" stripe style="width: 100%">
          <el-table-column label="时间" width="170">
            <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="用户" width="120">
            <template #default="{ row }">{{ getUserLabel(row.user_id) }}</template>
          </el-table-column>
          <el-table-column label="API Key" width="120">
            <template #default="{ row }">
              <span v-if="row.api_key_id">***{{ String(row.api_key_id).slice(-4) }}</span>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="模型" width="180">
            <template #default="{ row }">
              {{ row.model_id || '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="prompt_tokens" label="Prompt Tokens" width="130" align="right" />
          <el-table-column prop="completion_tokens" label="Completion Tokens" width="150" align="right" />
          <el-table-column label="延迟" width="100" align="right">
            <template #default="{ row }">{{ row.latency_ms }}ms</template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.status_code >= 400 ? 'danger' : 'success'" size="small">
                {{ row.status_code }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>

        <div class="pagination-wrap">
          <el-pagination
            v-model:current-page="usagePage"
            v-model:page-size="usagePageSize"
            :total="usageTotal"
            :page-sizes="[20, 50, 100]"
            layout="total, sizes, prev, pager, next"
            @current-change="fetchUsageLogs"
            @size-change="fetchUsageLogs"
          />
        </div>
      </el-tab-pane>

      <!-- 行为审计 Tab -->
      <el-tab-pane label="行为审计" name="action">
        <div class="filter-bar">
          <el-date-picker
            v-model="actionDateRange"
            type="datetimerange"
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            value-format="YYYY-MM-DDTHH:mm:ss"
            style="width: 380px"
            @change="fetchActionLogs"
          />
          <el-select
            v-model="actionUserId"
            placeholder="全部用户"
            clearable
            filterable
            style="width: 160px; margin-left: 12px"
            @change="fetchActionLogs"
          >
            <el-option v-for="u in users" :key="u.id" :label="u.username" :value="u.id" />
          </el-select>
          <el-select
            v-model="actionType"
            placeholder="全部操作"
            clearable
            style="width: 160px; margin-left: 12px"
            @change="fetchActionLogs"
          >
            <el-option label="chat_completion" value="chat_completion" />
            <el-option label="login" value="login" />
            <el-option label="create" value="create" />
            <el-option label="update" value="update" />
            <el-option label="delete" value="delete" />
          </el-select>
          <el-button
            type="primary"
            plain
            style="margin-left: 12px"
            :loading="exporting"
            @click="handleExport"
          >
            <el-icon><Download /></el-icon>导出 CSV
          </el-button>
        </div>

        <el-table :data="actionLogs" v-loading="actionLoading" stripe style="width: 100%">
          <el-table-column label="时间" width="170">
            <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="用户" width="120">
            <template #default="{ row }">{{ getUserLabel(row.user_id) }}</template>
          </el-table-column>
          <el-table-column prop="action" label="操作" width="160" />
          <el-table-column prop="request_path" label="路径" min-width="200" show-overflow-tooltip />
          <el-table-column label="状态码" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status_code >= 400 ? 'danger' : 'success'" size="small">
                {{ row.status_code }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="IP" width="140">
            <template #default="{ row }">{{ row.client_ip || '-' }}</template>
          </el-table-column>
          <el-table-column label="延迟" width="100" align="right">
            <template #default="{ row }">{{ row.latency_ms }}ms</template>
          </el-table-column>
        </el-table>

        <div class="pagination-wrap">
          <el-pagination
            v-model:current-page="actionPage"
            v-model:page-size="actionPageSize"
            :total="actionTotal"
            :page-sizes="[20, 50, 100]"
            layout="total, sizes, prev, pager, next"
            @current-change="fetchActionLogs"
            @size-change="fetchActionLogs"
          />
        </div>
      </el-tab-pane>

      <!-- 终端审计 Tab（Argus 客户端上报的审计事件，以终端为单位查看） -->
      <el-tab-pane label="终端审计" name="agent">
        <!-- 统计卡：未选终端=全部终端口径；选中终端后联动为该终端口径 -->
        <div v-if="statsCards" class="agent-stats-row">
          <div class="agent-stat-scope">
            <el-icon><Monitor /></el-icon>
            <span>{{ selectedTerminal ? `当前终端：${selectedTerminal.terminal_name}` : '全部终端' }}</span>
          </div>
          <div class="agent-stat-card">
            <div class="agent-stat-value">{{ statsCards.total_events }}</div>
            <div class="agent-stat-label">累计事件</div>
          </div>
          <div class="agent-stat-card">
            <div class="agent-stat-value">{{ statsCards.today_events }}</div>
            <div class="agent-stat-label">今日事件</div>
          </div>
          <div class="agent-stat-card">
            <div class="agent-stat-value warn">{{ statsCards.alerts_today }}</div>
            <div class="agent-stat-label">今日非放行</div>
          </div>
          <div class="agent-stat-card">
            <div class="agent-stat-value danger">{{ statsCards.high_risk_today }}</div>
            <div class="agent-stat-label">今日高危（≥0.7）</div>
          </div>
        </div>

        <div class="agent-workspace">
          <!-- 左栏：终端列表（按最近审计时间倒序，无审计终端置后） -->
          <aside class="agent-panel agent-terminal-panel">
            <div class="agent-panel-head">
              <span class="agent-panel-title">终端列表</span>
              <el-tag size="small" type="info" disable-transitions>{{ filteredTerminalStats.length }}</el-tag>
              <el-button class="agent-panel-refresh" link size="small" title="刷新" @click="refreshAgentWorkspace">
                <el-icon><Refresh /></el-icon>
              </el-button>
            </div>
            <div class="agent-panel-search">
              <el-input v-model="terminalKeyword" placeholder="搜索终端名称 / 主机" clearable size="small">
                <template #prefix><el-icon><Search /></el-icon></template>
              </el-input>
            </div>
            <div class="agent-terminal-scroll">
              <div
                v-for="t in filteredTerminalStats"
                :key="t.terminal_id"
                class="agent-terminal-card"
                :class="[terminalCardLevel(t), { 'is-active': selectedTerminalId === t.terminal_id }]"
                @click="selectTerminal(t)"
              >
                <div class="agent-term-head">
                  <span class="agent-term-name" :title="t.terminal_name">{{ t.terminal_name }}</span>
                  <el-tag size="small" :type="terminalStateTag(t).type" disable-transitions>
                    {{ terminalStateTag(t).label }}
                  </el-tag>
                </div>
                <div class="agent-term-sub">{{ t.hostname || '未上报主机名' }}{{ t.os_info ? ' · ' + t.os_info : '' }}</div>
                <div class="agent-term-metrics">
                  <span class="agent-term-total">{{ t.total_events }}<em> 事件</em></span>
                  <span class="agent-term-metric">今日 <b>{{ t.today_events }}</b></span>
                  <span class="agent-term-metric" :class="{ 'text-warn': t.alerts_today > 0 }">非放行 <b>{{ t.alerts_today }}</b></span>
                  <span class="agent-term-metric" :class="{ 'text-danger': t.high_risk_today > 0 }">高危 <b>{{ t.high_risk_today }}</b></span>
                </div>
                <div class="agent-term-foot">
                  <span>最近审计：{{ lastEventLabel(t) }}</span>
                  <span v-if="t.argus_version" class="agent-term-ver">CG {{ t.argus_version }}</span>
                </div>
              </div>
              <el-empty v-if="!agentLoadingTerminals && !filteredTerminalStats.length" description="暂无终端，请先在「终端管理」添加" :image-size="64" />
            </div>
          </aside>

          <!-- 右栏：选中终端的审计记录 -->
          <section class="agent-panel agent-main-panel">
            <div class="agent-context-bar">
              <div class="agent-context-left">
                <template v-if="selectedTerminal">
                  <span class="agent-ctx-dot" :class="terminalStateTag(selectedTerminal).cls"></span>
                  <strong class="agent-ctx-name">{{ selectedTerminal.terminal_name }}</strong>
                  <span class="agent-ctx-sep">审计记录</span>
                  <span class="agent-ctx-meta">最近上报 {{ lastEventLabel(selectedTerminal) }}</span>
                  <el-button link type="primary" size="small" @click="clearTerminal">查看全部终端</el-button>
                </template>
                <template v-else>
                  <strong class="agent-ctx-name">全部终端</strong>
                  <span class="agent-ctx-sep">审计事件</span>
                  <span class="agent-ctx-meta">点击左侧终端可聚焦单终端审计</span>
                </template>
              </div>
              <div class="agent-context-right">
                <el-radio-group v-model="agentViewMode" size="small">
                  <el-radio-button value="timeline">时间线</el-radio-button>
                  <el-radio-button value="table">表格</el-radio-button>
                </el-radio-group>
                <el-button
                  type="primary"
                  plain
                  size="small"
                  :loading="agentExporting"
                  @click="handleExportAgentEvents"
                >
                  <el-icon><Download /></el-icon>导出 CSV
                </el-button>
              </div>
            </div>

            <div class="filter-bar agent-filter-bar">
              <el-date-picker
                v-model="agentDateRange"
                type="datetimerange"
                range-separator="至"
                start-placeholder="开始时间"
                end-placeholder="结束时间"
                value-format="YYYY-MM-DDTHH:mm:ss"
                style="width: 320px"
                @change="applyAgentFilter"
              />
              <el-select v-model="agentStage" placeholder="全部阶段" clearable style="width: 110px" @change="applyAgentFilter">
                <el-option v-for="o in stageOptions" :key="o.value" :label="o.label" :value="o.value" />
              </el-select>
              <el-select v-model="agentAction" placeholder="全部动作" clearable style="width: 110px" @change="applyAgentFilter">
                <el-option v-for="o in actionOptions" :key="o.value" :label="o.label" :value="o.value" />
              </el-select>
              <el-select v-model="agentRiskMin" placeholder="风险不限" clearable style="width: 110px" @change="applyAgentFilter">
                <el-option label="风险 ≥ 0.5" :value="0.5" />
                <el-option label="风险 ≥ 0.7" :value="0.7" />
                <el-option label="风险 ≥ 0.85" :value="0.85" />
              </el-select>
              <el-select v-model="agentModule" placeholder="全部模块" clearable filterable allow-create style="width: 130px" @change="applyAgentFilter">
                <el-option v-for="m in agentModuleOptions" :key="m" :label="m" :value="m" />
              </el-select>
              <el-input
                v-model="agentKeyword"
                placeholder="链路/会话/事件ID/理由"
                clearable
                style="width: 170px"
                @clear="applyAgentFilter"
                @keyup.enter="applyAgentFilter"
              />
            </div>

            <!-- 时间线视图（参考 Argus 审计页：事件卡片流 + 风险色） -->
            <div v-if="agentViewMode === 'timeline'" v-loading="agentLoading" class="agent-timeline">
              <div
                v-for="(ev, idx) in agentEvents"
                :key="ev.id"
                class="agent-tl-event"
                :class="eventLevel(ev)"
                @click="openAgentDetail(ev)"
              >
                <div class="agent-tl-seq">{{ (agentPage - 1) * agentPageSize + idx + 1 }}</div>
                <div class="agent-tl-card">
                  <div class="agent-tl-top">
                    <span class="agent-tl-stage">{{ stageLabel(ev.stage) }}</span>
                    <el-tag size="small" :type="actionTagType(ev.action)" disable-transitions>
                      {{ actionLabel(ev.action) }}
                    </el-tag>
                    <el-tag size="small" :type="riskTagType(ev.risk_score)" disable-transitions>
                      风险 {{ riskPercent(ev.risk_score) }}
                    </el-tag>
                    <span class="agent-tl-time">{{ formatDate(ev.event_time) }}</span>
                  </div>
                  <div class="agent-tl-title">
                    {{ ev.reason || stageLabel(ev.stage) + ' · ' + actionLabel(ev.action) + (ev.source_module ? ' · ' + ev.source_module : '') }}
                  </div>
                  <div class="agent-tl-meta">
                    <span v-if="ev.trace_id" class="agent-tl-chip" title="链路 ID">链路 {{ shortId(ev.trace_id) }}</span>
                    <span v-if="ev.session_id" class="agent-tl-chip" title="会话 ID">会话 {{ shortId(ev.session_id) }}</span>
                    <span v-if="ev.user_id" class="agent-tl-chip" title="用户">用户 {{ ev.user_id }}</span>
                    <span class="agent-tl-chip">{{ ev.source_module || '-' }}</span>
                    <span v-if="!selectedTerminal" class="agent-tl-chip agent-tl-terminal">{{ terminalLabel(ev) }}</span>
                    <span v-if="contentPreview(ev)" class="agent-tl-preview">{{ contentPreview(ev) }}</span>
                  </div>
                </div>
              </div>
              <el-empty
                v-if="!agentLoading && !agentEvents.length"
                :description="agentEmptyText"
                :image-size="80"
              />
            </div>

            <!-- 表格视图 -->
            <el-table v-else :data="agentEvents" v-loading="agentLoading" stripe style="width: 100%">
              <el-table-column label="时间" width="165">
                <template #default="{ row }">{{ formatDate(row.event_time) }}</template>
              </el-table-column>
              <el-table-column v-if="!selectedTerminal" label="终端" min-width="130" show-overflow-tooltip>
                <template #default="{ row }">{{ terminalLabel(row) }}</template>
              </el-table-column>
              <el-table-column label="阶段" width="100" align="center">
                <template #default="{ row }">
                  <el-tag size="small">{{ stageLabel(row.stage) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="动作" width="95" align="center">
                <template #default="{ row }">
                  <el-tag size="small" :type="actionTagType(row.action)">{{ actionLabel(row.action) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="风险" width="80" align="center">
                <template #default="{ row }">
                  <el-tag size="small" :type="riskTagType(row.risk_score)">{{ riskPercent(row.risk_score) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="模块" width="130" show-overflow-tooltip>
                <template #default="{ row }">{{ row.source_module }}</template>
              </el-table-column>
              <el-table-column label="用户" width="110" show-overflow-tooltip>
                <template #default="{ row }">{{ row.user_id || '-' }}</template>
              </el-table-column>
              <el-table-column label="链路 ID" width="140" show-overflow-tooltip>
                <template #default="{ row }">{{ row.trace_id || '-' }}</template>
              </el-table-column>
              <el-table-column label="理由" min-width="200" show-overflow-tooltip>
                <template #default="{ row }">{{ row.reason || '-' }}</template>
              </el-table-column>
              <el-table-column label="操作" width="80" fixed="right">
                <template #default="{ row }">
                  <el-button type="primary" link size="small" @click="openAgentDetail(row)">详情</el-button>
                </template>
              </el-table-column>
            </el-table>

            <div class="pagination-wrap">
              <el-pagination
                v-model:current-page="agentPage"
                v-model:page-size="agentPageSize"
                :total="agentTotal"
                :page-sizes="[20, 50, 100]"
                layout="total, sizes, prev, pager, next"
                @current-change="fetchAgentEvents"
                @size-change="applyAgentFilter"
              />
            </div>
          </section>
        </div>
      </el-tab-pane>

      <!-- 对话记录 Tab -->
      <el-tab-pane label="对话记录" name="conversation">
        <div class="filter-bar">
          <el-date-picker
            v-model="convDateRange"
            type="datetimerange"
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            value-format="YYYY-MM-DDTHH:mm:ss"
            style="width: 380px"
            @change="fetchConversations"
          />
          <el-select
            v-model="convUserId"
            placeholder="全部用户"
            clearable
            filterable
            style="width: 160px; margin-left: 12px"
            @change="fetchConversations"
          >
            <el-option v-for="u in users" :key="u.id" :label="u.username" :value="u.id" />
          </el-select>
          <el-input
            v-model="convModel"
            placeholder="模型名称"
            clearable
            style="width: 160px; margin-left: 12px"
            @clear="fetchConversations"
            @keyup.enter="fetchConversations"
          />
          <el-button
            type="primary"
            plain
            style="margin-left: 12px"
            :loading="convExporting"
            @click="handleExportConversations"
          >
            <el-icon><Download /></el-icon>导出 CSV
          </el-button>
        </div>

        <el-table :data="convLogs" v-loading="convLoading" stripe style="width: 100%">
          <el-table-column label="时间" width="170">
            <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="用户" width="120">
            <template #default="{ row }">{{ getUserLabel(row.user_id) }}</template>
          </el-table-column>
          <el-table-column label="模型" width="180">
            <template #default="{ row }">{{ row.model_id || '-' }}</template>
          </el-table-column>
          <el-table-column label="类型" width="100">
            <template #default="{ row }">
              <el-tag :type="row.is_stream ? '' : 'info'" size="small">
                {{ row.is_stream ? '流式' : '非流式' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态码" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status_code >= 400 ? 'danger' : 'success'" size="small">
                {{ row.status_code }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="openConvDetail(row)">查看</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="pagination-wrap">
          <el-pagination
            v-model:current-page="convPage"
            v-model:page-size="convPageSize"
            :total="convTotal"
            :page-sizes="[20, 50, 100]"
            layout="total, sizes, prev, pager, next"
            @current-change="fetchConversations"
            @size-change="fetchConversations"
          />
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 对话详情 Dialog -->
    <el-dialog v-model="detailVisible" title="对话详情" width="900px" destroy-on-close>
      <div v-loading="detailLoading" class="conv-detail-wrap">
        <template v-if="convDetail">
          <div class="detail-meta">
            <span>用户: {{ getUserLabel(convDetail.user_id) }}</span>
            <span>模型: {{ convDetail.model_id || '-' }}</span>
            <span>时间: {{ formatDate(convDetail.created_at) }}</span>
            <el-tag :type="convDetail.is_stream ? '' : 'info'" size="small">
              {{ convDetail.is_stream ? '流式' : '非流式' }}
            </el-tag>
            <el-tag :type="convDetail.status_code >= 400 ? 'danger' : 'success'" size="small">
              {{ convDetail.status_code }}
            </el-tag>
          </div>

          <h4 class="detail-section-title">请求内容</h4>
          <div v-if="parsedMessages.length" class="messages-list">
            <div v-for="(msg, idx) in parsedMessages" :key="idx" class="message-item">
              <span class="role-badge" :class="'role-' + msg.role">{{ msg.role }}</span>
              <div class="message-content">{{ msg.content }}</div>
            </div>
          </div>
          <div v-else class="no-content">无消息内容</div>

          <h4 class="detail-section-title">响应内容</h4>
          <pre v-if="convDetail.response_body" class="response-body">{{ convDetail.response_body }}</pre>
          <div v-else class="no-content">无响应内容</div>
        </template>
      </div>
    </el-dialog>

    <!-- 终端审计事件详情 Drawer -->
    <el-drawer v-model="agentDetailVisible" title="审计事件详情" size="640px">
      <div v-if="agentDetail" class="agent-detail-wrap">
        <div class="detail-meta">
          <span>时间: {{ formatDate(agentDetail.event_time) }}</span>
          <span>终端: {{ terminalLabel(agentDetail) }}</span>
          <span>用户: {{ agentDetail.user_id || '-' }}</span>
          <span>会话: {{ agentDetail.session_id || '-' }}</span>
        </div>
        <div class="agent-detail-tags">
          <el-tag size="small">{{ stageLabel(agentDetail.stage) }}</el-tag>
          <el-tag size="small" :type="actionTagType(agentDetail.action)">{{ actionLabel(agentDetail.action) }}</el-tag>
          <el-tag size="small" :type="riskTagType(agentDetail.risk_score)">风险 {{ riskPercent(agentDetail.risk_score) }}</el-tag>
          <el-tag v-if="agentDetail.source_module" size="small" type="info">{{ agentDetail.source_module }}</el-tag>
        </div>
        <div v-if="agentDetail.reason" class="agent-reason">{{ agentDetail.reason }}</div>
        <div class="agent-trace">
          事件ID: <code>{{ agentDetail.event_id }}</code><br />
          链路ID: <code>{{ agentDetail.trace_id || '-' }}</code>
        </div>
        <h4 class="detail-section-title">内容（content）</h4>
        <pre class="agent-json">{{ prettyJson(agentDetail.content) }}</pre>
        <h4 class="detail-section-title">元数据（metadata）</h4>
        <pre class="agent-json">{{ prettyJson(agentDetail.metadata) }}</pre>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getAuditLogs, exportAuditLogs, getUsers, getConversations, getConversationDetail, getAgentAuditEvents, getAgentAuditStats, getAgentTerminalStats, exportAgentAuditEvents } from '@/api/admin'

const activeTab = ref('usage')
const users = ref<any[]>([])

// --- 共享 ---
function formatDate(dateStr: string) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN')
}

function getUserLabel(userId: number) {
  const u = users.value.find((u: any) => u.id === userId)
  return u ? u.username : `用户 #${userId}`
}

async function fetchUsers() {
  try {
    const res = await getUsers()
    users.value = res.data.data || []
  } catch {
    ElMessage.error('获取用户列表失败')
  }
}

// --- 终端审计（Argus 客户端上报事件） ---
const stageOptions = [
  { label: '输入检测', value: 'input' },
  { label: '工具前置', value: 'tool_pre' },
  { label: '内容复检', value: 'content' },
  { label: '输出检测', value: 'output' },
  { label: '审计复核', value: 'audit' },
]
const actionOptions = [
  { label: '放行', value: 'allow' },
  { label: '拦截', value: 'block' },
  { label: '改写', value: 'rewrite' },
  { label: '人工复核', value: 'human_review' },
]

function stageLabel(v: string) {
  const hit = stageOptions.find((o) => o.value === v)
  return hit ? hit.label : v
}

function actionLabel(v: string) {
  const hit = actionOptions.find((o) => o.value === v)
  return hit ? hit.label : v
}

function actionTagType(v: string) {
  const map: Record<string, string> = { allow: 'success', block: 'danger', rewrite: 'warning', human_review: 'info' }
  return map[v] || ''
}

function riskTagType(r: number) {
  if (r >= 0.85) return 'danger'
  if (r >= 0.6) return 'warning'
  if (r >= 0.3) return 'primary'
  return 'info'
}

function riskPercent(r: number) {
  return `${Math.round(r * 100)}%`
}

function terminalLabel(row: any) {
  return row.terminal_name || '终端 #' + row.terminal_id
}

function shortId(v: string, head = 10, tail = 6) {
  const s = String(v || '')
  return s.length > head + tail + 1 ? `${s.slice(0, head)}…${s.slice(-tail)}` : s
}

function contentPreview(row: any) {
  try {
    const obj = JSON.parse(row.content || '{}')
    const text = JSON.stringify(obj)
      .replace(/[{}["]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
    return text ? text.slice(0, 120) : ''
  } catch {
    const s = String(row.content || '').replace(/\s+/g, ' ').trim()
    return s.slice(0, 120)
  }
}

// --- 终端审计：以终端为单位的工作区 ---
const agentTerminalStats = ref<any[]>([])
const agentLoadingTerminals = ref(false)
const terminalKeyword = ref('')
const selectedTerminalId = ref<number | null>(null)
const agentViewMode = ref<'timeline' | 'table'>('timeline')

const selectedTerminal = computed(() =>
  agentTerminalStats.value.find((t) => t.terminal_id === selectedTerminalId.value) || null
)

const filteredTerminalStats = computed(() => {
  const kw = terminalKeyword.value.trim().toLowerCase()
  if (!kw) return agentTerminalStats.value
  return agentTerminalStats.value.filter(
    (t) =>
      t.terminal_name.toLowerCase().includes(kw) ||
      (t.hostname || '').toLowerCase().includes(kw)
  )
})

// 统计卡：选中终端后切换为该终端口径（终端聚合来自 terminal-stats，口径与全局一致）
const statsCards = computed(() => {
  if (selectedTerminal.value) {
    return {
      total_events: selectedTerminal.value.total_events,
      today_events: selectedTerminal.value.today_events,
      alerts_today: selectedTerminal.value.alerts_today,
      high_risk_today: selectedTerminal.value.high_risk_today,
    }
  }
  return agentStats.value
})

function terminalStateTag(t: any) {
  if (t.status === 'pending') return { label: '未注册', type: 'info', cls: 'state-pending' }
  return t.online
    ? { label: '在线', type: 'success', cls: 'state-online' }
    : { label: '离线', type: 'info', cls: 'state-offline' }
}

function terminalCardLevel(t: any) {
  if (t.high_risk_today > 0) return 'card-level-danger'
  if (t.alerts_today > 0) return 'card-level-warn'
  if (t.total_events > 0) return 'card-level-events'
  return ''
}

function eventLevel(ev: any) {
  if (ev.action === 'block' || ev.risk_score >= 0.85) return 'tl-level-danger'
  if (ev.risk_score >= 0.6) return 'tl-level-warn'
  if (ev.action === 'human_review') return 'tl-level-warn'
  return ''
}

const agentModuleOptions = computed(() => {
  const set = new Set<string>()
  agentEvents.value.forEach((ev) => ev.source_module && set.add(ev.source_module))
  return Array.from(set).sort()
})

function lastEventLabel(t: any) {
  return t.last_event_time ? formatDate(t.last_event_time) : '暂无上报'
}

const agentEmptyText = computed(() => {
  if (!agentTerminalStats.value.length) return '暂无审计事件，等待终端 Argus 上报'
  if (selectedTerminal.value && selectedTerminal.value.total_events === 0) return '该终端暂无审计事件'
  return '当前条件下没有匹配的审计事件'
})

async function fetchAgentTerminalStats() {
  agentLoadingTerminals.value = true
  try {
    const res = await getAgentTerminalStats()
    agentTerminalStats.value = res.data?.data || []
  } catch {
    ElMessage.error('获取终端审计统计失败')
  } finally {
    agentLoadingTerminals.value = false
  }
}

function selectTerminal(t: any) {
  if (selectedTerminalId.value === t.terminal_id) return
  selectedTerminalId.value = t.terminal_id
  agentKeyword.value = ''
  agentStage.value = ''
  agentAction.value = ''
  agentRiskMin.value = null
  agentModule.value = ''
  agentDateRange.value = []
  agentPage.value = 1
  fetchAgentEvents()
}

function clearTerminal() {
  if (!selectedTerminalId.value) return
  selectedTerminalId.value = null
  agentPage.value = 1
  fetchAgentEvents()
}

async function refreshAgentWorkspace() {
  await Promise.all([fetchAgentTerminalStats(), fetchAgentStats()])
  const keepId = selectedTerminalId.value
  // 终端可能已删除，重拉后校验选中项
  if (keepId && !agentTerminalStats.value.some((t) => t.terminal_id === keepId)) {
    selectedTerminalId.value = null
  }
  fetchAgentEvents()
}

const agentStats = ref<any>(null)
const agentDateRange = ref<string[]>([])
const agentStage = ref('')
const agentAction = ref('')
const agentRiskMin = ref<number | null>(null)
const agentModule = ref('')
const agentKeyword = ref('')
const agentEvents = ref<any[]>([])
const agentLoading = ref(false)
const agentExporting = ref(false)
const agentPage = ref(1)
const agentPageSize = ref(20)
const agentTotal = ref(0)
const agentDetailVisible = ref(false)
const agentDetail = ref<any>(null)

function agentQueryParams() {
  const params: any = {
    page: agentPage.value,
    page_size: agentPageSize.value,
  }
  if (selectedTerminalId.value) params.terminal_id = selectedTerminalId.value
  if (agentStage.value) params.stage = agentStage.value
  if (agentAction.value) params.action = agentAction.value
  if (agentRiskMin.value != null) params.risk_min = agentRiskMin.value
  if (agentModule.value) params.source_module = agentModule.value
  if (agentKeyword.value) params.q = agentKeyword.value
  if (agentDateRange.value?.length === 2) {
    params.start_time = agentDateRange.value[0]
    params.end_time = agentDateRange.value[1]
  }
  return params
}

async function fetchAgentEvents() {
  agentLoading.value = true
  try {
    const res = await getAgentAuditEvents(agentQueryParams())
    agentEvents.value = res.data?.data || []
    agentTotal.value = res.data?.total || 0
  } catch {
    ElMessage.error('获取终端审计事件失败')
  } finally {
    agentLoading.value = false
  }
}

async function fetchAgentStats() {
  try {
    const res = await getAgentAuditStats()
    agentStats.value = res.data
  } catch {
    agentStats.value = null
  }
}

function applyAgentFilter() {
  agentPage.value = 1
  fetchAgentEvents()
}

async function handleExportAgentEvents() {
  agentExporting.value = true
  try {
    const params: any = agentQueryParams()
    params.page = 1
    params.page_size = 10000
    const res = await exportAgentAuditEvents(params)
    downloadBlob(res, `agent_audit_events_${new Date().toISOString().slice(0, 10)}.csv`)
    ElMessage.success('导出成功')
  } catch {
    ElMessage.error('导出失败')
  } finally {
    agentExporting.value = false
  }
}

function downloadBlob(res: any, name: string) {
  const blob = new Blob([res.data], { type: 'text/csv' })
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(url)
}

function openAgentDetail(row: any) {
  agentDetail.value = row
  agentDetailVisible.value = true
}

function prettyJson(raw: string) {
  if (!raw) return '{}'
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
}

// --- LLM 用量 ---
const usageDateRange = ref<string[]>([])
const usageUserId = ref<number | null>(null)
const usageModel = ref('')
const usageLogs = ref<any[]>([])
const usageLoading = ref(false)
const usagePage = ref(1)
const usagePageSize = ref(20)
const usageTotal = ref(0)

async function fetchUsageLogs() {
  usageLoading.value = true
  try {
    const params: any = {
      action: 'chat_completion',
      page: usagePage.value,
      page_size: usagePageSize.value,
    }
    if (usageUserId.value) params.user_id = usageUserId.value
    if (usageModel.value) params.model_id = usageModel.value
    if (usageDateRange.value?.length === 2) {
      params.start_time = usageDateRange.value[0]
      params.end_time = usageDateRange.value[1]
    }
    const res = await getAuditLogs(params)
    usageLogs.value = res.data?.data || []
    usageTotal.value = res.data?.total || 0
  } catch {
    ElMessage.error('获取用量日志失败')
  } finally {
    usageLoading.value = false
  }
}

// --- 行为审计 ---
const actionDateRange = ref<string[]>([])
const actionUserId = ref<number | null>(null)
const actionType = ref('')
const actionLogs = ref<any[]>([])
const actionLoading = ref(false)
const actionPage = ref(1)
const actionPageSize = ref(20)
const actionTotal = ref(0)
const exporting = ref(false)

async function fetchActionLogs() {
  actionLoading.value = true
  try {
    const params: any = {
      page: actionPage.value,
      page_size: actionPageSize.value,
    }
    if (actionUserId.value) params.user_id = actionUserId.value
    if (actionType.value) params.action = actionType.value
    if (actionDateRange.value?.length === 2) {
      params.start_time = actionDateRange.value[0]
      params.end_time = actionDateRange.value[1]
    }
    const res = await getAuditLogs(params)
    actionLogs.value = res.data?.data || []
    actionTotal.value = res.data?.total || 0
  } catch {
    ElMessage.error('获取审计日志失败')
  } finally {
    actionLoading.value = false
  }
}

async function handleExport() {
  exporting.value = true
  try {
    const params: any = {}
    if (actionUserId.value) params.user_id = actionUserId.value
    if (actionType.value) params.action = actionType.value
    if (actionDateRange.value?.length === 2) {
      params.start_time = actionDateRange.value[0]
      params.end_time = actionDateRange.value[1]
    }
    const res = await exportAuditLogs(params)
    downloadCsv(res)
    ElMessage.success('导出成功')
  } catch {
    ElMessage.error('导出失败')
  } finally {
    exporting.value = false
  }
}

async function handleExportUsage() {
  exporting.value = true
  try {
    const params: any = { action: 'chat_completion' }
    if (usageUserId.value) params.user_id = usageUserId.value
    if (usageModel.value) params.model_id = usageModel.value
    if (usageDateRange.value?.length === 2) {
      params.start_time = usageDateRange.value[0]
      params.end_time = usageDateRange.value[1]
    }
    const res = await exportAuditLogs(params)
    downloadCsv(res)
    ElMessage.success('导出成功')
  } catch {
    ElMessage.error('导出失败')
  } finally {
    exporting.value = false
  }
}

function downloadCsv(res: any) {
  const blob = new Blob([res.data], { type: 'text/csv' })
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `audit_logs_${new Date().toISOString().slice(0, 10)}.csv`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(url)
}

// --- 对话记录 ---
const convDateRange = ref<string[]>([])
const convUserId = ref<number | null>(null)
const convModel = ref('')
const convLogs = ref<any[]>([])
const convLoading = ref(false)
const convPage = ref(1)
const convPageSize = ref(20)
const convTotal = ref(0)
const convExporting = ref(false)

const detailVisible = ref(false)
const detailLoading = ref(false)
const convDetail = ref<any>(null)

const parsedMessages = computed(() => {
  if (!convDetail.value?.request_body) return []
  try {
    const body = typeof convDetail.value.request_body === 'string'
      ? JSON.parse(convDetail.value.request_body)
      : convDetail.value.request_body
    return body.messages || []
  } catch {
    return []
  }
})

async function fetchConversations() {
  convLoading.value = true
  try {
    const params: any = {
      page: convPage.value,
      page_size: convPageSize.value,
    }
    if (convUserId.value) params.user_id = convUserId.value
    if (convModel.value) params.model_id = convModel.value
    if (convDateRange.value?.length === 2) {
      params.start_time = convDateRange.value[0]
      params.end_time = convDateRange.value[1]
    }
    const res = await getConversations(params)
    convLogs.value = res.data?.data || []
    convTotal.value = res.data?.total || 0
  } catch {
    ElMessage.error('获取对话记录失败')
  } finally {
    convLoading.value = false
  }
}

async function handleExportConversations() {
  convExporting.value = true
  try {
    const params: any = { page: 1, page_size: 10000 }
    if (convUserId.value) params.user_id = convUserId.value
    if (convModel.value) params.model_id = convModel.value
    if (convDateRange.value?.length === 2) {
      params.start_time = convDateRange.value[0]
      params.end_time = convDateRange.value[1]
    }
    const res = await getConversations(params)
    const logs = res.data?.data || []
    downloadConversationsCsv(logs)
    ElMessage.success('导出成功')
  } catch {
    ElMessage.error('导出失败')
  } finally {
    convExporting.value = false
  }
}

function downloadConversationsCsv(logs: any[]) {
  const header = ['时间', '用户', '模型', '类型', '状态码', 'Prompt Tokens', 'Completion Tokens', '请求内容', '响应内容']
  const rows = logs.map(log => {
    let requestText = ''
    try {
      const body = typeof log.request_body === 'string' ? JSON.parse(log.request_body) : log.request_body
      const msgs = body.messages || []
      requestText = msgs.map((m: any) => `[${m.role}]: ${m.content}`).join('\n')
    } catch {
      requestText = log.request_body || ''
    }
    const responseText = log.response_body || ''
    return [
      formatDate(log.created_at),
      getUserLabel(log.user_id),
      log.model_id || '',
      log.is_stream ? '流式' : '非流式',
      log.status_code,
      log.prompt_tokens || 0,
      log.completion_tokens || 0,
      requestText,
      responseText,
    ]
  })
  const csvContent = [header, ...rows].map(row =>
    row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(',')
  ).join('\n')
  const bom = '\uFEFF'
  const blob = new Blob([bom + csvContent], { type: 'text/csv;charset=utf-8;' })
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `conversation_logs_${new Date().toISOString().slice(0, 10)}.csv`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(url)
}

async function openConvDetail(row: any) {
  detailVisible.value = true
  detailLoading.value = true
  convDetail.value = null
  try {
    const res = await getConversationDetail(row.id)
    convDetail.value = res.data
  } catch {
    ElMessage.error('获取对话详情失败')
  } finally {
    detailLoading.value = false
  }
}

function handleTabChange(tab: string) {
  if (tab === 'usage') {
    fetchUsageLogs()
  } else if (tab === 'action') {
    fetchActionLogs()
  } else if (tab === 'agent') {
    if (!agentTerminalStats.value.length) fetchAgentTerminalStats()
    fetchAgentStats()
    fetchAgentEvents()
  } else if (tab === 'conversation') {
    fetchConversations()
  }
}

onMounted(() => {
  fetchUsers()
  fetchUsageLogs()
})
</script>

<style scoped lang="scss">
.audit-page {
  padding: 0;
}

.page-title {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 20px;
}

.filter-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0;
  margin-bottom: 16px;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

// --- 对话详情 ---
.conv-detail-wrap {
  max-height: 70vh;
  overflow-y: auto;
}

.detail-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
  padding: 12px 16px;
  background: #f5f7fa;
  border-radius: 6px;
  font-size: 13px;
  color: #606266;
}

.detail-section-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin: 20px 0 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #ebeef5;
}

.messages-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.message-item {
  display: flex;
  gap: 12px;
  padding: 12px;
  background: #fafafa;
  border-radius: 6px;
  border: 1px solid #ebeef5;
}

.role-badge {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 60px;
  height: 24px;
  padding: 0 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  color: #fff;
}

.role-user {
  background: #409eff;
}

.role-assistant {
  background: #67c23a;
}

.role-system {
  background: #e6a23c;
}

.message-content {
  flex: 1;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.6;
  color: #303133;
  font-family: monospace;
}

.response-body {
  margin: 0;
  padding: 16px;
  background: #1e1e1e;
  color: #d4d4d4;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  max-height: 400px;
  overflow-y: auto;
}

.no-content {
  color: #909399;
  font-size: 13px;
  padding: 12px;
  text-align: center;
  background: #fafafa;
  border-radius: 6px;
}

// --- 终端审计 ---
.agent-stats-row {
  display: flex;
  align-items: stretch;
  gap: 12px;
  margin-bottom: 14px;
}

.agent-stat-scope {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 18px;
  background: #f0f7ff;
  border: 1px solid #d6e6ff;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #3370cc;
  white-space: nowrap;
}

.agent-stat-card {
  flex: 1;
  max-width: 200px;
  padding: 12px 18px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
}

.agent-stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #303133;
  line-height: 1.2;
}

.agent-stat-value.warn {
  color: #e6a23c;
}

.agent-stat-value.danger {
  color: #f56c6c;
}

.agent-stat-label {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
}

// --- 终端审计：双栏工作区（参考原项目审计页：左列表 + 右记录区） ---
.agent-workspace {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  min-width: 1080px; /* 窄视口下保持双栏结构，容器横向滚动（同原项目审计页 min-width 策略） */
}

.agent-panel {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
}

.agent-terminal-panel {
  flex: 0 0 300px;
  width: 300px;
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 300px);
  min-height: 420px;
}

.agent-panel-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px 8px;
}

.agent-panel-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.agent-panel-refresh {
  margin-left: auto;
  color: #909399;
}

.agent-panel-search {
  padding: 4px 12px 10px;
}

.agent-terminal-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 0 10px 10px;
}

.agent-terminal-card {
  position: relative;
  padding: 10px 12px 9px 14px;
  margin-bottom: 8px;
  background: #fafbfd;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
}

.agent-terminal-card::before {
  content: "";
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 0 2px 2px 0;
  background: #c0c4cc;
}

.agent-terminal-card.card-level-events::before {
  background: #409eff;
}

.agent-terminal-card.card-level-warn::before {
  background: #e6a23c;
}

.agent-terminal-card.card-level-danger::before {
  background: #f56c6c;
}

.agent-terminal-card:hover {
  background: #f5f9ff;
  border-color: #c6d8f5;
}

.agent-terminal-card.is-active {
  background: #ecf5ff;
  border-color: #a0cfff;
  box-shadow: inset 0 0 0 1px #a0cfff;
}

.agent-term-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.agent-term-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.agent-term-sub {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: #909399;
  margin-bottom: 6px;
}

.agent-term-metrics {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 5px;
}

.agent-term-total {
  font-size: 17px;
  font-weight: 700;
  color: #303133;
}

.agent-term-total em {
  font-size: 11px;
  font-style: normal;
  font-weight: 400;
  color: #909399;
}

.agent-term-metric {
  font-size: 11px;
  color: #909399;
}

.agent-term-metric b {
  color: #606266;
}

.agent-term-metric.text-warn b {
  color: #e6a23c;
}

.agent-term-metric.text-danger b {
  color: #f56c6c;
}

.agent-term-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 11px;
  color: #c0c4cc;
}

.agent-term-ver {
  flex: none;
}

.agent-main-panel {
  flex: 1;
  min-width: 0;
  padding: 10px 14px 14px;
}

.agent-context-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 2px 0 12px;
  border-bottom: 1px solid #ebeef5;
  margin-bottom: 10px;
}

.agent-context-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex-wrap: wrap;
}

.agent-ctx-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
  background: #c0c4cc;
}

.agent-ctx-dot.state-online {
  background: #67c23a;
  box-shadow: 0 0 0 3px rgba(103, 194, 58, 0.15);
}

.agent-ctx-dot.state-offline {
  background: #c0c4cc;
}

.agent-ctx-dot.state-pending {
  background: #e6a23c;
}

.agent-ctx-name {
  font-size: 14px;
  color: #303133;
}

.agent-ctx-sep {
  color: #909399;
  font-size: 13px;
}

.agent-ctx-meta {
  color: #c0c4cc;
  font-size: 12px;
}

.agent-context-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: none;
}

.agent-filter-bar {
  margin-bottom: 12px;
}

.agent-filter-bar .el-select,
.agent-filter-bar .el-input {
  margin-left: 8px;
}

.agent-filter-bar .el-select:first-of-type {
  margin-left: 12px;
}

// --- 时间线视图（参考原 Argus 审计页事件卡流） ---
.agent-timeline {
  min-height: 300px;
  padding: 2px 2px 6px;
}

.agent-tl-event {
  position: relative;
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr);
  gap: 10px;
  padding-bottom: 8px;
  cursor: pointer;
}

.agent-tl-event:not(:last-child)::before {
  content: "";
  position: absolute;
  left: 19px;
  top: 26px;
  bottom: 0;
  width: 1.5px;
  background: #e4e9f2;
}

.agent-tl-seq {
  position: relative;
  z-index: 1;
  display: grid;
  place-items: center;
  width: 39px;
  height: 24px;
  border: 1px solid #d8dee8;
  border-radius: 6px;
  color: #909399;
  background: #fff;
  font-size: 11px;
  font-weight: 700;
}

.agent-tl-card {
  background: #fafbfd;
  border: 1px solid #eef1f6;
  border-left: 3px solid #c0c4cc;
  border-radius: 6px;
  padding: 8px 12px 7px;
  transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
}

.agent-tl-event.tl-level-warn .agent-tl-card {
  border-left-color: #e6a23c;
  background: #fdf8ef;
}

.agent-tl-event.tl-level-danger .agent-tl-card {
  border-left-color: #f56c6c;
  background: #fef0f0;
}

.agent-tl-event.tl-level-warn .agent-tl-seq {
  color: #b88230;
  border-color: #e6a23c;
}

.agent-tl-event.tl-level-danger .agent-tl-seq {
  color: #d03050;
  border-color: #f56c6c;
}

.agent-tl-card:hover {
  border-color: #a0cfff;
  border-left-color: #409eff;
  box-shadow: 0 1px 6px rgba(30, 60, 120, 0.08);
}

.agent-tl-top {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.agent-tl-stage {
  font-size: 12px;
  font-weight: 600;
  color: #606266;
}

.agent-tl-time {
  margin-left: auto;
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.agent-tl-title {
  margin: 5px 0 4px;
  font-size: 13px;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-tl-event.tl-level-danger .agent-tl-title {
  color: #d03050;
  font-weight: 600;
}

.agent-tl-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.agent-tl-chip {
  padding: 1px 7px;
  border: 1px solid #e4e9f2;
  border-radius: 99px;
  background: #fff;
  font-size: 11px;
  color: #909399;
}

.agent-tl-terminal {
  color: #3370cc;
  border-color: #d6e6ff;
  background: #f0f7ff;
}

.agent-tl-preview {
  max-width: 45%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: #b0b7c2;
  font-family: 'Consolas', 'Monaco', monospace;
}

.agent-detail-wrap {
  max-height: 80vh;
  overflow-y: auto;
}

.agent-detail-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.agent-reason {
  margin: 0 0 12px;
  padding: 12px 16px;
  background: #f5f7fa;
  border-radius: 6px;
  font-size: 13px;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-word;
}

.agent-trace {
  font-size: 12px;
  color: #909399;
  line-height: 2;
  word-break: break-all;
  margin-bottom: 4px;
}

.agent-trace code {
  color: #606266;
}

.agent-json {
  margin: 0 0 8px;
  padding: 12px 14px;
  background: #1e1e1e;
  color: #d4d4d4;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  max-height: 320px;
  overflow-y: auto;
}
</style>
