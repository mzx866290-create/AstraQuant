<template>
  <div class="admin-models">
    <div class="page-header">
      <div>
        <h1 class="page-title">AI 模型管理</h1>
        <p class="page-subtitle">配置和管理大语言模型接入</p>
      </div>
      <el-button type="primary" @click="openAddDialog" class="btn-add">
        <el-icon><Plus /></el-icon>
        <span>新增模型</span>
      </el-button>
    </div>

    <!-- 骨架屏 -->
    <div v-if="loading" class="skeleton-list">
      <div v-for="i in 4" :key="i" class="skeleton-item">
        <div class="skeleton-header">
          <div class="skeleton-title"></div>
          <div class="skeleton-badge"></div>
        </div>
        <div class="skeleton-body">
          <div class="skeleton-line"></div>
          <div class="skeleton-line short"></div>
        </div>
      </div>
    </div>

    <!-- 模型卡片列表 -->
    <div v-else-if="models.length" class="models-grid">
      <div
        v-for="model in models"
        :key="model.id"
        class="model-card"
        :class="{ inactive: !model.is_active }"
      >
        <div class="model-header">
          <div class="model-info">
            <div class="model-name-row">
              <h3 class="model-name">{{ model.name }}</h3>
              <el-tag
                size="small"
                :type="model.is_active ? 'success' : 'info'"
                effect="light"
                class="status-tag"
              >
                {{ model.is_active ? '启用' : '禁用' }}
              </el-tag>
            </div>
            <span class="model-id">{{ model.model_id }}</span>
          </div>
          <div class="provider-badge" :class="model.provider">
            <span class="provider-dot" :class="model.provider"></span>
            {{ providerLabel(model.provider) }}
          </div>
        </div>

        <div class="model-body">
          <div v-if="model.description" class="model-desc">
            {{ model.description }}
          </div>
          <div class="model-meta">
            <div class="meta-item">
              <span class="meta-label">角色权限</span>
              <span class="meta-value">{{ model.allowed_roles || '全部' }}</span>
            </div>
            <div v-if="model.api_base_url" class="meta-item">
              <span class="meta-label">代理地址</span>
              <span class="meta-value truncate">{{ model.api_base_url }}</span>
            </div>
          </div>
        </div>

        <!-- 测试结果区域 -->
        <div v-if="testResults[model.id]" class="test-result" :class="testResults[model.id].status">
          <el-icon class="test-icon">
            <SuccessFilled v-if="testResults[model.id].status === 'success'" />
            <WarningFilled v-else />
          </el-icon>
          <span class="test-text">{{ testResults[model.id].message }}</span>
          <el-icon class="test-close" @click="clearTestResult(model.id)"><Close /></el-icon>
        </div>

        <div class="model-actions">
          <el-button type="primary" link @click="openEditDialog(model)">
            <el-icon><Edit /></el-icon>
            <span>编辑</span>
          </el-button>
          <el-button
            :type="model.is_active ? 'warning' : 'success'"
            link
            @click="toggleModel(model)"
          >
            <el-icon><SwitchButton v-if="model.is_active" /><CircleCheck v-else /></el-icon>
            <span>{{ model.is_active ? '禁用' : '启用' }}</span>
          </el-button>
          <el-button type="primary" link @click="testModelConnection(model)">
            <el-icon><Connection /></el-icon>
            <span>{{ testingIds.has(model.id) ? '测试中...' : '测试' }}</span>
          </el-button>
          <el-button type="danger" link @click="deleteModel(model)">
            <el-icon><Delete /></el-icon>
            <span>删除</span>
          </el-button>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-else class="empty-state">
      <el-icon :size="64" class="empty-icon"><Cpu /></el-icon>
      <h3>暂无 AI 模型</h3>
      <p>点击右上角按钮添加第一个模型</p>
    </div>

    <!-- 添加/编辑弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingModel ? '编辑模型' : '新增模型'"
      width="560px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="formRules"
        label-position="top"
        class="model-form"
      >
        <el-form-item label="模型名称" prop="name">
          <el-input v-model="form.name" placeholder="如：Claude 3.5 Sonnet" />
        </el-form-item>

        <el-form-item label="供应商" prop="provider">
          <el-select v-model="form.provider" class="w-full">
            <el-option label="OpenAI" value="openai">
              <span class="provider-option">
                <span class="provider-dot openai"></span>
                OpenAI
              </span>
            </el-option>
            <el-option label="Anthropic" value="anthropic">
              <span class="provider-option">
                <span class="provider-dot anthropic"></span>
                Anthropic
              </span>
            </el-option>
            <el-option label="DeepSeek" value="deepseek">
              <span class="provider-option">
                <span class="provider-dot deepseek"></span>
                DeepSeek
              </span>
            </el-option>
            <el-option label="Custom" value="custom">
              <span class="provider-option">
                <span class="provider-dot custom"></span>
                Custom
              </span>
            </el-option>
          </el-select>
        </el-form-item>

        <el-form-item label="模型 ID" prop="model_id">
          <el-input v-model="form.model_id" placeholder="如：gpt-4o-mini" />
        </el-form-item>

        <el-form-item label="API Key" prop="api_key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="editingModel ? '留空则不修改' : 'sk-...'"
          />
        </el-form-item>

        <el-form-item label="API Base URL (可选)">
          <el-input v-model="form.api_base_url" placeholder="如需代理或自定义端点" />
        </el-form-item>

        <el-form-item label="描述">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            placeholder="模型描述..."
          />
        </el-form-item>

        <el-form-item label="允许角色">
          <el-input v-model="form.allowed_roles" placeholder="free,premium,admin" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm" :loading="submitting">
          {{ editingModel ? '保存修改' : '创建模型' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  Plus,
  Edit,
  SwitchButton,
  CircleCheck,
  Connection,
  Delete,
  SuccessFilled,
  WarningFilled,
  Close,
  Cpu,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { adminApi } from '@/api'

type ModelProvider = 'openai' | 'anthropic' | 'deepseek' | 'custom'

interface AIModel {
  id: number
  name: string
  provider: ModelProvider | string
  model_id: string
  is_active: boolean
  allowed_roles?: string
  api_base_url?: string
  description?: string
  api_key?: string
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
const dialogVisible = ref(false)
const editingModel = ref<AIModel | null>(null)
const submitting = ref(false)
const formRef = ref<FormInstance>()
const testingIds = ref(new Set<number>())
const testResults = ref<Record<number, ModelTestResult>>({})

const emptyForm = (): ModelForm => ({
  name: '',
  provider: 'openai',
  model_id: '',
  api_key: '',
  api_base_url: '',
  description: '',
  allowed_roles: 'free,premium,admin',
})

const form = ref(emptyForm())

const formRules: FormRules = {
  name: [{ required: true, message: '请输入模型名称', trigger: 'blur' }],
  provider: [{ required: true, message: '请选择供应商', trigger: 'change' }],
  model_id: [{ required: true, message: '请输入模型 ID', trigger: 'blur' }],
  api_key: [{ required: true, message: '请输入 API Key', trigger: 'blur' }],
}

function providerLabel(provider: string) {
  const labels: Record<string, string> = {
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    deepseek: 'DeepSeek',
    custom: 'Custom',
  }
  return labels[provider] || provider
}

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

function openAddDialog() {
  editingModel.value = null
  form.value = emptyForm()
  dialogVisible.value = true
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
  dialogVisible.value = true
}

async function submitForm() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    if (editingModel.value) {
      const payload: Partial<ModelForm> = {}
      const fields: (keyof ModelForm)[] = ['name', 'provider', 'model_id', 'api_base_url', 'description', 'allowed_roles']
      for (const key of fields) {
        if (form.value[key]) {
          payload[key] = form.value[key]
        }
      }
      if (form.value.api_key) {
        payload.api_key = form.value.api_key
      }
      await adminApi.updateModel(editingModel.value.id, payload)
      ElMessage.success('模型更新成功')
    } else {
      await adminApi.createModel(form.value)
      ElMessage.success('模型创建成功')
    }
    dialogVisible.value = false
    loadModels()
  } catch (e) {
    ElMessage.error(editingModel.value ? '更新失败' : '创建失败')
  } finally {
    submitting.value = false
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

async function testModelConnection(model: AIModel) {
  if (testingIds.value.has(model.id)) return

  testingIds.value.add(model.id)
  clearTestResult(model.id)

  try {
    const result = await adminApi.testModel<ModelTestResult>(model.id)
    testResults.value[model.id] = {
      status: result.status,
      message: result.status === 'success'
        ? '连接成功，模型可正常使用'
        : `连接失败: ${result.message || '未知错误'}`,
    }
  } catch (e) {
    testResults.value[model.id] = {
      status: 'error',
      message: '测试失败，请检查 API Key 和网络连接',
    }
  } finally {
    testingIds.value.delete(model.id)
  }
}

function clearTestResult(modelId: number) {
  delete testResults.value[modelId]
}

async function deleteModel(model: AIModel) {
  try {
    await ElMessageBox.confirm(
      `确定删除模型 "${model.name}" 吗？此操作不可撤销！`,
      '确认删除',
      { type: 'warning' }
    )
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
.admin-models {
  max-width: 1200px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--space-6);
  gap: var(--space-4);
}

.page-title {
  font-size: 24px;
  font-weight: 800;
  color: var(--color-text);
  margin: 0 0 var(--space-1);
  letter-spacing: -0.02em;
}

.page-subtitle {
  margin: 0;
  color: var(--color-text-muted);
  font-size: 14px;
}

.btn-add {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 10px 20px;
  font-weight: 700;
}

/* Skeleton */
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.skeleton-item {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
}

.skeleton-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-3);
}

.skeleton-title {
  width: 160px;
  height: 20px;
  border-radius: var(--radius-sm);
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
}

.skeleton-badge {
  width: 60px;
  height: 24px;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
}

.skeleton-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.skeleton-line {
  width: 100%;
  height: 16px;
  border-radius: var(--radius-sm);
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
}

.skeleton-line.short {
  width: 40%;
}

@keyframes skeleton-loading {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Models grid */
.models-grid {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.model-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  transition: all var(--transition-base);
  position: relative;
  overflow: hidden;
}

.model-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, #6366f1 0%, #8b5cf6 100%);
  opacity: 0;
  transition: opacity var(--transition-base);
}

.model-card:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-card-hover);
  transform: translateY(-1px);
}

.model-card:hover::before {
  opacity: 1;
}

.model-card.inactive {
  opacity: 0.75;
  background: var(--color-surface-muted);
}

.model-card.inactive::before {
  background: var(--color-text-muted);
  opacity: 0.3;
}

.model-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.model-info {
  min-width: 0;
  flex: 1;
}

.model-name-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-1);
}

.model-name {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
  color: var(--color-text);
  letter-spacing: -0.01em;
}

.status-tag {
  font-weight: 700;
}

.model-id {
  font-family: var(--font-number);
  font-size: 13px;
  color: var(--color-text-muted);
}

.provider-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  color: var(--color-text-secondary);
  flex-shrink: 0;
}

.provider-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.provider-dot.openai {
  background: #10a37f;
}

.provider-dot.anthropic {
  background: #d97706;
}

.provider-dot.deepseek {
  background: #6366f1;
}

.provider-dot.custom {
  background: #6b7280;
}

.provider-badge.openai {
  background: rgba(16, 163, 127, 0.1);
  border-color: rgba(16, 163, 127, 0.2);
  color: #10a37f;
}

.provider-badge.anthropic {
  background: rgba(217, 119, 6, 0.1);
  border-color: rgba(217, 119, 6, 0.2);
  color: #d97706;
}

.provider-badge.deepseek {
  background: rgba(99, 102, 241, 0.1);
  border-color: rgba(99, 102, 241, 0.2);
  color: #6366f1;
}

.provider-badge.custom {
  background: rgba(107, 114, 128, 0.1);
  border-color: rgba(107, 114, 128, 0.2);
  color: #6b7280;
}

.model-body {
  margin-bottom: var(--space-3);
}

.model-desc {
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.6;
  margin-bottom: var(--space-3);
}

.model-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.meta-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.meta-value {
  font-size: 13px;
  color: var(--color-text-secondary);
}

.meta-value.truncate {
  max-width: 240px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Test result */
.test-result {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-sm);
  margin-bottom: var(--space-3);
  font-size: 13px;
  font-weight: 600;
  animation: slideDown 0.3s ease-out;
}

.test-result.success {
  background: var(--color-success-bg);
  color: var(--color-success);
  border: 1px solid rgba(22, 163, 106, 0.2);
}

.test-result.error {
  background: var(--color-danger-soft);
  color: var(--color-danger);
  border: 1px solid rgba(226, 59, 59, 0.2);
}

.test-icon {
  font-size: 18px;
  flex-shrink: 0;
}

.test-text {
  flex: 1;
}

.test-close {
  cursor: pointer;
  opacity: 0.6;
  transition: opacity var(--transition-fast);
  flex-shrink: 0;
}

.test-close:hover {
  opacity: 1;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Actions */
.model-actions {
  display: flex;
  gap: var(--space-1);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border);
}

.model-actions .el-button {
  padding: 6px 12px;
  font-size: 13px;
  font-weight: 600;
}

/* Empty state */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-12) var(--space-6);
  text-align: center;
  color: var(--color-text-muted);
}

.empty-state h3 {
  margin: var(--space-3) 0 var(--space-1);
  font-size: 18px;
  font-weight: 700;
  color: var(--color-text);
}

.empty-state p {
  margin: 0;
  font-size: 14px;
}

.empty-icon {
  color: var(--color-border-strong);
}

/* Dialog */
.model-form :deep(.el-form-item__label) {
  font-weight: 700;
  color: var(--color-text);
  padding-bottom: 4px;
}

.provider-option {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.w-full {
  width: 100%;
}

/* Responsive */
@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
    align-items: stretch;
  }

  .btn-add {
    width: 100%;
    justify-content: center;
  }

  .model-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .model-actions {
    flex-wrap: wrap;
  }
}
</style>
