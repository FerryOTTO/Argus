import api from './client'

// Provider APIs
export function getProviders() {
  return api.get('/api/admin/providers')
}

export function createProvider(data: any) {
  return api.post('/api/admin/providers', data)
}

export function updateProvider(id: number, data: any) {
  return api.put(`/api/admin/providers/${id}`, data)
}

export function deleteProvider(id: number) {
  return api.delete(`/api/admin/providers/${id}`)
}

// Model APIs
export function createModel(data: { provider_id: number; model_id: string; display_name?: string }) {
  return api.post('/api/admin/models', data)
}

export function getUpstreamModels(providerId: number) {
  return api.get(`/api/admin/providers/${providerId}/upstream-models`)
}

export function deleteModel(id: number) {
  return api.delete(`/api/admin/models/${id}`)
}

// User APIs
export function getUsers() {
  return api.get('/api/admin/users')
}

export function createUser(data: { username: string; password: string; email?: string; role: string; security_level?: string; specials?: string }) {
  return api.post('/api/admin/users', data)
}

export function updateUser(id: number, data: any) {
  return api.put(`/api/admin/users/${id}`, data)
}

export function deleteUser(id: number) {
  return api.delete(`/api/admin/users/${id}`)
}

export function resetUserPassword(id: number, newPassword: string) {
  return api.put(`/api/admin/users/${id}/password`, { new_password: newPassword })
}

// API Key management
export function getApiKeys() {
  return api.get('/api/admin/api-keys')
}

export function createApiKey(data: { name: string; permissions: string[]; user_id: number | null }) {
  return api.post('/api/admin/api-keys', data)
}

export function deactivateApiKey(id: number) {
  return api.post(`/api/admin/api-keys/${id}/deactivate`)
}

export function updateApiKey(id: number, data: { name: string; permissions: string[] }) {
  return api.put(`/api/admin/api-keys/${id}`, data)
}

export function deleteApiKey(id: number) {
  return api.delete(`/api/admin/api-keys/${id}`)
}

// System settings（企业名称/系统根地址/开放模型）与可选模型列表
export function getSettings() {
  return api.get('/api/admin/settings')
}

export function updateSettings(data: {
  enterprise_name: string
  system_base_url: string
  open_models: string[]
}) {
  return api.put('/api/admin/settings', data)
}

export function getAdminModels() {
  return api.get('/api/admin/models')
}

// 当前登录管理员改密（含首次登录强制改密）
export function changePassword(currentPassword: string, newPassword: string) {
  return api.put('/api/admin/change-password', {
    current_password: currentPassword,
    new_password: newPassword,
  })
}

// Quota APIs
export function getQuotas(params?: { user_id?: number }) {
  return api.get('/api/admin/quotas', { params })
}

export function createQuota(data: { user_id: number; model_id: string; quota_type: string; limit_value: number }) {
  return api.post('/api/admin/quotas', data)
}

export function deleteQuota(id: number) {
  return api.delete(`/api/admin/quotas/${id}`)
}

// Audit APIs
export function getAuditLogs(params: {
  action?: string; user_id?: number; model_id?: string;
  start_time?: string; end_time?: string; page?: number; page_size?: number;
}) {
  return api.get('/api/admin/audit-logs', { params })
}

export function exportAuditLogs(params: any) {
  return api.get('/api/admin/audit-logs/export', { params, responseType: 'blob' })
}

// Conversation APIs
export function getConversations(params: {
  user_id?: number; model_id?: string;
  start_time?: string; end_time?: string; page?: number; page_size?: number;
}) {
  return api.get('/api/admin/conversations', { params })
}

export function getConversationDetail(id: number) {
  return api.get(`/api/admin/conversations/${id}`)
}

export function getDashboard() {
  return api.get('/api/admin/dashboard')
}

// Agent Terminal APIs (遥测/集控终端)
export function getTerminals(params?: {
  agent_type?: string
  keyword?: string
  page?: number
  page_size?: number
}) {
  return api.get('/api/admin/terminals', { params })
}

export function createTerminal(data: {
  name: string
  agent_type?: string
  bound_user_id?: number | null
  description?: string
}) {
  return api.post('/api/admin/terminals', data)
}

export function updateTerminal(id: number, data: { name?: string; bound_user_id?: number | null; description?: string }) {
  return api.put(`/api/admin/terminals/${id}`, data)
}

export function deleteTerminal(id: number) {
  return api.delete(`/api/admin/terminals/${id}`)
}

export function regenerateTerminalCode(id: number) {
  return api.post(`/api/admin/terminals/${id}/regenerate-code`)
}

export function revokeTerminal(id: number) {
  return api.post(`/api/admin/terminals/${id}/revoke`)
}

export function getTerminalConfig(id: number) {
  return api.get(`/api/admin/terminals/${id}/config`)
}

export function updateTerminalConfig(id: number, config: string) {
  return api.put(`/api/admin/terminals/${id}/config`, { config })
}

// Agent audit events（终端 Clawguard 审计事件，审计日志 · 终端审计板块）
export function getAgentAuditEvents(params: {
  terminal_id?: number
  stage?: string
  action?: string
  source_module?: string
  risk_min?: number
  q?: string
  start_time?: string
  end_time?: string
  page?: number
  page_size?: number
}) {
  return api.get('/api/admin/audit-events', { params })
}

export function getAgentAuditStats() {
  return api.get('/api/admin/audit-events/stats')
}

export function getAgentTerminalStats() {
  return api.get('/api/admin/audit-events/terminal-stats')
}

export function exportAgentAuditEvents(params: any) {
  return api.get('/api/admin/audit-events/export', { params, responseType: 'blob' })
}

// ── 扩展治理：skill/MCP 安装审批 + Skill 分发 ──

export function getExtensionApprovals(params: {
  state?: string
  kind?: string
  terminal_id?: number
  keyword?: string
  page?: number
  page_size?: number
}) {
  return api.get('/api/admin/extensions/approvals', { params })
}

export function getExtensionApprovalStats() {
  return api.get('/api/admin/extensions/approvals/stats')
}

export function approveExtensionApproval(id: number, note?: string) {
  return api.post(`/api/admin/extensions/approvals/${id}/approve`, { note: note || '' })
}

export function rejectExtensionApproval(id: number, note: string) {
  return api.post(`/api/admin/extensions/approvals/${id}/reject`, { note })
}

export function getSkillPackages(params: { keyword?: string; page?: number; page_size?: number }) {
  return api.get('/api/admin/extensions/skill-packages', { params })
}

export function uploadSkillPackage(formData: FormData) {
  return api.post('/api/admin/extensions/skill-packages', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60000,
  })
}

export function updateSkillPackage(id: number, description: string) {
  return api.put(`/api/admin/extensions/skill-packages/${id}`, { description })
}

export function deleteSkillPackage(id: number) {
  return api.delete(`/api/admin/extensions/skill-packages/${id}`)
}

export function getSkillPackageAssignments(id: number) {
  return api.get(`/api/admin/extensions/skill-packages/${id}/assignments`)
}

export function setSkillPackageAssignments(id: number, terminal_ids: number[]) {
  return api.put(`/api/admin/extensions/skill-packages/${id}/assignments`, { terminal_ids })
}

export function getExtensionTerminalOptions() {
  return api.get('/api/admin/extensions/terminal-options')
}

export function getDefaultSkillPackages() {
  return api.get('/api/admin/extensions/default-skill-packages')
}

export function setDefaultSkillPackages(data: { enabled: boolean; package_ids: number[] }) {
  return api.put('/api/admin/extensions/default-skill-packages', data)
}
