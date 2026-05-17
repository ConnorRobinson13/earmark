import { useEffect, useRef, useState } from 'react'
import { api, fmt } from '../api'

/**
 * Click-to-edit "income this month" — sum of untagged income in the selected month.
 * Editing posts a delta-adjusted income transaction so the total matches the typed value.
 */
export default function InlineIncome({ value, month, readOnly, onChange }) {
  const [editing, setEditing] = useState(false)
  const [v, setV] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const inputRef = useRef(null)
  const submittedRef = useRef(false)
  const current = Number(value || 0)

  useEffect(() => {
    if (editing) {
      submittedRef.current = false
      setV(current.toFixed(2))
      setTimeout(() => inputRef.current?.select(), 0)
    }
  }, [editing])

  async function commit() {
    if (submittedRef.current) return
    submittedRef.current = true
    setErr('')
    const next = Number(v)
    if (!Number.isFinite(next) || next < 0) {
      setErr('Must be ≥ 0'); submittedRef.current = false; return
    }
    if (Math.abs(next - current) < 0.005) { setEditing(false); return }
    setBusy(true)
    try {
      await api.bulk.setMonthlyIncome(month, next)
      setEditing(false)
      onChange?.()
    } catch (e) {
      setErr(String(e)); submittedRef.current = false
    } finally { setBusy(false) }
  }

  function cancel() { submittedRef.current = true; setEditing(false); setErr('') }

  if (editing) {
    return (
      <>
        <input
          ref={inputRef}
          inputMode="decimal"
          value={v}
          disabled={busy}
          onChange={(e) => setV(e.target.value.replace(/-/g, ''))}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit()
            if (e.key === 'Escape') cancel()
          }}
          style={{
            fontSize: 22, fontWeight: 700,
            padding: '2px 4px',
            background: 'transparent',
            border: 'none',
            borderBottom: '2px solid var(--accent)',
            borderRadius: 0,
            color: 'var(--good)',
            width: '100%',
          }}
        />
        {err && <div className="bad small">{err}</div>}
      </>
    )
  }

  if (readOnly) {
    return <span className="good">{fmt(current)}</span>
  }
  return (
    <button
      className="balance-btn"
      style={{ font: 'inherit', fontSize: 22, fontWeight: 700, color: 'var(--good)', padding: '2px 4px' }}
      onClick={() => setEditing(true)}
      title="Click to edit income"
    >
      {fmt(current)}
    </button>
  )
}
