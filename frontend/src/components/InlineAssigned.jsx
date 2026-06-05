import { useEffect, useRef, useState } from 'react'
import { api, fmt, todayISO } from '../api'

/**
 * Click-to-edit "assigned this month" for a fund. Renders a single button or
 * a single input, sized to fill its parent grid cell — no internal label
 * (the column header in .col-lbl handles that).
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

  if (editing) {
    return (
      <input
        ref={inputRef}
        className="assign-edit"
        inputMode="decimal"
        value={value}
        disabled={busy}
        onChange={(e) => setValue(e.target.value.replace(/-/g, ''))}
        onBlur={commit}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit()
          if (e.key === 'Escape') cancel()
        }}
      />
    )
  }

  return (
    <button
      className="assign-button"
      onClick={(e) => { e.stopPropagation(); if (!readOnly) setEditing(true) }}
      disabled={readOnly}
      title={readOnly ? 'Past month — read only' : 'Click to edit assignment'}
    >
      {current ? fmt(current) : <span style={{ color: 'var(--text-mute)' }}>—</span>}
      {err && <span className="bad small" style={{ display: 'block' }}>{err}</span>}
    </button>
  )
}
