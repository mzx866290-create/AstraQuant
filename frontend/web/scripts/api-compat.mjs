import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'
import { build } from 'esbuild'

class MemoryStorage {
  #items = new Map()

  getItem(key) {
    return this.#items.has(key) ? this.#items.get(key) : null
  }

  setItem(key, value) {
    this.#items.set(key, String(value))
  }

  removeItem(key) {
    this.#items.delete(key)
  }

  clear() {
    this.#items.clear()
  }
}

const localStorageMock = new MemoryStorage()
const locationMock = {
  origin: 'http://localhost:5175',
  pathname: '/',
  search: '',
  hash: '',
  replacedWith: null,
  replace(value) {
    this.replacedWith = value
  },
}

Object.defineProperty(globalThis, 'localStorage', {
  value: localStorageMock,
  configurable: true,
})

Object.defineProperty(globalThis, 'window', {
  value: {
    location: locationMock,
    localStorage: localStorageMock,
  },
  configurable: true,
})

const bundled = await build({
  absWorkingDir: process.cwd(),
  alias: {
    '@': './src',
  },
  bundle: true,
  define: {
    'import.meta.env.VITE_API_BASE_URL': '""',
  },
  format: 'esm',
  logLevel: 'silent',
  platform: 'browser',
  stdin: {
    contents: "export * from '@/api'\nexport { default } from '@/api'\n",
    loader: 'ts',
    resolveDir: process.cwd(),
    sourcefile: 'scripts/api-compat-entry.ts',
  },
  write: false,
})

const apiModuleUrl = pathToFileURL(`${process.cwd()}/scripts/api-compat-entry.ts`).href
const apiModule = await import(
  `data:text/javascript;base64,${Buffer.from(`${bundled.outputFiles[0].text}\n//# sourceURL=${apiModuleUrl}`).toString('base64')}`
)

const expectedFunctions = [
  'registerAuthStateClearer',
  'normalizeApiBaseUrl',
  'isDirectServiceBaseUrl',
  'isFeatureUnavailableError',
]
const expectedApiObjects = [
  'stockApi',
  'userApi',
  'alertApi',
  'analysisApi',
  'newsApi',
  'crawlApi',
  'adminApi',
  'watchlistApi',
]

assert.ok(apiModule.default, '@/api should export a default api client')
assert.equal(apiModule.default, apiModule.api, 'default export should remain the named api client')

for (const exportName of expectedFunctions) {
  assert.equal(typeof apiModule[exportName], 'function', `@/api should export ${exportName}()`)
}

for (const exportName of expectedApiObjects) {
  assert.equal(typeof apiModule[exportName], 'object', `@/api should export ${exportName}`)
  assert.ok(apiModule[exportName], `${exportName} should be defined`)
}

assert.equal(
  typeof apiModule.adminApi.getResearchReviewReadiness,
  'function',
  'adminApi should expose getResearchReviewReadiness()',
)

assert.equal(apiModule.normalizeApiBaseUrl(' https://example.test/api/// '), 'https://example.test/api')
assert.equal(apiModule.isDirectServiceBaseUrl('http://localhost:8001'), true)
assert.equal(apiModule.isDirectServiceBaseUrl('http://127.0.0.1:8002/'), true)
assert.equal(apiModule.isDirectServiceBaseUrl('http://analysis-service:8003'), true)
assert.equal(apiModule.isDirectServiceBaseUrl('/api/v1'), false)

assert.equal(apiModule.isFeatureUnavailableError({ isFeatureUnavailable: true }), true)
assert.equal(apiModule.isFeatureUnavailableError(new Error('available')), false)
