import api from './client'

export const adminApi = {
  getModels: <T = unknown>() =>
    api.get<T>('/api/v1/admin/models'),
  createModel: <T = unknown>(data: unknown) =>
    api.post<T>('/api/v1/admin/models', data),
  updateModel: <T = unknown>(id: number, data: unknown) =>
    api.put<T>(`/api/v1/admin/models/${id}`, data),
  deleteModel: <T = unknown>(id: number) =>
    api.delete<T>(`/api/v1/admin/models/${id}`),
  toggleModel: <T = unknown>(id: number) =>
    api.patch<T>(`/api/v1/admin/models/${id}/toggle`),
  testModel: <T = unknown>(id: number) =>
    api.post<T>(`/api/v1/admin/models/${id}/test`),

  getUsers: <T = unknown>(params?: unknown) =>
    api.get<T>('/api/v1/admin/users', { params }),
  getUser: <T = unknown>(id: number) =>
    api.get<T>(`/api/v1/admin/users/${id}`),
  updateUser: <T = unknown>(id: number, data: unknown) =>
    api.put<T>(`/api/v1/admin/users/${id}`, data),
  updateUserQuota: <T = unknown>(id: number, data: unknown) =>
    api.put<T>(`/api/v1/admin/users/${id}/quota`, data),
  resetUserQuota: <T = unknown>(id: number) =>
    api.post<T>(`/api/v1/admin/users/${id}/reset-quota`),
  deleteUser: <T = unknown>(id: number) =>
    api.delete<T>(`/api/v1/admin/users/${id}`),

  getStatsOverview: <T = unknown>() =>
    api.get<T>('/api/v1/admin/stats/overview'),
  getDataQualityBaseline: <T = unknown>() =>
    api.get<T>('/api/v1/admin/stats/data-quality-baseline'),
  getCallsByDay: (days?: number) =>
    api.get('/api/v1/admin/stats/calls-by-day', { params: { days } }),
  getCallsByModel: () =>
    api.get('/api/v1/admin/stats/calls-by-model'),
  getTopUsers: (limit?: number) =>
    api.get('/api/v1/admin/stats/top-users', { params: { limit } }),
  getResearchReviewScheduler: <T = unknown>() =>
    api.get<T>('/api/v1/admin/stats/review-scheduler'),
  getResearchReviewReadiness: <T = unknown>(params?: unknown) =>
    api.get<T>('/api/v1/admin/stats/review-readiness', { params }),
  getResearchReviewReport: <T = unknown>(params?: unknown) =>
    api.get<T>('/api/v1/admin/stats/review-report', { params }),
  getResearchReviewFactorReport: <T = unknown>(params?: unknown) =>
    api.get<T>('/api/v1/admin/stats/review-factor-report', { params }),
  getResearchReviewFactorValidation: <T = unknown>(params?: unknown) =>
    api.get<T>('/api/v1/admin/stats/review-factor-validation', { params }),
  getResearchReviewTopNReport: <T = unknown>(params?: unknown) =>
    api.get<T>('/api/v1/admin/stats/review-topn-report', { params }),
  getResearchWeightSuggestions: <T = unknown>(params?: unknown) =>
    api.get<T>('/api/v1/admin/stats/review-weight-suggestions', { params }),
  getResearchWeightSuggestionAudits: <T = unknown>(params?: unknown) =>
    api.get<T>('/api/v1/admin/stats/review-weight-suggestion-audits', { params }),
  getResearchWeightStrategyPatchPreview: <T = unknown>(auditId: number, params?: unknown) =>
    api.get<T>(`/api/v1/admin/stats/review-weight-suggestion-audits/${auditId}/strategy-patch`, { params }),
  createResearchWeightStrategyPatchProposal: <T = unknown>(auditId: number, data?: unknown) =>
    api.post<T>(`/api/v1/admin/stats/review-weight-suggestion-audits/${auditId}/strategy-patch-proposals`, data || {}),
  getResearchWeightStrategyPatchProposals: <T = unknown>(params?: unknown) =>
    api.get<T>('/api/v1/admin/stats/strategy-weight-patch-proposals', { params }),
  updateResearchWeightStrategyPatchProposal: <T = unknown>(proposalId: number, data: unknown) =>
    api.patch<T>(`/api/v1/admin/stats/strategy-weight-patch-proposals/${proposalId}`, data),
  applyResearchWeightStrategyPatchProposal: <T = unknown>(proposalId: number, data?: unknown) =>
    api.post<T>(`/api/v1/admin/stats/strategy-weight-patch-proposals/${proposalId}/apply`, data || {}),
  getResearchWeightStrategyPatchImpactPreview: <T = unknown>(proposalId: number, params?: unknown) =>
    api.get<T>(`/api/v1/admin/stats/strategy-weight-patch-proposals/${proposalId}/impact-preview`, { params }),
  getResearchWeightStrategyVersions: <T = unknown>(params?: unknown) =>
    api.get<T>('/api/v1/admin/stats/strategy-weight-versions', { params }),
  rollbackResearchWeightStrategyVersion: <T = unknown>(versionId: number) =>
    api.post<T>(`/api/v1/admin/stats/strategy-weight-versions/${versionId}/rollback`),
  updateResearchWeightSuggestionAudit: <T = unknown>(auditId: number, data: unknown) =>
    api.patch<T>(`/api/v1/admin/stats/review-weight-suggestion-audits/${auditId}`, data),
  runResearchReview: <T = unknown>(params?: unknown) =>
    api.post<T>('/api/v1/admin/stats/review-scheduler/run-once', null, { params }),

  getLogs: <T = unknown>(params?: unknown) =>
    api.get<T>('/api/v1/admin/logs', { params }),
  getLogCount: <T = unknown>(params?: unknown) =>
    api.get<T>('/api/v1/admin/logs/count', { params }),
  exportLogs: <T = Blob>(params?: unknown) =>
    api.get<T>('/api/v1/admin/logs/export', { params, responseType: 'blob' }),
  getActivityLogs: <T = unknown>(params?: unknown) =>
    api.get<T>('/api/v1/admin/logs/activity', { params }),
  getActivityLogCount: <T = unknown>(params?: unknown) =>
    api.get<T>('/api/v1/admin/logs/activity/count', { params }),
}
