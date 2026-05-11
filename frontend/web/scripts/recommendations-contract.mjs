import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'
import { build } from 'esbuild'

async function importBundledModule(sourcefile, contents) {
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
      contents,
      loader: 'ts',
      resolveDir: process.cwd(),
      sourcefile,
    },
    write: false,
  })

  const moduleUrl = pathToFileURL(`${process.cwd()}/${sourcefile}`).href
  return import(
    `data:text/javascript;base64,${Buffer.from(`${bundled.outputFiles[0].text}\n//# sourceURL=${moduleUrl}`).toString('base64')}`
  )
}

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

const calls = []
const localStorageMock = new MemoryStorage()

Object.defineProperty(globalThis, 'localStorage', {
  value: localStorageMock,
  configurable: true,
})

Object.defineProperty(globalThis, 'window', {
  value: {
    location: {
      origin: 'http://localhost:5175',
      pathname: '/',
      search: '',
      hash: '',
      replace() {},
    },
    localStorage: localStorageMock,
  },
  configurable: true,
})

const analysisModule = await importBundledModule(
  'scripts/recommendations-analysis-entry.ts',
  `
    import { analysisApi } from '@/api/analysis'
    import { api } from '@/api/client'

    api.get = async (url, config) => {
      globalThis.__recommendationCalls.push({ method: 'get', url, config })
      return { ok: true }
    }

    export { analysisApi }
  `,
)

Object.defineProperty(globalThis, '__recommendationCalls', {
  value: calls,
  configurable: true,
})

await analysisModule.analysisApi.getRecommendations()
await analysisModule.analysisApi.getRecommendations('SZ', 25, true, 'value_quality', 80, false, false, true)
await analysisModule.analysisApi.getRecentReviews(['000001.SZ', '600000.SH'], 'growth_momentum')

assert.equal(calls[0].url, '/api/v1/analysis/score/batch/recommend')
assert.deepEqual(calls[0].config.params, {
  market: 'ALL',
  limit: 10,
  force_refresh: false,
  strategy: 'auto',
  max_candidates: 200,
  include_evidence: true,
  include_debate: true,
  initial_full_scan: false,
})
assert.equal(calls[0].config.timeout, 180000)

assert.deepEqual(calls[1].config.params, {
  market: 'SZ',
  limit: 25,
  force_refresh: true,
  strategy: 'value_quality',
  max_candidates: 80,
  include_evidence: false,
  include_debate: false,
  initial_full_scan: true,
})

assert.equal(calls[2].url, '/api/v1/analysis/reviews/recent')
assert.deepEqual(calls[2].config.params, {
  symbols: '000001.SZ,600000.SH',
  strategy: 'growth_momentum',
  offsets: 'T+1,T+5,T+20',
  limit_per_symbol: 1,
})

const recommendations = await importBundledModule(
  'scripts/recommendations-utils-entry.ts',
  "export * from '@/utils/recommendations'\n",
)

assert.equal(recommendations.strategyLabel('growth_momentum'), '成长动量')
assert.equal(recommendations.regimeLabel('weak_market'), '弱市场')
assert.equal(recommendations.resolveRecentReviewStrategy('auto', 'growth_momentum'), 'growth_momentum')
assert.equal(recommendations.resolveRecentReviewStrategy('auto', 'auto'), 'auto')
assert.equal(recommendations.resolveRecentReviewStrategy('value_quality', 'growth_momentum'), 'value_quality')
assert.equal(recommendations.resolveRecentReviewStrategy(undefined, 'growth_momentum'), 'auto')

const hardVeto = {
  passed: false,
  level: 'hard',
  vetoes: [
    {
      key: 'financial_red',
      type: 'financial_deterioration',
      severity: 'hard',
      detail: 'Revenue and profit yoy are both negative',
      score_delta: -18,
      handling: 'exclude deteriorating fundamentals',
    },
  ],
  warnings: [
    {
      type: 'negative_operating_cashflow',
      severity: 'soft',
      detail: 'Operating cash flow is negative',
      score_delta: -8,
    },
  ],
}

assert.equal(recommendations.vetoLabel(hardVeto), '已否决')
assert.equal(recommendations.vetoTagType(hardVeto), 'danger')
assert.equal(recommendations.vetoDetailItems(hardVeto).length, 2)
assert.deepEqual(
  recommendations.recommendationRowWarnings({
    symbol: '000001.SZ',
    data_grade: { grade: 'B', label: '可用', analysis_scope: '行情+财务' },
    veto_result: hardVeto,
  }),
  ['数据等级 B：可用', '行情+财务', 'Operating cash flow is negative'],
)

const noEvidenceRow = { symbol: '000001.SZ' }
assert.deepEqual(recommendations.evidenceTopItems(noEvidenceRow), [])
assert.equal(recommendations.recommendationTrustState({ status: 'ok', candidate_source: 'db', scored_count: 1 }).level, 'stable')
assert.equal(recommendations.recommendationTrustState({ status: 'ok', candidate_source: 'db', scored_count: 0 }).level, 'warning')
assert.equal(recommendations.recommendationTrustState({ status: 'ok', candidate_source: 'fallback', scored_count: 1 }).level, 'blocked')
