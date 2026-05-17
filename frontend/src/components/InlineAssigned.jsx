import { useEffect, useRef, useState } from 'react'
import { api, fmt, todayISO } from '../api'

/**
 * Click-to-edit "assigned this month" for a fund.
 * Editing posts an assignment for the delta against Unassigned.
 * `month` is YYYY-MM-01 of the view; assignments date to today if it's the current
 * month, otherwise to the 1st of the selected month (e.g. planning future).
 */
export default function InlineAssigned({ fund, onChange, month, readOnly }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const inputRef = useRef(null)
  const submittedRef = useRef(false)

  const current = Number(fund.assigned_this_month || 0)

  useEffect(() => {
    if (editing) {
      submittedRef.current = false
      setValue(current.toFixed(2))
      setTimeout(() => inputRef.current?.select(), 0)
    }
  }, [editing])

  async function commit() {
    if (submittedRef.current) return
    submittedRef.current = true
    setErr('')
    const next = Number(value)
    if (!Number.isFinite(next) || next < 0) {
      setErr('Must be ≥ 0')
      submittedRef.current = false
      return
    }
    if (Math.abs(next - current) < 0.005) {
      setEditing(false)
      return
    }
    const delta = +(next - current).toFixed(2)
    setBusy(true)
    try {
      const today = todayISO()
      const isCurrent = !month || month === today.slice(0, 7) + '-01'
      await api.transactions.assign({
        fund_id: fund.id,
        amount: delta,
        date: isCurrent ? today : month,
        notes: 'Inline assignment edit',
      })
      setEditing(false)
      onChange?.()
    } catch (e) {
      setErr(String(e))
      submittedRef.current = false
    } finally {
      setBusy(false)
    }
  }

  function cancel() {
    submittedRef.current = true
    setEditing(false)
    setErr('')
  }

  if (!editing) {
    if (readOnly) {
      return (
        <div className="assigned-btn" style={{ cursor: 'default' }}>
          <div className="muted small">assigned</div>
          <div className="assigned-amount">{fmt(current)}</div>
        </div>
      )
    }
    return (
      <button className="assigned-btn" onClick={() => setEditing(true)} title="Click to edit assignment">
        <div className="muted small">assigned</div>
        <div className="assigned-amount">{fmt(current)}</div>
      </button>
    )
  }

  return (
    <div className="col" style={{ alignItems: 'flex-end' }}>
      <div className="muted small">assigned</div>
      <input
        ref={inputRef}
        className="assigned-input"
        inputMode="decimal"
        value={value}
        disabled={busy}
        onChange={(e) => setValue(e.target.value.replace(/-/g, ''))}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit()
          if (e.key === 'Escape') cancel()
        }}
      />
      {err && <div className="bad small">{err}</div>}
    </div>
  )
}
