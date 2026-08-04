/**
 * Display formatting shared across views.
 *
 * Each of these used to exist twice: a relative-time helper in Settings and
 * another in PlaidConnect, a month-label closure in the dashboard's trend
 * chart and another in the net-worth chart, a target-date line spelled out in
 * both goal cards. The copies had drifted — PlaidConnect counted "21d ago"
 * where Settings said "3w ago" — which is the tell that they wanted to be one
 * function.
 *
 * Month strings are YYYY-MM-01 and dates are YYYY-MM-DD, both parsed by
 * splitting rather than by `new Date(str)`: a bare date string is UTC, so
 * `new Date('2026-08-01')` is July 31st for anyone west of Greenwich.
 */
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "just now" · "18m ago" · "3d ago" · "5w ago". Takes a `Date` or an ISO timestamp. */
export function relativeTime(when) {
  const at = when instanceof Date ? when : new Date(when)
  const seconds = Math.floor((Date.now() - at.getTime()) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  const days = Math.floor(seconds / 86400)
  if (days < 14) return `${days}d ago`
  return `${Math.floor(days / 7)}w ago`
}

/** "2026-08-01" → "Aug 2026". */
export function monthLabel(monthStr) {
  const [y, m] = monthStr.split('-').map(Number)
  return `${MONTHS[m - 1]} ${y}`
}

/** "2026-08-01" → "Aug". For axes with no room for the year. */
export function monthShort(monthStr) {
  const [, m] = monthStr.split('-').map(Number)
  return MONTHS[m - 1]
}

/** "2026-08-01" → "Aug 26". For axes spanning more than a year. */
export function monthShortYear(monthStr) {
  const [y, m] = monthStr.split('-').map(Number)
  return `${MONTHS[m - 1]} ${String(y).slice(-2)}`
}

/** "2026-12-31" → "Dec 31, 2026". A goal's target date. */
export function dateLabel(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number)
  return `${MONTHS[m - 1]} ${d}, ${y}`
}
