import { useEffect, useState } from 'react'
import { api, fmt } from '../api'

export default function Inbox() {
  const [items, setItems] = useState([])
  const [funds, setFunds] = useState([])
  const [idx, setIdx] = useState(0)
  const [override, setOverride] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function load() {
    try {
      const [i, f] = await Promise.all([api.inbox.list(), api.funds.list()])
      setItems(i); setFunds(f); setIdx(0); setOverride('')
    } catch (e) { setErr(String(e)) }
  }
  useEffect(() => { load() }, [])

  async function syncPlaid() {
    setBusy(true); setErr('')
    try { await api.plaid.sync(); await load() }
    catch (e) { setErr(String(e)) }
    finally { setBusy(false) }
  }

  if (err) return <div className="card bad">{err}</div>
  if (items.length === 0) return (
    <div>
      <h1>Inbox</h1>
      <div className="card muted">Empty. Tap sync to pull from Plaid.</div>
      <button className="primary" onClick={syncPlaid} disabled={busy}>Sync Plaid</button>
    </div>
  )

  const item = items[idx]
  if (!item) return (
    <div>
      <h1>Inbox</h1>
      <div className="card good">All caught up.</div>
      <button onClick={load}>Refresh</button>
    </div>
  )

  const suggestedFund = funds.find(f => f.id === item.suggested_fund_id)
  const chosenId = override || (item.suggested_fund_id ? String(item.suggested_fund_id) : '')

  async function approve() {
    if (!chosenId) return
    setBusy(true)
    try {
      await api.inbox.approve(item.id, Number(chosenId))
      setIdx(idx + 1); setOverride('')
    } catch (e) { setErr(String(e)) }
    finally { setBusy(false) }
  }

  async function reject() {
    setBusy(true)
    try {
      await api.inbox.reject(item.id)
      setIdx(idx + 1); setOverride('')
    } catch (e) { setErr(String(e)) }
    finally { setBusy(false) }
  }

  return (
    <div>
      <h1>Inbox ({idx + 1}/{items.length})</h1>
      <div className="swipe-card">
        <div className="merchant">{item.merchant || '(no merchant)'}</div>
        <div className="muted small">{item.date}</div>
        <div className={`amount ${Number(item.amount) >= 0 ? 'bad' : 'good'}`}>
          {Number(item.amount) >= 0 ? '−' : '+'}{fmt(Math.abs(Number(item.amount)))}
        </div>
        <div className="suggested">
          {suggestedFund ? `Suggested: ${suggestedFund.name}` : 'No suggestion'}
        </div>
        <select value={chosenId} onChange={e => setOverride(e.target.value)}>
          <option value="">Choose fund…</option>
          {funds.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
        </select>
      </div>
      <div className="swipe-actions">
        <button onClick={reject} disabled={busy} className="danger">Reject</button>
        <button onClick={approve} disabled={busy || !chosenId} className="primary">Approve</button>
      </div>
    </div>
  )
}
