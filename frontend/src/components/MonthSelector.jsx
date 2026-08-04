import { todayISO } from '../api'

/**
 * Month arithmetic. Month strings are YYYY-MM-01 (matches backend `date`
 * columns). Turning one into something a human reads is `../format`.
 */

export function shiftMonth(monthStr, delta) {
  const [y, m] = monthStr.split('-').map(Number)
  const d = new Date(Date.UTC(y, m - 1 + delta, 1))
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-01`
}

export function thisMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

/**
 * The date to stamp a write with, for a view scoped to `month`: today when
 * that is the current month, otherwise the first of the month being edited.
 *
 * Without this, editing an archived month from the top bar would file the
 * transaction under today and it would vanish from the month you were looking
 * at.
 */
export function dateInMonth(month) {
  return !month || month === thisMonth() ? todayISO() : month
}

/**
 * Legacy compat: views that previously rendered an inline MonthSelector
 * now read month from the shell topbar. This component is a no-op so old
 * imports don't break.
 */
export default function MonthSelector() {
  return null
}
