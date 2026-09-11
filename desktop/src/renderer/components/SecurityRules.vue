<template>
  <div class="space-y-6 select-none">
    <!-- Top Bar: Four Security Levels Overview -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <div
        v-for="level in levels"
        :key="level.id"
        class="coder-card p-5 flex flex-col justify-between"
      >
        <div>
          <div class="flex items-center justify-between mb-2">
            <span :class="['text-xs px-2.5 py-0.5 rounded-full font-bold border', level.badgeClass]">
              {{ level.tag }}
            </span>
            <span class="text-xs text-zinc-400 font-mono">{{ level.id }}</span>
          </div>
          <h4 class="text-sm font-bold text-zinc-900">{{ level.name }}</h4>
          <p class="text-xs text-zinc-500 mt-1 leading-relaxed">{{ level.desc }}</p>
        </div>
        <div class="mt-4 pt-3 border-t border-zinc-100 flex items-center justify-between text-[11px] text-zinc-400">
          <span>覆盖资产</span>
          <span class="text-zinc-900 font-semibold">{{ level.count }} 条</span>
        </div>
      </div>
    </div>

    <!-- Rule Management Table Card -->
    <div class="coder-card p-6">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div>
          <h3 class="font-bold text-zinc-900 text-lg">零信任访问控制规则矩阵 (Access Control Matrix)</h3>
          <p class="text-xs text-zinc-500">对智能体（Agent）所调用的工具指令、文件路径及网络请求进行强约束</p>
        </div>
        <div class="flex items-center gap-3">
          <input
            v-model="searchQuery"
            placeholder="搜索规则、路径、动作..."
            class="px-3 py-1.5 rounded-xl bg-zinc-50 border border-zinc-200 text-xs text-zinc-900 placeholder-zinc-400 focus:outline-none focus:border-[#FF6900]"
          />
          <button @click="showAddModal = true" class="mimo-btn-primary text-xs cursor-pointer">
            <Plus class="w-3.5 h-3.5" />
            新建防护规则
          </button>
        </div>
      </div>

      <!-- Table -->
      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs text-zinc-700">
          <thead class="bg-zinc-50 text-zinc-500 font-semibold border-b border-zinc-200">
            <tr>
              <th class="p-3">规则名称</th>
              <th class="p-3">密级</th>
              <th class="p-3">匹配模式 (Path / Tool)</th>
              <th class="p-3">判定动作</th>
              <th class="p-3">状态</th>
              <th class="p-3 text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-zinc-100 font-mono">
            <tr v-for="rule in filteredRules" :key="rule.id" class="hover:bg-zinc-50/80 transition-colors">
              <td class="p-3 font-sans font-medium text-zinc-900">{{ rule.name }}</td>
              <td class="p-3">
                <span :class="['px-2 py-0.5 rounded text-[10px] font-bold border', rule.levelBadge]">
                  {{ rule.level }}
                </span>
              </td>
              <td class="p-3 text-cyan-700 font-semibold">{{ rule.pattern }}</td>
              <td class="p-3">
                <span :class="['px-2 py-0.5 rounded text-[10px] font-bold', rule.action === 'BLOCK' ? 'bg-red-50 text-red-600 border border-red-200' : 'bg-emerald-50 text-emerald-600 border border-emerald-200']">
                  {{ rule.action }}
                </span>
              </td>
              <td class="p-3">
                <span class="inline-flex items-center gap-1 text-emerald-600 font-sans">
                  <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                  生效中
                </span>
              </td>
              <td class="p-3 text-right space-x-2 font-sans">
                <button class="text-zinc-500 hover:text-zinc-900 cursor-pointer">编辑</button>
                <button @click="deleteRule(rule.id)" class="text-red-600 hover:underline cursor-pointer">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Add Rule Modal -->
    <div v-if="showAddModal" class="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4">
      <div class="bg-white rounded-2xl max-w-md w-full p-6 space-y-4 border border-zinc-200 shadow-2xl">
        <h4 class="font-bold text-zinc-900 text-base">添加零信任拦截策略</h4>
        <div>
          <label class="block text-xs text-zinc-600 font-medium mb-1">规则名称</label>
          <input v-model="newRule.name" class="w-full px-3 py-2 rounded-xl bg-zinc-50 border border-zinc-200 text-xs text-zinc-900 focus:outline-none focus:border-[#FF6900]" placeholder="例如：禁止读写SSH私钥" />
        </div>
        <div>
          <label class="block text-xs text-zinc-600 font-medium mb-1">安全密级</label>
          <select v-model="newRule.level" class="w-full px-3 py-2 rounded-xl bg-zinc-50 border border-zinc-200 text-xs text-zinc-900 focus:outline-none focus:border-[#FF6900]">
            <option value="L4 绝密">L4 绝密 (TopSecret)</option>
            <option value="L3 机密">L3 机密 (Secret)</option>
            <option value="L2 内部">L2 内部 (Internal)</option>
            <option value="L1 公开">L1 公开 (Public)</option>
          </select>
        </div>
        <div>
          <label class="block text-xs text-zinc-600 font-medium mb-1">资源或模式匹配 (Glob)</label>
          <input v-model="newRule.pattern" class="w-full px-3 py-2 rounded-xl bg-zinc-50 border border-zinc-200 text-xs text-zinc-900 focus:outline-none focus:border-[#FF6900]" placeholder="**/.env* 或 ~/.ssh/**" />
        </div>
        <div>
          <label class="block text-xs text-zinc-600 font-medium mb-1">拦截动作</label>
          <select v-model="newRule.action" class="w-full px-3 py-2 rounded-xl bg-zinc-50 border border-zinc-200 text-xs text-zinc-900 focus:outline-none focus:border-[#FF6900]">
            <option value="BLOCK">直接阻断 (BLOCK)</option>
            <option value="QUARANTINE">投递近永久隔离区 (QUARANTINE)</option>
            <option value="ALLOW">审计放行 (ALLOW)</option>
          </select>
        </div>
        <div class="flex justify-end gap-3 pt-4 border-t border-zinc-100">
          <button @click="showAddModal = false" class="mimo-btn-ghost text-xs cursor-pointer">取消</button>
          <button @click="addRule" class="mimo-btn-primary text-xs cursor-pointer">确认添加</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Plus } from 'lucide-vue-next'

const showAddModal = ref(false)
const searchQuery = ref('')

const levels = [
  { id: 'L1', name: '公开数据 (Public)', tag: 'L1 公开', desc: '开源代码、公开发布文档、无涉密资产', count: 142, badgeClass: 'bg-zinc-100 text-zinc-600 border-zinc-300' },
  { id: 'L2', name: '内部业务 (Internal)', tag: 'L2 内部', desc: '项目架构图、研发规范与普通配置文件', count: 86, badgeClass: 'bg-blue-50 text-blue-600 border-blue-200' },
  { id: 'L3', name: '机密核心 (Secret)', tag: 'L3 机密', desc: '.gitconfig、.env、API密钥与数据库配置', count: 28, badgeClass: 'bg-amber-50 text-amber-600 border-amber-200' },
  { id: 'L4', name: '绝密最高级 (TopSecret)', tag: 'L4 绝密', desc: 'SSH 私钥、支付商户证书、核心模型权重', count: 9, badgeClass: 'bg-red-50 text-red-600 border-red-200' },
]

const rules = ref([
  { id: 1, name: '拦截用户 Git 凭据外泄', level: 'L3 机密', levelBadge: 'bg-amber-50 text-amber-600 border-amber-200', pattern: '**/.gitconfig', action: 'BLOCK' },
  { id: 2, name: '保护本地环境密钥变量', level: 'L4 绝密', levelBadge: 'bg-red-50 text-red-600 border-red-200', pattern: '**/.env*', action: 'BLOCK' },
  { id: 3, name: '保护 SSH 密钥体系', level: 'L4 绝密', levelBadge: 'bg-red-50 text-red-600 border-red-200', pattern: '~/.ssh/**', action: 'BLOCK' },
  { id: 4, name: '拦截高危提权与删除命令', level: 'L4 绝密', levelBadge: 'bg-red-50 text-red-600 border-red-200', pattern: 'rm -rf /* | curl * | sh', action: 'BLOCK' },
  { id: 5, name: '项目普通源码只读访问', level: 'L1 公开', levelBadge: 'bg-zinc-100 text-zinc-600 border-zinc-200', pattern: 'src/**/*.js', action: 'ALLOW' }
])

const newRule = ref({
  name: '',
  level: 'L3 机密',
  pattern: '',
  action: 'BLOCK'
})

const filteredRules = computed(() => {
  if (!searchQuery.value) return rules.value
  const q = searchQuery.value.toLowerCase()
  return rules.value.filter(r =>
    r.name.toLowerCase().includes(q) ||
    r.pattern.toLowerCase().includes(q) ||
    r.level.toLowerCase().includes(q)
  )
})

function addRule() {
  if (!newRule.value.name || !newRule.value.pattern) {
    alert('请填写完整规则名称与匹配模式！')
    return
  }
  rules.value.push({
    id: Date.now(),
    name: newRule.value.name,
    level: newRule.value.level,
    levelBadge: newRule.value.level.includes('L4') ? 'bg-red-50 text-red-600 border-red-200' : 'bg-amber-50 text-amber-600 border-amber-200',
    pattern: newRule.value.pattern,
    action: newRule.value.action
  })
  showAddModal.value = false
  newRule.value = { name: '', level: 'L3 机密', pattern: '', action: 'BLOCK' }
}

function deleteRule(id) {
  rules.value = rules.value.filter(r => r.id !== id)
}
</script>
