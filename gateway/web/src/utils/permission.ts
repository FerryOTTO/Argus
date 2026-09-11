import { useAuthStore } from '@/stores/auth'

export function isAdmin(): boolean {
  const authStore = useAuthStore()
  return authStore.user?.role === 'admin'
}

export function canAccessAdmin(): boolean {
  return isAdmin()
}

export function canAccessUser(): boolean {
  const authStore = useAuthStore()
  return authStore.isLoggedIn
}
