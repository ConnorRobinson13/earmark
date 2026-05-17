/**
 * Month navigation pill. Value/onChange are YYYY-MM-01 strings.
 */
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

function shift(monthStr, delta) {
  const [y, m] = monthStr.split('-').map(Number)
  const d = new Date(Date.UTC(y, m - 1 + delta, 1))
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-01`
}

function thisMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

function label(monthStr) {
  const [y, m] = monthStr.split('-').map(Number)
  return `${MONTHS[m - 1]} ${y}`
}

export default function MonthSelector({ value, onChange }) {
  const current = value || thisMonth()
  const isCurrent = current === thisMonth()
  return (
    <div className="month-selector">
      <button className="ghost" onClick={() => onChange(shift(current, -1))} aria-label="Previous month">‹</button>
      <div className="col" style={{ alignItems: 'center', flex: 1 }}>
        <div className="month-label">{label(current)}</div>
        {!isCurrent && (
          <button className="ghost small" onClick={() => onChange(thisMonth())}>jump to today</button>
        )}
      </div>
      <button className="ghost" onClick={() => onChange(shift(current, 1))} aria-label="Next month">›</button>
    </div>
  )
}

export { thisMonth, label as monthLabel }
