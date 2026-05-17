import { useState } from 'react'
import { api, fmt, todayISO } from '../api'

export default function AssignModal({ fund, unassigned, onClose, onDone }) {
  const [amount, setAmount] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function submit(e) {
    e.preventDefault()
    const n = Number(amount)
    if (!n || n <= 0) return
    setBusy(true)
    setErr('')
    try {
      await api.transactions.assign({
        fund_id: fund.id,
        amount: n,
        date: todayISO(),
      })
      onDone()
    } catch (e) { setErr(String(e)); setBusy(false) }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="modal" onClick={e => e.stopPropagation()} onSubmit={submit}>
        <h2 style={{ margin: 0 }}>Assign to {fund.name}</h2>
        <div className="muted small" style={{ marginBottom: 12 }}>
          Unassigned: {fmt(unassigned)} · Current balance: {fmt(fund.balance)}
        </div>
        <input
          autoFocus
          inputMode="decimal"
          placeholder="Amount"
          value={amount}
          onChange={e => setAmount(e.target.value)}
        />
        {err && <div className="bad small" style={{ marginTop: 8 }}>{err}</div>}
        <div className="row" style={{ marginTop: 12 }}>
          <button type="button" className="ghost" onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy}>Assign</button>
        </div>
      </form>
    </div>
  )
}
