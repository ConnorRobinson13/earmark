/**
 * Month helpers. Month strings are YYYY-MM-01 (matches backend `date` columns).
 */
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

export function shiftMonth(monthStr, delta) {
  const [y, m] = monthStr.split('-').map(Number)
  const d = new Date(Date.UTC(y, m - 1 + delta, 1))
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-01`
}

export function thisMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

export function monthLabel(monthStr) {
  const [y, m] = monthStr.split('-').map(Number)
  return `${MONTHS[m - 1]} ${y}`
}

/**
 * Legacy compat: views that previously rendered an inline MonthSelector
 * now read month from the shell topbar. This component is a no-op so old
 * imports don't break.
 */
export default function MonthSelector() {
  return null
}
