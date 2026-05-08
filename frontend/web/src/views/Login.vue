<template>
  <div class="login-page">
    <el-card class="login-card" shadow="never">
      <template #header>
        <h2>{{ isLogin ? '登录' : '注册' }}</h2>
      </template>

      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item v-if="!isLogin" label="邮箱" prop="email">
          <el-input v-model="form.email" placeholder="请输入邮箱" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="请输入密码" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleSubmit" :loading="loading" class="submit-btn">
            {{ isLogin ? '登录' : '注册' }}
          </el-button>
        </el-form-item>
      </el-form>

      <div class="toggle">
        <el-link type="primary" @click="isLogin = !isLogin">
          {{ isLogin ? '没有账号？立即注册' : '已有账号？立即登录' }}
        </el-link>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { userApi } from '@/api'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const isLogin = ref(true)
const loading = ref(false)
const formRef = ref()

const form = reactive({
  username: '',
  email: '',
  password: '',
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  email: [{ required: true, message: '请输入邮箱', trigger: 'blur' }],
  password: [{ required: true, min: 8, message: '密码至少8位', trigger: 'blur' }],
}

function getSafeRedirect() {
  const raw = route.query.redirect
  const redirect = Array.isArray(raw) ? raw[0] : raw
  if (!redirect || !redirect.startsWith('/') || redirect.startsWith('//')) return '/'

  try {
    const url = new URL(redirect, window.location.origin)
    if (url.origin !== window.location.origin) return '/'
    return `${url.pathname}${url.search}${url.hash}` || '/'
  } catch {
    return '/'
  }
}

async function handleSubmit() {
  if (!formRef.value) return
  await formRef.value.validate()
  loading.value = true
  try {
    if (isLogin.value) {
      await userStore.login(form.username, form.password)
      ElMessage.success('登录成功')
      router.push(getSafeRedirect())
    } else {
      await userApi.register(form.username, form.email, form.password)
      ElMessage.success('注册成功，请登录')
      isLogin.value = true
    }
  } catch (error) {
    const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    const msg = Array.isArray(detail) ? detail.map((d) => (d as { msg?: string }).msg).filter(Boolean).join('; ') : (detail || '操作失败')
    ElMessage.error(msg as string)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: calc(100vh - 200px);
}
.login-card {
  width: 400px;
}
.login-card h2 {
  text-align: center;
  margin: 0;
}
.submit-btn {
  width: 100%;
}

.toggle {
  text-align: center;
  margin-top: 16px;
}
</style>
