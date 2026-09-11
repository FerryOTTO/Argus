<template>
  <div class="users-page">
    <div class="page-header">
      <h2 class="page-title">用户管理</h2>
      <el-button type="primary" @click="openDialog()">
        <el-icon><Plus /></el-icon>添加用户
      </el-button>
    </div>

    <el-table :data="users" v-loading="loading" stripe>
      <el-table-column prop="username" label="用户名" />
      <el-table-column prop="email" label="邮箱" />
      <el-table-column prop="role" label="角色" width="120">
        <template #default="{ row }">
          <el-tag :type="row.role === 'admin' ? 'danger' : ''" size="small">
            {{ row.role === 'admin' ? '管理员' : '终端用户（仅身份归属）' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="security_level" label="安全等级" width="110">
        <template #default="{ row }">
          <el-tag size="small">{{ levelLabel(row.security_level) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'warning'" size="small">
            {{ row.is_active ? '正常' : '禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="180">
        <template #default="{ row }">
          {{ formatDate(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" size="small" link @click="openDialog(row)">编辑</el-button>
          <el-button type="warning" size="small" link @click="openPasswordDialog(row)">重置密码</el-button>
          <el-popconfirm title="确定删除此用户？" @confirm="handleDelete(row.id)">
            <template #reference>
              <el-button type="danger" size="small" link>删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <!-- User Dialog -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingUser ? '编辑用户' : '添加用户'"
      width="480px"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" :disabled="!!editingUser" placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item v-if="!editingUser" label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="请输入密码" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="form.email" placeholder="请输入邮箱" />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="form.role" placeholder="选择角色">
            <el-option label="管理员（可登录控制台）" value="admin" />
            <el-option label="终端用户（仅身份归属，不可登录）" value="user" />
          </el-select>
        </el-form-item>
        <el-form-item label="安全等级" prop="security_level">
          <el-select v-model="form.security_level" placeholder="选择安全等级">
            <el-option label="公开 public" value="public" />
            <el-option label="内部 internal" value="internal" />
            <el-option label="秘密 secret" value="secret" />
            <el-option label="绝密 top_secret" value="top_secret" />
          </el-select>
        </el-form-item>
        <el-form-item label="特例" prop="specials">
          <el-input v-model="form.specials" placeholder="如 *,!tool:write_file（逗号分隔，可空）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>

    <!-- Password Reset Dialog -->
    <el-dialog v-model="passwordDialogVisible" title="重置密码" width="400px">
      <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-width="80px">
        <el-form-item label="新密码" prop="new_password">
          <el-input v-model="pwdForm.new_password" type="password" show-password placeholder="请输入新密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleResetPassword">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance } from 'element-plus'
import { getUsers, createUser, updateUser, deleteUser, resetUserPassword } from '@/api/admin'

const loading = ref(false)
const submitting = ref(false)
const users = ref<any[]>([])
const dialogVisible = ref(false)
const passwordDialogVisible = ref(false)
const editingUser = ref<any>(null)
const formRef = ref<FormInstance>()
const pwdFormRef = ref<FormInstance>()

const form = reactive({
  username: '',
  password: '',
  email: '',
  role: 'user',
  security_level: 'internal',
  specials: '',
})

const LEVEL_LABELS: Record<string, string> = {
  public: '公开',
  internal: '内部',
  secret: '秘密',
  top_secret: '绝密',
}

function levelLabel(raw: any) {
  const key = String(raw || 'internal').toLowerCase()
  const name = LEVEL_LABELS[key] || LEVEL_LABELS.internal
  return `${name} ${key}`
}

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur', min: 6 }],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
}

const pwdForm = reactive({
  new_password: '',
})

const pwdRules = {
  new_password: [{ required: true, message: '请输入新密码', trigger: 'blur' }],
}

function formatDate(dateStr: string) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN')
}

async function fetchUsers() {
  loading.value = true
  try {
    const res = await getUsers()
    users.value = res.data.data || []
  } catch {
    ElMessage.error('获取用户列表失败')
  } finally {
    loading.value = false
  }
}

function openDialog(user?: any) {
  editingUser.value = user || null
  if (user) {
    Object.assign(form, {
      username: user.username,
      password: '',
      email: user.email || '',
      role: user.role,
      security_level: user.security_level || 'internal',
      specials: user.specials || '',
    })
  } else {
    Object.assign(form, {
      username: '',
      password: '',
      email: '',
      role: 'user',
      security_level: 'internal',
      specials: '',
    })
  }
  dialogVisible.value = true
}

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    if (editingUser.value) {
      await updateUser(editingUser.value.id, {
        email: form.email,
        role: form.role,
        security_level: form.security_level,
        specials: form.specials,
      })
      ElMessage.success('更新成功')
    } else {
      await createUser({ ...form })
      ElMessage.success('创建成功')
    }
    dialogVisible.value = false
    fetchUsers()
  } catch {
    ElMessage.error('操作失败')
  } finally {
    submitting.value = false
  }
}

async function handleDelete(id: number) {
  try {
    await deleteUser(id)
    ElMessage.success('删除成功')
    fetchUsers()
  } catch {
    ElMessage.error('删除失败')
  }
}

function openPasswordDialog(user: any) {
  editingUser.value = user
  pwdForm.new_password = ''
  passwordDialogVisible.value = true
}

async function handleResetPassword() {
  const valid = await pwdFormRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    await resetUserPassword(editingUser.value.id, pwdForm.new_password)
    ElMessage.success('密码重置成功')
    passwordDialogVisible.value = false
  } catch {
    ElMessage.error('密码重置失败')
  } finally {
    submitting.value = false
  }
}

onMounted(fetchUsers)
</script>

<style scoped lang="scss">
.users-page {
  padding: 0;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-title {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}
</style>
