import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/api/client'

interface User {
  id: number
  username: string
  email: string
  role: string
  must_change_password?: boolean
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>('')
  const user = ref<User | null>(null)
  const mustChangePassword = ref<boolean>(false)

  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => user.value?.role === 'admin')

  function loadFromStorage() {
    const savedToken = localStorage.getItem('llmgate_token')
    const savedUser = localStorage.getItem('llmgate_user')
    const savedMustChange = localStorage.getItem('llmgate_must_change_password')
    if (savedToken) {
      token.value = savedToken
    }
    if (savedUser) {
      try {
        user.value = JSON.parse(savedUser)
      } catch {
        user.value = null
      }
    }
    if (savedMustChange === 'true') {
      mustChangePassword.value = true
    }
  }

  async function login(username: string, password: string) {
    const res = await api.post('/api/auth/login', { username, password })
    token.value = res.data.token
    user.value = res.data.user
    mustChangePassword.value = res.data.user.must_change_password === true
    localStorage.setItem('llmgate_token', token.value)
    localStorage.setItem('llmgate_user', JSON.stringify(user.value))
    if (mustChangePassword.value) {
      localStorage.setItem('llmgate_must_change_password', 'true')
    }
  }

  function clearMustChangePassword() {
    mustChangePassword.value = false
    localStorage.removeItem('llmgate_must_change_password')
    if (user.value) {
      user.value.must_change_password = false
      localStorage.setItem('llmgate_user', JSON.stringify(user.value))
    }
  }

  function logout() {
    token.value = ''
    user.value = null
    mustChangePassword.value = false
    localStorage.removeItem('llmgate_token')
    localStorage.removeItem('llmgate_user')
    localStorage.removeItem('llmgate_must_change_password')
  }

  async function refreshToken() {
    try {
      const res = await api.post('/api/auth/refresh')
      token.value = res.data.token
      localStorage.setItem('llmgate_token', token.value)
    } catch {
      logout()
    }
  }

  return {
    token,
    user,
    mustChangePassword,
    isLoggedIn,
    isAdmin,
    loadFromStorage,
    login,
    logout,
    refreshToken,
    clearMustChangePassword,
  }
})
