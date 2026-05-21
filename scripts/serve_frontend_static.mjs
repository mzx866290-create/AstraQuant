import { createReadStream } from 'node:fs'
import { access, stat } from 'node:fs/promises'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const distDir = path.resolve(process.env.FRONTEND_DIST_DIR || path.join(root, 'frontend', 'web', 'dist'))
const host = process.env.FRONTEND_HOST || '0.0.0.0'
const port = Number(process.env.FRONTEND_PORT || 5175)
const authRateLimitMax = readPositiveNumber('AUTH_RATE_LIMIT_MAX', 10)
const authRateLimitWindowMs = readPositiveNumber('AUTH_RATE_LIMIT_WINDOW_MS', 60_000)
const trustProxy = process.env.TRUST_PROXY === 'true'
const allowCloudflareInsights = process.env.ALLOW_CLOUDFLARE_INSIGHTS === 'true'

const backends = {
  user: normalizeBackend(process.env.USER_SERVICE_URL || 'http://127.0.0.1:8002'),
  market: normalizeBackend(process.env.MARKET_SERVICE_URL || 'http://127.0.0.1:8001'),
  analysis: normalizeBackend(process.env.ANALYSIS_SERVICE_URL || 'http://127.0.0.1:8003'),
}

const blockedPrefixes = [
  '/@vite',
  '/__vite',
  '/src',
  '/node_modules',
  '/.vite',
  '/vite.svg',
]

const hopByHopHeaders = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'expect',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
])

const contentTypes = new Map([
  ['.html', 'text/html; charset=utf-8'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.css', 'text/css; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.svg', 'image/svg+xml'],
  ['.png', 'image/png'],
  ['.jpg', 'image/jpeg'],
  ['.jpeg', 'image/jpeg'],
  ['.gif', 'image/gif'],
  ['.ico', 'image/x-icon'],
  ['.woff', 'font/woff'],
  ['.woff2', 'font/woff2'],
  ['.ttf', 'font/ttf'],
])

const scriptSources = ["'self'"]
const connectSources = ["'self'"]
if (allowCloudflareInsights) {
  scriptSources.push('https://static.cloudflareinsights.com')
  connectSources.push('https://cloudflareinsights.com')
}

const contentSecurityPolicy = [
  "default-src 'self'",
  "base-uri 'self'",
  `connect-src ${connectSources.join(' ')}`,
  "font-src 'self' data:",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "img-src 'self' data: https:",
  "object-src 'none'",
  `script-src ${scriptSources.join(' ')}`,
  "style-src 'self' 'unsafe-inline'",
].join('; ')

const authRateLimits = new Map()

function normalizeBackend(value) {
  return value.replace(/\/+$/, '')
}

function readPositiveNumber(name, fallback) {
  const value = Number(process.env[name])
  return Number.isFinite(value) && value > 0 ? value : fallback
}

function securityHeaders(extra = {}) {
  const headers = {
    'Content-Security-Policy': contentSecurityPolicy,
    'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'same-origin',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    ...extra,
  }
  if (process.env.ENABLE_HSTS === 'false') {
    delete headers['Strict-Transport-Security']
  }
  return headers
}

function sendText(res, status, body, headers = {}) {
  res.writeHead(status, securityHeaders({
    'Content-Type': 'text/plain; charset=utf-8',
    'Cache-Control': 'no-store',
    ...headers,
  }))
  res.end(body)
}

function isBlockedPath(pathname) {
  return blockedPrefixes.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))
}

function backendFor(pathname) {
  if (pathname.startsWith('/api/v1/auth') || pathname.startsWith('/api/v1/watchlists')) {
    return backends.user
  }
  if (pathname.startsWith('/api/v1/admin') || pathname.startsWith('/api/v1/analysis')) {
    return backends.analysis
  }
  if (pathname.startsWith('/api/v1')) {
    return backends.market
  }
  return null
}

function clientAddress(req) {
  if (trustProxy) {
    const forwardedFor = String(req.headers['x-forwarded-for'] || '').split(',')[0].trim()
    if (forwardedFor) {
      return forwardedFor
    }
  }
  return req.socket.remoteAddress || 'unknown'
}

function isAuthRateLimited(pathname) {
  return pathname === '/api/v1/auth/login' || pathname === '/api/v1/auth/register'
}

function rateLimitRetryAfter(req, url) {
  if (!isAuthRateLimited(url.pathname)) {
    return null
  }

  const now = Date.now()
  const key = `${req.method || 'GET'}:${url.pathname}:${clientAddress(req)}`
  const current = authRateLimits.get(key)

  if (!current || current.expiresAt <= now) {
    authRateLimits.set(key, { count: 1, expiresAt: now + authRateLimitWindowMs })
    return null
  }

  current.count += 1
  if (current.count <= authRateLimitMax) {
    return null
  }

  if (authRateLimits.size > 10_000) {
    for (const [entryKey, entry] of authRateLimits.entries()) {
      if (entry.expiresAt <= now) {
        authRateLimits.delete(entryKey)
      }
    }
  }

  return Math.max(1, Math.ceil((current.expiresAt - now) / 1000))
}

function requestBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = []
    req.on('data', (chunk) => chunks.push(chunk))
    req.on('end', () => resolve(chunks.length ? Buffer.concat(chunks) : undefined))
    req.on('error', reject)
  })
}

function proxyHeaders(req, target) {
  const headers = {}
  for (const [key, value] of Object.entries(req.headers)) {
    if (!hopByHopHeaders.has(key.toLowerCase()) && typeof value !== 'undefined') {
      headers[key] = value
    }
  }
  headers.host = new URL(target).host
  headers['x-forwarded-host'] = req.headers.host || ''
  headers['x-forwarded-proto'] = 'https'
  return headers
}

async function proxyApi(req, res, url, target) {
  try {
    const body = ['GET', 'HEAD'].includes(req.method || 'GET') ? undefined : await requestBody(req)
    const upstream = await fetch(`${target}${url.pathname}${url.search}`, {
      method: req.method,
      headers: proxyHeaders(req, target),
      body,
    })

    const headers = {}
    upstream.headers.forEach((value, key) => {
      if (!hopByHopHeaders.has(key.toLowerCase())) {
        headers[key] = value
      }
    })
    res.writeHead(upstream.status, securityHeaders(headers))
    if (req.method === 'HEAD') {
      res.end()
      return
    }
    const buffer = Buffer.from(await upstream.arrayBuffer())
    res.end(buffer)
  } catch (error) {
    console.error('API proxy failed:', error)
    sendText(res, 502, 'bad gateway\n')
  }
}

async function fileExists(filePath) {
  try {
    await access(filePath)
    return true
  } catch {
    return false
  }
}

function safeStaticPath(pathname) {
  let decoded
  try {
    decoded = decodeURIComponent(pathname)
  } catch {
    return null
  }
  const normalized = path.normalize(decoded).replace(/^(\.\.(\/|\\|$))+/, '')
  const fullPath = path.resolve(distDir, `.${normalized}`)
  if (!fullPath.startsWith(distDir)) {
    return null
  }
  return fullPath
}

async function serveFile(res, filePath, { immutable = false } = {}) {
  const info = await stat(filePath)
  if (!info.isFile()) {
    sendText(res, 404, 'not found\n')
    return
  }
  const ext = path.extname(filePath).toLowerCase()
  const headers = securityHeaders({
    'Content-Type': contentTypes.get(ext) || 'application/octet-stream',
    'Content-Length': String(info.size),
    'Cache-Control': immutable ? 'public, max-age=31536000, immutable' : 'no-store',
  })
  res.writeHead(200, headers)
  createReadStream(filePath).pipe(res)
}

async function serveStatic(req, res, url) {
  if (isBlockedPath(url.pathname)) {
    sendText(res, 404, 'not found\n')
    return
  }

  if (url.pathname === '/health') {
    sendText(res, 200, 'healthy\n')
    return
  }

  const filePath = safeStaticPath(url.pathname)
  if (!filePath) {
    sendText(res, 400, 'bad request\n')
    return
  }

  const ext = path.extname(url.pathname).toLowerCase()
  const isStaticAssetRequest = url.pathname.startsWith('/assets/') || contentTypes.has(ext)
  if (isStaticAssetRequest && await fileExists(filePath)) {
    await serveFile(res, filePath, { immutable: url.pathname.startsWith('/assets/') })
    return
  }

  if (isStaticAssetRequest) {
    sendText(res, 404, 'not found\n')
    return
  }

  await serveFile(res, path.join(distDir, 'index.html'))
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`)
  const retryAfter = rateLimitRetryAfter(req, url)
  if (retryAfter) {
    sendText(res, 429, 'too many requests\n', { 'Retry-After': String(retryAfter) })
    return
  }

  const target = backendFor(url.pathname)
  if (target) {
    await proxyApi(req, res, url, target)
    return
  }
  await serveStatic(req, res, url)
})

server.listen(port, host, () => {
  console.log(`frontend static gateway listening on http://${host}:${port}`)
  console.log(`serving ${distDir}`)
})
