import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'
import { build } from 'esbuild'

const bundled = await build({
  absWorkingDir: process.cwd(),
  alias: {
    '@': './src',
  },
  bundle: true,
  format: 'esm',
  logLevel: 'silent',
  platform: 'browser',
  stdin: {
    contents: "export * from '@/utils/dataQuality'\n",
    loader: 'ts',
    resolveDir: process.cwd(),
    sourcefile: 'scripts/data-quality-compat-entry.ts',
  },
  write: false,
})

const moduleUrl = pathToFileURL(`${process.cwd()}/scripts/data-quality-compat-entry.ts`).href
const dataQuality = await import(
  `data:text/javascript;base64,${Buffer.from(`${bundled.outputFiles[0].text}\n//# sourceURL=${moduleUrl}`).toString('base64')}`
)

const nestedQuality = {
  quote: {
    source: 'eastmoney',
    updated_at: '2026-05-07T09:30:00+00:00',
    confidence: 0.82,
  },
  news: {
    source: 'news-db',
    warning: 'headline_deduped',
    warnings: ['secondary_source'],
  },
}

assert.deepEqual(
  dataQuality.pickDataQuality(nestedQuality, 'quote'),
  nestedQuality.quote,
  'nested quality should select the requested section',
)
assert.equal(
  dataQuality.pickDataQuality({ quote: {} }, 'quote'),
  null,
  'empty nested quality should not render a misleading panel',
)
assert.deepEqual(
  dataQuality.pickDataQuality({ confidence: 0 }, 'quote'),
  { confidence: 0 },
  'zero confidence is a valid quality signal and should remain visible',
)
assert.deepEqual(
  dataQuality.pickDataQuality({ source: 'fallback', is_fallback: true }, 'quote'),
  { source: 'fallback', is_fallback: true },
  'flat quality payloads should remain supported',
)

assert.deepEqual(
  dataQuality.qualityWarnings(nestedQuality.news),
  ['headline_deduped', 'secondary_source'],
  'single warning should be prepended before warnings[]',
)
assert.deepEqual(dataQuality.qualityWarnings(null), [])

assert.equal(dataQuality.formatQualityTime('2026-05-07T09:30:00+00:00'), '2026-05-07 09:30')
assert.equal(dataQuality.formatQualityTime(), '')
assert.equal(dataQuality.formatConfidence(0.824), '82%')
assert.equal(dataQuality.formatConfidence(0), '0%')
assert.equal(dataQuality.formatConfidence(82), '82')
assert.equal(dataQuality.formatConfidence('high'), 'high')
assert.equal(dataQuality.formatConfidence(''), '')

assert.deepEqual(dataQuality.qualityRiskTags(null), [])
assert.deepEqual(dataQuality.qualityRiskTags({ is_fallback: true, status: 'fallback' }), ['风险：开发兜底数据'])
assert.deepEqual(dataQuality.qualityRiskTags({ status: 'unavailable' }), ['风险：数据源不可用'])
assert.deepEqual(dataQuality.qualityRiskTags({ status: 'empty' }), ['风险：数据为空'])
assert.deepEqual(dataQuality.qualityRiskTags({ warning: 'stale', warnings: ['secondary'] }), ['风险：存在数据告警'])

assert.equal(dataQuality.crawlStatusLevel('success'), 'success')
assert.equal(dataQuality.crawlStatusLevel({ status: 'partial' }), 'warning')
assert.equal(dataQuality.crawlStatusLevel({ status: 'empty_symbol_pool' }), 'warning')
assert.equal(dataQuality.crawlStatusLevel({ status: 'unavailable' }), 'error')
assert.equal(dataQuality.crawlStatusLevel({ status: 'not_implemented' }), 'info')
assert.equal(dataQuality.crawlStatusLevel(undefined), 'info')

const successStatus = dataQuality.formatCrawlStatus(
  {
    status: 'success',
    finished_at: '2026-05-07T08:30:00+00:00',
    saved_count: 3,
  },
  'rows',
)
assert.match(successStatus, /2026-05-07 08:30/)
assert.match(successStatus, /3 rows/)

const errorStatus = dataQuality.formatCrawlStatus({
  status: 'error',
  finished_at: '2026-05-07T08:30:00+00:00',
  error_message: 'upstream timeout',
})
assert.match(errorStatus, /upstream timeout/)
assert.doesNotMatch(errorStatus, /保存|saved/i, 'error status should not imply saved rows')

assert.equal(dataQuality.formatCrawlError({ response: { status: 500, data: { detail: 'boom' } } }, 'news'), 'boom')
assert.match(dataQuality.formatCrawlError({ response: { status: 401 } }, 'news'), /news/)
assert.match(dataQuality.formatCrawlError({ response: { status: 403 } }, 'news'), /news/)
assert.equal(dataQuality.formatCrawlError({ message: 'network down' }, 'news'), 'network down')
