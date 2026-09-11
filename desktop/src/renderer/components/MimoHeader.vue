<template>
  <header class="h-14 bg-[#0B0E14]/90 backdrop-blur-md border-b border-white/10 flex items-center justify-between px-4 select-none drag-region z-50">
    <!-- Left: Brand Logo & Title -->
    <div class="flex items-center gap-3 no-drag">
      <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-[#FF6900] to-[#FF8533] p-[1.5px] shadow-[0_0_12px_rgba(255,105,0,0.35)] flex items-center justify-center">
        <div class="w-full h-full bg-[#121824] rounded-[6.5px] flex items-center justify-center">
          <ShieldAlert class="w-4 h-4 text-[#FF6900]" />
        </div>
      </div>
      <div class="flex items-center gap-2">
        <span class="font-bold text-white tracking-wide text-sm">Argus</span>
        <span class="text-xs px-2 py-0.5 rounded-full bg-[#FF6900]/15 text-[#FF6900] border border-[#FF6900]/30 font-medium">MiMo v2.1</span>
      </div>
      <!-- Status Badge -->
      <div class="ml-3 hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs">
        <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
        <span>主动防护中</span>
      </div>
    </div>

    <!-- Center: Navigation Tabs -->
    <nav class="hidden md:flex items-center gap-1 no-drag bg-[#121824]/60 p-1 rounded-xl border border-white/5">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        @click="$emit('update:activeTab', tab.id)"
        :class="[
          'flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all duration-200',
          activeTab === tab.id
            ? 'bg-[#FF6900] text-white shadow-[0_2px_12px_rgba(255,105,0,0.35)]'
            : 'text-slate-400 hover:text-white hover:bg-white/5'
        ]"
      >
        <component :is="tab.icon" class="w-3.5 h-3.5" />
        <span>{{ tab.label }}</span>
      </button>
    </nav>

    <!-- Right: Quick Status & Window Controls -->
    <div class="flex items-center gap-2 no-drag">
      <!-- Edition Toggle Indicator -->
      <div class="flex items-center bg-[#121824] border border-white/10 rounded-lg p-0.5 text-xs text-slate-400">
        <button 
          @click="$emit('update:edition', 'personal')"
          :class="['px-2.5 py-1 rounded-md transition-all', edition === 'personal' ? 'bg-white/10 text-white font-medium' : 'hover:text-slate-200']">
          个人版
        </button>
        <button 
          @click="$emit('update:edition', 'enterprise')"
          :class="['px-2.5 py-1 rounded-md transition-all', edition === 'enterprise' ? 'bg-[#FF6900]/20 text-[#FF6900] border border-[#FF6900]/30 font-medium' : 'hover:text-slate-200']">
          企业版
        </button>
      </div>

      <!-- Frameless Window Controls -->
      <div class="flex items-center ml-2 border-l border-white/10 pl-2">
        <button
          @click="minimizeWindow"
          title="最小化"
          class="w-7 h-7 flex items-center justify-center rounded-md text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
        >
          <Minus class="w-3.5 h-3.5" />
        </button>
        <button
          @click="maximizeWindow"
          title="最大化"
          class="w-7 h-7 flex items-center justify-center rounded-md text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
        >
          <Square class="w-3.5 h-3.5" />
        </button>
        <button
          @click="closeWindow"
          title="关闭"
          class="w-7 h-7 flex items-center justify-center rounded-md text-slate-400 hover:text-white hover:bg-red-500/80 transition-colors"
        >
          <X class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  </header>
</template>

<script setup>
import { 
  ShieldAlert, 
  ShieldCheck, 
  KeyRound, 
  Activity, 
  Terminal, 
  Minus, 
  Square, 
  X 
} from 'lucide-vue-next'

const props = defineProps({
  activeTab: {
    type: String,
    default: 'overview'
  },
  edition: {
    type: String,
    default: 'personal'
  }
})

const emit = defineEmits(['update:activeTab', 'update:edition'])

const tabs = [
  { id: 'overview', label: '极简防护', icon: ShieldCheck },
  { id: 'rules', label: '密级与规则', icon: KeyRound },
  { id: 'telemetry', label: '企业遥测与隔离区', icon: Activity },
  { id: 'console', label: '后台控制台', icon: Terminal },
]

function minimizeWindow() {
  if (window.electronAPI) {
    window.electronAPI.minimize()
  }
}

function maximizeWindow() {
  if (window.electronAPI) {
    window.electronAPI.maximize()
  }
}

function closeWindow() {
  if (window.electronAPI) {
    window.electronAPI.close()
  }
}
</script>

<style scoped>
.drag-region {
  -webkit-app-region: drag;
}
.no-drag {
  -webkit-app-region: no-drag;
}
</style>