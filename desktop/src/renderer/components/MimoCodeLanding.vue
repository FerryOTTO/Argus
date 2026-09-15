<template>
  <div class="mimo-code-page landing-layout">
    <aside class="landing-sidebar" :aria-label="ui.serviceStatus">
      <button class="landing-sidebar__brand" :aria-label="copy.home" type="button" @click="activeSection = 'home'">
        <span class="hero__logo-text">Argus</span>
      </button>
      <div class="landing-sidebar__divider" aria-hidden="true"></div>
      <nav v-if="workspaceEdition !== 'pro'" class="landing-sidebar__nav" :aria-label="ui.serviceStatus">
        <div v-for="section in sections" :key="section.id" class="landing-sidebar__group">
          <button type="button" class="landing-sidebar__item" :class="{ 'is-active': activeSection === section.id }" :aria-current="activeSection === section.id ? 'page' : undefined" @click="selectSection(section)">
            <span class="landing-sidebar__item-index">{{ section.index }}</span><span>{{ section.label }}</span>
          </button>
          <div v-if="section.children && expandedSection === section.id" class="landing-sidebar__subnav">
            <button v-for="child in section.children" :key="child.id" type="button" class="landing-sidebar__subitem" :class="{ 'is-active': activeSection === section.id && activeSubSection === child.id }" @click="selectSubSection(section.id, child.id)">
              {{ child.label }}
            </button>
          </div>
        </div>
      </nav>
      <button type="button" class="landing-sidebar__item landing-sidebar__settings" :class="{ 'is-active': activeSection === 'settings' }" @click="openSettings">
        <span class="landing-sidebar__item-index"><Settings :size="15" /></span><span>{{ ui.settings }}</span>
      </button>
    </aside>
    <main class="landing-main">
      <template v-if="workspaceEdition === 'pro'">
        <section class="claw-panel" style="max-width:640px;margin:60px auto;padding:32px;text-align:center">
          <h2 style="font-size:18px;font-weight:800;margin-bottom:8px">Enterprise mode</h2>
          <p style="font-size:13px;color:#71717a">Personal workspace hidden. Guard still running. Use mini window for level / usage / connection.</p>
        </section>
        <EnterpriseMini :dark-mode="appSettings.darkMode" @back-personal="switchToPersonal" />
      </template>
      <template v-else>
      <template v-if="activeSection === 'home'">
        <section class="claw-dashboard">
          <div class="claw-dashboard__header">
            <div>
              <h1 class="claw-dashboard__title">{{ ui.dashboardTitle }}</h1>
              <p class="claw-dashboard__subtitle">{{ ui.dashboardSubtitle }}</p>
            </div>
            <span class="claw-dashboard__live"><span></span>{{ ui.realtimeMonitoring }}</span>
          </div>

          <div class="claw-dashboard__top-grid">
            <section class="claw-panel claw-log-panel">
              <div class="claw-panel__heading"><div><h2>{{ ui.startupLogs }}</h2></div></div>
              <div class="claw-log-stream">
                <div v-for="(log, index) in startupLogs" :key="index" class="claw-log-line"><span class="claw-log-time">{{ log.time }}</span><span class="claw-log-dot" :class="log.level"></span><span class="claw-log-message">{{ log.message }}</span></div>
                <div class="claw-log-cursor"><span></span>{{ ui.listening }}</div>
              </div>
            </section>

            <section class="claw-panel claw-status-panel">
              <div class="claw-panel__heading"><div><h2>{{ ui.connectionStatus }}</h2></div></div>
              <div class="claw-status-fan" :aria-label="ui.serviceStatus">
                <div class="claw-status-fan__ring" :class="{ 'is-checking': checkingServices }" :style="statusRingStyle"><span v-for="(service, index) in serviceStatuses" :key="service.name" class="claw-status-fan__segment" :class="serviceStateClass(service)" :style="segmentStyle(index)"></span><span v-if="checkingServices" class="claw-status-fan__arrow" :style="arrowStyle" aria-hidden="true"></span><div class="claw-status-fan__center"><strong>{{ readyServices }}</strong><small>{{ checkingServices ? ui.checking : ui.connected }}</small></div></div>
                <div class="claw-status-callouts"><div v-for="(service, index) in serviceStatuses" :key="service.name" class="claw-status-callout"  :class="['claw-status-callout--' + index, serviceStateClass(service)]"><div class="claw-status-callout__content"><div><strong>{{ service.name }}</strong><em>{{ service.state === "checking" ? ui.checking : service.ready ? ui.running : ui.failed }}</em></div></div></div></div>
              </div>
            </section>
          </div>

          <section class="claw-panel claw-usage-panel">
            <div class="claw-usage-toolbar">
              <div class="claw-usage-title"><span class="claw-usage-title__icon"><Activity :size="19" /></span><div><h2>{{ ui.modelUsage }}</h2><p>{{ ui.usageSubtitle }}</p></div></div>
              <div class="claw-usage-controls"><div class="claw-range-tabs"><button v-for="range in usageRanges" :key="range.id" type="button" :class="{ 'is-active': selectedRange === range.id }" @click="selectedRange = range.id">{{ range.label }}</button></div><select v-model="selectedProvider" :aria-label="ui.selectProvider"><option value="all">{{ ui.allModels }}</option><option v-for="provider in providers" :key="provider.id" :value="provider.id">{{ provider.name }}<template v-if="provider.model"> · {{ provider.model }}</template></option></select><button class="claw-icon-button" type="button" :title="ui.refresh" @click="loadRuntimeDashboard"><RefreshCw :size="15" /></button></div>
            </div>
            <div class="claw-usage-hero">
              <div class="claw-usage-total"><span class="claw-usage-total__icon"><Zap :size="20" /></span><div><span>{{ ui.realTokenUse }}</span><strong>{{ usageSummary.totalTokens }}</strong><small>{{ ui.tokenDescription }}</small></div></div>
              <div class="claw-usage-quick-stats"><div><span><Activity :size="14" /> 请求数</span><strong>{{ usageSummary.requests }}</strong><small>{{ usageSummary.successRate }} 成功</small></div><div><span><Database :size="14" /> 缓存命中</span><strong>{{ usageSummary.cacheRate }}</strong><small>已节省 {{ usageSummary.cacheSaved }}</small></div><div><span><span class="claw-dollar">$</span> 预估费用</span><strong>{{ usageSummary.cost }}</strong><small>当前统计周期</small></div></div>
            </div>
            <div class="claw-token-cards"><div v-for="metric in usageMetrics" :key="metric.key" class="claw-token-card" :class="'is-' + metric.key"><span class="claw-token-card__icon"><component :is="metric.icon" :size="16" /></span><div><span>{{ metric.label }}</span><strong>{{ metric.value }}</strong><small>{{ metric.note }}</small></div></div></div>
            <div class="claw-chart-section">
              <div class="claw-chart-section__header"><div><strong>{{ ui.usageTrend }}</strong><span>{{ trendIntervalLabel }}</span></div><div class="claw-chart-legend"><button v-for="series in chartSeries" :key="series.key" type="button" :class="{ 'is-muted': hiddenSeries.includes(series.key) }" @click="toggleSeries(series.key)"><i :style="{ background: series.color }"></i>{{ typeof series.label === 'string' ? series.label : series.label.value }}</button></div></div>
              <div class="claw-chart-wrap" @mousemove="handleChartMove" @mouseleave="chartHoverIndex = null"><svg class="claw-chart" viewBox="0 0 1000 310" preserveAspectRatio="none" role="img" :aria-label="ui.usageTrendAria"><defs><linearGradient v-for="series in chartSeries" :id="'usage-fill-' + series.key" :key="series.key" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" :stop-color="series.color" stop-opacity=".18"/><stop offset="100%" :stop-color="series.color" stop-opacity="0"/></linearGradient></defs><line v-for="y in chartGridY" :key="y" x1="42" :y1="y" x2="990" :y2="y" class="claw-chart__grid" /><text v-for="(label,index) in chartYLabels" :key="label" x="0" :y="chartGridY[index] + 4" class="claw-chart__label">{{ label }}</text><template v-for="series in visibleChartSeries" :key="series.key"><path v-if="series.area" :d="seriesAreaPath(series.key)" class="claw-chart__area" :style="{ fill: 'url(#usage-fill-' + series.key + ')' }"/><path :d="seriesPath(series.key)" class="claw-chart__line" :class="{ 'is-dashed': series.key === 'cost' }" :style="{ stroke: series.color }"/></template><line v-if="chartHoverIndex !== null" :x1="chartX(chartHoverIndex)" y1="18" :x2="chartX(chartHoverIndex)" y2="268" class="claw-chart__crosshair" /><circle v-for="series in visibleChartSeries" v-show="chartHoverIndex !== null" :key="series.key" :cx="chartX(chartHoverIndex || 0)" :cy="seriesY(chartData[chartHoverIndex || 0][series.key], series.key)" r="4" class="claw-chart__point" :style="{ fill: series.color }" /></svg><div v-if="chartHoverIndex !== null" class="claw-chart-tooltip" :style="tooltipStyle"><div class="claw-tooltip-title"><strong>{{ chartData[chartHoverIndex].time }}</strong><span>{{ selectedRangeLabel }}</span></div><div v-for="series in chartSeries" :key="series.key" class="claw-tooltip-row"><span><i :style="{ background: series.color }"></i>{{ typeof series.label === 'string' ? series.label : series.label.value }}</span><strong>{{ formatSeriesValue(chartData[chartHoverIndex][series.key], series.key) }}</strong></div></div></div>
              <div class="claw-chart-axis"><span v-for="point in chartData" :key="point.time">{{ point.time }}</span></div>
            </div>
          </section>
          <section class="claw-panel claw-usage-panel claw-provider-panel">
            <div class="claw-usage-toolbar"><div class="claw-usage-title"><span class="claw-usage-title__icon"><SlidersHorizontal :size="19" /></span><div><h2>本地模型配置</h2><p>直接编辑本机 openclaw.json 的模型通道，保存即落盘（自动备份 .bak）</p></div></div><div class="claw-usage-controls"><button class="claw-icon-button" type="button" title="重新读取" :disabled="configEditor.loading || configEditor.saving" @click="loadOpenclawConfig(true)"><RefreshCw :size="15" /></button></div></div>
            <div v-if="configEditor.loading" class="claw-provider-empty"><LoaderCircle :size="21" class="is-spinning" /><strong>正在读取本地配置…</strong></div>
            <div v-else-if="configEditor.error" class="claw-provider-empty"><strong>读取失败</strong><span>{{ configEditor.error }}</span><button type="button" @click="loadOpenclawConfig(true)">重试</button></div>
            <template v-else>

              <div class="claw-chart-section"><div class="claw-chart-section__header"><div><strong>openclaw.json 全文</strong><span>models / agents 段可改，网关段只读 · 保存前自动校验 JSON</span></div><div class="claw-chart-legend"><span class="claw-provider-status" v-if="configEditor.status">{{ configEditor.status }}</span><span class="claw-provider-path" v-if="configEditor.path">{{ configEditor.path }}</span></div></div><div class="claw-provider-editor"><textarea v-model="configEditor.text" rows="22" spellcheck="false" class="cfg-rules"></textarea></div>
              <div class="claw-provider-footer"><span class="claw-field-hint">非法 JSON 拒绝落盘 · 保存自动备份 .bak</span><div class="claw-provider-footer__actions"><button type="button" class="claw-provider-cancel" :disabled="configEditor.saving" @click="loadOpenclawConfig(true)">放弃修改</button><button type="button" class="claw-provider-save" :disabled="configEditor.saving" @click="saveOpenclawConfig"><Save :size="15" />{{ configEditor.saving ? '保存中' : '保存到本地' }}</button></div></div></div>
            </template>
          </section>
        </section>
      </template>

      <section v-else-if="activeSection === 'settings'" class="claw-settings-page">
        <header class="claw-settings-page__header"><div><h1>{{ ui.settings }}</h1><p>{{ ui.settingsHelp }}</p></div></header>
        <div class="claw-settings-grid">
          <section class="claw-settings-card"><div class="claw-settings-card__heading"><div><span>{{ ui.appExperience }}</span><h2>{{ ui.appearance }}</h2></div></div><div class="claw-setting-list"><div class="claw-setting-row"><div><strong>{{ ui.darkMode }}</strong><small>{{ ui.darkModeHelp }}</small></div><button type="button" class="claw-toggle" :class="{ 'is-on': appSettings.darkMode }" @click="appSettings.darkMode = !appSettings.darkMode"><i></i></button></div><div class="claw-setting-row"><div><strong>{{ ui.compactMode }}</strong><small>{{ ui.compactModeHelp }}</small></div><button type="button" class="claw-toggle" :class="{ 'is-on': appSettings.compactMode }" @click="appSettings.compactMode = !appSettings.compactMode"><i></i></button></div><div class="claw-setting-row"><div><strong>{{ ui.interfaceLanguage }}</strong><small>{{ ui.interfaceLanguageHelp }}</small></div><select v-model="locale"><option value="zh">简体中文</option><option value="en">English</option></select></div></div></section>
          <section class="claw-settings-card"><div class="claw-settings-card__heading"><div><span>{{ ui.startupNotifications }}</span><h2>{{ ui.backgroundGuard }}</h2></div></div><div class="claw-setting-list"><div class="claw-setting-row"><div><strong>{{ ui.autoStart }}</strong><small>{{ ui.autoStartHelp }}</small></div><button type="button" class="claw-toggle" :class="{ 'is-on': appSettings.autoStart }" @click="toggleAutoStart"><i></i></button></div><div class="claw-setting-row"><div><strong>{{ ui.minimizeToTray }}</strong><small>{{ ui.minimizeToTrayHelp }}</small></div><button type="button" class="claw-toggle" :class="{ 'is-on': appSettings.minimizeToTray }" @click="appSettings.minimizeToTray = !appSettings.minimizeToTray"><i></i></button></div><div class="claw-setting-row"><div><strong>{{ ui.securityAlerts }}</strong><small>{{ ui.securityAlertsHelp }}</small></div><button type="button" class="claw-toggle" :class="{ 'is-on': appSettings.securityNotifications }" @click="appSettings.securityNotifications = !appSettings.securityNotifications"><i></i></button></div></div></section>
          <section class="claw-settings-card"><div class="claw-settings-card__heading"><div><span>{{ ui.dataSecurity }}</span><h2>{{ ui.localProtectionTitle }}</h2></div></div><div class="claw-setting-list"><div class="claw-setting-row"><div><strong>{{ ui.healthCheck }}</strong><small>{{ ui.healthCheckHelp }}</small></div><button type="button" class="claw-toggle" :class="{ 'is-on': appSettings.healthCheck }" @click="appSettings.healthCheck = !appSettings.healthCheck"><i></i></button></div><div class="claw-setting-row"><div><strong>{{ ui.auditRetention }}</strong><small>{{ ui.auditRetentionHelp }}</small></div><select v-model.number="appSettings.auditRetention"><option :value="7">{{ t('days', { days: 7 }) }}</option><option :value="30">{{ t('days', { days: 30 }) }}</option><option :value="90">{{ t('days', { days: 90 }) }}</option></select></div><div class="claw-setting-row"><div><strong>{{ ui.diagnosticLogs }}</strong><small>{{ ui.diagnosticLogsHelp }}</small></div><button type="button" class="claw-toggle" :class="{ 'is-on': appSettings.diagnosticLogs }" @click="appSettings.diagnosticLogs = !appSettings.diagnosticLogs"><i></i></button></div></div></section>
        </div>
        <footer class="claw-settings-edition-footer">
          <div class="claw-edition-switch" role="group" :aria-label="ui.workspaceEdition">
            <button type="button" :class="{ 'is-active': workspaceEdition === 'personal' }" :disabled="workspaceEdition === 'pro'" :title="workspaceEdition === 'pro' ? ui.personalUnavailable : ''" @click="switchToPersonal">{{ ui.personal }}</button>
            <button type="button" :class="{ 'is-active': workspaceEdition === 'pro' }" @click="openEnterpriseLogin">{{ ui.enterprise }}</button>
          </div>
        </footer>
        <div v-if="enterpriseLogin.open" class="claw-provider-modal claw-enterprise-modal" role="dialog" aria-modal="true" aria-labelledby="enterprise-login-title" @click.self="closeEnterpriseLogin">
          <section class="claw-enterprise-dialog">
            <header><div><h2 id="enterprise-login-title">{{ ui.enterpriseLogin }}</h2><p>{{ ui.enterpriseLoginHelp }}</p></div><button type="button" class="claw-provider-dialog__close" :aria-label="ui.cancel" @click="closeEnterpriseLogin"><X :size="20" /></button></header>
            <form @submit.prevent="confirmEnterpriseSwitch">
              <label><span>{{ ui.account }}</span><input v-model.trim="enterpriseLogin.account" autocomplete="username" :placeholder="ui.account"></label>
              <label><span>{{ ui.invitationCode }}</span><input v-model.trim="enterpriseLogin.invitationCode" autocomplete="off" :placeholder="ui.invitationCode"></label>
              <div class="claw-enterprise-warning"><AlertTriangle :size="18" /><p>{{ ui.enterpriseSwitchWarning }}</p></div>
              <label class="claw-enterprise-acknowledgement"><input v-model="enterpriseLogin.acknowledged" type="checkbox"><span>{{ ui.acknowledgeEnterpriseWarning }}</span></label>
              <label class="claw-enterprise-acknowledgement"><input v-model="enterpriseLogin.rememberMe" type="checkbox"><span>{{ ui.rememberAccount }}</span></label>
              <footer><button type="button" @click="closeEnterpriseLogin">{{ ui.cancel }}</button><button type="submit" :disabled="!enterpriseLogin.acknowledged">{{ ui.confirmAndEnterEnterprise }}</button></footer>
            </form>
          </section>
        </div>
      </section>
      <!-- 02 内容检测 - 模块监测 -->
      <ContentMonitor :dark-mode="appSettings.darkMode"
        v-else-if="activeSection === 'content' && (!activeSubSection || activeSubSection === 'monitor')"
      />

      <!-- 03 访问控制 - 模块监测 -->
      <AccessMonitor :dark-mode="appSettings.darkMode"
        v-else-if="activeSection === 'access' && (!activeSubSection || activeSubSection === 'monitor')"
      />

      <!-- 04 工具检测 - 模块监测 -->
      <ToolMonitor :dark-mode="appSettings.darkMode"
        v-else-if="activeSection === 'tools' && (!activeSubSection || activeSubSection === 'monitor')"
      />

      <!-- 05 沙箱安全 - 模块监测 -->
      <SandboxMonitor :dark-mode="appSettings.darkMode"
        v-else-if="activeSection === 'sandbox' && (!activeSubSection || activeSubSection === 'monitor')"
      />

      <!-- 配置修改：照搬企业后台分组，直连本地真实文件 -->
      <ModuleConfigPanel v-else-if="activeSubSection === 'config' && ['content','access','tools','sandbox','audit'].includes(activeSection)" :module="activeSection" :dark-mode="appSettings.darkMode" />

      <!-- 06 审计日志 - 模块监测 -->
      <AuditMonitor :dark-mode="appSettings.darkMode"
        v-else-if="activeSection === 'audit' && (!activeSubSection || activeSubSection === 'monitor')"
      />

      <div v-else class="landing-empty-page" aria-hidden="true"></div>
      </template>
    </main>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Activity, AlertTriangle, ArrowDownToLine, ArrowUpFromLine, Check, Copy, Database, GripVertical, LoaderCircle, MoreHorizontal, Play, Plus, RefreshCw, Save, Search, Settings, SlidersHorizontal, TestTube2, Trash2, X, Zap } from 'lucide-vue-next'
import ContentMonitor from './ContentMonitor.vue'
import AccessMonitor from './AccessMonitor.vue'
import ToolMonitor from './ToolMonitor.vue'
import SandboxMonitor from './SandboxMonitor.vue'
import AuditMonitor from './AuditMonitor.vue'
import ModuleConfigPanel from './ModuleConfigPanel.vue'
import EnterpriseMini from './EnterpriseMini.vue'
import featureModel from '../assets/coder/assets/feature-model.png'
import featureAgent from '../assets/coder/assets/feature-agent.png'
import featureContext from '../assets/coder/assets/feature-context.png'
import featureEvolution from '../assets/coder/assets/feature-evolution.png'
import featureCompose from '../assets/coder/assets/feature-compose.png'

const emit = defineEmits(['open-workspace', 'nav', 'product'])
const locale = ref(localStorage.getItem('argus.locale') || 'zh')
const moduleActions = computed(() => [
  { id: 'monitor', label: ui.value.moduleMonitor },
  { id: 'config', label: ui.value.configEdit }
])
const sections = computed(() => [
  { id: 'home', index: '01', label: ui.value.home },
  { id: 'content', index: '02', label: ui.value.contentDetection, children: moduleActions.value },
  { id: 'access', index: '03', label: ui.value.accessControl, children: moduleActions.value },
  { id: 'tools', index: '04', label: ui.value.toolDetection, children: moduleActions.value },
  { id: 'sandbox', index: '05', label: ui.value.sandboxSecurity, children: moduleActions.value },
  { id: 'audit', index: '06', label: ui.value.auditLogs, children: moduleActions.value }
])

const activeSection = ref('home')
const expandedSection = ref(null)
const activeSubSection = ref(null)
const workspaceEdition = ref(localStorage.getItem('argus.workspace-edition') || 'personal')
const enterpriseLoginStorageKey = 'argus.enterprise-login.v1'
function loadSavedEnterpriseLogin(){ try{ const v = JSON.parse(localStorage.getItem(enterpriseLoginStorageKey) || 'null'); if(v && typeof v === 'object') return { account: v.account || '', invitationCode: v.invitationCode || '' }; }catch{} return { account:'', invitationCode:'' } }
const enterpriseLogin = ref({ open:false, account:'', invitationCode:'', acknowledged:false, rememberMe:false })
function closeEnterpriseLogin() { enterpriseLogin.value.open = false }
function switchToPersonal() { workspaceEdition.value = 'personal'; try{ localStorage.setItem('argus.workspace-edition','personal'); }catch{} }
  try{ fetch('http://127.0.0.1:8000/v1/local/edition', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({edition:'personal'})}); }catch{}

function openEnterpriseLogin() {
  if (workspaceEdition.value === 'pro') { emit('product', 'enterprise'); return }
  const saved = loadSavedEnterpriseLogin();
  enterpriseLogin.value = { open:true, account:saved.account, invitationCode:saved.invitationCode, acknowledged:false, rememberMe:!!(saved.account || saved.invitationCode) }
}
function confirmEnterpriseSwitch() {
  if (!enterpriseLogin.value.acknowledged) return
  try{ if(enterpriseLogin.value.rememberMe){ localStorage.setItem(enterpriseLoginStorageKey, JSON.stringify({ account:enterpriseLogin.value.account, invitationCode:enterpriseLogin.value.invitationCode })); } else { localStorage.removeItem(enterpriseLoginStorageKey); } }catch{}
  workspaceEdition.value = 'pro'
  try{ fetch('http://127.0.0.1:8000/v1/local/edition', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({edition:'pro'})}); }catch{}
  closeEnterpriseLogin()
  emit('product', 'enterprise')
}
const settingsStorageKey = 'argus.desktop-settings.v1'
function loadAppSettings() { try { return { darkMode:false, compactMode:false, autoStart:false, minimizeToTray:true, securityNotifications:true, healthCheck:true, auditRetention:30, diagnosticLogs:false, ...JSON.parse(localStorage.getItem(settingsStorageKey) || '{}') } } catch { return { darkMode:false, compactMode:false, autoStart:false, minimizeToTray:true, securityNotifications:true, healthCheck:true, auditRetention:30, diagnosticLogs:false } } }
const appSettings = ref(loadAppSettings())
function applyAppSettings() { document.documentElement.classList.toggle('claw-dark-mode', appSettings.value.darkMode); document.documentElement.classList.toggle('claw-compact-mode', appSettings.value.compactMode) }
function openSettings() { activeSection.value = 'settings'; activeSubSection.value = null; expandedSection.value = null }
async function toggleAutoStart() { const next = !appSettings.value.autoStart; appSettings.value.autoStart = next; try { const result = await window.electronAPI?.setAutoStart?.(next); if (result && result.enabled !== undefined) appSettings.value.autoStart = result.enabled } catch {} }
watch(locale, (value) => localStorage.setItem('argus.locale', value))
watch(workspaceEdition, (value) => localStorage.setItem('argus.workspace-edition', value))
watch(appSettings, () => { try { localStorage.setItem(settingsStorageKey, JSON.stringify(appSettings.value)) } catch {}; applyAppSettings() }, { deep:true })

function selectSection(section) {
  activeSection.value = section.id
  if (!section.children) {
    expandedSection.value = null
    activeSubSection.value = null
    return
  }

  const shouldCollapse = expandedSection.value === section.id
  expandedSection.value = shouldCollapse ? null : section.id
  activeSubSection.value = shouldCollapse ? null : 'monitor'
}

function selectSubSection(sectionId, childId) {
  activeSection.value = sectionId
  activeSubSection.value = childId
}
const platform = ref('unix')
const copied = ref(false)
const heroMask = ref(null)
const hero = ref(null)
const subtitle = ref(null)
let ctx
let animationFrame
let resizeHandler
let copyTimer
let typingTimers = []
let titleObserver
let daemonLogCleanup
let lastX = null
let lastY = null
let running = false
const stamps = []

const translations = {
  zh: {
    home: '返回 Argus 首页',
    mainNav: '主导航',
    product: '产品',
    personal: '个人版',
    enterprise: '企业版',
    join: '加入我们',
    language: '语言',
    subtitle: '面向 AI 智能体的新一代零信任安全守护平台，帮助你更安全地理解、构建与协作。',
    installPlatform: '安装平台',
    copyCommand: '复制命令',
    copied: '已复制',
    workspace: '进入工作台',
    featuresTitle: '为什么选择 Argus',
    copyright: 'Copyright©2026 Argus. All Rights Reserved',
    cookiePolicy: 'Cookie 政策',
    cookiePreferences: 'Cookie 偏好设置'
  },
  en: {
    home: 'Back to Argus home',
    mainNav: 'Main navigation',
    product: 'Products',
    personal: 'Personal',
    enterprise: 'Enterprise',
    join: 'Join us',
    language: 'Language',
    subtitle: 'A next-generation zero-trust security guardian for AI agents, helping you understand, build, and collaborate more safely.',
    installPlatform: 'Installation platform',
    copyCommand: 'Copy command',
    copied: 'Copied',
    workspace: 'Open workspace',
    featuresTitle: 'Why Argus',
    copyright: 'Copyright©2026 Argus. All Rights Reserved',
    cookiePolicy: 'Cookie Policy',
    cookiePreferences: 'Cookie Preferences'
  }
}

const copy = computed(() => translations[locale.value])
const uiDictionary = {
  zh: { home:'首页', settings:'设置', moduleMonitor:'模块监测', configEdit:'配置修改', contentDetection:'内容检测', accessControl:'访问控制', toolDetection:'工具检测', sandboxSecurity:'沙箱安全', auditLogs:'审计日志', dashboardTitle:'安全运行总览', dashboardSubtitle:'实时观察本地防御链路、模型消耗与配额使用情况', realtimeMonitoring:'实时监控', startupLogs:'启动日志', listening:'正在监听新事件', connectionStatus:'连接状态', serviceStatus:'服务连接状态', checking:'检测中', connected:'已连接', running:'运行中', failed:'连接失败', modelUsage:'模型使用量', usageSubtitle:'Token 消耗、请求与费用趋势', selectProvider:'选择模型或供应商', allModels:'全部模型', refresh:'刷新', realTokenUse:'真实消耗 Tokens', tokenDescription:'包含输入、输出与缓存 Token', requests:'请求数', success:'成功', cacheHits:'缓存命中', saved:'已节省', estimatedCost:'预估费用', currentPeriod:'当前统计周期', usageTrend:'使用趋势', usageTrendAria:'模型使用量趋势图', providers:'供应商', providerSubtitle:'选择当前模型服务并管理连接配置', searchProviders:'搜索供应商', addProvider:'添加供应商', searchPlaceholder:'搜索供应商名称、备注或接口地址', results:'个结果', dragToSort:'拖动排序', current:'当前', todayUsage:'今日用量', requestUnit:'次请求', enabled:'已启用', disabled:'未启用', inUse:'使用中', enable:'启用', editConfig:'编辑配置', moreActions:'更多操作', duplicateProvider:'复制供应商', testing:'正在检测…', connectivityTest:'连通性检测', usageConfig:'用量配置', deleteProvider:'删除供应商', noProviders:'没有找到供应商', noProvidersHelp:'尝试其他关键词，或添加新的模型服务。', systemPreferences:'系统偏好', settingsHelp:'管理本地工作台外观、启动方式、通知和安全体验。', workspaceEdition:'工作台版本', personal:'个人版', pro:'企业版', enterprise:'企业版', enterpriseLogin:'企业版登录', enterpriseLoginHelp:'确认后将在当前客户端中打开企业安全管理平台。', account:'账号', password:'密码', invitationCode:'邀请码', cancel:'取消', confirmAndEnterEnterprise:'确认并进入企业版', enterpriseSwitchWarning:'警告：确认切换到企业版后，个人版工作台将无法继续使用。', acknowledgeEnterpriseWarning:'我已了解并确认上述切换限制', rememberAccount:'记住账号密码，下次自动填写', personalUnavailable:'切换到企业版后不可使用', currentWorkspace:'当前工作空间', personalWorkspace:'Argus 个人版', proWorkspace:'Argus 专业版', personalWorkspaceHelp:'个人本地防御、模型用量与安全对话。', proWorkspaceHelp:'团队策略、审计协同与高级服务路由已启用。', localProtection:'本地安全防护', modelMonitoring:'模型与用量监控', teamAudit:'团队审计与策略协同', failover:'高级服务故障切换', appExperience:'应用体验', appearance:'外观与操作', darkMode:'深色模式', darkModeHelp:'为低光环境切换深色工作台界面。', compactMode:'紧凑布局', compactModeHelp:'收紧卡片间距，在小屏幕中容纳更多信息。', interfaceLanguage:'界面语言', interfaceLanguageHelp:'选择当前桌面端的显示语言。', startupNotifications:'启动与通知', backgroundGuard:'后台守护', autoStart:'开机自动启动', autoStartHelp:'登录 Windows 后自动启动 Argus 和本地守护服务。', minimizeToTray:'最小化到托盘', minimizeToTrayHelp:'关闭主窗口时保持后台防护继续运行。', securityAlerts:'安全告警通知', securityAlertsHelp:'发现高风险调用、策略拦截或服务离线时提醒。', dataSecurity:'数据与安全', localProtectionTitle:'本地保护', healthCheck:'启动时健康检查', healthCheckHelp:'每次启动后自动检查 FastAPI 和 OpenClaw。', auditRetention:'保留本地审计记录', auditRetentionHelp:'在本机保存近期安全事件，便于追踪问题。', days:'保留 {days} 天', diagnosticLogs:'诊断日志', diagnosticLogsHelp:'记录更多服务启动和连接诊断信息。', today:'今日', days7:'7 天', days30:'30 天', hourly:'按小时统计', daily7:'按日统计 · 最近 7 天', daily30:'按日统计 · 最近 30 天', inputTokens:'输入 Token', outputTokens:'输出 Token', cacheWrite:'缓存写入', cacheRead:'缓存读取', cost:'费用', newContext:'新增上下文', generation:'模型生成', createCache:'创建缓存', reuseContext:'复用上下文' },
  en: { home:'Home', settings:'Settings', moduleMonitor:'Module monitoring', configEdit:'Configuration', contentDetection:'Content inspection', accessControl:'Access control', toolDetection:'Tool inspection', sandboxSecurity:'Sandbox security', auditLogs:'Audit logs', dashboardTitle:'Security overview', dashboardSubtitle:'Observe local defense services, model usage, and quota utilization in real time.', realtimeMonitoring:'Live monitoring', startupLogs:'Startup logs', listening:'Listening for new events', connectionStatus:'Connection status', serviceStatus:'Service connection status', checking:'Checking', connected:'Connected', running:'Running', failed:'Connection failed', modelUsage:'Model usage', usageSubtitle:'Token consumption, requests, and cost trends', selectProvider:'Select a model or provider', allModels:'All models', refresh:'Refresh', realTokenUse:'Token consumption', tokenDescription:'Includes input, output, and cached tokens', requests:'Requests', success:'successful', cacheHits:'Cache hits', saved:'Saved', estimatedCost:'Estimated cost', currentPeriod:'Current period', usageTrend:'Usage trend', usageTrendAria:'Model usage trend chart', providers:'Providers', providerSubtitle:'Select the active model service and manage its connection.', searchProviders:'Search providers', addProvider:'Add provider', searchPlaceholder:'Search by provider name, note, or endpoint', results:'results', dragToSort:'Drag to reorder', current:'Current', todayUsage:'Today usage', requestUnit:'requests', enabled:'Enabled', disabled:'Disabled', inUse:'In use', enable:'Enable', editConfig:'Edit configuration', moreActions:'More actions', duplicateProvider:'Duplicate provider', testing:'Testing…', connectivityTest:'Test connection', usageConfig:'Usage configuration', deleteProvider:'Delete provider', noProviders:'No providers found', noProvidersHelp:'Try another keyword or add a model service.', systemPreferences:'System preferences', settingsHelp:'Manage workspace appearance, startup behavior, notifications, and local security.', workspaceEdition:'Workspace edition', personal:'Personal', pro:'Enterprise', enterprise:'Enterprise', enterpriseLogin:'Enterprise sign in', enterpriseLoginHelp:'After confirmation, the enterprise security platform opens in this desktop window.', account:'Account', password:'Password', invitationCode:'Invitation code', cancel:'Cancel', confirmAndEnterEnterprise:'Confirm and open Enterprise', enterpriseSwitchWarning:'Warning: after switching to Enterprise, the Personal workspace will no longer be available.', acknowledgeEnterpriseWarning:'I understand and accept this switch restriction', rememberAccount:'Remember account and invitation code for next time', personalUnavailable:'Unavailable after switching to Enterprise', currentWorkspace:'Current workspace', personalWorkspace:'Argus Personal', proWorkspace:'Argus Professional', personalWorkspaceHelp:'Personal local defense, model usage, and secure chat.', proWorkspaceHelp:'Team policies, audit collaboration, and advanced service routing are enabled.', localProtection:'Local protection', modelMonitoring:'Model and usage monitoring', teamAudit:'Team audit and policy collaboration', failover:'Advanced service failover', appExperience:'Application experience', appearance:'Appearance and behavior', darkMode:'Dark mode', darkModeHelp:'Use a darker workspace in low-light environments.', compactMode:'Compact layout', compactModeHelp:'Reduce card spacing to fit more information on smaller screens.', interfaceLanguage:'Interface language', interfaceLanguageHelp:'Choose the display language for this desktop app.', startupNotifications:'Startup and notifications', backgroundGuard:'Background guard', autoStart:'Launch at sign-in', autoStartHelp:'Start Argus and local guard services after you sign in to Windows.', minimizeToTray:'Minimize to tray', minimizeToTrayHelp:'Keep background protection running when the main window is closed.', securityAlerts:'Security alerts', securityAlertsHelp:'Notify you when a high-risk call, policy block, or service outage is detected.', dataSecurity:'Data and security', localProtectionTitle:'Local protection', healthCheck:'Startup health check', healthCheckHelp:'Check FastAPI and OpenClaw automatically after each launch.', auditRetention:'Keep local audit records', auditRetentionHelp:'Store recent security events on this device for troubleshooting.', days:'Keep {days} days', diagnosticLogs:'Diagnostic logs', diagnosticLogsHelp:'Record additional service startup and connection diagnostics.', today:'Today', days7:'7 days', days30:'30 days', hourly:'Hourly', daily7:'Daily · last 7 days', daily30:'Daily · last 30 days', inputTokens:'Input tokens', outputTokens:'Output tokens', cacheWrite:'Cache writes', cacheRead:'Cache reads', cost:'Cost', newContext:'New context', generation:'Model generation', createCache:'Create cache', reuseContext:'Reuse context' }
}
const ui = computed(() => uiDictionary[locale.value] || uiDictionary.zh)
function t(key, params = {}) { return String(ui.value[key] || key).replace(/\{(\w+)\}/g, (_, name) => params[name] ?? '') }


// 首页启动日志与“守护集群实时控制台”共用 Electron 主进程转发的真实 stdout / stderr。
const startupLogs = ref([])
function formatDaemonTime(timestamp = Date.now()) {
  const date = new Date(timestamp)
  return [date.getHours(), date.getMinutes(), date.getSeconds()].map(value => String(value).padStart(2, '0')).join(':')
}
function daemonEntriesToStartupLogs(entry) {
  const level = entry?.level === 'error' ? 'error' : entry?.level === 'warn' ? 'warn' : 'success'
  return String(entry?.text || '').split(/\r?\n/).map(message => message.trim()).filter(Boolean).map(message => ({
    time: formatDaemonTime(entry?.timestamp), level, message: entry?.source ? '[' + entry.source + '] ' + message : message
  }))
}
function appendStartupDaemonLog(entry) {
  const lines = daemonEntriesToStartupLogs(entry)
  if (!lines.length) return
  startupLogs.value = [...startupLogs.value, ...lines].slice(-8)
}
 const serviceStatuses = ref([
  { name: 'Build for production', ready: false, state: 'checking', url: null },
  { name: 'FastAPI', ready: false, state: 'checking', url: 'http://127.0.0.1:8000/health' },
  { name: 'OpenClaw', ready: false, state: 'checking', url: 'http://127.0.0.1:18789/health' }
 ])
 const checkingServices = ref(false)
const checkingIndex = ref(-1)
// 服务状态重试/轮询参数（OpenClaw 启动较慢，首轮探测常扑空）
const SERVICE_RECHECK_INTERVAL_MS = 2000
const SERVICE_RECHECK_MAX = 20
const SERVICE_POLL_INTERVAL_MS = 5000
let serviceRecheckTimer = null
let serviceRecheckCount = 0
let servicePollTimer = null
let serviceVisibilityHandler = null
const readyServices = computed(() => serviceStatuses.value.filter(service => service.ready).length)
const arrowStyle = computed(() => ({ transform: 'rotate(' + (checkingIndex.value * 120 - 60) + 'deg)' }))
const statusRingStyle = computed(() => {
  const colors = serviceStatuses.value.map(service => service.state === 'failed' ? '#e35d68' : service.ready ? '#36b675' : '#d9d4cf')
  return { background: 'conic-gradient(from -60deg, ' + colors.map((color, index) => color + ' ' + (index * 120) + 'deg ' + (index * 120 + 106) + 'deg, transparent ' + (index * 120 + 106) + 'deg ' + ((index + 1) * 120) + 'deg').join(', ') + ')' }
})
function serviceStateClass(service) { return { 'is-ready': service.ready, 'is-failed': service.state === 'failed', 'is-checking': service.state === 'checking' } }
async function probeService(service) {
  if (!service.url) return true
  try {
    await fetch(service.url, { cache: 'no-store' })
    return true
  } catch {
    return false
  }
}
// 首轮检测带一次动画；此后全部静默，避免观测本身打扰界面。
async function probeAllServices(animate) {
  let daemonStatus = null
  try { daemonStatus = await window.electronAPI?.getDaemonStatus?.() } catch { daemonStatus = null }
  const statusKeys = ['build', 'fastapi', 'openclaw']
  let allReady = true
  for (let index = 0; index < serviceStatuses.value.length; index += 1) {
    const service = serviceStatuses.value[index]
    if (animate) { checkingIndex.value = index; service.state = 'checking' }
    const detected = daemonStatus ? Boolean(daemonStatus[statusKeys[index]]) : await probeService(service)
    const ready = animate
      ? await new Promise(resolve => setTimeout(() => resolve(detected), index === 0 ? 650 : 780))
      : detected
    service.ready = ready
    service.state = ready ? 'ready' : 'failed'
    if (!ready) allReady = false
  }
  if (animate) checkingIndex.value = -1
  return allReady
}

async function startServiceChecks() {
  if (checkingServices.value) return
  checkingServices.value = true
  serviceStatuses.value.forEach(service => { service.ready = false; service.state = 'checking' })
  const allReady = await probeAllServices(true)
  await new Promise(resolve => setTimeout(resolve, 300))
  checkingIndex.value = -1
  checkingServices.value = false
  serviceRecheckCount = 0
  scheduleServiceRecheck(allReady)
  startServicePolling()
}

// OpenClaw 由守护进程在应用启动后异步拉起（实测比 Electron 主进程晚 3s 以上），
// 首轮探测经常扑空。这里在未全部就绪时静默重试，直到就绪或超过上限。
function scheduleServiceRecheck(allReady) {
  if (serviceRecheckTimer) { window.clearTimeout(serviceRecheckTimer); serviceRecheckTimer = null }
  if (allReady || serviceRecheckCount >= SERVICE_RECHECK_MAX) return
  serviceRecheckCount += 1
  serviceRecheckTimer = window.setTimeout(async () => {
    serviceRecheckTimer = null
    let ok = false
    try { ok = await probeAllServices(false) } catch { ok = false }
    scheduleServiceRecheck(ok)
  }, SERVICE_RECHECK_INTERVAL_MS)
}

// 后台静默轮询：服务中途退出/恢复时，面板也能反映真实状态。
function startServicePolling() {
  if (servicePollTimer) return
  servicePollTimer = window.setInterval(async () => {
    if (checkingServices.value) return
    try { await probeAllServices(false) } catch { /* 忽略瞬时探测失败 */ }
  }, SERVICE_POLL_INTERVAL_MS)
  // 窗口被遮挡/最小化时，Chromium（Electron 默认 backgroundThrottling）
  // 会节流定时器，导致状态面板更新迟滞。回到前台时立即补一次检测。
  serviceVisibilityHandler = () => {
    if (document.visibilityState !== 'visible') return
    if (checkingServices.value) return
    probeAllServices(false).catch(() => {})
  }
  document.addEventListener('visibilitychange', serviceVisibilityHandler)
  window.addEventListener('focus', serviceVisibilityHandler)
}
const providerStorageKey = 'argus.providers.v1'
// 个人版真相源：本机 OpenClaw 配置文件（~/.openclaw/openclaw.json）的 models.providers。
// 首页供应商卡片已删除，改由"本地模型配置"整文件编辑（见 configEditor）；以下旧函数仅保留
// loadLocalProviders 给用量下拉框用，其余 CRUD 已下线（后端 openclaw-providers 代理接口仍保留）。
const defaultProviders = []
// 个人版本地模型配置：整文件编辑 openclaw.json（经 :8000 代理读写，自动备份 .bak）。
const configEditor = ref({ loading: true, saving: false, error: '', status: '', text: '', path: '' })
async function loadOpenclawConfig(manual) {
  if (!manual && configEditor.value.text) return
  configEditor.value.loading = true; configEditor.value.error = ''; if (manual) configEditor.value.status = ''
  try {
    const response = await fetch('http://127.0.0.1:8000/v1/local/openclaw-providers/raw', { cache: 'no-store' })
    if (!response.ok) throw new Error('HTTP ' + response.status)
    const payload = await response.json()
    configEditor.value.text = payload?.data?.text || ''
    configEditor.value.path = payload?.data?.path || ''
    if (!configEditor.value.text) throw new Error('empty config')
  } catch (e) { configEditor.value.error = '读取失败：' + (e.message || e) + '，确认 8000 已启动（需重启新版）' }
  finally { configEditor.value.loading = false }
}
async function saveOpenclawConfig() {
  let parsed
  try { parsed = JSON.parse(configEditor.value.text) }
  catch (e) { configEditor.value.error = 'JSON 非法，拒绝保存：' + e.message; return }
  if (!parsed || typeof parsed !== 'object' || !parsed.models) { configEditor.value.error = '缺少 models 段，拒绝保存'; return }
  configEditor.value.saving = true; configEditor.value.error = ''
  try {
    const response = await fetch('http://127.0.0.1:8000/v1/local/openclaw-providers/raw', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: configEditor.value.text }) })
    if (!response.ok) throw new Error('HTTP ' + response.status)
    const payload = await response.json()
    configEditor.value.status = '已保存' + (payload?.data?.path ? '：' + payload.data.path : '')
    await loadRuntimeDashboard()
  } catch (e) { configEditor.value.error = '保存失败：' + (e.message || e) }
  finally { configEditor.value.saving = false }
}
async function loadLocalProviders() {
  // 用量下拉框仍用卡片列表（经 :8000 代理读文件）。
  try {
    const response = await fetch('http://127.0.0.1:8000/v1/local/openclaw-providers', { cache: 'no-store' })
    if (!response.ok) throw new Error('provider_source_unavailable')
    const payload = await response.json()
    const list = payload && payload.data && payload.data.providers
    return Array.isArray(list) ? list : []
  } catch {
    return []
  }
}
const providers = ref([])
// 旧供应商卡片 CRUD 已删除（被上方本地模型配置整文件编辑替代）。用量下拉框仍用 providers/selectedProvider（见下方）。
const selectedProvider = ref('all')
const runtimeUsage = ref({ today:[], '7d':[], '30d':[] })
const runtimeDataLoaded = ref(false)
const usageLedgerSummary = ref({ total: 0, calls: 0, models: [] })
let usageRefreshTimer = null

function numberOrZero(value) {
  const number = Number(value)
  return Number.isFinite(number) && number > 0 ? number : 0
}

function normalizeUsagePoint(point) {
  if (!point || typeof point !== 'object') return null
  return {
    time: String(point.time || ''),
    input: numberOrZero(point.input),
    output: numberOrZero(point.output),
    cacheCreate: numberOrZero(point.cacheCreate ?? point.cacheWrite),
    cacheRead: numberOrZero(point.cacheRead),
    cost: numberOrZero(point.cost),
    requests: numberOrZero(point.requests),
    // llm_output 账本中的每条记录都是一次已完成的模型输出；后端没有再单独写 successes。
    successes: numberOrZero(point.successes ?? point.requests)
  }
}

function normalizeUsageBuckets(usage) {
  const normalized = { today: [], '7d': [], '30d': [] }
  for (const key of Object.keys(normalized)) {
    const points = Array.isArray(usage?.[key]) ? usage[key] : []
    normalized[key] = points.map(normalizeUsagePoint).filter(Boolean)
  }
  return normalized
}

function fallbackPointFromLedger() {
  const summary = usageLedgerSummary.value
  if (!numberOrZero(summary.total) && !numberOrZero(summary.calls)) return null
  const models = Array.isArray(summary.models) ? summary.models : []
  const aggregate = models.reduce((totals, model) => ({
    input: totals.input + numberOrZero(model?.input),
    output: totals.output + numberOrZero(model?.output),
    cacheCreate: totals.cacheCreate + numberOrZero(model?.cacheWrite ?? model?.cacheCreate),
    cacheRead: totals.cacheRead + numberOrZero(model?.cacheRead)
  }), { input: 0, output: 0, cacheCreate: 0, cacheRead: 0 })
  return {
    time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    input: aggregate.input,
    output: aggregate.output,
    cacheCreate: aggregate.cacheCreate,
    cacheRead: aggregate.cacheRead,
    cost: 0,
    requests: numberOrZero(summary.calls),
    successes: numberOrZero(summary.calls)
  }
}

async function loadRuntimeDashboard() {
  let runtimeLoaded = false
  try {
    const response = await fetch('http://127.0.0.1:8000/v1/desktop/runtime', { cache:'no-store' })
    if (!response.ok) throw new Error('runtime_data_unavailable')
    const payload = await response.json()
    const normalized = normalizeUsageBuckets(payload?.usage)
    if (normalized.today.length || normalized['7d'].length || normalized['30d'].length) {
      runtimeUsage.value = normalized
    }
    runtimeLoaded = true
  } catch {
    runtimeLoaded = false
  }

  // 同时读取累计账本，避免网关刚启动、时间桶尚未刷新时首页暂时显示 0。
  try {
    const response = await fetch('http://127.0.0.1:8000/v1/local/usage', { cache:'no-store' })
    if (!response.ok) throw new Error('usage_ledger_unavailable')
    const payload = await response.json()
    const data = payload?.data || {}
    usageLedgerSummary.value = {
      total: numberOrZero(data.total),
      calls: numberOrZero(data.calls),
      models: Array.isArray(data.models) ? data.models : []
    }
    const hasLivePoint = Object.values(runtimeUsage.value).some(points => points.some(point =>
      numberOrZero(point.input) + numberOrZero(point.output) + numberOrZero(point.cacheCreate) + numberOrZero(point.cacheRead) > 0
    ))
    const fallback = fallbackPointFromLedger()
    if (!hasLivePoint && fallback) {
      runtimeUsage.value = { today: [fallback], '7d': [fallback], '30d': [fallback] }
      runtimeLoaded = true
    }
  } catch {
    // runtime 接口已经成功时不影响正常展示。
  }
  runtimeDataLoaded.value = runtimeLoaded

  // 供应商真相源 = 本机 openclaw.json（经 :8000 代理读文件，直接改配置文件生效）。
  try {
    providers.value = await loadLocalProviders()
    if (selectedProvider.value !== 'all' && !providers.value.some(item => item.id === selectedProvider.value)) selectedProvider.value = 'all'
  } catch {
    providers.value = []
  }
}
const selectedRange = ref('today')
const usageRanges = computed(() => [{ id: 'today', label: ui.value.today }, { id: '7d', label: ui.value.days7 }, { id: '30d', label: ui.value.days30 }])
const selectedRangeLabel = computed(() => usageRanges.value.find(item => item.id === selectedRange.value)?.label || ui.value.today)
const chartHoverIndex = ref(null)
const hiddenSeries = ref([])
const chartSeries = [
  { key: 'input', label: computed(() => ui.value.inputTokens), color: '#5b8ff9', area: true },
  { key: 'output', label: computed(() => ui.value.outputTokens), color: '#35b779', area: false },
  { key: 'cacheCreate', label: computed(() => ui.value.cacheWrite), color: '#f6a23a', area: false },
  { key: 'cacheRead', label: computed(() => ui.value.cacheRead), color: '#9b6de3', area: false },
  { key: 'cost', label: computed(() => ui.value.cost), color: '#e85d75', area: false }
]
const usageDataByRange = {
  today: [
    { time: '09:00', input: 120, output: 28, cacheCreate: 45, cacheRead: 210, cost: .06 },
    { time: '10:00', input: 340, output: 72, cacheCreate: 118, cacheRead: 480, cost: .18 },
    { time: '11:00', input: 720, output: 166, cacheCreate: 260, cacheRead: 910, cost: .60 },
    { time: '12:00', input: 510, output: 108, cacheCreate: 180, cacheRead: 1060, cost: .42 },
    { time: '13:00', input: 290, output: 64, cacheCreate: 90, cacheRead: 430, cost: .22 },
    { time: '14:00', input: 640, output: 142, cacheCreate: 235, cacheRead: 760, cost: .51 },
    { time: '15:00', input: 860, output: 205, cacheCreate: 330, cacheRead: 1180, cost: .79 }
  ],
  '7d': [
    { time: '09/02', input: 3180, output: 620, cacheCreate: 910, cacheRead: 4860, cost: 2.48 },
    { time: '09/03', input: 4250, output: 880, cacheCreate: 1280, cacheRead: 7320, cost: 3.26 },
    { time: '09/04', input: 2960, output: 540, cacheCreate: 760, cacheRead: 5580, cost: 2.11 },
    { time: '09/05', input: 5120, output: 1060, cacheCreate: 1540, cacheRead: 8860, cost: 4.08 },
    { time: '09/06', input: 3880, output: 790, cacheCreate: 1120, cacheRead: 6940, cost: 3.02 },
    { time: '09/07', input: 5780, output: 1240, cacheCreate: 1860, cacheRead: 10420, cost: 4.71 },
    { time: '09/08', input: 6320, output: 1380, cacheCreate: 2050, cacheRead: 11860, cost: 5.16 }
  ],
  '30d': [
    { time: '08/10', input: 12600, output: 2420, cacheCreate: 3850, cacheRead: 22600, cost: 9.42 },
    { time: '08/15', input: 18400, output: 3780, cacheCreate: 5420, cacheRead: 31800, cost: 13.85 },
    { time: '08/20', input: 15800, output: 3160, cacheCreate: 4680, cacheRead: 28600, cost: 11.92 },
    { time: '08/25', input: 23200, output: 4840, cacheCreate: 7140, cacheRead: 42200, cost: 18.16 },
    { time: '08/30', input: 19800, output: 4120, cacheCreate: 6260, cacheRead: 36500, cost: 15.28 },
    { time: '09/04', input: 27400, output: 5680, cacheCreate: 8420, cacheRead: 49600, cost: 21.44 },
    { time: '09/08', input: 31600, output: 6420, cacheCreate: 9860, cacheRead: 58400, cost: 24.76 }
  ]
}
// CCSwitch 的趋势图是按当前选择的模型服务分别取数，而不是把一条总曲线等比例缩放。
// 下面为本地演示数据保留了同样的“按服务 / 模型分桶”结构：每个服务在各时间段都有独立走势。
const providerTrendProfiles = {
  openai: [0.64, 0.93, 0.56, 1.08, 0.84, 0.62, 0.96],
  aliyun: [0.18, 0.12, 0.48, 0.22, 0.54, 0.71, 0.31],
  ccqt: [0.08, 0.29, 0.16, 0.43, 0.14, 0.31, 0.57]
}
const providerBaseShares = { openai: 0.70, aliyun: 0.24, ccqt: 0.12 }
function stableProviderSeed(id) { return [...String(id)].reduce((seed, char) => (seed * 31 + char.charCodeAt(0)) >>> 0, 7) }
function providerTrendWeight(provider, index, length) {
  const knownProfile = providerTrendProfiles[provider.id]
  if (knownProfile) return knownProfile[index % knownProfile.length]
  // 新增供应商也拥有一条稳定、独立的趋势，而不是复用当前模型的曲线。
  const seed = stableProviderSeed(provider.id)
  const phase = (seed % 628) / 100
  const wave = .58 + ((Math.sin(phase + index * 1.73) + 1) * .23)
  const drift = .78 + ((seed >> (index % 12)) & 15) / 52
  return wave * drift
}
function selectedProviderChart(provider) {
  const source = usageDataByRange[selectedRange.value]
  const share = providerBaseShares[provider.id] ?? (.16 + (stableProviderSeed(provider.id) % 15) / 100)
  const metricBias = {
    input: .98 + (stableProviderSeed(provider.id + 'input') % 10) / 100,
    output: .94 + (stableProviderSeed(provider.id + 'output') % 15) / 100,
    cacheCreate: .82 + (stableProviderSeed(provider.id + 'cache-create') % 19) / 100,
    cacheRead: .88 + (stableProviderSeed(provider.id + 'cache-read') % 21) / 100,
    cost: .92 + (stableProviderSeed(provider.id + 'cost') % 17) / 100
  }
  return source.map((point, index) => {
    const weight = providerTrendWeight(provider, index, source.length)
    return {
      time: point.time,
      input: Math.round(point.input * share * weight * metricBias.input),
      output: Math.round(point.output * share * weight * metricBias.output),
      cacheCreate: Math.round(point.cacheCreate * share * weight * metricBias.cacheCreate),
      cacheRead: Math.round(point.cacheRead * share * weight * metricBias.cacheRead),
      cost: Number((point.cost * share * weight * metricBias.cost).toFixed(2))
    }
  })
}
const chartData = computed(() => {
  const live = runtimeUsage.value[selectedRange.value]
  if (Array.isArray(live) && live.length) return live
  // 无真实审计数据时显示全零刻度，而非旧的演示曲线。
  return (usageDataByRange[selectedRange.value] || []).map(point => ({ time:point.time, input:0, output:0, cacheCreate:0, cacheRead:0, cost:0, requests:0, successes:0 }))
})
const chartGridY = [28, 108, 188, 268]
const chartTokenMax = computed(() => Math.max(1200, ...chartData.value.flatMap(point => [point.input, point.output, point.cacheCreate, point.cacheRead])))
const chartCostMax = computed(() => Math.max(.9, ...chartData.value.map(point => point.cost)))
const chartYLabels = computed(() => [formatCompact(chartTokenMax.value), formatCompact(chartTokenMax.value * 2 / 3), formatCompact(chartTokenMax.value / 3), '0'])
const totals = computed(() => chartData.value.reduce((sum, point) => ({ input: sum.input + point.input, output: sum.output + point.output, cacheCreate: sum.cacheCreate + point.cacheCreate, cacheRead: sum.cacheRead + point.cacheRead, cost: sum.cost + point.cost, requests: sum.requests + Number(point.requests || 0), successes: sum.successes + Number(point.successes || 0) }), { input: 0, output: 0, cacheCreate: 0, cacheRead: 0, cost: 0, requests:0, successes:0 }))
const usageSummary = computed(() => ({ totalTokens: Math.round(totals.value.input + totals.value.output + totals.value.cacheCreate + totals.value.cacheRead).toLocaleString('en-US'), requests: Math.round(totals.value.requests).toLocaleString('en-US'), successRate: totals.value.requests ? (totals.value.successes / totals.value.requests * 100).toFixed(1) + '%' : '—', cacheRate: totals.value.input + totals.value.cacheCreate + totals.value.cacheRead ? (totals.value.cacheRead / (totals.value.input + totals.value.cacheCreate + totals.value.cacheRead) * 100).toFixed(1) + '%' : '—', cacheSaved: formatCompact(totals.value.cacheRead), cost: '$' + totals.value.cost.toFixed(2) }))
const usageMetrics = computed(() => [
  { key: 'input', label: ui.value.inputTokens, value: formatCompact(totals.value.input), note: ui.value.newContext, icon: ArrowDownToLine },
  { key: 'output', label: ui.value.outputTokens, value: formatCompact(totals.value.output), note: ui.value.generation, icon: ArrowUpFromLine },
  { key: 'cache-write', label: ui.value.cacheWrite, value: formatCompact(totals.value.cacheCreate), note: ui.value.createCache, icon: Database },
  { key: 'cache-read', label: ui.value.cacheRead, value: formatCompact(totals.value.cacheRead), note: ui.value.reuseContext, icon: Zap }
])
function formatCompact(value) { const amount = numberOrZero(value); if (amount >= 1000000) return (amount / 1000000).toFixed(2) + 'm'; if (amount >= 1000) return (amount / 1000).toFixed(2) + 'k'; return Math.round(amount).toLocaleString('en-US') }
const visibleChartSeries = computed(() => chartSeries.filter(series => !hiddenSeries.value.includes(series.key)))
function toggleSeries(key) { hiddenSeries.value = hiddenSeries.value.includes(key) ? hiddenSeries.value.filter(item => item !== key) : [...hiddenSeries.value, key] }
function chartX(index) { return 42 + index * (948 / Math.max(1, chartData.value.length - 1)) }
function seriesY(value, key) { const ratio = key === 'cost' ? value / chartCostMax.value : value / chartTokenMax.value; return 268 - Math.max(0, Math.min(1, ratio)) * 240 }
const trendIntervalLabel = computed(() => selectedRange.value === 'today' ? ui.value.hourly : selectedRange.value === '7d' ? ui.value.daily7 : ui.value.daily30)
function chartPoints(key) {
  return chartData.value.map((point, index) => ({ x: chartX(index), y: seriesY(point[key], key) }))
}
// 以 Catmull–Rom 转三次贝塞尔：每日采样点仍精确经过，视觉上不再是生硬的折线。
function smoothPath(points) {
  if (!points.length) return ''
  if (points.length === 1) return `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`
  let path = `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`
  for (let index = 0; index < points.length - 1; index += 1) {
    const previous = points[index - 1] || points[index]
    const current = points[index]
    const next = points[index + 1]
    const following = points[index + 2] || next
    const control1 = { x: current.x + (next.x - previous.x) / 6, y: current.y + (next.y - previous.y) / 6 }
    const control2 = { x: next.x - (following.x - current.x) / 6, y: next.y - (following.y - current.y) / 6 }
    path += ` C ${control1.x.toFixed(1)} ${control1.y.toFixed(1)}, ${control2.x.toFixed(1)} ${control2.y.toFixed(1)}, ${next.x.toFixed(1)} ${next.y.toFixed(1)}`
  }
  return path
}
function seriesPath(key) { return smoothPath(chartPoints(key)) }
function seriesAreaPath(key) { const points = chartPoints(key); return seriesPath(key) + ` L ${points[points.length - 1].x.toFixed(1)} 268 L ${points[0].x.toFixed(1)} 268 Z` }
function formatSeriesValue(value, key) { if (key === 'cost') return '$' + Number(value).toFixed(2); return value >= 1000 ? (value / 1000).toFixed(2) + 'm' : value + 'k' }
const tooltipStyle = computed(() => { const x = chartX(chartHoverIndex.value ?? 0); return { left: Math.min(Math.max(x / 10 - 8, 2), 74) + '%', top: '12%' } })
function segmentStyle(index) { return { transform: 'rotate(' + (index * 120 - 60) + 'deg)' } }
function handleChartMove(event) { const rect = event.currentTarget.getBoundingClientRect(); const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)); chartHoverIndex.value = Math.round(ratio * (chartData.value.length - 1)) }

const featureCopy = {
  zh: [
    ['开箱即用的深度防御', '无需复杂配置，即可启用 AI Agent 行为拦截、敏感文件保护与实时风险识别。'],
    ['模型 Agent 协同防护', '在工具调用、命令执行与网络外发之间建立安全策略，让智能体更可靠地完成复杂任务。'],
    ['无限上下文审计', '自动沉淀风险上下文，保留关键调用链路，让每一次决策都可追踪、可复盘。'],
    ['自进化安全系统', '基于使用反馈持续优化规则、工具链与工作流，越用越懂你的项目与安全边界。'],
    ['Compose 安全编排', '一个人的安全运营团队，从风险发现到隔离审批实现工业级闭环交付。']
  ],
  en: [
    ['Ready-to-use deep defense', 'Enable AI agent behavior blocking, sensitive file protection, and real-time risk detection without complex setup.'],
    ['Model-agent collaboration', 'Set security policies across tool calls, command execution, and network egress so agents can complete complex tasks more reliably.'],
    ['Unlimited context auditing', 'Automatically preserve risk context and critical call chains so every decision stays traceable and reviewable.'],
    ['Self-evolving security', 'Continuously improve rules, toolchains, and workflows from usage feedback, adapting to your project and security boundaries.'],
    ['Compose security orchestration', 'A one-person security operations team that closes the loop from risk discovery to isolation approval.']
  ]
}

const featureImages = [featureModel, featureAgent, featureContext, featureEvolution, featureCompose]
const features = computed(() => featureCopy[locale.value].map(([title, body], index) => ({
  className: `card--${index + 1}`,
  image: featureImages[index],
  title,
  body
})))

const installCommand = computed(() => platform.value === 'unix'
  ? 'cd Argus/terminal && python3 -m venv .venv && . .venv/bin/activate && python -m pip install -r requirements.txt && python -m uvicorn argus.api.main:app --host 127.0.0.1 --port 8000'
  : 'cd Argus\\terminal; py -m venv .venv; .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt; .\\.venv\\Scripts\\python.exe -m uvicorn argus.api.main:app --host 127.0.0.1 --port 8000')

function setLocale(nextLocale) {
  if (nextLocale === locale.value) return
  locale.value = nextLocale
}

function copyCommand() {
  navigator.clipboard?.writeText(installCommand.value)
  copied.value = true
  clearTimeout(copyTimer)
  if (usageRefreshTimer) window.clearInterval(usageRefreshTimer)
  copyTimer = setTimeout(() => { copied.value = false }, 1800)
}

function resizeCanvas() {
  const canvas = heroMask.value
  const host = hero.value
  if (!canvas || !host) return
  const rect = host.getBoundingClientRect()
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  canvas.width = Math.round(rect.width * dpr)
  canvas.height = Math.round(rect.height * dpr)
  canvas.style.width = `${rect.width}px`
  canvas.style.height = `${rect.height}px`
  ctx = canvas.getContext('2d')
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.globalCompositeOperation = 'source-over'
  ctx.fillStyle = 'rgb(252, 250, 248)'
  ctx.fillRect(0, 0, rect.width, rect.height)
  stamps.length = 0
}

function addStamp(x, y) {
  if (stamps.length >= 160) stamps.shift()
  stamps.push({ x, y, born: performance.now(), seed: Math.random() * Math.PI * 2, rmax: 128 * (0.55 + Math.random() * 0.45) })
}

function stampAlong(x, y) {
  if (lastX === null || lastY === null) {
    addStamp(x, y)
  } else {
    const dx = x - lastX
    const dy = y - lastY
    const steps = Math.max(1, Math.ceil(Math.hypot(dx, dy) / 12))
    for (let i = 1; i <= steps; i += 1) addStamp(lastX + (dx * i) / steps, lastY + (dy * i) / steps)
  }
  lastX = x
  lastY = y
}

function carveInk(x, y, radius, alpha, seed) {
  const gradient = ctx.createRadialGradient(x, y, radius * 0.25, x, y, radius)
  gradient.addColorStop(0, `rgba(0, 0, 0, ${0.95 * alpha})`)
  gradient.addColorStop(0.55, `rgba(0, 0, 0, ${0.88 * alpha})`)
  gradient.addColorStop(1, 'rgba(0, 0, 0, 0)')
  ctx.fillStyle = gradient
  ctx.beginPath()
  for (let i = 0; i <= 32; i += 1) {
    const angle = (i / 32) * Math.PI * 2
    const wobble = 0.78 + 0.14 * Math.sin(angle * 3 + seed) + 0.08 * Math.sin(angle * 7 + seed * 2.1) + 0.05 * Math.sin(angle * 13 + seed * 0.7)
    const px = x + Math.cos(angle) * radius * wobble
    const py = y + Math.sin(angle) * radius * wobble
    if (i === 0) ctx.moveTo(px, py)
    else ctx.lineTo(px, py)
  }
  ctx.closePath()
  ctx.fill()
}

function renderInk() {
  if (!ctx || !hero.value || !heroMask.value) return
  const rect = hero.value.getBoundingClientRect()
  const now = performance.now()
  ctx.globalCompositeOperation = 'source-over'
  ctx.fillStyle = 'rgb(252, 250, 248)'
  ctx.fillRect(0, 0, rect.width, rect.height)
  ctx.globalCompositeOperation = 'destination-out'
  for (let i = stamps.length - 1; i >= 0; i -= 1) {
    const stamp = stamps[i]
    const t = (now - stamp.born) / 520
    if (t >= 1) {
      stamps.splice(i, 1)
      continue
    }
    const ease = 1 - Math.pow(1 - t, 3)
    carveInk(stamp.x, stamp.y, 8 + (stamp.rmax - 8) * ease, 1 - t * t, stamp.seed)
  }
  if (stamps.length) animationFrame = requestAnimationFrame(renderInk)
  else running = false
}

function startInk() {
  if (!running) {
    running = true
    animationFrame = requestAnimationFrame(renderInk)
  }
}

function handleMouseEnter(event) {
  if (!ctx || !hero.value || !window.matchMedia('(hover: hover)').matches) return
  const rect = hero.value.getBoundingClientRect()
  lastX = event.clientX - rect.left
  lastY = event.clientY - rect.top
  stampAlong(lastX, lastY)
  startInk()
}

function handleMouseMove(event) {
  if (!ctx || !hero.value || !window.matchMedia('(hover: hover)').matches) return
  const rect = hero.value.getBoundingClientRect()
  stampAlong(event.clientX - rect.left, event.clientY - rect.top)
  startInk()
}

function handleMouseLeave() {
  lastX = null
  lastY = null
}

function typeFeatureTitle(el, cardIndex) {
  if (el.dataset.typed === 'true') return
  el.dataset.typed = 'true'
  const original = el.getAttribute('aria-label') || el.textContent.trim()
  el.textContent = ''
  el.classList.add('is-active')
  ;[...original].forEach((char, index) => {
    const span = document.createElement('span')
    span.className = 'char'
    span.textContent = char
    el.appendChild(span)
    const timer = setTimeout(() => span.classList.add('is-typed'), 80 + index * 65)
    typingTimers.push(timer)
  })
  const cursor = document.createElement('span')
  cursor.className = 'cursor'
  cursor.setAttribute('aria-hidden', 'true')
  el.appendChild(cursor)
  const doneTimer = setTimeout(() => el.classList.add('is-done'), 80 + original.length * 65 + 180)
  typingTimers.push(doneTimer)
}

function typeFeatureTitles() {
  const titles = [...document.querySelectorAll('.card__text h3')]
  if (!titles.length) return
  if (!('IntersectionObserver' in window)) {
    titles.forEach((el, index) => typeFeatureTitle(el, index))
    return
  }
  titleObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return
      const index = titles.indexOf(entry.target)
      typeFeatureTitle(entry.target, index)
      titleObserver.unobserve(entry.target)
    })
  }, { threshold: 0.35, rootMargin: '0px 0px -8% 0px' })
  titles.forEach((title) => titleObserver.observe(title))
}

function typeSubtitle() {
  if (!subtitle.value || window.matchMedia('(max-width: 700px)').matches) return
  const el = subtitle.value
  const original = el.textContent.trim()
  el.textContent = ''
  el.classList.add('is-typing')
  const chars = [...original]
  chars.forEach((char, index) => {
    const span = document.createElement('span')
    span.className = 'char'
    span.textContent = char
    el.appendChild(span)
    const timer = setTimeout(() => span.classList.add('is-typed'), 350 + index * 45)
    typingTimers.push(timer)
  })
  const caret = document.createElement('span')
  caret.className = 'type-caret'
  caret.setAttribute('aria-hidden', 'true')
  el.appendChild(caret)
  const doneTimer = setTimeout(() => el.classList.add('is-done'), 350 + chars.length * 45 + 150)
  typingTimers.push(doneTimer)
}

watch(locale, async () => {
  typingTimers.forEach((timer) => clearTimeout(timer))
  typingTimers = []
  titleObserver?.disconnect()
  await nextTick()
  typeSubtitle()
  typeFeatureTitles()
})

onMounted(async () => {
  // 先订阅，再读取控制台已有缓冲，确保能看到应用启动阶段已产生的真实日志。
  daemonLogCleanup = window.electronAPI?.onDaemonLog?.(appendStartupDaemonLog)
  try {
    const history = await window.electronAPI?.getDaemonLogHistory?.(80)
    if (Array.isArray(history)) startupLogs.value = history.flatMap(daemonEntriesToStartupLogs).slice(-8)
  } catch {
    // 浏览器开发模式没有 Electron IPC 时，等待后续服务输出即可。
  }
  applyAppSettings()
  startServiceChecks()
  await loadRuntimeDashboard()
  usageRefreshTimer = window.setInterval(() => { loadRuntimeDashboard() }, 15000)
  await loadOpenclawConfig(false)
  resizeCanvas()
  typeSubtitle()
  typeFeatureTitles()
  resizeHandler = resizeCanvas
  window.addEventListener('resize', resizeHandler)
  hero.value?.addEventListener('mouseenter', handleMouseEnter)
  hero.value?.addEventListener('mousemove', handleMouseMove)
  hero.value?.addEventListener('mouseleave', handleMouseLeave)
})

onUnmounted(() => {
  cancelAnimationFrame(animationFrame)
  daemonLogCleanup?.()
  clearTimeout(copyTimer)
  if (serviceRecheckTimer) window.clearTimeout(serviceRecheckTimer)
  if (servicePollTimer) window.clearInterval(servicePollTimer)
  if (serviceVisibilityHandler) {
    document.removeEventListener('visibilitychange', serviceVisibilityHandler)
    window.removeEventListener('focus', serviceVisibilityHandler)
  }
  typingTimers.forEach((timer) => clearTimeout(timer))
  typingTimers = []
  titleObserver?.disconnect()
  window.removeEventListener('resize', resizeHandler)
  hero.value?.removeEventListener('mouseenter', handleMouseEnter)
  hero.value?.removeEventListener('mousemove', handleMouseMove)
  hero.value?.removeEventListener('mouseleave', handleMouseLeave)
})


</script>























