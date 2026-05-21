import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const frontendDir = path.join(root, 'frontend', 'web')
const distDir = path.join(frontendDir, 'dist')
const viteBin = path.join(frontendDir, 'node_modules', 'vite', 'bin', 'vite.js')
const port = Number(process.env.FRONTEND_SMOKE_PORT || 4175)
const host = '127.0.0.1'
const baseUrl = `http://${host}:${port}`
const smokePassword = 'DemoPass123'
const smokeDetailSymbol = '600000.SH'
const frontendRequire = createRequire(path.join(frontendDir, 'package.json'))
const { chromium, expect } = frontendRequire('@playwright/test')

if (!existsSync(distDir)) {
  throw new Error('frontend/web/dist is missing. Run npm run build before npm run smoke:frontend.')
}

if (!existsSync(viteBin)) {
  throw new Error('frontend/web/node_modules is missing Vite. Run npm install in frontend/web first.')
}

const preview = spawn(
  process.execPath,
  [viteBin, 'preview', '--host', host, '--port', String(port), '--strictPort'],
  {
    cwd: frontendDir,
    env: { ...process.env, BROWSER: 'none' },
    stdio: ['ignore', 'pipe', 'pipe'],
  },
)

let output = ''
preview.stdout.on('data', (chunk) => {
  output += chunk.toString()
})
preview.stderr.on('data', (chunk) => {
  output += chunk.toString()
})

function stopPreview() {
  if (!preview.killed) {
    preview.kill('SIGTERM')
  }
}

process.on('exit', stopPreview)
process.on('SIGINT', () => {
  stopPreview()
  process.exit(130)
})

async function waitForPreview() {
  const deadline = Date.now() + 15000
  let lastError

  while (Date.now() < deadline) {
    if (preview.exitCode !== null) {
      throw new Error(`vite preview exited early with code ${preview.exitCode}\n${output}`)
    }

    try {
      const response = await fetch(`${baseUrl}/login`)
      if (response.ok) return
      lastError = new Error(`HTTP ${response.status}`)
    } catch (error) {
      lastError = error
    }

    await new Promise((resolve) => setTimeout(resolve, 300))
  }

  throw new Error(`vite preview did not become ready: ${lastError?.message || 'timeout'}\n${output}`)
}

function mockJson(route, data, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json; charset=utf-8',
    body: JSON.stringify(data),
  })
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function installApiMocks(page) {
  let nextAlertId = 12
  const alertRows = [{
    id: 11,
    stock_symbol: '600000.SH',
    stock_name: 'Smoke SH Bank',
    alert_type: 'price_above',
    threshold: 10.8,
    is_active: true,
    triggered_at: null,
    created_at: '2026-05-07T09:30:00Z',
  }]
  const schedulerStatus = {
    running: true,
    enabled: true,
    interval_seconds: 60,
    last_result: {
      checked_count: 1,
      triggered_count: 0,
      items: [],
    },
  }
  const adminModels = [{
    id: 1,
    name: 'Smoke Admin Model',
    provider: 'openai',
    model_id: 'smoke-admin-model',
    is_active: true,
    allowed_roles: 'free,premium,admin',
    api_base_url: '',
    description: 'Smoke admin model',
  }]
  const adminUsers = [{
    id: 99,
    username: 'admin-smoke',
    email: 'admin-smoke@example.test',
    role: 'admin',
    is_active: true,
    daily_used: 3,
    daily_limit: 50,
    monthly_used: 20,
    monthly_limit: 500,
  }, {
    id: 2,
    username: 'regular-smoke',
    email: 'regular-smoke@example.test',
    role: 'free',
    is_active: true,
    daily_used: 1,
    daily_limit: 20,
    monthly_used: 4,
    monthly_limit: 200,
  }]
  const usageLogs = [{
    id: 1,
    created_at: '2026-05-07T09:40:00Z',
    username: 'regular-smoke',
    user_id: 2,
    model_name: 'Smoke Admin Model',
    stock_symbol: '600000.SH',
    total_tokens: 128,
    cost: 0.0012,
    status: 'success',
    response_time_ms: 321,
  }]
  const activityLogs = [{
    id: 1,
    created_at: '2026-05-07T09:41:00Z',
    username: 'admin-smoke',
    user_id: 99,
    action: 'login',
    target: 'admin',
    ip_address: '127.0.0.1',
    user_agent: 'frontend-smoke',
  }]
  const reviewScheduler = {
    enabled: true,
    running: false,
    interval_seconds: 600,
    last_run_at: '2026-05-07T09:45:00Z',
    last_error: null,
    last_result: {
      status: 'ok',
      processed: 1,
      created: 1,
    },
  }
  const reviewReadiness = {
    status: 'no_pending_reviews',
    review_date: '2026-05-07',
    offsets: ['T+1', 'T+5', 'T+20'],
    tables: {
      research_observations: true,
      observation_reviews: true,
    },
    summary: {
      observations: 1,
      reviews: 1,
      pending_reviews: 0,
      strategies_with_reviews: 1,
    },
    latest_snapshot_date: '2026-05-06',
    latest_review_date: '2026-05-07',
    pending_reviews: [],
    review_report_summary: {},
  }
  const reviewReport = {
    status: 'ok',
    summary: {
      reviews: 1,
      strategies: 1,
      avg_return_pct: 1.2,
    },
    by_strategy: [{
      strategy_id: 'retail_small',
      reviews: 1,
      positive_reviews: 1,
      avg_return_pct: 1.2,
      falsification_triggered: 0,
      risk_signal_valid: 1,
      win_rate: 1,
    }],
  }
  const reviewFactorReport = {
    status: 'ok',
    summary: {
      factors: 1,
      reviews: 1,
    },
    by_factor: [{
      factor: 'valuation',
      label: 'Valuation',
      reviews: 1,
      positive_reviews: 1,
      win_rate: 1,
      avg_return_pct: 1.2,
      avg_impact: 0.4,
      positive_impact_reviews: 1,
      negative_impact_reviews: 0,
      falsification_triggered: 0,
      risk_signal_valid: 1,
    }],
  }
  const reviewFactorValidation = {
    status: 'ok',
    factor: 'valuation',
    summary: {
      reviews: 1,
      positive_reviews: 1,
      win_rate: 1,
      avg_return_pct: 1.2,
      avg_impact: 0.4,
      falsification_triggered: 0,
      risk_signal_valid: 1,
      min_reviews: 3,
      validation_state: 'insufficient_samples',
    },
    by_offset: [{
      review_offset: 'T+1',
      reviews: 1,
      win_rate: 1,
      avg_return_pct: 1.2,
      avg_impact: 0.4,
    }],
    samples: [],
  }
  const topNReport = {
    status: 'ok',
    summary: {
      snapshots: 1,
      strategies: 1,
      rows: 1,
      reviews: 1,
    },
    by_top_n: [{
      rank_cutoff: 5,
      review_offset: 'T+1',
      observations: 1,
      reviews: 1,
      coverage_rate: 1,
      win_rate: 1,
      avg_return_pct: 1.2,
      worst_return_pct: 1.2,
      max_drawdown_pct: -0.5,
    }],
  }
  const weightSuggestions = {
    status: 'ok',
    summary: {
      suggestions: 0,
      eligible_factors: 0,
      min_reviews: 3,
    },
    suggestions: [],
  }

  const quoteQuality = {
    source: 'mock-fallback',
    updated_at: '2026-05-07T09:35:00Z',
    freshness: 'fallback',
    confidence: 'low',
    is_fallback: true,
    warnings: ['smoke fallback quote'],
  }
  const recommendationPayload = {
    status: 'ok',
    candidate_source: 'fallback',
    warnings: ['smoke fallback recommendation'],
    candidate_count: 1,
    scored_count: 1,
    cache_hit: false,
    updated_at: '2026-05-07T09:40:00Z',
    market_regime: {
      regime: 'range_bound',
      confidence: 'medium',
      signals: [
        { indicator: 'hs300_trend', value: 'neutral', detail: '沪深300围绕MA20震荡' },
      ],
      suggested_strategies: ['retail_small', 'value_quality'],
    },
    active_strategy: {
      id: 'retail_small',
      name: '小而美观察',
      selection_mode: 'auto',
      selection_reason: 'market_regime:range_bound',
      engine_strategy: 'retail_small',
    },
    recommendations: [{
      symbol: '600000.SH',
      name: 'Smoke SH Bank',
      sector: 'Banking',
      candidate_source: 'fallback',
      source: 'fallback',
      warnings: ['smoke fallback candidate'],
      score: 67,
      rating: { level: 'C', text: '观察' },
      price: 10.32,
      change_pct: -1.15,
      lot_cost: 1032,
      reasons: ['烟测候选'],
      risk_flags: ['低可信'],
      score_breakdown: [
        { key: 'base', label: '基础分', delta: 60, status: 'positive', message: 'base' },
        { key: 'data', label: '数据质量', delta: -10, status: 'warning', message: 'fallback' },
      ],
      data_grade: {
        grade: 'D',
        label: '开发兜底',
        analysis_scope: '仅用于烟测',
        warnings: ['smoke fallback candidate'],
      },
      veto_result: {
        passed: true,
        level: 'soft',
        warnings: [{ type: 'fallback', severity: 'soft', detail: '烟测软警告' }],
      },
    }],
  }

  await page.route('**/api/v1/auth/login', async (route) => {
    const request = route.request()
    const body = request.postDataJSON()
    if (body?.username !== 'smoke-user' || body?.password !== smokePassword) {
      await mockJson(route, { detail: 'invalid smoke credentials' }, 401)
      return
    }

    await mockJson(route, { access_token: 'smoke-token' })
  })

  await page.route('**/api/v1/auth/me', async (route) => {
    const auth = route.request().headers().authorization
    if (!auth) {
      await mockJson(route, { detail: 'not authenticated' }, 401)
      return
    }

    if (auth.includes('admin-token')) {
      await mockJson(route, {
        id: 99,
        username: 'admin-smoke',
        email: 'admin-smoke@example.test',
        role: 'admin',
        is_active: true,
        created_at: '2026-05-07T09:00:00Z',
      })
      return
    }

    await mockJson(route, {
      id: 1,
      username: 'smoke-user',
      email: 'smoke@example.test',
      role: 'user',
      is_active: true,
      created_at: '2026-05-07T09:00:00Z',
    })
  })

  await page.route('**/api/v1/auth/me/password', async (route) => {
    const body = route.request().postDataJSON()
    if (body?.current_password !== smokePassword) {
      await mockJson(route, { detail: 'invalid current password' }, 400)
      return
    }

    await mockJson(route, { message: 'Password updated' })
  })

  await page.route('**/api/v1/analysis/ai/models', async (route) => {
    await mockJson(route, [{
      id: 1,
      name: 'Smoke Model',
      provider: 'smoke',
      health_status: 'healthy',
    }])
  })

  await page.route('**/api/v1/analysis/ai/quota', async (route) => {
    await mockJson(route, {
      daily_remaining: 19,
      daily_limit: 20,
      monthly_remaining: 99,
      monthly_limit: 100,
    })
  })

  await page.route('**/api/v1/analysis/public-health', async (route) => {
    await mockJson(route, {
      status: 'ok',
      services: [
        { service: 'market-service', status: 'ok' },
        { service: 'user-service', status: 'ok' },
        { service: 'analysis-service', status: 'ok' },
      ],
    })
  })

  await page.route('**/api/v1/admin/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const method = request.method()

    if (url.pathname === '/api/v1/admin/stats/overview' && method === 'GET') {
      await mockJson(route, {
        total_users: 2,
        active_users_today: 1,
        active_models: 1,
        total_api_calls_today: 7,
        total_tokens_today: 128,
        total_cost_month: 0.024,
        calls_by_day: [
          { date: '2026-05-06', count: 3 },
          { date: '2026-05-07', count: 4 },
        ],
        calls_by_model: [
          { model_name: 'Smoke Admin Model', count: 7 },
        ],
        top_users: [
          { username: 'regular-smoke', count: 5 },
        ],
      })
      return
    }

    if (url.pathname === '/api/v1/admin/stats/review-scheduler' && method === 'GET') {
      await mockJson(route, reviewScheduler)
      return
    }

    if (url.pathname === '/api/v1/admin/stats/review-readiness' && method === 'GET') {
      await mockJson(route, reviewReadiness)
      return
    }

    if (url.pathname === '/api/v1/admin/stats/review-report' && method === 'GET') {
      await mockJson(route, reviewReport)
      return
    }

    if (url.pathname === '/api/v1/admin/stats/review-factor-report' && method === 'GET') {
      await mockJson(route, reviewFactorReport)
      return
    }

    if (url.pathname === '/api/v1/admin/stats/review-factor-validation' && method === 'GET') {
      await mockJson(route, reviewFactorValidation)
      return
    }

    if (url.pathname === '/api/v1/admin/stats/review-topn-report' && method === 'GET') {
      await mockJson(route, topNReport)
      return
    }

    if (url.pathname === '/api/v1/admin/stats/data-quality-baseline' && method === 'GET') {
      await mockJson(route, {
        status: 'ok',
        summary: { total: 1, ok: 1, degraded: 0, unavailable: 0 },
        items: [{
          key: 'smoke-quotes',
          label: 'Smoke Quotes',
          status: 'ok',
          source: 'smoke',
          updated_at: '2026-05-07T09:40:00Z',
          row_count: 1,
          warnings: [],
        }],
      })
      return
    }

    if (url.pathname === '/api/v1/admin/stats/review-weight-suggestions' && method === 'GET') {
      await mockJson(route, weightSuggestions)
      return
    }

    if (url.pathname === '/api/v1/admin/stats/review-weight-suggestion-audits' && method === 'GET') {
      await mockJson(route, [])
      return
    }

    if (url.pathname === '/api/v1/admin/stats/strategy-weight-patch-proposals' && method === 'GET') {
      await mockJson(route, [])
      return
    }

    if (url.pathname === '/api/v1/admin/stats/review-readiness' && method === 'GET') {
      await mockJson(route, reviewReadiness)
      return
    }

    if (url.pathname === '/api/v1/admin/stats/review-report' && method === 'GET') {
      await mockJson(route, reviewReport)
      return
    }

    if (url.pathname === '/api/v1/admin/stats/review-factor-report' && method === 'GET') {
      await mockJson(route, reviewFactorReport)
      return
    }

    if (url.pathname === '/api/v1/admin/stats/review-factor-validation' && method === 'GET') {
      await mockJson(route, reviewFactorValidation)
      return
    }

    if (url.pathname === '/api/v1/admin/stats/review-topn-report' && method === 'GET') {
      await mockJson(route, topNReport)
      return
    }

    if (url.pathname === '/api/v1/admin/stats/data-quality-baseline' && method === 'GET') {
      await mockJson(route, {
        status: 'ok',
        summary: { total: 1, ok: 1, degraded: 0, unavailable: 0 },
        items: [{
          key: 'smoke-quotes',
          label: 'Smoke Quotes',
          status: 'ok',
          source: 'smoke',
          updated_at: '2026-05-07T09:40:00Z',
          row_count: 1,
          warnings: [],
        }],
      })
      return
    }

    if (url.pathname === '/api/v1/admin/models' && method === 'GET') {
      await mockJson(route, adminModels)
      return
    }

    const modelTestMatch = url.pathname.match(/^\/api\/v1\/admin\/models\/(\d+)\/test$/)
    if (modelTestMatch && method === 'POST') {
      await mockJson(route, { status: 'success' })
      return
    }

    const modelToggleMatch = url.pathname.match(/^\/api\/v1\/admin\/models\/(\d+)\/toggle$/)
    if (modelToggleMatch && method === 'PATCH') {
      const id = Number(modelToggleMatch[1])
      const model = adminModels.find((item) => item.id === id)
      if (!model) {
        await mockJson(route, { detail: 'model not found' }, 404)
        return
      }
      model.is_active = !model.is_active
      await mockJson(route, model)
      return
    }

    if (url.pathname === '/api/v1/admin/users' && method === 'GET') {
      await mockJson(route, { items: adminUsers, total: adminUsers.length })
      return
    }

    if (url.pathname === '/api/v1/admin/logs/activity' && method === 'GET') {
      await mockJson(route, activityLogs)
      return
    }

    if (url.pathname === '/api/v1/admin/logs/export' && method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'text/csv; charset=utf-8',
        body: 'created_at,username,model_name,status\n2026-05-07T09:40:00Z,regular-smoke,Smoke Admin Model,success\n',
      })
      return
    }

    if (url.pathname === '/api/v1/admin/logs' && method === 'GET') {
      await mockJson(route, usageLogs)
      return
    }

    await mockJson(route, { detail: 'unhandled smoke admin route' }, 404)
  })

  await page.route('**/api/v1/alerts**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const method = request.method()

    if (url.pathname === '/api/v1/alerts/scheduler/status' && method === 'GET') {
      await mockJson(route, schedulerStatus)
      return
    }

    if (url.pathname === '/api/v1/alerts/check' && method === 'POST') {
      const result = {
        checked_count: alertRows.filter((row) => row.is_active).length,
        triggered_count: 1,
        items: [{
          alert_id: 11,
          status: 'triggered',
          message: 'Smoke price crossed above 10.80',
        }],
      }
      schedulerStatus.last_result = result
      await mockJson(route, result)
      return
    }

    if (url.pathname === '/api/v1/alerts' && method === 'GET') {
      await mockJson(route, alertRows)
      return
    }

    if (url.pathname === '/api/v1/alerts' && method === 'POST') {
      const body = request.postDataJSON()
      const created = {
        id: nextAlertId++,
        stock_symbol: body?.stock_id === 101 ? '600000.SH' : 'UNKNOWN',
        stock_name: body?.stock_id === 101 ? 'Smoke SH Bank' : 'Smoke Stock',
        alert_type: body?.alert_type || 'price_above',
        threshold: Number(body?.threshold ?? 0),
        is_active: true,
        triggered_at: null,
        created_at: '2026-05-07T09:45:00Z',
      }
      alertRows.push(created)
      await mockJson(route, created, 201)
      return
    }

    const toggleMatch = url.pathname.match(/^\/api\/v1\/alerts\/(\d+)\/toggle$/)
    if (toggleMatch && method === 'PUT') {
      const id = Number(toggleMatch[1])
      const row = alertRows.find((item) => item.id === id)
      if (!row) {
        await mockJson(route, { detail: 'alert not found' }, 404)
        return
      }
      row.is_active = !row.is_active
      await mockJson(route, row)
      return
    }

    const deleteMatch = url.pathname.match(/^\/api\/v1\/alerts\/(\d+)$/)
    if (deleteMatch && method === 'DELETE') {
      const id = Number(deleteMatch[1])
      const index = alertRows.findIndex((item) => item.id === id)
      if (index === -1) {
        await mockJson(route, { detail: 'alert not found' }, 404)
        return
      }
      alertRows.splice(index, 1)
      await mockJson(route, { ok: true })
      return
    }

    await mockJson(route, { detail: 'unhandled smoke alert route' }, 404)
  })

  await page.route('**/api/v1/analysis/score/batch/recommend**', async (route) => {
    await delay(500)
    await mockJson(route, recommendationPayload)
  })

  await page.route('**/api/v1/analysis/ai/model-health**', async (route) => {
    await mockJson(route, {
      models: [{ id: 1, name: 'Smoke Model', status: 'healthy' }],
    })
  })

  await page.route('**/api/v1/analysis/ai/readiness/**', async (route) => {
    await mockJson(route, {
      ready: true,
      quality: 'good',
      items: {
        quote: { label: '行情', ready: true, count: 1, quality: { source: 'mock-fallback', confidence: 'low' } },
        news: { label: '新闻', ready: true, count: 1, quality: { source: 'mock-news', confidence: 'medium' } },
      },
      blocking: [],
      missing_context: [],
    })
  })

  await page.route('**/api/v1/analysis/ai/batch-summary', async (route) => {
    await mockJson(route, {
      items: [{
        symbol: '600000.SH',
        summary: 'Smoke watchlist AI summary',
        batch_cache_hit: true,
        model_status: 'ok',
        risk_lights: {
          data: { label: 'Mock Data', level: 'yellow', message: 'smoke watchlist summary' },
        },
        data_quality: {
          source: 'mock-watchlist-summary',
          updated_at: '2026-05-07T09:42:00Z',
          freshness: 'intraday',
          confidence: 'medium',
          is_fallback: false,
          warnings: [],
        },
      }],
    })
  })

  await page.route('**/api/v1/kline/**', async (route) => {
    await mockJson(route, {
      data: [
        { date: '2026-05-05', open: 10.0, high: 10.8, low: 9.8, close: 10.2, volume: 1000 },
        { date: '2026-05-06', open: 10.2, high: 10.9, low: 10.1, close: 10.6, volume: 1200 },
        { date: '2026-05-07', open: 10.6, high: 10.7, low: 10.0, close: 10.3, volume: 900 },
      ],
      indicators: {},
      source: 'mock-kline',
      data_quality: {
        source: 'mock-kline',
        updated_at: '2026-05-07T09:35:00Z',
        freshness: 'daily',
        confidence: 'medium',
        is_fallback: false,
        warnings: [],
      },
    })
  })

  await page.route('**/api/v1/crawl/**/status', async (route) => {
    await mockJson(route, {
      statuses: {
        news: null,
        announcements: null,
        financials: null,
      },
    })
  })

  await page.route('**/api/v1/crawl/**/news', async (route) => {
    await mockJson(route, {
      symbol: '600000',
      data_type: 'news',
      status: 'fresh',
      skipped: true,
      from_cache: true,
      message: '5分钟前已更新，无需重复采集',
      fetched: 1,
      saved: 1,
      updated_at: '2026-05-07T09:20:00Z',
      crawl_status: {
        status: 'fresh',
        message: '5分钟前已更新，无需重复采集',
        finished_at: '2026-05-07T09:20:00Z',
        saved: 1,
      },
    })
  })

  await page.route('**/api/v1/news/**', async (route) => {
    await mockJson(route, {
      news: [{
        id: 1,
        title: 'Smoke News Title',
        source: 'SmokeWire',
        sentiment: '中性',
        publish_time: '2026-05-07T09:20:00Z',
      }],
      sentiment_summary: {
        positive: 0,
        neutral: 1,
        negative: 0,
        dominant: '中性',
      },
      data_quality: {
        news: {
          source: 'mock-news',
          updated_at: '2026-05-07T09:20:00Z',
          freshness: 'intraday',
          confidence: 'medium',
          warnings: [],
        },
      },
    })
  })

  await page.route('**/api/v1/announcements/**', async (route) => {
    await mockJson(route, {
      announcements: [{
        id: 1,
        title: 'Smoke Announcement',
        category: '临时公告',
        announce_date: '2026-05-07T00:00:00Z',
      }],
      data_quality: {
        announcements: {
          source: 'mock-announcement',
          updated_at: '2026-05-07T09:00:00Z',
          freshness: 'daily',
          confidence: 'medium',
          warnings: [],
        },
      },
    })
  })

  await page.route('**/api/v1/financials/**', async (route) => {
    await mockJson(route, {
      reports: [{
        report_date: '2026-03-31',
        report_type: 'Q1',
        revenue: 1000000000,
        revenue_yoy: 12.3,
        net_profit: 150000000,
        net_profit_yoy: 9.1,
        gross_margin: 35.2,
        net_margin: 15.0,
        roe: 12.8,
        eps: 1.24,
        pe_ttm: 14.6,
        pb: 2.1,
      }],
      data_quality: {
        financial: {
          source: 'mock-financial',
          updated_at: '2026-05-07T08:00:00Z',
          freshness: 'quarterly',
          confidence: 'medium',
          warnings: [],
        },
      },
    })
  })

  await page.route('**/api/v1/quotes/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/money-flow')) {
      await mockJson(route, {
        data: [{
          date: '2026-05-07',
          main_inflow: 12000000,
          super_inflow: 5000000,
          big_inflow: 3000000,
          mid_inflow: -1000000,
          small_inflow: -2000000,
        }],
        data_quality: {
          source: 'mock-money-flow',
          updated_at: '2026-05-07T09:10:00Z',
          freshness: 'daily',
          confidence: 'medium',
          warnings: [],
        },
      })
      return
    }

    await mockJson(route, {
      symbol: smokeDetailSymbol,
      name: 'Smoke SH Bank',
      price: 10.32,
      change: -0.12,
      change_pct: -1.15,
      high: 10.68,
      low: 10.11,
      open: 10.55,
      volume: 123456,
      turnover: 7890123,
      turnover_rate: 1.23,
      pe_ttm: 14.6,
      total_mv: 12000000000,
      circ_mv: 9800000000,
      up_limit: 11.35,
      down_limit: 9.29,
      timestamp: '2026-05-07T09:35:00Z',
      source: 'mock-fallback',
      data_quality: quoteQuality,
    })
  })

  await page.route('**/api/v1/watchlists**', async (route) => {
    await mockJson(route, [{
      id: 1,
      name: 'Smoke Watchlist',
      items: [{
        stock_id: 101,
        symbol: '600000.SH',
        name: 'Smoke SH Bank',
        market: 'SH',
        sector: 'Banking',
      }],
    }])
  })

  await page.route('**/api/v1/stocks**', async (route) => {
    const url = new URL(route.request().url())
    const detailMatch = url.pathname.match(/\/api\/v1\/stocks\/([^/]+)$/)
    if (detailMatch) {
      await mockJson(route, {
        name: 'Smoke SH Bank',
        sector: 'Banking',
        list_date: '1999-11-10',
        latest_price: 10.32,
        total_mv: 12000000000,
        circ_mv: 9800000000,
        total_shares: 1100000000,
        float_shares: 950000000,
      })
      return
    }

    const market = url.searchParams.get('market') || 'SH'
    const rows = market === 'SZ'
      ? [{ symbol: '000001.SZ', name: 'Smoke SZ Bank', market: 'SZ', sector: 'Banking' }]
      : [{ symbol: '600000.SH', name: 'Smoke SH Bank', market: 'SH', sector: 'Banking' }]

    await mockJson(route, { stocks: rows })
  })
}

async function runSmoke() {
  await waitForPreview()

  const browser = await launchBrowser()
  const page = await newSmokePage(browser)

  try {
    await page.goto('/login')
    await expect(page.locator('.form-wrapper')).toBeVisible()
    await expect(page.locator('.submit-btn')).toBeVisible()
    console.log('ok /login renders in browser')

    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'AstraQuant' })).toBeVisible()
    await expect(page.getByText('AI 驱动的 A 股观察平台')).toBeVisible()
    await expect(page.getByText('每日观察池、自选同步与预警管理需要登录后使用。')).toBeVisible()
    await expect(page.getByRole('button', { name: '登录查看观察池' }).first()).toBeVisible()
    console.log('ok public home hides observation rows before login')

    await page.goto('/recommendations')
    await expect(page).toHaveURL(/\/login\?redirect=(%2F|\/)recommendations$/)
    console.log('ok daily observation route requires login')

    await page.goto('/watchlist')
    await expect(page).toHaveURL(/\/login\?redirect=(%2F|\/)watchlist$/)
    console.log('ok protected route redirects to login')

    await page.locator('.login-form input').nth(0).fill('smoke-user')
    await page.locator('.login-form input').nth(1).fill(smokePassword)
    await page.locator('.submit-btn').click()
    await expect(page).toHaveURL(`${baseUrl}/watchlist`)
    console.log('ok login form posts mocked API and follows redirect')

    await expect(page.locator('.watchlist-page')).toBeVisible()
    await expect(page.getByText('600000.SH')).toBeVisible()
    await expect(page.getByText('Smoke SH Bank')).toBeVisible()
    await expect(page.getByText('Smoke watchlist AI summary')).toBeVisible()
    await expect(page.getByText('Mock Data')).toBeVisible()
    console.log('ok /watchlist renders mocked watchlist and batch summary API data')

    await page.goto('/alerts')
    await expect(page.locator('.alerts-page')).toBeVisible()
    await expect(page.locator('.watchlist-card')).toBeVisible()
    await expect(page.getByText('600000.SH').first()).toBeVisible()
    await expect(page.getByText('Smoke SH Bank').first()).toBeVisible()
    await expect(page.getByText('10.8')).toBeVisible()
    await page.locator('.header-actions .el-button').first().click()
    await expect(page.locator('.check-result.triggered')).toContainText('Smoke price crossed above 10.80')
    console.log('ok /alerts renders mocked watchlist, alert rules, and check result path')

    await page.locator('.watchlist-table .el-table__body-wrapper tbody tr:visible').first().locator('button').click()
    const createAlertDialog = page.locator('.el-dialog:visible')
    await expect(createAlertDialog).toBeVisible()
    await createAlertDialog.locator('.el-input-number input').fill('9.99')
    await createAlertDialog.locator('.el-dialog__footer .el-button--primary').click()
    await expect(createAlertDialog).toBeHidden()

    const alertRuleRows = page.locator('.alerts-page > .el-table .el-table__body-wrapper tbody tr:visible')
    let createdAlertRow = alertRuleRows.filter({ hasText: '9.99' }).first()
    await expect(createdAlertRow).toBeVisible()
    await createdAlertRow.locator('button').first().click()

    createdAlertRow = alertRuleRows.filter({ hasText: '9.99' }).first()
    await expect(createdAlertRow.locator('.el-tag--info')).toBeVisible()
    await createdAlertRow.locator('button').nth(1).click()
    await page.locator('.el-message-box:visible .el-button--primary').click()
    await expect(alertRuleRows.filter({ hasText: '9.99' })).toHaveCount(0)
    console.log('ok /alerts creates, toggles, and deletes a mocked alert rule')

    await page.goto('/admin')
    await expect(page).toHaveURL(/\/403\?from=/)
    await expect(page.locator('.status-code')).toHaveText('403')
    console.log('ok non-admin user is blocked from /admin')

    await page.goto('/')
    await expect(page.locator('.signed-home')).toBeVisible()
    await expect(page.locator('.market-summary-card')).toBeVisible()
    await expect(page.getByText('Smoke SH Bank')).toBeVisible()
    console.log('ok signed-in home renders protected daily observation pool')

    await page.goto('/recommendations')
    await expect(page.getByRole('heading', { name: '每日观察池' })).toBeVisible()
    await expect(page.getByText('可信状态：调试数据')).toBeVisible()
    await expect(page.getByText('Smoke SH Bank')).toBeVisible()
    await expect(page.locator('.card-actions .el-button', { hasText: '加自选' }).first()).toHaveClass(/is-disabled/)
    console.log('ok recommendations page blocks fallback candidate action')

    await page.goto('/stocks')
    await expect(page.locator('.stocks-page')).toBeVisible()
    await expect(page.getByText('600000.SH')).toBeVisible()
    await expect(page.getByText('Smoke SH Bank')).toBeVisible()
    await expect(page.getByText('000001.SZ')).toBeVisible()
    console.log('ok /stocks renders mocked async API data')

    await page.goto(`/stocks/${smokeDetailSymbol}`)
    await expect(page.locator('.stock-detail')).toBeVisible()
    await expect(page.locator('.quote-warning')).toBeVisible()
    await expect(page.locator('.quote-panel .quality-item').filter({ hasText: 'mock-fallback' })).toBeVisible()
    await expect(page.getByRole('button', { name: '刷新缓存' })).toBeVisible()
    await page.getByRole('button', { name: '采集最新新闻' }).click()
    await expect(page.getByText('5分钟前已更新，无需重复采集', { exact: true })).toBeVisible()
    console.log('ok stock detail surfaces quote quality and manual news crawl cooldown signals')

    await page.goto('/about')
    await expect(page.locator('.about-page')).toBeVisible()
    await expect(page.locator('.about-hero')).toBeVisible()
    await expect(page.locator('.disclaimer-card')).toBeVisible()
    console.log('ok /about renders product and disclaimer content')

    await page.goto('/settings')
    await expect(page.locator('.settings-page')).toBeVisible()
    await expect(page.locator('.setting-card')).toHaveCount(3)
    await page.locator('.settings-page .el-button--success').click()
    await expect(page.locator('.test-result.success')).toBeVisible()
    console.log('ok /settings renders and tests mocked gateway connection')

    await page.goto('/profile')
    await expect(page.locator('.profile-page')).toBeVisible()
    await expect(page.locator('.profile-card')).toBeVisible()
    await expect(page.locator('.el-dialog:visible')).toHaveCount(0)
    await page.locator('.profile-page .edit-btn').click()
    const passwordDialog = page.locator('.el-dialog:visible')
    await expect(passwordDialog).toBeVisible()
    await passwordDialog.locator('input').nth(0).fill(smokePassword)
    await passwordDialog.locator('input').nth(1).fill('NewPass123')
    await passwordDialog.locator('input').nth(2).fill('NewPass123')
    await passwordDialog.locator('.el-dialog__footer .el-button--primary').click()
    await expect(passwordDialog).toBeHidden()
    console.log('ok /profile hides password form until requested and submits mocked change')

    await page.goto('/403')
    await expect(page.locator('.forbidden-page')).toBeVisible()
    await expect(page.locator('.status-code')).toHaveText('403')
    console.log('ok /403 renders forbidden page')

    await page.evaluate(() => {
      localStorage.setItem('access_token', 'admin-token')
    })

    await page.goto('/admin/stats')
    await expect(page.locator('.admin-layout')).toBeVisible()
    await expect(page.locator('.admin-stats')).toBeVisible()
    await expect(page.getByText('Smoke Admin Model')).toBeVisible()
    await expect(page.getByText('regular-smoke')).toBeVisible()
    console.log('ok /admin/stats renders mocked admin overview')

    await page.goto('/admin/models')
    await expect(page.locator('.admin-models')).toBeVisible()
    await expect(page.locator('.model-card .model-name', { hasText: 'Smoke Admin Model' })).toBeVisible()
    await page.locator('.model-card .model-actions .el-button').nth(2).click()
    await expect(page.locator('.model-card .test-result.success')).toBeVisible()
    console.log('ok /admin/models renders and tests mocked model connection')

    await page.goto('/admin/users')
    await expect(page.locator('.admin-users')).toBeVisible()
    await expect(page.locator('.user-card .user-name', { hasText: 'admin-smoke' })).toBeVisible()
    await expect(page.locator('.user-card .user-name', { hasText: 'regular-smoke' })).toBeVisible()
    const adminUserRow = page.locator('.user-card').filter({ hasText: 'admin-smoke' }).first()
    await expect(adminUserRow.locator('.user-actions .el-button').nth(2)).toBeDisabled()
    console.log('ok /admin/users renders and protects admin account delete action')

    await page.goto('/admin/logs')
    await expect(page.locator('.admin-logs')).toBeVisible()
    await expect(page.getByText('600000.SH')).toBeVisible()
    await page.locator('.admin-logs .tab-button').nth(1).click()
    await expect(page.getByText('login')).toBeVisible()
    console.log('ok /admin/logs renders usage and activity tabs')

    await page.close().catch(() => {})
    const mobilePage = await newSmokePage(browser, { width: 390, height: 844 })
    try {
      await mobilePage.goto('/login')
      await mobilePage.evaluate(() => {
        localStorage.setItem('access_token', 'smoke-token')
      })
      for (const route of ['/', '/recommendations', '/watchlist', '/stocks', `/stocks/${smokeDetailSymbol}`, '/alerts']) {
        await mobilePage.goto(route)
        await expect(mobilePage.locator('body')).toBeVisible()
        const metrics = await mobilePage.evaluate(() => ({
          scrollWidth: document.documentElement.scrollWidth,
          clientWidth: document.documentElement.clientWidth,
        }))
        expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth + 2)
      }
      console.log('ok mobile viewport has no horizontal overflow on core pages')
    } finally {
      await mobilePage.close().catch(() => {})
    }
  } finally {
    await page.close().catch(() => {})
    await browser.close().catch(() => {})
  }
}

async function newSmokePage(browser, viewport = { width: 1280, height: 800 }) {
  const page = await browser.newPage({
    viewport,
    baseURL: baseUrl,
  })
  page.setDefaultTimeout(10000)
  await installApiMocks(page)
  return page
}

async function launchBrowser() {
  try {
    return await chromium.launch()
  } catch (error) {
    const message = String(error?.message || error)
    if (!message.includes('Executable doesn')) {
      throw error
    }

    console.warn('Playwright bundled Chromium is missing; falling back to the local Chrome channel.')
    return chromium.launch({ channel: 'chrome' })
  }
}

try {
  await runSmoke()
} finally {
  stopPreview()
}
