<template>
  <div class="account-page">
    <section class="account-panel">
      <h1>找回密码</h1>
      <el-alert
        v-if="message"
        class="account-alert"
        type="success"
        show-icon
        :closable="false"
        :title="message"
      />
      <el-alert
        v-if="error"
        class="account-alert"
        type="error"
        show-icon
        :closable="false"
        :title="error"
      />
      <el-form ref="formRef" :model="form" :rules="rules" @submit.prevent="submit">
        <el-form-item prop="identifier">
          <el-input
            v-model="form.identifier"
            size="large"
            placeholder="用户名或邮箱"
            autocomplete="username"
            clearable
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-button type="primary" size="large" class="account-submit" :loading="loading" @click="submit">
          发送重置邮件
        </el-button>
      </el-form>
      <router-link class="account-link" to="/login">返回登录</router-link>
    </section>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { userApi } from '@/api'

const formRef = ref()
const loading = ref(false)
const message = ref('')
const error = ref('')

const form = reactive({
  identifier: '',
})

const rules = {
  identifier: [{ required: true, min: 3, message: '请输入用户名或邮箱', trigger: 'blur' }],
}

function resetErrorMessage(err: unknown) {
  const response = (err as { response?: { status?: number; data?: { detail?: unknown } } }).response
  if (response?.status === 503) return '密码重置邮件服务未配置，请联系管理员。'
  if (response?.status === 429) return '请求过于频繁，请稍后再试。'
  return '暂时无法发送重置邮件，请稍后再试。'
}

async function submit() {
  if (!formRef.value || loading.value) return
  error.value = ''
  message.value = ''
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await userApi.requestPasswordReset(form.identifier.trim())
    message.value = '如果账号存在，重置邮件会发送到绑定邮箱。'
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
