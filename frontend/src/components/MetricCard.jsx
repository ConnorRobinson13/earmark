import { useState } from 'react'

/**
 * Compact dashboard tile.
 *  - `label`     : top-left small caps label
 *  - `value`     : big number
 *  - `subtext`   : optional muted small text below the value
 *  - `tone`      : 'ok' | 'warn' | 'bad' | undefined (color of the value)
 *  - `info`      : description shown when the ⓘ button is clicked
 *  - `action`    : optional node rendered bottom-right (e.g. a button)
 */
export default function MetricCard({ label, value, subtext, tone, info, action }) {
  const [showInfo, setShowInfo] = useState(false)
  const toneClass = tone === 'bad' ? 'bad' : tone === 'warn' ? 'warn' : tone === 'muted' ? 'muted' : ''

  return (
    <div className="metric-card">
      <div className="metric-head">
        <span className="muted small">{label}</span>
        {info && (
          <button
            type="button"
            className="info-btn"
            onClick={() => setShowInfo(s => !s)}
            aria-label="What does this mean?"
            title="What does this mean?"
          >
            ⓘ
          </button>
        )}
      </div>
      <div className={`metric-value ${toneClass}`}>{value}</div>
      {subtext && <div className="muted small">{subtext}</div>}
      {showInfo && info && <div className="metric-info small">{info}</div>}
      {action && <div style={{ marginTop: 10 }}>{action}</div>}
    </div>
  )
}
