<template>
  <div class="admin-models">
    <div class="header">
      <h1>AI 模型管理</h1>
      <button @click="showFormDialog = true" class="btn-primary">+ 新增模型</button>
    </div>

    <div v-if="loading" class="loading">加载中...</div>

    <table v-else class="models-table">
      <thead>
        <tr>
          <th>名称</th>
          <th>供应商</th>
          <th>模型 ID</th>
          <th>状态</th>
          <th>允许角色</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="model in models" :key="model.id">
          <td>{{ model.name }}</td>
          <td>
            <span class="provider-badge" :class="model.provider">{{ model.provider }}</span>
          </td>
          <td class="model-id">{{ model.model_id }}</td>
          <td>
            <span :class="model.is_active ? 'status-active' : 'status-inactive'">
              {{ model.is_active ? '启用' : '禁用' }}
            </span>
          </td>
          <td>{{ model.allowed_roles }}</td>
          <td>
            <button @click="openEditDialog(model)" class="btn-small">编辑</button>
            <button @click="toggleModel(model)" class="btn-small">
              {{ model.is_active ? '禁用' : '启用' }}
            </button>
            <button @click="testModel(model)" class="btn-small">测试</button>
            <button @click="deleteModel(model)" class="btn-small btn-danger">删除</button>
          </td>
        </tr>
        <tr v-if="!models.length">
          <td colspan="6" class="no-data">暂无模型，请点击上方按钮添加</td>
        </tr>
      </tbody>
    </table>

    <!-- 添加/编辑弹窗 -->
    <div v-if="showFormDialog" class="dialog-overlay" @click.self="closeFormDialog">
      <div class="dialog">
        <h2>{{ editingModel ? '编辑模型' : '新增模型' }}</h2>
        <form @submit.prevent="submitForm">
          <div class="form-group">
            <label>模型名称</label>
            <input v-model="form.name" required placeholder="如: Claude 3.5 Sonnet" />
          </div>
          <div class="form-group">
            <label>供应商</label>
            <select v-model="form.provider" required>
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="deepseek">DeepSeek</option>
              <option value="custom">Custom</option>
            </select>
          </div>
          <div class="form-group">
            <label>模型 ID</label>
            <input v-model="form.model_id" required placeholder="如: gpt-4o-mini" />
          </div>
          <div class="form-group">
            <label>API Key</label>
            <input v-model="form.api_key" type="password" :placeholder="editingModel ? '留空则不修改' : 'sk-...'" :required="!editingModel" />
          </div>
          <div class="form-group">
            <label>API Base URL (可选)</label>
            <input v-model="form.api_base_url" placeholder="如需代理或自定义端点" />
          </div>
          <div class="form-group">
            <label>描述</label>
            <textarea v-model="form.description" placeholder="模型描述..."></textarea>
          </div>
          <div class="form-group">
            <label>允许角色</label>
            <input v-model="form.allowed_roles" placeholder="free,premium,admin" />
          </div>
          <div class="form-actions">
            <button type="button" @click="closeFormDialog" class="btn-secondary">取消</button>
            <button type="submit" class="btn-primary">{{ editingModel ? '保存' : '创建' }}</button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { adminApi } from '@/api'
import { ElMessage, ElMessageBox } from 'element-plus'

type ModelProvider = 'openai' | 'anthropic' | 'deepseek' | 'custom'

type ModelFormPayload = Omit<ModelForm, 'provider'> & { provider: string }
type ModelFormKey = keyof ModelFormPayload

type ModelUpdatePayload = Partial<ModelFormPayload>

interface AIModel {
  id: number
  name: string
  provider: ModelProvider | string
  model_id: string
  is_active: boolean
  allowed_roles?: string
  api_base_url?: string
  description?: string
}

interface ModelForm {
  name: string
  provider: string
  model_id: string
  api_key: string
  api_base_url: string
  description: string
  allowed_roles: string
}

interface ModelTestResult {
  status: string
  message?: string
}

const loading = ref(true)
const models = ref<AIModel[]>([])
const showFormDialog = ref(false)
const editingModel = ref<AIModel | null>(null)

function emptyForm(): ModelForm {
  return {
    name: '',
    provider: 'openai',
    model_id: '',
    api_key: '',
    api_base_url: '',
    description: '',
    allowed_roles: 'free,premium,admin',
  }
}

const form = ref(emptyForm())

async function loadModels() {
  try {
    loading.value = true
    models.value = await adminApi.getModels<AIModel[]>()
  } catch (e) {
    ElMessage.error('加载模型失败')
  } finally {
    loading.value = false
  }
}

function openEditDialog(model: AIModel) {
  editingModel.value = model
  form.value = {
    name: model.name,
    provider: model.provider,
    model_id: model.model_id,
    api_key: '',
    api_base_url: model.api_base_url || '',
    description: model.description || '',
    allowed_roles: model.allowed_roles || 'free,premium,admin',
  }
  showFormDialog.value = true
}

function closeFormDialog() {
  showFormDialog.value = false
  editingModel.value = null
  form.value = emptyForm()
}

async function submitForm() {
  try {
    if (editingModel.value) {
      // 编辑模式: 只发送有变化的字段
      const payload: ModelUpdatePayload = {}
      const fields: ModelFormKey[] = ['name', 'provider', 'model_id', 'api_base_url', 'description', 'allowed_roles']
      for (const key of fields) {
        if (form.value[key]) {
          payload[key] = form.value[key]
        }
      }
      if (form.value.api_key) {
        payload['api_key'] = form.value.api_key
      }
      await adminApi.updateModel(editingModel.value.id, payload)
      ElMessage.success('模型更新成功')
    } else {
      await adminApi.createModel(form.value)
      ElMessage.success('模型创建成功')
    }
    closeFormDialog()
    loadModels()
  } catch (e) {
    ElMessage.error(editingModel.value ? '更新失败' : '创建失败')
  }
}

async function toggleModel(model: AIModel) {
  try {
    await adminApi.toggleModel(model.id)
    ElMessage.success(model.is_active ? '已禁用' : '已启用')
    loadModels()
  } catch (e) {
    ElMessage.error('操作失败')
  }
}

async function testModel(model: AIModel) {
  try {
    ElMessage.info('正在测试连接...')
    const result = await adminApi.testModel<ModelTestResult>(model.id)
    if (result.status === 'success') {
      ElMessage.success('连接成功')
    } else {
      ElMessage.error('连接失败: ' + result.message)
    }
  } catch (e) {
    ElMessage.error('测试失败')
  }
}

async function deleteModel(model: AIModel) {
  try {
    await ElMessageBox.confirm(`确定删除模型 "${model.name}" 吗?`, '确认删除', { type: 'warning' })
    await adminApi.deleteModel(model.id)
    ElMessage.success('删除成功')
    loadModels()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error('删除失败')
  }
}

onMounted(loadModels)
</script>

<style scoped>
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

h1 {
  margin: 0;
}

.loading, .no-data {
  text-align: center;
  padding: 40px;
  color: #999;
}

.models-table {
  width: 100%;
  background: #fff;
  border-radius: 8px;
  border-collapse: collapse;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.models-table th,
.models-table td {
  padding: 12px 15px;
  text-align: left;
  border-bottom: 1px solid #eee;
}

.models-table th {
  background: #f9f9f9;
  font-weight: 600;
  color: #333;
}

.provider-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.provider-badge.openai { background: #10a37f; color: #fff; }
.provider-badge.anthropic { background: #d97706; color: #fff; }
.provider-badge.deepseek { background: #6366f1; color: #fff; }
.provider-badge.custom { background: #6b7280; color: #fff; }

.model-id {
  font-family: monospace;
  font-size: 12px;
  color: #666;
}

.status-active { color: #10a37f; font-weight: 500; }
.status-inactive { color: #dc2626; font-weight: 500; }

.btn-small {
  padding: 4px 8px;
  margin-right: 5px;
  border: 1px solid #ddd;
  background: #fff;
  border-radius: 4px;
  cursor: pointer;
}

.btn-danger {
  color: #dc2626;
  border-color: #dc2626;
}

.btn-danger:hover {
  background: #fef2f2;
}

.btn-primary {
  padding: 8px 16px;
  background: #7c3aed;
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.btn-secondary {
  padding: 8px 16px;
  background: #fff;
  color: #333;
  border: 1px solid #ddd;
  border-radius: 4px;
  cursor: pointer;
}

.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.dialog {
  background: #fff;
  border-radius: 8px;
  padding: 24px;
  width: 500px;
  max-height: 80vh;
  overflow-y: auto;
}

.dialog h2 {
  margin: 0 0 20px;
}

.form-group {
  margin-bottom: 15px;
}

.form-group label {
  display: block;
  margin-bottom: 5px;
  font-weight: 500;
  color: #333;
}

.form-group input,
.form-group select,
.form-group textarea {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
  box-sizing: border-box;
}

.form-group textarea {
  height: 80px;
  resize: vertical;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}
</style>