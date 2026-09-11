<template>
  <div class="desktop-shell">
    <header v-if="!isDebugConsole" class="app-titlebar">
      <div class="app-titlebar-brand">
        <img :src="argusLogo" alt="" class="app-titlebar-logo" />
        <span class="app-titlebar-name">Argus</span>
        <span class="app-titlebar-badge">Desktop</span>
      </div>
      <div class="app-titlebar-actions">
        <span class="app-titlebar-status"><span class="app-titlebar-status-dot"></span>安全守护中</span>
        <button class="app-titlebar-button" type="button" aria-label="最小化" @click="minimizeWindow"><Minus :size="15" /></button>
        <button class="app-titlebar-button" type="button" aria-label="最大化" @click="maximizeWindow"><Square :size="13" /></button>
        <button class="app-titlebar-button app-titlebar-close" type="button" aria-label="关闭" @click="closeWindow"><X :size="15" /></button>
      </div>
    </header>

    <main class="desktop-content">
      <DaemonConsole v-if="isDebugConsole" standalone />

      <FirstRunSetup
    v-else-if="currentView === 'setup'"
    @setup-done="currentView = 'home'"
  />

  <MimoCodeLanding
    v-else-if="currentView === 'home'"
    @open-workspace="enterPersonal"
    @nav="handleNav"
    @product="handleProduct"
  />

  <PersonalWorkspace
    v-else-if="currentView === 'personal' || currentView === 'workspace'"
    @back-home="currentView = 'home'"
  />

  <div v-else-if="currentView === 'enterprise'" class="mini-window-host">
    <EnterpriseMini mini-window @back-personal="backToPersonalDev" />
  </div>

  <div v-else class="min-h-screen bg-[#FAFAF8] text-zinc-900 font-sans">
    <main class="max-w-6xl mx-auto px-6 py-8 space-y-6">
      <div class="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm">
        <div class="flex items-center gap-3">
          <button class="rounded-xl p-2 text-zinc-500 transition-colors hover:bg-zinc-100" title="返回官网介绍" @click="currentView = 'home'">
            <ArrowLeft class="h-4 w-4" />
          </button>
          <div>
            <h2 class="text-base font-bold">{{ currentView === 'workspace' ? '个人版安全守护工作台' : 'Argus 安全技术白皮书与博客' }}</h2>
            <p class="text-xs text-zinc-400">{{ currentView === 'workspace' ? '本地守护进程协同运行中 · 零数据外传至公网' : 'AI 智能体时代下的零信任纵深防御思考与演进' }}</p>
          </div>
        </div>

        <div v-if="currentView === 'workspace'" class="flex items-center gap-1 rounded-xl bg-zinc-100 p-1 text-xs font-medium text-zinc-600">
          <button v-for="tab in workspaceTabs" :key="tab.id" class="rounded-lg px-3 py-1.5 transition-all" :class="activeWorkspaceTab === tab.id ? 'bg-white text-zinc-900 shadow-sm font-semibold' : 'hover:text-zinc-900'" @click="activeWorkspaceTab = tab.id">{{ tab.label }}</button>
        </div>
      </div>

      <template v-if="currentView === 'workspace'">
        <BentoCards v-if="activeWorkspaceTab === 'dashboard'" />
        <SecurityRules v-else-if="activeWorkspaceTab === 'rules'" />
        <TelemetryView v-else-if="activeWorkspaceTab === 'telemetry'" />
        <DaemonConsole v-else />
      </template>

      <article v-else class="space-y-6 text-sm leading-relaxed text-zinc-600">
        <section class="space-y-3 rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm">
          <div class="font-mono text-xs text-[#FF6900]">2026-09-08 · 安全架构</div>
          <h3 class="text-lg font-bold text-zinc-900">为什么传统 WAF 无法抵御 AI Agent 的隐蔽越权？</h3>
          <p>传统 WAF 依赖 HTTP 文本特征与 SQL 注入规则，而自主智能体会直接调用本机命令、Git 客户端或私有 API 完成任务。Argus 在工具调用链路中建立可追溯的策略裁决与安全拦截。</p>
        </section>
        <section class="space-y-3 rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm">
          <div class="font-mono text-xs text-[#FF6900]">2026-09-07 · 密级设计</div>
          <h3 class="text-lg font-bold text-zinc-900">四级动态密级矩阵与近永久隔离区的实战考量</h3>
          <p>将研发环境的核心资产划分为 L1（公开）至 L4（绝密），并在网关层对高风险工具执行实施隔离存证，为企业安全团队提供完整的工单流转基础。</p>
        </section>
      </article>
    </main>
  </div>
    </main>
  </div>
</template>

<script setup>
import argusLogo from './assets/logo.svg'
import { nextTick, onMounted, ref } from 'vue'
import { ArrowLeft, Minus, Square, X } from 'lucide-vue-next'
import MimoCodeLanding from './components/MimoCodeLanding.vue'
import PersonalWorkspace from './components/PersonalWorkspace.vue'
import BentoCards from './components/BentoCards.vue'
import SecurityRules from './components/SecurityRules.vue'
import TelemetryView from './components/TelemetryView.vue'
import DaemonConsole from './components/DaemonConsole.vue'
import EnterpriseMini from './components/EnterpriseMini.vue'
import FirstRunSetup from './components/FirstRunSetup.vue'

const launchView = new URLSearchParams(window.location.search).get('view') || 'home'
let startView = launchView
try { if (launchView === 'home' && localStorage.getItem('argus.setup-done') !== '1') startView = 'setup' } catch { startView = 'setup' }
const currentView = ref(startView)
const isDebugConsole = launchView === 'debug'
try { if (launchView === 'home' && localStorage.getItem('argus.workspace-edition') === 'pro') { currentView.value = 'enterprise' } } catch {}
const activeWorkspaceTab = ref('dashboard')
const workspaceTabs = [
  { id: 'dashboard', label: '防御看板' },
  { id: 'rules', label: '密级规则' },
  { id: 'telemetry', label: '遥测隔离' },
  { id: 'console', label: '控制台' },
]

function handleNav(target) {
  currentView.value = target === 'blog' ? 'blog' : 'home'
}

function persistEdition(ed){ try{ localStorage.setItem('argus.workspace-edition', ed); }catch{} try{ fetch('http://127.0.0.1:8000/v1/local/edition', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({edition:ed})}); }catch{} }
async function backToPersonalDev(){
  // 先把 OpenClaw 模型还原回个人版，再退企业服务。
  try{ await window.electronAPI?.usePersonalModel?.() }catch{}
  try{ window.electronAPI && window.electronAPI.exitMiniMode && window.electronAPI.exitMiniMode(); }catch{}
  try{ await window.electronAPI?.stopEnterpriseService?.() }catch{}
  persistEdition('personal'); currentView.value = 'home';
}
function enterMiniMode(){ nextTick(() => { try { window.electronAPI && window.electronAPI.enterMiniMode && window.electronAPI.enterMiniMode({ width: 380, height: 480 }); } catch (e) {} }) }
onMounted(async () => {
  if (isDebugConsole) return
  try {
    const done = await window.electronAPI?.setupIsDone?.()
    if (done) {
      try { localStorage.setItem('argus.setup-done', '1') } catch {}
      if (currentView.value === 'setup') currentView.value = 'home'
    }
  } catch {}
  if (currentView.value === 'enterprise') { await enterEnterprise() }
  try {
    const r = await fetch('http://127.0.0.1:8000/v1/local/edition', {cache:'no-store'});
    if (r.ok) {
      const j = await r.json().catch(() => null);
      const ed = j && j.data && j.data.edition;
      if (ed === 'pro' && currentView.value !== 'enterprise') { await enterEnterprise(); }
      else if (ed === 'personal' && currentView.value === 'enterprise') { try{ if (localStorage.getItem('argus.workspace-edition') !== 'pro') currentView.value = 'home'; }catch{} }
    }
  } catch {}
})

function enterPersonal(){ try{ if (localStorage.getItem('argus.workspace-edition') === 'pro') return; }catch{} currentView.value = 'personal'; }
async function enterEnterprise() {
  persistEdition('pro');
  // Personal runs local daemons only; LLMGate(:8080) starts on demand here.
  const svc = await ensureEnterpriseService();
  // Follow-switch: route OpenClaw models via the enterprise gateway.
  try {
    const r = await window.electronAPI?.useEnterpriseModel?.();
    if (r && !r.ok) console.warn('[argus] 企业版模型切换未生效:', r.reason);
  } catch (e) { console.warn('[argus] 企业版模型切换调用失败'); }
  currentView.value = 'enterprise';
  enterMiniMode();
  return svc;
}
async function ensureEnterpriseService() {
  try { return await window.electronAPI?.startEnterpriseService?.() } catch { return { ok: false } }
}

async function handleProduct(type) {
  if (type === 'personal') {
    enterPersonal()
    return
  }

  if (type === 'enterprise') {
    // Enterprise shows only the small floating window: no big workspace, no OpenGuard page.
    await enterEnterprise()
  }
}

function minimizeWindow() {
  window.electronAPI?.minimize?.()
}

function maximizeWindow() {
  window.electronAPI?.maximize?.()
}

function closeWindow() {
  window.electronAPI?.close?.()
}
</script>


<style>
.desktop-shell {
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100vh;
  min-height: 0;
  overflow: hidden;
  background: #fafaf8;
}

.app-titlebar {
  position: relative;
  z-index: 100;
  display: flex;
  flex: 0 0 42px;
  align-items: center;
  justify-content: space-between;
  height: 42px;
  padding: 0 10px 0 14px;
  color: #3f3d39;
  background: rgba(255, 255, 255, 0.88);
  border-bottom: 1px solid rgba(39, 37, 30, 0.1);
  box-shadow: 0 3px 18px rgba(70, 55, 40, 0.04);
  backdrop-filter: blur(16px);
  -webkit-app-region: drag;
  user-select: none;
}

.app-titlebar-brand,
.app-titlebar-actions {
  display: flex;
  align-items: center;
}

.app-titlebar-brand {
  gap: 8px;
  min-width: 0;
}

.app-titlebar-logo {
  width: 22px;
  height: 22px;
  object-fit: contain;
}

.app-titlebar-name {
  color: #27251f;
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0.02em;
}

.app-titlebar-badge {
  padding: 3px 6px;
  color: #9b9791;
  font-size: 9px;
  line-height: 1;
  border: 1px solid #ebe7e2;
  border-radius: 5px;
  background: rgba(248, 247, 245, 0.9);
}

.app-titlebar-actions {
  gap: 3px;
  height: 100%;
  -webkit-app-region: no-drag;
}

.app-titlebar-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-right: 10px;
  color: #8d8984;
  font-size: 10px;
}

.app-titlebar-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #17a673;
  box-shadow: 0 0 0 3px rgba(23, 166, 115, 0.12);
}

.app-titlebar-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 27px;
  padding: 0;
  color: #8c8883;
  border: 0;
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  -webkit-app-region: no-drag;
}

.app-titlebar-button:hover {
  color: #393631;
  background: #f1efec;
}

.app-titlebar-button.app-titlebar-close:hover {
  color: #fff;
  background: #d95e55;
}

.desktop-content {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}

@media (max-width: 640px) {
  .app-titlebar-status,
  .app-titlebar-badge {
    display: none;
  }
}
.embedded-openguard {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: #f7f8fa;
}

.embedded-openguard__toolbar {
  display: flex;
  flex: 0 0 48px;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
  color: #52525b;
  background: rgba(255, 255, 255, 0.96);
  border-bottom: 1px solid #e4e4e7;
}

.embedded-openguard__back {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 7px 11px;
  color: #52525b;
  font-size: 13px;
  font-weight: 600;
  border: 1px solid #e4e4e7;
  border-radius: 9px;
  background: #fff;
  cursor: pointer;
  transition: color 160ms ease, background 160ms ease, border-color 160ms ease;
}

.embedded-openguard__back:hover {
  color: #18181b;
  border-color: #d4d4d8;
  background: #f4f4f5;
}

.embedded-openguard__label {
  color: #a1a1aa;
  font-size: 12px;
}

.embedded-openguard__frame {
  display: flex;
  flex: 1 1 auto;
  width: 100%;
  min-height: 0;
  border: 0;
  background: #f7f8fa;
}

.mini-window-host { width: 100%; height: 100%; min-height: 0; overflow: hidden; background: #ffffff; }
.mini-window-host .ent-mini { height: 100%; }
</style>


