const toFiniteNumber = (value: unknown) => {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

export function formatPrice(value?: number | string | null, empty = '--') {
  const number = toFiniteNumber(value)
  return number !== null && number > 0 ? number.toFixed(2) : empty
}

export function formatSigned(value?: number | string | null) {
  const number = toFiniteNumber(value)
  if (number === null || number === 0) return '0.00'
  return `${number > 0 ? '+' : ''}${number.toFixed(2)}`
}

export function formatPct(value?: number | string | null, empty = '--') {
  const number = toFiniteNumber(value)
  if (number === null) return empty
  return `${number > 0 ? '+' : ''}${number.toFixed(2)}%`
}

export function formatMoney(value?: number | string | null, empty = 'N/A') {
  const number = toFiniteNumber(value)
  return number !== null && number > 0 ? `${Math.round(number)}元` : empty
}

export function formatVolume(value?: number | string | null) {
  const number = toFiniteNumber(value)
  if (!number) return '--'
  if (number >= 1e8) return `${(number / 1e8).toFixed(2)}亿`
  if (number >= 1e4) return `${(number / 1e4).toFixed(2)}万`
  return number.toString()
}

export function formatMarketValue(value?: number | string | null) {
  const number = toFiniteNumber(value)
  if (!number) return '--'
  if (number >= 1e12) return `${(number / 1e12).toFixed(2)}万亿`
  if (number >= 1e8) return `${(number / 1e8).toFixed(2)}亿`
  return `${(number / 1e4).toFixed(2)}万`
}

export function formatShares(value?: number | string | null) {
  const number = toFiniteNumber(value)
  if (!number) return '--'
  if (number >= 1e8) return `${(number / 1e8).toFixed(2)}亿股`
  if (number >= 1e4) return `${(number / 1e4).toFixed(2)}万股`
  return `${number.toFixed(0)}股`
}

export function formatDelta(value?: number | string | null) {
  const number = toFiniteNumber(value)
  if (number === null) return ''
  return number > 0 ? `+${number}` : `${number}`
}

export function formatDuration(totalSeconds: number) {
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}
