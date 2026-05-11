<template>
  <div class="admin-stats">
    <div class="page-header">
      <div>
        <h1 class="page-title">使用统计</h1>
        <p class="page-subtitle">系统运行概览与研究复盘状态</p>
      </div>
      <button class="refresh-btn" @click="loadStats" :disabled="loading">
        {{ loading ? '加载中...' : '刷新数据' }}
      </button>
    </div>

    <div v-if="loading" class="skeleton-stats">
      <div v-for="i in 6" :key="i" class="skeleton-stat-card">
        <div class="skeleton-value"></div>
        <div class="skeleton-label"></div>
      </div>
    </div>

    <template v-else-if="stats">
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-icon users">
            <el-icon :size="24"><User /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ formatNumber(stats.total_users) }}</div>
            <div class="stat-label">总用户数</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon active">
            <el-icon :size="24"><TrendCharts /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ formatNumber(stats.active_users_today) }}</div>
            <div class="stat-label">今日活跃用户</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon models">
            <el-icon :size="24"><Cpu /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ stats.active_models }}</div>
            <div class="stat-label">启用模型数</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon calls">
            <el-icon :size="24"><Connection /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ formatNumber(stats.total_api_calls_today) }}</div>
            <div class="stat-label">今日调用次数</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon tokens">
            <el-icon :size="24"><DataLine /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ formatNumber(stats.total_tokens_today) }}</div>
            <div class="stat-label">今日 Token</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon cost">
            <el-icon :size="24"><Money /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">${{ formatMoney(stats.total_cost_month) }}</div>
            <div class="stat-label">本月费用</div>
          </div>
        </div>
      </div>

      <div class="research-grid">
        <div class="chart-card">
          <div class="chart-header">
            <h3>复盘链路 Readiness</h3>
            <span class="status-chip" :class="readinessClass">{{ readinessLabel }}</span>
          </div>
          <div v-if="reviewReadiness" class="scheduler-meta">
            <div class="readiness-tables">
              <span
                class="table-chip"
                :class="{ ok: reviewReadiness.tables?.research_observations, missing: !reviewReadiness.tables?.research_observations }"
              >
                observations {{ reviewReadiness.tables?.research_observations ? 'ok' : 'missing' }}
              </span>
              <span
                class="table-chip"
                :class="{ ok: reviewReadiness.tables?.observation_reviews, missing: !reviewReadiness.tables?.observation_reviews }"
              >
                reviews {{ reviewReadiness.tables?.observation_reviews ? 'ok' : 'missing' }}
              </span>
            </div>
            <div class="meta-row">
              <span>观察快照</span>
              <strong>{{ formatNumber(reviewReadiness.summary?.observations || 0) }}</strong>
            </div>
            <div class="meta-row">
              <span>复盘记录</span>
              <strong>{{ formatNumber(reviewReadiness.summary?.reviews || 0) }}</strong>
            </div>
            <div class="meta-row">
              <span>待复盘</span>
              <strong>{{ formatNumber(reviewReadiness.summary?.pending_reviews || 0) }}</strong>
            </div>
            <div class="meta-row">
              <span>最新快照</span>
              <strong>{{ reviewReadiness.latest_snapshot_date || '-' }}</strong>
            </div>
            <div class="meta-row">
              <span>最新复盘</span>
              <strong>{{ reviewReadiness.latest_review_date || '-' }}</strong>
            </div>
          </div>
          <div v-else class="chart-empty">暂无 readiness 数据</div>
        </div>

        <div class="chart-card">
          <div class="chart-header">
            <h3>研究复盘概览</h3>
            <span class="chart-period">{{ reviewReport?.status || 'unknown' }}</span>
          </div>
          <div v-if="reviewReport" class="review-summary-grid">
            <div class="summary-tile">
              <div class="summary-value">{{ formatNumber(reviewReport.summary?.reviews || 0) }}</div>
              <div class="summary-label">累计复盘</div>
            </div>
            <div class="summary-tile">
              <div class="summary-value">{{ formatNumber(reviewReport.summary?.strategies || 0) }}</div>
              <div class="summary-label">覆盖策略</div>
            </div>
            <div class="summary-tile">
              <div class="summary-value">{{ formatPercent(reviewReport.summary?.avg_return_pct) }}</div>
              <div class="summary-label">平均收益率</div>
            </div>
          </div>
          <div v-else class="chart-empty">暂无复盘数据</div>
        </div>

        <div class="chart-card">
          <div class="chart-header">
            <h3>复盘调度状态</h3>
            <div class="header-actions">
              <span class="status-chip" :class="schedulerClass">{{ schedulerLabel }}</span>
              <button class="run-review-btn" :disabled="reviewRunning" @click="runReviewNow">
                {{ reviewRunning ? '执行中...' : '立即复盘' }}
              </button>
            </div>
          </div>
          <div v-if="reviewScheduler" class="scheduler-meta">
            <div class="meta-row">
              <span>调度开关</span>
              <strong>{{ reviewScheduler.enabled ? '已启用' : '未启用' }}</strong>
            </div>
            <div class="meta-row">
              <span>运行状态</span>
              <strong>{{ reviewScheduler.running ? '运行中' : '未运行' }}</strong>
            </div>
            <div class="meta-row">
              <span>执行间隔</span>
              <strong>{{ formatInterval(reviewScheduler.interval_seconds) }}</strong>
            </div>
            <div class="meta-row">
              <span>上次运行</span>
              <strong>{{ formatDateTime(reviewScheduler.last_run_at) }}</strong>
            </div>
            <div class="meta-row">
              <span>最近结果</span>
              <strong>{{ schedulerResultText }}</strong>
            </div>
            <div v-if="reviewScheduler.last_error" class="scheduler-error">
              {{ reviewScheduler.last_error }}
            </div>
          </div>
          <div v-else class="chart-empty">暂无调度状态</div>
        </div>
      </div>

      <div class="charts-grid">
        <div class="chart-card chart-main">
          <div class="chart-header">
            <h3>每日调用量趋势</h3>
            <span v-if="callsByDay.length" class="chart-period">近 {{ callsByDay.length }} 天</span>
          </div>
          <div v-if="callsByDay.length" class="chart-bar-chart">
            <div
              v-for="item in callsByDay"
              :key="item.date"
              class="bar-group"
              :style="{ height: `${(item.count / maxCalls) * 100}%` }"
            >
              <div class="bar"></div>
              <span class="bar-count">{{ item.count }}</span>
              <span class="bar-date">{{ formatDate(item.date) }}</span>
            </div>
          </div>
          <div v-else class="chart-empty">暂无数据</div>
        </div>

        <div class="chart-card chart-side">
          <h3>模型调用占比</h3>
          <div v-if="callsByModel.length" class="model-ranking">
            <div
              v-for="(item, index) in callsByModel.slice(0, 8)"
              :key="item.model_name"
              class="ranking-item"
            >
              <span class="rank-number">{{ index + 1 }}</span>
              <span class="rank-name">{{ item.model_name }}</span>
              <span class="rank-count">{{ item.count }}</span>
            </div>
          </div>
          <div v-else class="chart-empty">暂无数据</div>
        </div>
      </div>

      <div class="review-table-card">
        <div class="chart-header">
          <h3>策略复盘表现</h3>
          <span class="chart-period">按策略聚合</span>
        </div>
        <div v-if="reviewStrategies.length" class="strategy-table">
          <div class="strategy-head strategy-row">
            <span>策略</span>
            <span>复盘数</span>
            <span>胜率</span>
            <span>平均收益</span>
            <span>证伪触发</span>
            <span>风险预警命中</span>
          </div>
          <div
            v-for="item in reviewStrategies"
            :key="item.strategy_id"
            class="strategy-row"
          >
            <span class="strategy-name">{{ item.strategy_id }}</span>
            <span>{{ item.reviews }}</span>
            <span>{{ formatWinRate(item.win_rate) }}</span>
            <span :class="returnClass(item.avg_return_pct)">{{ formatPercent(item.avg_return_pct) }}</span>
            <span>{{ item.falsification_triggered }}</span>
            <span>{{ item.risk_signal_valid }}</span>
          </div>
        </div>
        <div v-else class="chart-empty">暂无策略复盘数据</div>
      </div>

      <div class="review-table-card">
        <div class="chart-header">
          <h3>因子复盘归因</h3>
          <span class="chart-period">{{ formatNumber(factorReport?.summary?.factors || 0) }} factors</span>
        </div>
        <div v-if="factorRows.length" class="factor-table">
          <div class="factor-head factor-row">
            <span>因子</span>
            <span>复盘数</span>
            <span>胜率</span>
            <span>平均收益</span>
            <span>平均影响</span>
            <span>正/负影响</span>
            <span>证伪/风险</span>
          </div>
          <div
            v-for="item in factorRows"
            :key="item.factor"
            class="factor-row"
          >
            <span class="strategy-name">{{ item.label || item.factor }}</span>
            <span>{{ item.reviews }}</span>
            <span>{{ formatWinRate(item.win_rate) }}</span>
            <span :class="returnClass(item.avg_return_pct)">{{ formatPercent(item.avg_return_pct) }}</span>
            <span :class="returnClass(item.avg_impact)">{{ formatSignedNumber(item.avg_impact) }}</span>
            <span>{{ item.positive_impact_reviews }} / {{ item.negative_impact_reviews }}</span>
            <span>{{ item.falsification_triggered }} / {{ item.risk_signal_valid }}</span>
          </div>
        </div>
        <div v-else class="chart-empty">暂无因子归因数据</div>
      </div>

      <div class="review-table-card">
        <div class="chart-header">
          <h3>权重调整建议</h3>
          <div class="header-actions">
            <span class="chart-period">{{ formatNumber(weightSuggestions?.summary?.suggestions || 0) }} suggestions</span>
            <button class="run-review-btn" :disabled="auditSaving" @click="saveWeightSuggestionAudit">
              {{ auditSaving ? '保存中...' : '保存审计' }}
            </button>
          </div>
        </div>
        <div v-if="suggestionRows.length" class="suggestion-table">
          <div class="suggestion-head suggestion-row">
            <span>因子</span>
            <span>动作</span>
            <span>置信度</span>
            <span>样本/胜率</span>
            <span>收益/影响</span>
            <span>理由</span>
          </div>
          <div
            v-for="item in suggestionRows"
            :key="item.factor"
            class="suggestion-row"
          >
            <span class="strategy-name">{{ item.label || item.factor }}</span>
            <span>
              <span class="action-chip" :class="item.action">{{ actionLabel(item.action) }}</span>
            </span>
            <span>{{ confidenceLabel(item.confidence) }}</span>
            <span>{{ item.metrics.reviews }} / {{ formatWinRate(item.metrics.win_rate) }}</span>
            <span>
              <span :class="returnClass(item.metrics.avg_return_pct)">{{ formatPercent(item.metrics.avg_return_pct) }}</span>
              /
              <span :class="returnClass(item.metrics.avg_impact)">{{ formatSignedNumber(item.metrics.avg_impact) }}</span>
            </span>
            <span>{{ item.reason }}</span>
          </div>
        </div>
        <div v-else class="chart-empty">暂无权重调整建议</div>

        <div class="audit-section">
          <div class="audit-section-header">
            <h4>最近审计记录</h4>
            <button class="text-btn" :disabled="auditsLoading" @click="loadWeightSuggestionAudits">
              {{ auditsLoading ? '刷新中...' : '刷新' }}
            </button>
          </div>
          <div v-if="weightSuggestionAudits.length" class="audit-table">
            <div class="audit-head audit-row">
              <span>时间</span>
              <span>状态</span>
              <span>建议</span>
              <span>备注</span>
              <span>操作</span>
            </div>
            <div
              v-for="audit in weightSuggestionAudits"
              :key="audit.id"
              class="audit-row"
            >
              <span>{{ formatDateTime(audit.generated_at || audit.created_at) }}</span>
              <span>
                <span class="audit-status" :class="auditStatusClass(audit.accepted)">
                  {{ auditStatusLabel(audit.accepted) }}
                </span>
              </span>
              <span>{{ formatNumber(audit.summary?.suggestions ?? audit.suggestions.length) }}</span>
              <span>
                <textarea
                  v-model="auditNotes[audit.id]"
                  class="audit-notes"
                  rows="2"
                  placeholder="备注"
                ></textarea>
              </span>
              <span class="audit-actions">
                <button
                  class="mini-btn accept"
                  :disabled="isAuditUpdating(audit.id)"
                  @click="updateAuditDecision(audit.id, true)"
                >
                  接受
                </button>
                <button
                  class="mini-btn reject"
                  :disabled="isAuditUpdating(audit.id)"
                  @click="updateAuditDecision(audit.id, false)"
                >
                  驳回
                </button>
                <button
                  class="mini-btn"
                  :disabled="isAuditUpdating(audit.id)"
                  @click="updateAuditDecision(audit.id, null)"
                >
                  清空
                </button>
                <button
                  class="mini-btn"
                  :disabled="isAuditUpdating(audit.id)"
                  @click="updateAuditNotes(audit.id)"
                >
                  备注
                </button>
                <button
                  class="mini-btn patch"
                  :disabled="isPatchPreviewLoading(audit.id)"
                  @click="loadPatchPreview(audit.id)"
                >
                  {{ isPatchPreviewLoading(audit.id) ? '...' : 'Patch' }}
                </button>
              </span>
            </div>
          </div>
          <div v-else class="audit-empty">暂无审计记录</div>
        </div>

        <div v-if="patchPreview || patchPreviewLoadingAuditId" class="patch-preview">
          <div class="patch-preview-header">
            <div>
              <h4>Strategy Patch Preview</h4>
              <p v-if="patchPreview">
                audit #{{ patchPreview.audit_id }} / {{ patchPreview.strategy_id }}
              </p>
              <p v-else>Loading retail_small preview...</p>
            </div>
            <span
              class="status-chip"
              :class="patchPreview?.status === 'ok' ? 'idle' : 'error'"
            >
              {{ patchPreview?.status || 'loading' }}
            </span>
          </div>

          <div v-if="patchPreview?.status === 'ok'" class="proposal-toolbar">
            <button
              class="run-review-btn"
              :disabled="proposalSaving"
              @click="createPatchProposal"
            >
              {{ proposalSaving ? 'Saving...' : 'Save Proposal' }}
            </button>
            <span class="proposal-hint">Creates a pending proposal only. It does not write strategy config.</span>
          </div>

          <div v-if="patchPreview && patchPreview.status !== 'ok'" class="patch-preview-note">
            {{ patchPreviewStatusText }}
          </div>

          <div v-if="patchPreviewRows.length" class="patch-table">
            <div class="patch-head patch-row">
              <span>Factor</span>
              <span>Before</span>
              <span>After</span>
              <span>Delta</span>
            </div>
            <div
              v-for="row in patchPreviewRows"
              :key="row.factor"
              class="patch-row"
            >
              <span class="strategy-name">{{ row.factor }}</span>
              <span>{{ formatWeight(row.before) }}</span>
              <span>{{ formatWeight(row.after) }}</span>
              <span :class="returnClass(row.delta)">{{ formatSignedWeight(row.delta) }}</span>
            </div>
          </div>
          <div v-else-if="patchPreview && patchPreview.status === 'ok'" class="audit-empty">
            No patch changes.
          </div>
        </div>

        <div class="proposal-section">
          <div class="audit-section-header">
            <h4>Strategy Patch Proposals</h4>
            <button class="text-btn" :disabled="proposalsLoading" @click="loadPatchProposals">
              {{ proposalsLoading ? 'Refreshing...' : 'Refresh' }}
            </button>
          </div>
          <div v-if="patchProposals.length" class="proposal-table">
            <div class="proposal-head proposal-row">
              <span>ID / Audit</span>
              <span>Strategy</span>
              <span>Status</span>
              <span>Applied</span>
              <span>Changes</span>
              <span>Actions</span>
            </div>
            <div
              v-for="proposal in patchProposals"
              :key="proposal.id"
              class="proposal-row"
            >
              <span>#{{ proposal.id }} / #{{ proposal.audit_id }}</span>
              <span>{{ proposal.strategy_id }}</span>
              <span>
                <span class="audit-status" :class="proposalStatusClass(proposal.status)">
                  {{ proposal.status }}
                </span>
              </span>
              <span>{{ formatDateTime(proposal.applied_at) }}</span>
              <span>{{ proposal.items?.length || Object.keys(proposal.delta || {}).length }}</span>
              <span class="audit-actions">
                <button class="mini-btn accept" @click="decidePatchProposal(proposal.id, 'approved')">
                  Approve
                </button>
                <button class="mini-btn reject" @click="decidePatchProposal(proposal.id, 'rejected')">
                  Reject
                </button>
                <button class="mini-btn" @click="decidePatchProposal(proposal.id, 'pending')">
                  Reset
                </button>
                <button
                  v-if="canApplyPatchProposal(proposal)"
                  class="mini-btn patch"
                  :disabled="isProposalApplying(proposal.id)"
                  @click="applyPatchProposal(proposal.id)"
                >
                  {{ isProposalApplying(proposal.id) ? 'Applying...' : 'Apply' }}
                </button>
                <button
                  class="mini-btn"
                  :disabled="impactPreviewLoadingProposalId === proposal.id"
                  @click="loadImpactPreview(proposal.id)"
                >
                  {{ impactPreviewLoadingProposalId === proposal.id ? 'Previewing...' : 'A/B' }}
                </button>
                <button
                  class="mini-btn"
                  :disabled="versionsLoading && selectedVersionStrategyId === proposal.strategy_id"
                  @click="loadStrategyVersions(proposal.strategy_id)"
                >
                  Versions
                </button>
              </span>
            </div>
          </div>
          <div v-else class="audit-empty">No strategy patch proposals.</div>
        </div>

        <div class="proposal-section">
          <div class="audit-section-header">
            <div>
              <h4>Strategy Impact Preview</h4>
              <p class="proposal-hint">
                {{ impactPreview ? `proposal #${impactPreview.proposal_id} / changed ${impactPreview.changed_count || 0}/${impactPreview.sample_count || 0}` : 'Run A/B from a proposal to compare ranking before Apply.' }}
              </p>
            </div>
          </div>
          <div v-if="impactPreview?.items?.length" class="version-table">
            <div class="version-head version-row">
              <span>Stock</span>
              <span>Rank</span>
              <span>Score</span>
              <span>Delta</span>
              <span>Name</span>
              <span>Base</span>
            </div>
            <div
              v-for="item in impactPreview.items"
              :key="item.symbol"
              class="version-row"
            >
              <span>{{ item.symbol }}</span>
              <span>
                {{ item.before_rank ?? '-' }} -> {{ item.after_rank ?? '-' }}
                <b :class="returnClass(item.rank_delta)">{{ formatSignedInteger(item.rank_delta) }}</b>
              </span>
              <span>{{ item.before_score ?? '-' }} -> {{ item.after_score ?? '-' }}</span>
              <span :class="returnClass(item.score_delta)">{{ formatSignedInteger(item.score_delta) }}</span>
              <span>{{ item.name || '-' }}</span>
              <span>{{ item.base_score ?? '-' }}</span>
            </div>
          </div>
          <div v-else class="audit-empty">
            {{ impactPreviewStatusText || 'No impact preview yet.' }}
          </div>
        </div>

        <div class="proposal-section">
          <div class="audit-section-header">
            <div>
              <h4>Strategy Weight Versions</h4>
              <p class="proposal-hint">
                {{ selectedVersionStrategyId ? `strategy: ${selectedVersionStrategyId}` : 'Select a proposal strategy to view history.' }}
              </p>
            </div>
            <button
              class="text-btn"
              :disabled="!selectedVersionStrategyId || versionsLoading"
              @click="refreshStrategyVersions"
            >
              {{ versionsLoading ? 'Refreshing...' : 'Refresh Versions' }}
            </button>
          </div>
          <div v-if="strategyVersions.length" class="version-table">
            <div class="version-head version-row">
              <span>Version</span>
              <span>Proposal</span>
              <span>Applied</span>
              <span>Rollback</span>
              <span>Notes</span>
              <span>Actions</span>
            </div>
            <div
              v-for="version in strategyVersions"
              :key="version.id"
              class="version-row"
            >
              <span>#{{ version.version ?? version.id }}</span>
              <span>{{ version.proposal_id ? `#${version.proposal_id}` : '-' }}</span>
              <span>{{ formatDateTime(version.applied_at || version.created_at) }}</span>
              <span>
                <span v-if="version.rollback_error" class="audit-status rejected">error</span>
                <span v-else-if="version.rolled_back_at" class="audit-status pending">
                  {{ formatDateTime(version.rolled_back_at) }}
                </span>
                <span v-else>-</span>
              </span>
              <span>{{ version.notes || version.rollback_error || '-' }}</span>
              <span class="audit-actions">
                <button
                  class="mini-btn reject"
                  :disabled="isVersionRollingBack(version.id)"
                  @click="rollbackStrategyVersion(version.id)"
                >
                  {{ isVersionRollingBack(version.id) ? 'Rolling...' : 'Rollback' }}
                </button>
              </span>
            </div>
          </div>
          <div v-else class="audit-empty">
            {{ selectedVersionStrategyId ? 'No strategy weight versions.' : 'No strategy selected.' }}
          </div>
        </div>
      </div>

      <div class="top-users-card">
        <h3>活跃用户排行</h3>
        <div v-if="topUsers.length" class="users-list">
          <div
            v-for="(item, index) in topUsers"
            :key="item.username"
            class="user-item"
            :class="{ top3: index < 3 }"
          >
            <span class="user-rank">{{ index + 1 }}</span>
            <div class="user-info">
              <span class="user-name">{{ item.username }}</span>
              <span class="user-count">{{ item.count }} 次调用</span>
            </div>
          </div>
        </div>
        <div v-else class="chart-empty">暂无数据</div>
      </div>
    </template>

    <div v-else class="error-state">
      <el-icon :size="48" class="error-icon"><WarningFilled /></el-icon>
      <h3>数据加载失败</h3>
      <p>请稍后重试</p>
      <el-button type="primary" @click="loadStats">重试</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  Connection,
  Cpu,
  DataLine,
  Money,
  TrendCharts,
  User,
  WarningFilled,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api'

interface CallsByDayItem {
  date: string
  count: number
}

interface CallsByModelItem {
  model_name: string
  count: number
}

interface TopUserItem {
  username: string
  count: number
}

interface StatsOverview {
  total_users: number
  active_users_today: number
  total_models: number
  active_models: number
  total_api_calls_today: number
  total_api_calls_month: number
  total_tokens_today: number
  total_cost_month?: number
  calls_by_day?: CallsByDayItem[]
  calls_by_model?: CallsByModelItem[]
  top_users?: TopUserItem[]
}

interface ReviewSchedulerStatus {
  enabled: boolean
  running: boolean
  interval_seconds?: number
  last_run_at?: string | null
  last_error?: string | null
  last_result?: {
    created?: number
    processed?: number
    status?: string
  } | null
}

interface ReviewReadiness {
  status: string
  review_date?: string
  offsets?: string[]
  tables?: {
    research_observations?: boolean
    observation_reviews?: boolean
  }
  summary?: {
    observations?: number
    reviews?: number
    pending_reviews?: number
    strategies_with_reviews?: number
  }
  latest_snapshot_date?: string | null
  latest_review_date?: string | null
  pending_reviews?: Array<{
    observation_id?: number
    symbol?: string
    strategy_id?: string
    snapshot_date?: string
    review_offset?: string
    base_price?: number | string | null
  }>
  review_report_summary?: Record<string, unknown>
}

interface ReviewReportStrategy {
  strategy_id: string
  reviews: number
  positive_reviews: number
  avg_return_pct: number | null
  falsification_triggered: number
  risk_signal_valid: number
  win_rate: number
}

interface ReviewReport {
  status: string
  summary?: {
    reviews?: number
    strategies?: number
    avg_return_pct?: number | null
  }
  by_strategy?: ReviewReportStrategy[]
}

interface FactorReportItem {
  factor: string
  label: string
  reviews: number
  positive_reviews: number
  win_rate: number
  avg_return_pct: number | null
  avg_impact: number
  positive_impact_reviews: number
  negative_impact_reviews: number
  falsification_triggered: number
  risk_signal_valid: number
}

interface FactorReport {
  status: string
  summary?: {
    factors?: number
    reviews?: number
  }
  by_factor?: FactorReportItem[]
}

type WeightAction = 'increase' | 'decrease' | 'hold'
type SuggestionConfidence = 'low' | 'medium' | 'high'

interface WeightSuggestionItem {
  factor: string
  label: string
  action: WeightAction
  confidence: SuggestionConfidence
  reason: string
  metrics: {
    reviews: number
    win_rate: number
    avg_return_pct: number | null
    avg_impact: number
    falsification_triggered: number
    risk_signal_valid: number
  }
}

interface WeightSuggestions {
  status: string
  summary?: {
    suggestions?: number
    eligible_factors?: number
    min_reviews?: number
  }
  suggestions?: WeightSuggestionItem[]
}

interface WeightSuggestionAudit {
  id: number
  generated_at?: string | null
  snapshot_from?: string | null
  snapshot_to?: string | null
  min_reviews?: number
  status?: string
  suggestions: WeightSuggestionItem[]
  summary?: {
    suggestions?: number
    eligible_factors?: number
    min_reviews?: number
  }
  accepted?: boolean | null
  accepted_by?: number | null
  accepted_at?: string | null
  notes?: string | null
  created_at?: string | null
}

interface StrategyPatchPreviewItem {
  factor?: string
  source_factor?: string
  key?: string
  name?: string
  before?: number | null
  after?: number | null
  delta?: number | null
  normalized_delta?: number | null
  requested_delta?: number | null
  applied_delta?: number | null
}

interface StrategyPatchPreview {
  status: string
  audit_id: number
  strategy_id: string
  before?: Record<string, number | null>
  after?: Record<string, number | null>
  delta?: Record<string, number | null>
  items?: StrategyPatchPreviewItem[]
  message?: string
  detail?: string
  reason?: string
}

interface PatchPreviewRow {
  factor: string
  before: number | null
  after: number | null
  delta: number | null
}

interface StrategyPatchProposal {
  id: number
  audit_id: number
  strategy_id: string
  status: 'pending' | 'approved' | 'rejected' | string
  step?: number
  max_delta?: number
  before?: Record<string, number | null>
  after?: Record<string, number | null>
  delta?: Record<string, number | null>
  items?: StrategyPatchPreviewItem[]
  notes?: string | null
  applied_at?: string | null
  applied_by?: string | number | null
  created_at?: string | null
}

interface StrategyWeightVersion {
  id: number
  strategy_id: string
  proposal_id?: number | null
  version?: number | null
  before?: Record<string, number | null> | null
  after?: Record<string, number | null> | null
  applied_by?: string | number | null
  applied_at?: string | null
  rolled_back_by?: string | number | null
  rolled_back_at?: string | null
  rollback_error?: string | null
  notes?: string | null
  created_at?: string | null
  status?: string | null
}

interface StrategyImpactPreviewItem {
  symbol: string
  name?: string | null
  before_rank?: number | null
  after_rank?: number | null
  rank_delta?: number | null
  base_score?: number | null
  before_score?: number | null
  after_score?: number | null
  score_delta?: number | null
}

interface StrategyImpactPreview {
  status: string
  proposal_id: number
  strategy_id?: string | null
  market?: string | null
  sample_count?: number
  changed_count?: number
  items?: StrategyImpactPreviewItem[]
  warnings?: string[]
}

const loading = ref(true)
const stats = ref<StatsOverview | null>(null)
const callsByDay = ref<CallsByDayItem[]>([])
const callsByModel = ref<CallsByModelItem[]>([])
const topUsers = ref<TopUserItem[]>([])
const reviewScheduler = ref<ReviewSchedulerStatus | null>(null)
const reviewReadiness = ref<ReviewReadiness | null>(null)
const reviewReport = ref<ReviewReport | null>(null)
const factorReport = ref<FactorReport | null>(null)
const weightSuggestions = ref<WeightSuggestions | null>(null)
const reviewRunning = ref(false)
const auditSaving = ref(false)
const auditsLoading = ref(false)
const weightSuggestionAudits = ref<WeightSuggestionAudit[]>([])
const auditNotes = ref<Record<number, string>>({})
const auditUpdating = ref<Record<number, boolean>>({})
const patchPreview = ref<StrategyPatchPreview | null>(null)
const patchPreviewLoadingAuditId = ref<number | null>(null)
const patchProposals = ref<StrategyPatchProposal[]>([])
const proposalsLoading = ref(false)
const proposalSaving = ref(false)
const proposalApplying = ref<Record<number, boolean>>({})
const selectedVersionStrategyId = ref<string | null>(null)
const strategyVersions = ref<StrategyWeightVersion[]>([])
const versionsLoading = ref(false)
const versionRollingBack = ref<Record<number, boolean>>({})
const impactPreview = ref<StrategyImpactPreview | null>(null)
const impactPreviewLoadingProposalId = ref<number | null>(null)

const maxCalls = computed(() => {
  if (!callsByDay.value.length) return 1
  return Math.max(...callsByDay.value.map((item) => item.count))
})

const reviewStrategies = computed(() => reviewReport.value?.by_strategy || [])
const factorRows = computed(() => factorReport.value?.by_factor || [])
const suggestionRows = computed(() => weightSuggestions.value?.suggestions || [])
const patchPreviewRows = computed<PatchPreviewRow[]>(() => {
  const preview = patchPreview.value
  if (!preview) return []
  if (preview.items?.length) {
    return preview.items.map((item, index) => {
      const fallbackKey = `item_${index + 1}`
      return {
        factor: item.factor || item.key || item.name || fallbackKey,
        before: item.before ?? null,
        after: item.after ?? null,
        delta: item.delta ?? item.normalized_delta ?? item.applied_delta ?? null,
      }
    })
  }

  const keys = new Set([
    ...Object.keys(preview.before || {}),
    ...Object.keys(preview.after || {}),
    ...Object.keys(preview.delta || {}),
  ])
  return Array.from(keys).sort().map((factor) => ({
    factor,
    before: preview.before?.[factor] ?? null,
    after: preview.after?.[factor] ?? null,
    delta: preview.delta?.[factor] ?? null,
  }))
})
const patchPreviewStatusText = computed(() => {
  if (!patchPreview.value) return ''
  return patchPreview.value.message || patchPreview.value.detail || patchPreview.value.reason || patchPreview.value.status
})

const schedulerClass = computed(() => {
  if (!reviewScheduler.value) return 'idle'
  if (reviewScheduler.value.last_error) return 'error'
  if (reviewScheduler.value.enabled && reviewScheduler.value.running) return 'running'
  if (reviewScheduler.value.enabled) return 'idle'
  return 'disabled'
})

const schedulerLabel = computed(() => {
  if (!reviewScheduler.value) return 'unknown'
  if (reviewScheduler.value.last_error) return 'error'
  if (reviewScheduler.value.enabled && reviewScheduler.value.running) return 'running'
  if (reviewScheduler.value.enabled) return 'ready'
  return 'disabled'
})

const schedulerResultText = computed(() => {
  const result = reviewScheduler.value?.last_result
  if (!result) return '-'
  const created = result.created ?? 0
  const processed = result.processed ?? 0
  const status = result.status || 'unknown'
  return `${status} / ${created} created / ${processed} processed`
})

const readinessClass = computed(() => {
  const status = reviewReadiness.value?.status
  if (status === 'reviewed' || status === 'no_pending_reviews') return 'idle'
  if (status === 'pending_reviews') return 'running'
  if (status === 'no_observations') return 'disabled'
  if (status === 'tables_missing' || status === 'error') return 'error'
  return 'disabled'
})

const readinessLabel = computed(() => {
  const status = reviewReadiness.value?.status
  const mapping: Record<string, string> = {
    reviewed: 'reviewed',
    pending_reviews: 'pending',
    no_pending_reviews: 'ready',
    no_observations: 'no snapshots',
    tables_missing: 'tables missing',
    error: 'error',
  }
  return mapping[status || ''] || status || 'unknown'
})

function formatNumber(num?: number | null) {
  if (num === null || num === undefined) return '-'
  return num.toLocaleString('zh-CN')
}

function formatMoney(num?: number | null) {
  if (num === null || num === undefined) return '0.0000'
  return num.toFixed(4)
}

function formatPercent(num?: number | null) {
  if (num === null || num === undefined) return '-'
  return `${num.toFixed(2)}%`
}

function formatWinRate(num?: number | null) {
  if (num === null || num === undefined) return '-'
  return `${(num * 100).toFixed(1)}%`
}

function formatSignedNumber(num?: number | null) {
  if (num === null || num === undefined) return '-'
  const sign = num > 0 ? '+' : ''
  return `${sign}${num.toFixed(2)}`
}

function formatWeight(num?: number | null) {
  if (num === null || num === undefined) return '-'
  return num.toFixed(4)
}

function formatSignedWeight(num?: number | null) {
  if (num === null || num === undefined) return '-'
  const sign = num > 0 ? '+' : ''
  return `${sign}${num.toFixed(4)}`
}

function formatSignedInteger(num?: number | null) {
  if (num === null || num === undefined) return '-'
  const sign = num > 0 ? '+' : ''
  return `${sign}${num}`
}

function formatDate(dateStr?: string | null) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return `${d.getMonth() + 1}/${d.getDate()}`
}

function formatDateTime(dateStr?: string | null) {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  if (Number.isNaN(d.getTime())) return dateStr
  return d.toLocaleString('zh-CN', { hour12: false })
}

function formatInterval(seconds?: number) {
  if (!seconds) return '-'
  if (seconds < 60) return `${seconds}s`
  if (seconds % 60 === 0) return `${seconds / 60}m`
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

function returnClass(value?: number | null) {
  if (value === null || value === undefined) return ''
  if (value > 0) return 'positive'
  if (value < 0) return 'negative'
  return ''
}

const impactPreviewStatusText = computed(() => {
  if (!impactPreview.value) return ''
  if (impactPreview.value.status === 'ok') return 'No ranking or score change in current sample.'
  return impactPreview.value.status
})

function actionLabel(action?: WeightAction) {
  if (action === 'increase') return '上调'
  if (action === 'decrease') return '下调'
  return '观察'
}

function confidenceLabel(value?: SuggestionConfidence) {
  if (value === 'high') return '高'
  if (value === 'medium') return '中'
  return '低'
}

function auditStatusLabel(value?: boolean | null) {
  if (value === true) return '已接受'
  if (value === false) return '已驳回'
  return '待处理'
}

function auditStatusClass(value?: boolean | null) {
  if (value === true) return 'accepted'
  if (value === false) return 'rejected'
  return 'pending'
}

function proposalStatusClass(status?: string | null) {
  if (status === 'approved') return 'accepted'
  if (status === 'rejected') return 'rejected'
  return 'pending'
}

function isAuditUpdating(auditId: number) {
  return Boolean(auditUpdating.value[auditId])
}

function isPatchPreviewLoading(auditId: number) {
  return patchPreviewLoadingAuditId.value === auditId
}

function canApplyPatchProposal(proposal: StrategyPatchProposal) {
  return proposal.status === 'approved' && !proposal.applied_at
}

function isProposalApplying(proposalId: number) {
  return Boolean(proposalApplying.value[proposalId])
}

function isVersionRollingBack(versionId: number) {
  return Boolean(versionRollingBack.value[versionId])
}

function setAuditUpdating(auditId: number, updating: boolean) {
  auditUpdating.value = {
    ...auditUpdating.value,
    [auditId]: updating,
  }
}

function setProposalApplying(proposalId: number, applying: boolean) {
  proposalApplying.value = {
    ...proposalApplying.value,
    [proposalId]: applying,
  }
}

function setVersionRollingBack(versionId: number, rollingBack: boolean) {
  versionRollingBack.value = {
    ...versionRollingBack.value,
    [versionId]: rollingBack,
  }
}

function syncAuditNotes(audits: WeightSuggestionAudit[]) {
  auditNotes.value = audits.reduce<Record<number, string>>((acc, audit) => {
    acc[audit.id] = audit.notes || ''
    return acc
  }, {})
}

async function loadWeightSuggestionAudits() {
  try {
    auditsLoading.value = true
    const audits = await adminApi.getResearchWeightSuggestionAudits<WeightSuggestionAudit[]>({ limit: 20 })
    weightSuggestionAudits.value = audits
    syncAuditNotes(audits)
  } catch (error) {
    ElMessage.error('加载审计记录失败')
    console.error('加载审计记录失败:', error)
  } finally {
    auditsLoading.value = false
  }
}

async function saveWeightSuggestionAudit() {
  try {
    auditSaving.value = true
    const suggestions = await adminApi.getResearchWeightSuggestions<WeightSuggestions>({
      min_reviews: 3,
      save_audit: true,
    })
    weightSuggestions.value = suggestions
    ElMessage.success('审计记录已保存')
    await loadWeightSuggestionAudits()
  } catch (error) {
    ElMessage.error('保存审计记录失败')
    console.error('保存审计记录失败:', error)
  } finally {
    auditSaving.value = false
  }
}

async function updateAudit(auditId: number, data: { accepted?: boolean | null; notes?: string | null }) {
  try {
    setAuditUpdating(auditId, true)
    const updated = await adminApi.updateResearchWeightSuggestionAudit<WeightSuggestionAudit>(auditId, data)
    weightSuggestionAudits.value = weightSuggestionAudits.value.map((audit) =>
      audit.id === auditId ? updated : audit,
    )
    auditNotes.value = {
      ...auditNotes.value,
      [auditId]: updated.notes || '',
    }
    ElMessage.success('审计记录已更新')
  } catch (error) {
    ElMessage.error('更新审计记录失败')
    console.error('更新审计记录失败:', error)
  } finally {
    setAuditUpdating(auditId, false)
  }
}

async function updateAuditDecision(auditId: number, accepted: boolean | null) {
  await updateAudit(auditId, { accepted })
}

async function updateAuditNotes(auditId: number) {
  await updateAudit(auditId, { notes: auditNotes.value[auditId] || null })
}

async function loadPatchPreview(auditId: number) {
  try {
    patchPreviewLoadingAuditId.value = auditId
    patchPreview.value = null
    patchPreview.value = await adminApi.getResearchWeightStrategyPatchPreview<StrategyPatchPreview>(auditId, {
      strategy_id: 'retail_small',
      step: 0.03,
      max_delta: 0.08,
    })
  } catch (error) {
    ElMessage.error('Patch preview failed')
    console.error('Patch preview failed:', error)
  } finally {
    patchPreviewLoadingAuditId.value = null
  }
}

async function loadPatchProposals() {
  try {
    proposalsLoading.value = true
    patchProposals.value = await adminApi.getResearchWeightStrategyPatchProposals<StrategyPatchProposal[]>({
      limit: 20,
    })
  } catch (error) {
    ElMessage.error('Load patch proposals failed')
    console.error('Load patch proposals failed:', error)
  } finally {
    proposalsLoading.value = false
  }
}

async function loadStrategyVersions(strategyId: string) {
  try {
    selectedVersionStrategyId.value = strategyId
    versionsLoading.value = true
    strategyVersions.value = await adminApi.getResearchWeightStrategyVersions<StrategyWeightVersion[]>({
      strategy_id: strategyId,
      limit: 20,
    })
  } catch (error) {
    ElMessage.error('Load strategy versions failed')
    console.error('Load strategy versions failed:', error)
  } finally {
    versionsLoading.value = false
  }
}

async function refreshStrategyVersions() {
  if (!selectedVersionStrategyId.value) return
  await loadStrategyVersions(selectedVersionStrategyId.value)
}

async function createPatchProposal() {
  if (!patchPreview.value) return
  try {
    proposalSaving.value = true
    const proposal = await adminApi.createResearchWeightStrategyPatchProposal<StrategyPatchProposal>(
      patchPreview.value.audit_id,
      {
        strategy_id: patchPreview.value.strategy_id,
        step: 0.03,
        max_delta: 0.08,
        notes: 'created_from_admin_preview',
      },
    )
    if (proposal.status === 'preview_not_ready') {
      ElMessage.warning('Patch preview is not ready for proposal')
    } else {
      ElMessage.success('Patch proposal saved')
    }
    await loadPatchProposals()
  } catch (error) {
    ElMessage.error('Save patch proposal failed')
    console.error('Save patch proposal failed:', error)
  } finally {
    proposalSaving.value = false
  }
}

async function decidePatchProposal(proposalId: number, status: 'pending' | 'approved' | 'rejected') {
  try {
    const updated = await adminApi.updateResearchWeightStrategyPatchProposal<StrategyPatchProposal>(proposalId, {
      status,
    })
    patchProposals.value = patchProposals.value.map((proposal) =>
      proposal.id === proposalId ? updated : proposal,
    )
    ElMessage.success('Patch proposal updated')
  } catch (error) {
    ElMessage.error('Update patch proposal failed')
    console.error('Update patch proposal failed:', error)
  }
}

async function applyPatchProposal(proposalId: number) {
  try {
    setProposalApplying(proposalId, true)
    const updated = await adminApi.applyResearchWeightStrategyPatchProposal<StrategyPatchProposal>(proposalId, {
      notes: 'applied_from_admin_stats',
    })
    patchProposals.value = patchProposals.value.map((proposal) =>
      proposal.id === proposalId ? updated : proposal,
    )
    ElMessage.success('Patch proposal applied')
    await loadStrategyVersions(updated.strategy_id)
  } catch (error) {
    ElMessage.error('Apply patch proposal failed')
    console.error('Apply patch proposal failed:', error)
  } finally {
    setProposalApplying(proposalId, false)
  }
}

async function loadImpactPreview(proposalId: number) {
  try {
    impactPreviewLoadingProposalId.value = proposalId
    impactPreview.value = null
    impactPreview.value = await adminApi.getResearchWeightStrategyPatchImpactPreview<StrategyImpactPreview>(
      proposalId,
      {
        market: 'ALL',
        limit: 20,
        candidate_limit: 60,
        concurrency: 8,
      },
    )
  } catch (error) {
    ElMessage.error('Load impact preview failed')
    console.error('Load impact preview failed:', error)
  } finally {
    impactPreviewLoadingProposalId.value = null
  }
}

async function rollbackStrategyVersion(versionId: number) {
  try {
    setVersionRollingBack(versionId, true)
    const rolledBack = await adminApi.rollbackResearchWeightStrategyVersion<StrategyWeightVersion>(versionId)
    if (rolledBack?.id) {
      strategyVersions.value = strategyVersions.value.map((version) =>
        version.id === versionId ? { ...version, ...rolledBack } : version,
      )
    }
    ElMessage.success('Strategy version rolled back')
    await refreshStrategyVersions()
  } catch (error) {
    ElMessage.error('Rollback strategy version failed')
    console.error('Rollback strategy version failed:', error)
  } finally {
    setVersionRollingBack(versionId, false)
  }
}

async function loadStats() {
  try {
    loading.value = true
    const [overview, scheduler, readiness, report, factor, suggestions, audits, proposals] = await Promise.all([
      adminApi.getStatsOverview<StatsOverview>(),
      adminApi.getResearchReviewScheduler<ReviewSchedulerStatus>(),
      adminApi.getResearchReviewReadiness<ReviewReadiness>(),
      adminApi.getResearchReviewReport<ReviewReport>(),
      adminApi.getResearchReviewFactorReport<FactorReport>(),
      adminApi.getResearchWeightSuggestions<WeightSuggestions>({ min_reviews: 3 }),
      adminApi.getResearchWeightSuggestionAudits<WeightSuggestionAudit[]>({ limit: 20 }),
      adminApi.getResearchWeightStrategyPatchProposals<StrategyPatchProposal[]>({ limit: 20 }),
    ])
    stats.value = overview
    callsByDay.value = overview.calls_by_day || []
    callsByModel.value = overview.calls_by_model || []
    topUsers.value = overview.top_users || []
    reviewScheduler.value = scheduler
    reviewReadiness.value = readiness
    reviewReport.value = report
    factorReport.value = factor
    weightSuggestions.value = suggestions
    weightSuggestionAudits.value = audits
    patchProposals.value = proposals
    syncAuditNotes(audits)
  } catch (error) {
    ElMessage.error('加载统计失败')
    console.error('加载统计失败:', error)
  } finally {
    loading.value = false
  }
}

async function runReviewNow() {
  try {
    reviewRunning.value = true
    await adminApi.runResearchReview()
    ElMessage.success('复盘执行完成')
    await loadStats()
  } catch (error) {
    ElMessage.error('复盘执行失败')
    console.error('复盘执行失败:', error)
  } finally {
    reviewRunning.value = false
  }
}

onMounted(loadStats)
</script>

<style scoped>
.admin-stats {
  max-width: 1200px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}

.page-title {
  margin: 0 0 var(--space-1);
  font-size: 24px;
  font-weight: 800;
  color: var(--color-text);
  letter-spacing: -0.02em;
}

.page-subtitle {
  margin: 0;
  color: var(--color-text-muted);
  font-size: 14px;
}

.refresh-btn {
  min-height: 40px;
  padding: 0 16px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.refresh-btn:disabled {
  cursor: not-allowed;
  opacity: 0.7;
}

.skeleton-stats,
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--space-4);
}

.skeleton-stat-card,
.stat-card,
.chart-card,
.review-table-card,
.top-users-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.skeleton-stat-card {
  padding: var(--space-5);
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.skeleton-value,
.skeleton-label {
  border-radius: var(--radius-sm);
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
}

.skeleton-value {
  width: 80px;
  height: 28px;
}

.skeleton-label {
  width: 60px;
  height: 14px;
}

@keyframes skeleton-loading {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.stats-grid {
  margin-bottom: var(--space-6);
}

.stat-card {
  padding: var(--space-5);
  display: flex;
  align-items: center;
  gap: var(--space-4);
  transition: all var(--transition-base);
}

.stat-card:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-card-hover);
  transform: translateY(-1px);
}

.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-icon.users {
  background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%);
  color: #2563eb;
}

.stat-icon.active {
  background: linear-gradient(135deg, #dcfce7 0%, #bbf7d0 100%);
  color: #16a34a;
}

.stat-icon.models {
  background: linear-gradient(135deg, #f3e8ff 0%, #e9d5ff 100%);
  color: #9333ea;
}

.stat-icon.calls {
  background: linear-gradient(135deg, #ffedd5 0%, #fed7aa 100%);
  color: #ea580c;
}

.stat-icon.tokens {
  background: linear-gradient(135deg, #ccfbf1 0%, #99f6e4 100%);
  color: #0d9488;
}

.stat-icon.cost {
  background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%);
  color: #dc2626;
}

.stat-body {
  min-width: 0;
}

.stat-value,
.summary-value {
  font-size: 28px;
  font-weight: 800;
  color: var(--color-text);
  font-family: var(--font-number);
  line-height: 1.2;
  letter-spacing: -0.02em;
}

.stat-label,
.summary-label {
  margin-top: 2px;
  color: var(--color-text-muted);
  font-size: 13px;
  font-weight: 600;
}

.research-grid,
.charts-grid {
  display: grid;
  gap: var(--space-5);
  margin-bottom: var(--space-5);
}

.research-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.charts-grid {
  grid-template-columns: 2fr 1fr;
}

.chart-card,
.review-table-card,
.top-users-card {
  padding: var(--space-5);
}

.chart-card h3,
.review-table-card h3,
.top-users-card h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.header-actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

.run-review-btn {
  min-height: 26px;
  padding: 0 10px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.run-review-btn:disabled {
  cursor: not-allowed;
  opacity: 0.7;
}

.chart-period,
.status-chip {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.chart-period {
  color: var(--color-text-muted);
  background: var(--color-surface-muted);
}

.status-chip.running {
  background: #ecfdf5;
  color: #047857;
}

.status-chip.error {
  background: #fee2e2;
  color: #b91c1c;
}

.status-chip.idle {
  background: #eff6ff;
  color: #1d4ed8;
}

.status-chip.disabled {
  background: var(--color-surface-muted);
  color: var(--color-text-muted);
}

.review-summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
}

.summary-tile {
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
}

.scheduler-meta {
  display: grid;
  gap: var(--space-3);
}

.readiness-tables {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.table-chip {
  padding: 4px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.table-chip.ok {
  background: #ecfdf5;
  color: #047857;
}

.table-chip.missing {
  background: #fee2e2;
  color: #b91c1c;
}

.meta-row {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
  color: var(--color-text-secondary);
  font-size: 13px;
}

.meta-row strong {
  color: var(--color-text);
  font-weight: 700;
  text-align: right;
}

.scheduler-error {
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--color-danger-soft);
  color: #b91c1c;
  font-size: 12px;
  line-height: 1.5;
}

.chart-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 140px;
  color: var(--color-text-muted);
  font-size: 14px;
}

.chart-bar-chart {
  display: flex;
  align-items: flex-end;
  justify-content: space-around;
  height: 200px;
  gap: var(--space-2);
  padding-top: var(--space-4);
}

.bar-group {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  min-width: 0;
}

.bar {
  width: 100%;
  max-width: 40px;
  height: 100%;
  border-radius: 4px 4px 0 0;
  background: linear-gradient(180deg, #6366f1 0%, #8b5cf6 100%);
}

.bar-count {
  margin-top: var(--space-1);
  color: var(--color-text-secondary);
  font-size: 11px;
  font-weight: 700;
}

.bar-date {
  margin-top: 2px;
  color: var(--color-text-muted);
  font-size: 11px;
  white-space: nowrap;
}

.model-ranking,
.users-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.ranking-item,
.user-item,
.strategy-row {
  display: grid;
  align-items: center;
  gap: var(--space-3);
}

.ranking-item {
  grid-template-columns: 24px 1fr auto;
}

.rank-number,
.user-rank {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--color-surface-muted);
  color: var(--color-text-muted);
  font-weight: 700;
  font-family: var(--font-number);
}

.rank-number {
  width: 24px;
  height: 24px;
  font-size: 12px;
}

.rank-name,
.user-name,
.strategy-name {
  color: var(--color-text);
  font-weight: 600;
}

.rank-count {
  color: var(--color-text-secondary);
  font-size: 13px;
  font-weight: 700;
}

.strategy-table,
.factor-table,
.suggestion-table,
.audit-table,
.version-table {
  display: grid;
}

.strategy-row,
.factor-row,
.suggestion-row,
.audit-row,
.version-row {
  grid-template-columns: 1.3fr 0.8fr 0.8fr 0.9fr 0.8fr 1fr;
  padding: 12px 0;
  border-bottom: 1px solid var(--color-border);
  font-size: 13px;
  color: var(--color-text-secondary);
}

.factor-row {
  grid-template-columns: 1.3fr 0.7fr 0.7fr 0.8fr 0.8fr 0.9fr 0.9fr;
}

.suggestion-row {
  grid-template-columns: 1.1fr 0.6fr 0.6fr 0.8fr 0.9fr 2fr;
}

.audit-row {
  grid-template-columns: 1.2fr 0.7fr 0.5fr 1.4fr 1.8fr;
  align-items: center;
  gap: var(--space-2);
  padding: 10px 0;
}

.version-row {
  grid-template-columns: 0.7fr 0.7fr 1.1fr 1.1fr 1.5fr 0.8fr;
  align-items: center;
  gap: var(--space-2);
  padding: 10px 0;
  font-size: 12px;
}

.strategy-row:last-child,
.factor-row:last-child,
.suggestion-row:last-child,
.audit-row:last-child,
.version-row:last-child {
  border-bottom: none;
}

.strategy-head,
.factor-head,
.suggestion-head,
.audit-head,
.version-head {
  padding-top: 0;
  color: var(--color-text-muted);
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
}

.audit-section {
  margin-top: var(--space-5);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.audit-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}

.audit-section-header h4 {
  margin: 0;
  color: var(--color-text);
  font-size: 14px;
  font-weight: 700;
}

.text-btn {
  border: none;
  background: transparent;
  color: var(--color-primary);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.text-btn:disabled {
  cursor: not-allowed;
  opacity: 0.7;
}

.audit-status,
.mini-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 24px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 800;
}

.audit-status {
  padding: 0 8px;
}

.audit-status.accepted {
  background: #ecfdf5;
  color: #047857;
}

.audit-status.rejected {
  background: #fee2e2;
  color: #b91c1c;
}

.audit-status.pending {
  background: var(--color-surface-muted);
  color: var(--color-text-secondary);
}

.audit-notes {
  width: 100%;
  min-height: 34px;
  padding: 6px 8px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text);
  font: inherit;
  font-size: 12px;
  resize: vertical;
}

.audit-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.mini-btn {
  padding: 0 8px;
  border: 1px solid var(--color-border-strong);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  cursor: pointer;
}

.mini-btn.accept {
  border-color: #bbf7d0;
  color: #047857;
}

.mini-btn.reject {
  border-color: #fecaca;
  color: #b91c1c;
}

.mini-btn.patch {
  border-color: #bfdbfe;
  color: #1d4ed8;
}

.mini-btn:disabled {
  cursor: not-allowed;
  opacity: 0.7;
}

.audit-empty {
  padding: var(--space-4) 0 0;
  color: var(--color-text-muted);
  font-size: 13px;
}

.patch-preview {
  margin-top: var(--space-4);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.patch-preview-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.patch-preview-header h4 {
  margin: 0;
  color: var(--color-text);
  font-size: 14px;
  font-weight: 800;
}

.patch-preview-header p {
  margin: 3px 0 0;
  color: var(--color-text-muted);
  font-size: 12px;
}

.patch-preview-note {
  margin-bottom: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  background: #fff7ed;
  color: #9a3412;
  font-size: 12px;
  line-height: 1.5;
}

.proposal-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.proposal-hint {
  color: var(--color-text-muted);
  font-size: 12px;
}

.patch-table {
  display: grid;
}

.patch-row {
  display: grid;
  grid-template-columns: 1.4fr repeat(3, minmax(80px, 0.7fr));
  align-items: center;
  gap: var(--space-3);
  padding: 8px 0;
  border-bottom: 1px solid var(--color-border);
  color: var(--color-text-secondary);
  font-size: 12px;
}

.patch-row:last-child {
  border-bottom: none;
}

.patch-head {
  padding-top: 0;
  color: var(--color-text-muted);
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
}

.proposal-section {
  margin-top: var(--space-4);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.proposal-table {
  display: grid;
}

.proposal-row {
  display: grid;
  grid-template-columns: 0.8fr 1fr 0.8fr 1fr 0.6fr 1.7fr;
  align-items: center;
  gap: var(--space-3);
  padding: 10px 0;
  border-bottom: 1px solid var(--color-border);
  color: var(--color-text-secondary);
  font-size: 12px;
}

.proposal-row:last-child {
  border-bottom: none;
}

.proposal-head {
  padding-top: 0;
  color: var(--color-text-muted);
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
}

.action-chip {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 800;
}

.action-chip.increase {
  background: #ecfdf5;
  color: #047857;
}

.action-chip.decrease {
  background: #fee2e2;
  color: #b91c1c;
}

.action-chip.hold {
  background: var(--color-surface-muted);
  color: var(--color-text-secondary);
}

.positive {
  color: #047857;
  font-weight: 700;
}

.negative {
  color: #b91c1c;
  font-weight: 700;
}

.user-item {
  grid-template-columns: 32px 1fr;
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--color-border);
}

.user-item:last-child {
  border-bottom: none;
}

.user-rank {
  width: 32px;
  height: 32px;
  font-size: 14px;
  font-weight: 800;
}

.user-item.top3 .user-rank {
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: #fff;
}

.user-info {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.user-count {
  color: var(--color-text-muted);
  font-size: 12px;
}

.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-16) 0;
  text-align: center;
  color: var(--color-text-muted);
}

.error-state h3 {
  margin: var(--space-3) 0 var(--space-1);
  font-size: 18px;
  font-weight: 700;
  color: var(--color-text);
}

.error-state p {
  margin: 0 0 var(--space-4);
  font-size: 14px;
}

.error-icon {
  color: var(--color-text-muted);
}

@media (max-width: 1024px) {
  .research-grid,
  .charts-grid {
    grid-template-columns: 1fr;
  }

  .strategy-row,
  .factor-row,
  .suggestion-row,
  .audit-row,
  .patch-row,
  .version-row {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .strategy-head,
  .factor-head,
  .suggestion-head,
  .audit-head,
  .patch-head,
  .version-head {
    display: none;
  }
}

@media (max-width: 640px) {
  .page-header {
    flex-direction: column;
  }

  .refresh-btn {
    width: 100%;
  }

  .stats-grid {
    grid-template-columns: 1fr;
  }

  .stat-card {
    align-items: flex-start;
  }

  .review-summary-grid {
    grid-template-columns: 1fr;
  }

  .chart-bar-chart {
    height: 160px;
  }

  .meta-row {
    flex-direction: column;
  }
}
</style>
