<template>
  <div class="account-page">
    <section class="account-panel">
      <h1>设置新密码</h1>
      <el-alert
        v-if="error"
        class="account-alert"
        type="error"
        show-icon
        :closable="false"
        :title="error"
      />
      <el-form ref="formRef" :model="form" :rules="rules" @submit.prevent="submit">
        <el-form-item prop="newPassword">
          <el-input
            v-model="form.newPassword"
            size="large"
            type="password"
            show-password
            placeholder="新密码"
            autocomplete="new-password"
          />
        </el-form-item>
        <el-form-item prop="confirmPassword">
          <el-input
            v-model="form.confirmPassword"
            size="large"
            type="password"
            show-password
            placeholder="确认新密码"
            autocomplete="new-password"
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-button type="primary" size="large" class="account-submit" :loading="loading" @click="submit">
          更新密码
        </el-button>
      </el-form>
      <router-link class="account-link" to="/login">返回登录</router-link>
    </section>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { userApi } from '@/api'

const route = useRoute()
const router = useRouter()
const token = String(route.query.token || '')
const formRef = ref()
const loading = ref(false)
const error = ref(token ? '' : '重置链接无效或缺少 token。')

const form = reactive({
  newPassword: '',
  confirmPassword: '',
})

function validatePassword(_rule: unknown, value: string, callback: (error?: Error) => void) {
  if (!value || value.length < 8) return callback(new Error('密码至少 8 位'))
  if (!/[A-Z]/.test(value)) return callback(new Error('密码需要包含大写字母'))
  if (!/[a-z]/.test(value)) return callback(new Error('密码需要包含小写字母'))
  if (!/\d/.test(value)) return callback(new Error('密码需要包含数字'))
  callback()
}

function validateConfirm(_rule: unknown, value: string, callback: (error?: Error) => void) {
  if (value !== form.newPassword) return callback(new Error('两次输入的密码不一致'))
  callback()
}

const rules = {
  newPassword: [{ required: true, validator: validatePassword, trigger: 'blur' }],
  confirmPassword: [{ required: true, validator: validateConfirm, trigger: 'blur' }],
}

function resetErrorMessage(err: unknown) {
  const response = (err as { response?: { status?: number; data?: { detail?: unknown } } }).response
  if (response?.status === 400) return '重置链接无效、已过期，或新密码不符合要求。'
  if (response?.status === 429) return '请求过于频繁，请稍后再试。'
  return '暂时无法更新密码，请稍后再试。'
}

async function submit() {
  if (!formRef.value || loading.value || !token) return
  error.value = ''
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await userApi.resetPassword(token, form.newPassword)
    ElMessage.success('密码已更新，请重新登录。')
    router.replace('/login')
  } catch (err) {
    error.value = resetErrorMessage(err)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.account-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: #f4f7fb;
}

.account-panel {
  width: min(420px, 100%);
  padding: 28px;
  border: 1px solid #d8e0ed;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 16px 40px rgba(15, 23, 42, 0.08);
}

.account-panel h1 {
  margin: 0 0 20px;
  font-size: 24px;
  color: #0f172a;
}

.account-alert {
  margin-bottom: 16px;
}

.account-submit {
  width: 100%;
}

.account-link {
  display: inline-flex;
  margin-top: 18px;
  color: #2563eb;
  text-decoration: none;
}
</style>
