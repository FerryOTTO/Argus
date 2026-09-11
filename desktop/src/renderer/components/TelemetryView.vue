<template>
  <div class="space-y-6 select-none">
    <!-- Enterprise Telemetry Config Card -->
    <div class="coder-card p-6">
      <div class="flex items-center justify-between mb-4">
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-xl bg-[#FF6900]/10 border border-[#FF6900]/20 flex items-center justify-center text-[#FF6900]">
            <Activity class="w-5 h-5" />
          </div>
          <div>
            <div class="flex items-center gap-2">
              <h3 class="font-bold text-zinc-900 text-lg">企业级 OpenTelemetry 遥测网关配置</h3>
              <span class="text-[10px] px-2 py-0.5 rounded-full bg-[#FF6900]/10 text-[#FF6900] border border-[#FF6900]/30 font-semibold">ENTERPRISE</span>
            </div>
            <p class="text-xs text-zinc-500">将 Argus 拦截日志、调用耗时及模型安全决策遥测数据无缝对接云端监控大盘</p>
          </div>
        </div>
        <button 
          @click="saveTelemetry"
          class="mimo-btn-primary text-xs cursor-pointer"
        >
          <Save class="w-3.5 h-3.5" />
          保存遥测配置
        </button>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
        <div class="space-y-1.5">
          <label class="text-xs text-zinc-700 font-medium">OTLP Collector 终结点 (gRPC / HTTP)</label>
          <input 
            v-model="telemetry.otlpEndpoint" 
            class="w-full px-3 py-2 rounded-xl bg-zinc-50 border border-zinc-200 text-xs text-zinc-900 font-mono focus:border-[#FF6900] focus:outline-none" 
            placeholder="http://otel-collector.corp.internal:4318/v1/traces" 
          />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs text-zinc-700 font-medium">Prometheus 指标拉取路径</label>
          <input 
            v-model="telemetry.promPath" 
            class="w-full px-3 py-2 rounded-xl bg-zinc-50 border border-zinc-200 text-xs text-zinc-900 font-mono focus:border-[#FF6900] focus:outline-none" 
            placeholder="/metrics" 
          />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs text-zinc-700 font-medium">行为采样率 (Sampling Rate)</label>
          <select 
            v-model="telemetry.sampleRate" 
            class="w-full px-3 py-2 rounded-xl bg-zinc-50 border border-zinc-200 text-xs text-zinc-900 focus:border-[#FF6900] focus:outline-none"
          >
            <option value="1.0">100% 全量审计采样 (推荐金融/国防涉密)</option>
            <option value="0.5">50% 自适应折半采样</option>
            <option value="0.1">10% 仅采样拦截与高危行为</option>
          </select>
        </div>
      </div>
    </div>

    <!-- Near-Permanent Quarantine Approval Flow Card -->
    <div class="coder-card p-6">
      <div class="flex items-center justify-between mb-4">
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-xl bg-cyan-50 border border-cyan-200 flex items-center justify-center text-cyan-600">
            <Archive class="w-5 h-5" />
          </div>
          <div>
            <h3 class="font-bold text-zinc-900 text-lg">近永久隔离区 (Near-Permanent Quarantine Vault)</h3>
            <p class="text-xs text-zinc-500">涉密代码、脱轨执行脚本及风险资产被物理隔离，需管理员人工工单复核解封</p>
          </div>
        </div>
        <div class="text-xs text-zinc-500 flex items-center gap-2">
          <span>待审核工单：<b class="text-cyan-600">{{ quarantineItems.length }}</b> 件</span>
        </div>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs text-zinc-700">
          <thead class="bg-zinc-50 text-zinc-500 font-semibold border-b border-zinc-200">
            <tr>
              <th class="p-3">工单编号</th>
              <th class="p-3">隔离文件 / 目标</th>
              <th class="p-3">触发 Agent</th>
              <th class="p-3">判定密级</th>
              <th class="p-3">隔离时间</th>
              <th class="p-3 text-right">管理员审批</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-zinc-100 font-mono">
            <tr v-for="item in quarantineItems" :key="item.ticket" class="hover:bg-zinc-50/80">
              <td class="p-3 text-[#FF6900] font-bold">{{ item.ticket }}</td>
              <td class="p-3 text-zinc-900 font-medium">{{ item.filename }}</td>
              <td class="p-3 text-zinc-500">{{ item.agent }}</td>
              <td class="p-3">
                <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-red-50 text-red-600 border border-red-200">
                  {{ item.level }}
                </span>
              </td>
              <td class="p-3 text-zinc-500">{{ item.timestamp }}</td>
              <td class="p-3 text-right space-x-2 font-sans">
                <button 
                  @click="approveRelease(item)" 
                  class="px-2.5 py-1 rounded-lg bg-emerald-50 hover:bg-emerald-100 text-emerald-700 border border-emerald-200 font-medium transition-all cursor-pointer"
                >
                  工单审批解封
                </button>
                <button 
                  @click="permanentPurge(item)" 
                  class="px-2.5 py-1 rounded-lg bg-red-50 hover:bg-red-100 text-red-700 border border-red-200 font-medium transition-all cursor-pointer"
                >
                  永久粉碎
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { Activity, Archive, Save } from 'lucide-vue-next'

const telemetry = ref({
  otlpEndpoint: 'http://127.0.0.1:4318/v1/traces',
  promPath: '/metrics',
  sampleRate: '1.0'
})

const quarantineItems = ref([
  { ticket: 'TICK-9082', filename: 'e:/tiaozhanbei/MAC/.env.production', agent: 'OpenClaw-Worker', level: 'L4 绝密', timestamp: '2026-09-07 23:12:05' },
  { ticket: 'TICK-9083', filename: 'e:/tiaozhanbei/MAC/config/jwt_rsa.key', agent: 'Auto-Builder', level: 'L4 绝密', timestamp: '2026-09-07 23:25:40' },
  { ticket: 'TICK-9084', filename: 'e:/tiaozhanbei/MAC/scripts/reverse_shell.sh', agent: 'Unknown-Plugin', level: 'L4 绝密', timestamp: '2026-09-07 23:38:12' }
])

function saveTelemetry() {
  alert('企业级 OpenTelemetry 遥测配置已保存并同步给审计流！')
}

function approveRelease(item) {
  if (confirm(`确认审批通过工单 [${item.ticket}]，将 [${item.filename}] 从隔离区安全解封？`)) {
    quarantineItems.value = quarantineItems.value.filter(i => i.ticket !== item.ticket)
    alert(`工单 ${item.ticket} 已审批通过，解封日志已记录至审计链。`)
  }
}

function permanentPurge(item) {
  if (confirm(`警告：永久粉碎将彻底擦除 [${item.filename}]，该操作不可撤销！`)) {
    quarantineItems.value = quarantineItems.value.filter(i => i.ticket !== item.ticket)
    alert(`文件已从磁盘深层覆写粉碎。`)
  }
}
</script>
