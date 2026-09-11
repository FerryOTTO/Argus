<template>
  <el-container class="admin-layout">
    <el-aside width="220px" class="sidebar">
      <div class="logo">
        <el-icon :size="24"><Connection /></el-icon>
        <span>Clawguard 控制台</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        router
        class="sidebar-menu"
        background-color="#1d1e2c"
        text-color="#a0a4b8"
        active-text-color="#409eff"
      >
        <el-menu-item index="/admin/dashboard">
          <el-icon><DataBoard /></el-icon>
          <span>仪表盘</span>
        </el-menu-item>
        <el-menu-item index="/admin/providers">
          <el-icon><Cloudy /></el-icon>
          <span>供应商管理</span>
        </el-menu-item>
        <el-menu-item index="/admin/users">
          <el-icon><User /></el-icon>
          <span>用户管理</span>
        </el-menu-item>
        <el-menu-item index="/admin/quotas">
          <el-icon><Coin /></el-icon>
          <span>配额管理</span>
        </el-menu-item>
        <el-menu-item index="/admin/audit">
          <el-icon><Document /></el-icon>
          <span>审计日志</span>
        </el-menu-item>
        <el-menu-item index="/admin/terminals">
          <el-icon><Monitor /></el-icon>
          <span>终端管理</span>
        </el-menu-item>
        <el-menu-item index="/admin/extensions">
          <el-icon><Box /></el-icon>
          <span>扩展管理</span>
          <el-badge
            v-if="pendingApprovals > 0"
            :value="pendingApprovals"
            :max="99"
            class="menu-badge"
          />
        </el-menu-item>
        <el-menu-item index="/admin/apikeys">
          <el-icon><Key /></el-icon>
          <span>密钥管理</span>
        </el-menu-item>
        <el-menu-item index="/admin/settings">
          <el-icon><Setting /></el-icon>
          <span>系统设置</span>
        </el-menu-item>
        <el-menu-item index="/admin/change-password">
          <el-icon><Lock /></el-icon>
          <span>修改密码</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <div class="header-right">
          <el-dropdown @command="handleCommand">
            <span class="user-info">
              <el-icon><Avatar /></el-icon>
              {{ authStore.user?.username }}
              <el-icon class="el-icon--right"><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main class="main-content">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { getExtensionApprovalStats } from '@/api/admin'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const activeMenu = computed(() => route.path)

// 扩展管理侧栏待审批徽标：60s 轮询一次（轻量接口）
const pendingApprovals = ref(0)
let statsTimer: number | undefined

async function fetchApprovalStats() {
  try {
    const res = await getExtensionApprovalStats()
    pendingApprovals.value = Number(res.data?.data?.pending) || 0
  } catch {
    /* 轮询失败静默，下次重试 */
  }
}

function handleCommand(command: string) {
  if (command === 'logout') {
    authStore.logout()
    router.push('/login')
  }
}

onMounted(() => {
  fetchApprovalStats()
  statsTimer = window.setInterval(fetchApprovalStats, 60000)
})

onUnmounted(() => {
  if (statsTimer) window.clearInterval(statsTimer)
})
</script>

<style scoped lang="scss">
.admin-layout {
  height: 100vh;
}

.sidebar {
  background-color: #1d1e2c;
  overflow: hidden;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #fff;
  font-size: 18px;
  font-weight: 700;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.sidebar-menu {
  border-right: none;
}

.menu-badge {
  margin-left: auto;
  margin-right: 8px;
}

.header {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  background: #fff;
  border-bottom: 1px solid #e8e8e8;
  padding: 0 20px;
}

.header-right {
  display: flex;
  align-items: center;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font-size: 14px;
  color: #333;
}

.main-content {
  background: #f5f7fa;
  overflow-y: auto;
}
</style>
