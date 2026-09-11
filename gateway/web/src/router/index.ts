import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AdminLayout from '@/components/layout/AdminLayout.vue'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/admin',
    component: AdminLayout,
    meta: { requiresAdmin: true },
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/admin/DashboardView.vue'),
      },
      {
        path: 'providers',
        name: 'Providers',
        component: () => import('@/views/admin/ProvidersView.vue'),
      },
      {
        path: 'users',
        name: 'Users',
        component: () => import('@/views/admin/UsersView.vue'),
      },
      {
        path: 'quotas',
        name: 'Quotas',
        component: () => import('@/views/admin/QuotasView.vue'),
      },
      {
        path: 'audit',
        name: 'Audit',
        component: () => import('@/views/admin/AuditView.vue'),
      },
      {
        path: 'terminals',
        name: 'Terminals',
        component: () => import('@/views/admin/TerminalsView.vue'),
      },
      {
        path: 'extensions',
        name: 'Extensions',
        component: () => import('@/views/admin/ExtensionsView.vue'),
      },
      {
        path: 'apikeys',
        name: 'AdminApiKeys',
        component: () => import('@/views/admin/ApiKeysView.vue'),
      },
      {
        path: 'settings',
        name: 'SystemSettings',
        component: () => import('@/views/admin/SystemSettingsView.vue'),
      },
      {
        path: 'change-password',
        name: 'ChangePassword',
        component: () => import('@/views/admin/ChangePasswordView.vue'),
      },
    ],
  },
  {
    path: '/',
    redirect: '/admin/dashboard',
  },
  // 未知路径兜底：普通用户界面已下线，一律回仪表盘（守卫会再拦截登录态）
  {
    path: '/:pathMatch(.*)*',
    redirect: '/admin/dashboard',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  if (to.meta.public) {
    next()
    return
  }

  const authStore = useAuthStore()
  if (!authStore.isLoggedIn) {
    next('/login')
    return
  }

  // Force password change if required (except for the change-password page itself)
  if (authStore.mustChangePassword && to.path !== '/admin/change-password') {
    next('/admin/change-password')
    return
  }

  // 系统仅向管理员开放控制台：非 admin 一律登出回登录页
  if (to.meta.requiresAdmin && !authStore.isAdmin) {
    authStore.logout()
    next('/login')
    return
  }

  next()
})

export default router
