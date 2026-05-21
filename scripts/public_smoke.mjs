#!/usr/bin/env node
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const baseUrl = (process.env.PUBLIC_SMOKE_BASE_URL || 'https://yhang.cc.cd').replace(/\/+$/, '')
const username = process.env.PUBLIC_SMOKE_USERNAME || ''
const password = process.env.PUBLIC_SMOKE_PASSWORD || ''
const runWrites = process.env.PUBLIC_SMOKE_WRITE_TESTS === 'true' || process.argv.includes('--writes')
const runBrowser = process.env.PUBLIC_SMOKE_BROWSER !== 'false' && !process.argv.includes('--no-browser')

const currentUser = { role: '' }

const apiTests = [
  ['auth.me', '/api/v1/auth/me', 10000],
  ['stocks.list', '/api/v1/stocks?limit=5', 10000],
  ['stocks.detail', '/api/v1/stocks/600000.SH', 12000],
  ['stocks.search', '/api/v1/search?q=600000&limit=5', 10000],
  ['quotes.detail', '/api/v1/quotes/600000.SH', 15000],
  ['quotes.money_flow', '/api/v1/quotes/600000.SH/money-flow?days=5', 15000],
  ['kline.daily', '/api/v1/kline/600000.SH?period=1d&limit=5', 15000],
  ['sectors.list', '/api/v1/sectors', 10000],
  ['sectors.stocks', '/api/v1/sectors/%E9%87%91%E8%9E%8D/stocks?limit=3', 10000],
  ['indices.list', '/api/v1/indices', 10000],
  ['news.list', '/api/v1/news/600000.SH?limit=5', 12000],
  ['announcements.list', '/api/v1/announcements/600000.SH?limit=5', 12000],
  ['financials.list', '/api/v1/financials/600000.SH', 12000],
  ['crawl.status', '/api/v1/crawl/600000.SH/status', 10000],
  ['watchlists.list', '/api/v1/watchlists', 10000],
  ['alerts.list', '/api/v1/alerts', 10000],
  ['alerts.scheduler', '/api/v1/alerts/scheduler/status', 10000],
  ['analysis.public_health', '/api/v1/analysis/public-health', 10000],
  ['analysis.system_health', '/api/v1/analysis/system-health', 10000],
  ['analysis.technical', '/api/v1/analysis/technical/600000.SH?indicators=ma5', 20000],
  ['analysis.compare', '/api/v1/analysis/compare?symbols=600000.SH,000001.SZ&indicators=ma5&limit=20', 30000],
  ['analysis.performance', '/api/v1/analysis/compare/performance?symbols=600000.SH,000001.SZ&periods=5d', 30000],
  ['analysis.patterns', '/api/v1/analysis/patterns/600000.SH', 20000],
  ['analysis.score', '/api/v1/analysis/score/600000.SH', 30000],
  ['analysis.recommend', '/api/v1/analysis/score/batch/recommend?market=ALL&limit=5&max_candidates=20&include_evidence=false&include_debate=false&concurrency=4', 30000],
  ['analysis.reviews', '/api/v1/analysis/reviews/recent?symbols=600000.SH&limit_per_symbol=1', 10000],
  ['analysis.financial', '/api/v1/analysis/financial/600000.SH', 15000],
  ['analysis.dupont', '/api/v1/analysis/financial/600000.SH/dupont', 15000],
  ['analysis.fscore', '/api/v1/analysis/financial/600000.SH/fscore', 15000],
  ['analysis.valuation', '/api/v1/analysis/valuation/600000.SH', 15000],
  ['analysis.pe_band', '/api/v1/analysis/valuation/600000.SH/pe-band', 15000],
  ['ai.models', '/api/v1/analysis/ai/models', 10000],
  ['ai.quota', '/api/v1/analysis/ai/quota', 10000],
  ['ai.readiness', '/api/v1/analysis/ai/readiness/600000.SH', 15000],
  ['admin.overview', '/api/v1/admin/stats/overview', 10000],
  ['admin.data_quality', '/api/v1/admin/stats/data-quality-baseline', 10000],
  ['admin.models', '/api/v1/admin/models', 10000],
  ['admin.users', '/api/v1/admin/users?limit=5', 10000],
  ['admin.logs', '/api/v1/admin/logs?limit=5', 10000],
  ['admin.logs_count', '/api/v1/admin/logs/count', 10000],
]

const publicPageRoutes = [
  '/',
  '/stocks',
  '/stocks/600000.SH',
  '/compare',
  '/about',
]

const protectedPageRoutes = [
  '/recommendations',
  '/watchlist',
  '/alerts',
  '/profile',
  '/settings',
  '/admin/stats',
  '/admin/models',
  '/admin/users',
  '/admin/logs',
]

const pageRoutes = [...publicPageRoutes, ...protectedPageRoutes]

const failures = []
const details = []

function record(name, ok, data = {}) {
  const entry = { name, ok, ...data }
  details.push(entry)
  const icon = ok ? 'OK' : 'FAIL'
  console.log(`${icon} ${name}${data.status ? ` (${data.status})` : ''}${data.ms ? ` ${data.ms}ms` : ''}`)
  if (!ok) failures.push(entry)
}

function requireCredentials() {
  if (!username || !password) {
    console.error('Set PUBLIC_SMOKE_USERNAME and PUBLIC_SMOKE_PASSWORD before running this script.')
    process.exit(2)
  }
}

async function request(pathname, { method = 'GET', token, body, timeout = 10000 } = {}) {
  const headers = token ? { authorization: `Bearer ${token}` } : {}
  let payload
  if (body !== undefined) {
    headers['content-type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  const started = Date.now()
  const response = await fetch(`${baseUrl}${pathname}`, {
    method,
    headers,
    body: payload,
    signal: AbortSignal.timeout(timeout),
  })
  const text = await response.text().catch(() => '')
  let json = null
  try {
    json = text ? JSON.parse(text) : null
  } catch {
    // Some checks intentionally fetch HTML.
  }
  return {
    status: response.status,
    ms: Date.now() - started,
    bytes: text.length,
    headers: response.headers,
    json,
    text,
  }
}

async function login() {
  const result = await request('/api/v1/auth/login', {
    method: 'POST',
    body: { username, password },
    timeout: 10000,
  })
  const token = result.json?.access_token
  record('auth.login', result.status === 200 && Boolean(token), { status: result.status, ms: result.ms })
  if (result.json?.user?.role) currentUser.role = String(result.json.user.role)
  return token
}

async function runHttpSecurityChecks(token) {
  const home = await request('/', { timeout: 10000 })
  const csp = home.headers.get('content-security-policy') || ''
  record('http.home', home.status === 200 && home.text.includes('<div id="app">'), { status: home.status, ms: home.ms })
  record('headers.csp', csp.includes("default-src 'self'"))
  record('headers.frame_options', home.headers.get('x-frame-options') === 'DENY')
  record('headers.nosniff', home.headers.get('x-content-type-options') === 'nosniff')

  for (const blocked of ['/@vite/client', '/src/main.ts', '/node_modules/.vite/deps/vue.js', '/vite.svg']) {
    const result = await request(blocked, { timeout: 10000 })
    record(`blocked.${blocked}`, result.status === 404, { status: result.status, ms: result.ms })
  }

  const registration = await request('/api/v1/auth/register', {
    method: 'POST',
    body: {
      username: `publicsmoke${Date.now()}`,
      email: `publicsmoke${Date.now()}@example.local`,
      password: 'Temp6216835Mo!',
    },
    timeout: 10000,
  })
  record('auth.registration_policy', [200, 201, 403, 409].includes(registration.status), { status: registration.status, ms: registration.ms })

  for (const protectedPath of [
    '/api/v1/watchlists',
    '/api/v1/analysis/system-health',
    '/api/v1/admin/stats/overview',
  ]) {
    const result = await request(protectedPath, { timeout: 10000 })
    record(`auth.required.${protectedPath}`, result.status === 401, { status: result.status, ms: result.ms })
  }

  const publicStocks = await request('/api/v1/stocks?limit=1', { timeout: 10000 })
  record('auth.public./api/v1/stocks?limit=1', publicStocks.status === 200, { status: publicStocks.status, ms: publicStocks.ms })

  const authed = await request('/api/v1/stocks?limit=1', { token, timeout: 10000 })
  record('auth.authed_api', authed.status === 200, { status: authed.status, ms: authed.ms })
}

async function runApiChecks(token) {
  for (const [name, pathname, timeout] of apiTests) {
    try {
      const result = await request(pathname, { token, timeout })
      const adminOnly = name.startsWith('admin.') || ['alerts.scheduler', 'analysis.system_health'].includes(name)
      const expectedForbidden = adminOnly && currentUser.role !== 'admin'
      record(`api.${name}`, expectedForbidden ? result.status === 403 : result.status >= 200 && result.status < 300, {
        status: result.status,
        ms: result.ms,
        bytes: result.bytes,
      })
    } catch (error) {
      record(`api.${name}`, false, { error: error.name || String(error) })
    }
  }
}

function commonBrowserPaths() {
  return [
    process.env.PUBLIC_SMOKE_BROWSER_PATH,
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
  ].filter(Boolean)
}

async function resolveBrowser() {
  const require = createRequire(import.meta.url)
  let chromium
  try {
    ;({ chromium } = require(path.join(root, 'frontend', 'web', 'node_modules', 'playwright')))
  } catch {
    return null
  }

  const fs = await import('node:fs')
  const executablePath = commonBrowserPaths().find((candidate) => fs.existsSync(candidate))
  if (!executablePath) return null
  return { chromium, executablePath }
}

async function runBrowserChecks(token) {
  if (!runBrowser) {
    record('browser.skipped', true, { reason: 'disabled' })
    return
  }
  const browserConfig = await resolveBrowser()
  if (!browserConfig) {
    record('browser.skipped', true, { reason: 'playwright or browser executable unavailable' })
    return
  }

  const browser = await browserConfig.chromium.launch({
    headless: true,
    executablePath: browserConfig.executablePath,
  })
  try {
    for (const route of publicPageRoutes) {
      const page = await browser.newPage()
      await page.goto(`${baseUrl}${route}`, { waitUntil: 'networkidle', timeout: 30000 }).catch(() => {})
      const finalUrl = new URL(page.url())
      record(`page.public.${route}`, finalUrl.pathname !== '/login', { final: `${finalUrl.pathname}${finalUrl.search}` })
      await page.close()
    }

    for (const route of protectedPageRoutes) {
      const page = await browser.newPage()
      await page.goto(`${baseUrl}${route}`, { waitUntil: 'networkidle', timeout: 30000 }).catch(() => {})
      const finalUrl = new URL(page.url())
      record(`page.unauth.${route}`, finalUrl.pathname === '/login', { final: `${finalUrl.pathname}${finalUrl.search}` })
      await page.close()
    }

    const context = await browser.newContext()
    await context.addInitScript((storedToken) => localStorage.setItem('access_token', storedToken), token)
    for (const route of pageRoutes) {
      const page = await context.newPage()
      const errors = []
      const badResponses = []
      page.on('console', (message) => {
        if (message.type() === 'error') errors.push(message.text())
      })
      page.on('pageerror', (error) => errors.push(error.message))
      page.on('response', (response) => {
        if (response.status() >= 500 || [401, 403].includes(response.status())) {
          badResponses.push(`${response.status()} ${response.url()}`)
        }
      })
      let navError = null
      const started = Date.now()
      try {
        await page.goto(`${baseUrl}${route}`, { waitUntil: 'networkidle', timeout: 45000 })
        await page.waitForTimeout(500)
      } catch (error) {
        navError = error.name || String(error)
      }
      const body = await page.locator('body').innerText({ timeout: 3000 }).catch(() => '')
      record(`page.authed.${route}`, !navError && body.trim() !== 'not found' && errors.length === 0 && badResponses.length === 0, {
        ms: Date.now() - started,
        errors: errors.length,
        badResponses: badResponses.length,
        errorSamples: errors.slice(0, 3),
        badResponseSamples: badResponses.slice(0, 3),
      })
      await page.close()
    }
    await context.close()
  } finally {
    await browser.close()
  }
}

async function runWriteChecks(token) {
  if (!runWrites) {
    record('writes.skipped', true, { reason: 'set PUBLIC_SMOKE_WRITE_TESTS=true or pass --writes' })
    return
  }

  const watchlists = await request('/api/v1/watchlists', { token })
  const list = watchlists.json?.[0]
  record('writes.watchlist.list', watchlists.status === 200 && Boolean(list?.id), { status: watchlists.status })
  if (list?.id) {
    const existing = new Set((list.items || []).map((item) => item.symbol))
    const symbol = ['600000.SH', '000001.SZ', '600004.SH', '600036.SH'].find((candidate) => !existing.has(candidate))
    if (symbol) {
      const added = await request(`/api/v1/watchlists/${list.id}/items`, {
        method: 'POST',
        token,
        body: { symbol },
      })
      record('writes.watchlist.add', added.status >= 200 && added.status < 300 && Boolean(added.json?.stock_id), { status: added.status })
      if (added.json?.stock_id) {
        const reordered = await request(`/api/v1/watchlists/${list.id}/items/reorder`, {
          method: 'PUT',
          token,
          body: { stock_ids: [added.json.stock_id, ...(list.items || []).map((item) => item.stock_id)] },
        })
        record('writes.watchlist.reorder', reordered.status >= 200 && reordered.status < 300, { status: reordered.status })
        const removed = await request(`/api/v1/watchlists/${list.id}/items/${added.json.stock_id}`, { method: 'DELETE', token })
        record('writes.watchlist.remove', removed.status >= 200 && removed.status < 300, { status: removed.status })
      }
    } else {
      record('writes.watchlist.add.skipped', true, { reason: 'all candidates already present' })
    }
  }

  let alertId = null
  const stock = await request('/api/v1/stocks/600000.SH', { token })
  if (stock.json?.id) {
    const created = await request('/api/v1/alerts', {
      method: 'POST',
      token,
      body: { stock_id: stock.json.id, alert_type: 'price_above', threshold: 99999 },
    })
    alertId = created.json?.id
    record('writes.alert.create', created.status >= 200 && created.status < 300 && Boolean(alertId), { status: created.status })
    if (alertId) {
      try {
        const toggled = await request(`/api/v1/alerts/${alertId}/toggle`, { method: 'PUT', token })
        record('writes.alert.toggle', toggled.status >= 200 && toggled.status < 300, { status: toggled.status })
      } finally {
        const deleted = await request(`/api/v1/alerts/${alertId}`, { method: 'DELETE', token })
        record('writes.alert.delete', deleted.status >= 200 && deleted.status < 300, { status: deleted.status })
      }
    }
  } else {
    record('writes.alert.stock_lookup', false, { status: stock.status })
  }

  let modelId = null
  const modelName = `codex-smoke-${Date.now()}`
  const createdModel = await request('/api/v1/admin/models', {
    method: 'POST',
    token,
    body: {
      name: modelName,
      provider: 'custom',
      model_id: 'codex-smoke',
      api_key: 'not-real',
      description: 'temporary smoke test model',
      is_active: false,
      sort_order: 9999,
      allowed_roles: 'admin',
    },
  })
  modelId = createdModel.json?.id
  record('writes.admin_model.create', createdModel.status >= 200 && createdModel.status < 300 && Boolean(modelId), { status: createdModel.status })
  if (modelId) {
    try {
      const updated = await request(`/api/v1/admin/models/${modelId}`, {
        method: 'PUT',
        token,
        body: { description: 'temporary smoke test model updated', sort_order: 9998 },
      })
      record('writes.admin_model.update', updated.status >= 200 && updated.status < 300, { status: updated.status })
      const toggled = await request(`/api/v1/admin/models/${modelId}/toggle`, { method: 'PATCH', token })
      record('writes.admin_model.toggle', toggled.status >= 200 && toggled.status < 300, { status: toggled.status })
    } finally {
      const deleted = await request(`/api/v1/admin/models/${modelId}`, { method: 'DELETE', token })
      record('writes.admin_model.delete', deleted.status >= 200 && deleted.status < 300, { status: deleted.status })
    }
  }
}

requireCredentials()
const token = await login()
if (token) {
  await runHttpSecurityChecks(token)
  await runApiChecks(token)
  await runBrowserChecks(token)
  await runWriteChecks(token)
}

console.log(`\nSummary: ${details.length - failures.length}/${details.length} checks passed`)
if (failures.length) {
  console.log(JSON.stringify({ failures }, null, 2))
  process.exit(1)
}
