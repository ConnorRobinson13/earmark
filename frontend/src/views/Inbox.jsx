import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { api, fmt } from '../api'
import { Icon } from '../components/Icons'

export default function Inbox() {
  const { refresh, refreshTick } = useOutletContext()
  const [items, setItems] = useState([])
  const [funds, setFunds] = useState([])
  const [idx, setIdx] = useState(0)
  const [override, setOverride] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  // For income items: user picks "Paycheck" (untagged, doesn't bump Unassigned —
  // already covered by planned income) OR a fund (= reimbursement, credits that fund).
  const [incomeMode, setIncomeMode] = useState('paycheck')

  async function load() {
    try {
      const [i, f] = await Promise.all([api.inbox.list(), api.funds.list()])
      setItems(i); setFunds(f); setIdx(0); setOverride('')
    } catch (e) { setErr(String(e)) }
  }
  useEffect(() => { load() }, [refreshTick])

  async function syncPlaid() {
    setBusy(true); setErr('')
    try { await api.plaid.sync(); await load(); refresh() }
    catch (e) { setErr(String(e)) }
    finally { setBusy(false) }
  }

  if (err) return <div className="card"><span className="bad">{err}</span></div>

  if (items.length === 0 || idx >= items.length) {
    return (
      <div className="inbox-wrap">
        <div className="inbox-empty">
          <div className="icon"><Icon name="check" size={28} /></div>
          <h2>All caught up</h2>
          <p>No pending transactions to categorize.</p>
          <button className="btn primary" onClick={syncPlaid} disabled={busy}>
            <Icon name="sync" /> {busy ? 'Syncing…' : 'Sync Plaid'}
          </button>
        </div>
      </div>
    )
  }

  const item = items[idx]
  const suggestedFund = funds.find(f => f.id === item.suggested_fund_id)
  const chosenId = override || (item.suggested_fund_id ? String(item.suggested_fund_id) : '')
  const amount = Number(item.amount)
  const isIncome = amount < 0
  const initials = (item.merchant || '?').trim().slice(0, 2).toUpperCase()

  async function approve() {
    setBusy(true); setErr('')
    try {
      if (isIncome && incomeMode === 'paycheck') {
        await api.inbox.approve(item.id, null, true)
      } else {
        if (!chosenId) { setBusy(false); return }
        await api.inbox.approve(item.id, Number(chosenId), false)
      }
      setIdx(idx + 1); setOverride(''); setIncomeMode('paycheck')
      refresh()
    } catch (e) { setErr(String(e)) }
    finally { setBusy(false) }
  }

  async function reject() {
    setBusy(true); setErr('')
    try {
      await api.inbox.reject(item.id)
      setIdx(idx + 1); setOverride('')
      refresh()
    } catch (e) { setErr(String(e)) }
    finally { setBusy(false) }
  }

  const progressPct = ((idx) / items.length) * 100

  return (
    <div className="inbox-wrap">
      <div className="inbox-progress">
        <div className="bar"><div style={{ width: `${progressPct}%` }} /></div>
        <div className="count">{idx + 1} / {items.length}</div>
      </div>

      <div className="txcard">
        <div className="merchant-row">
          <div className="mlogo">{initials}</div>
          <div className="merchant-info">
            <div className="name">{item.merchant || '(no merchant)'}</div>
            <div className="meta">{item.date}</div>
          </div>
        </div>

        <div className={`amount ${isIncome ? 'income' : 'expense'}`}>
          {isIncome ? '+' : '−'}{fmt(Math.abs(amount))}
        </div>

        {isIncome && (
          <div className="row" style={{ gap: 8, marginBottom: 16 }}>
            <div className="type-toggle" style={{ display: 'flex' }}>
              <button
                type="button"
                className={incomeMode === 'paycheck' ? 'active' : ''}
                onClick={() => setIncomeMode('paycheck')}
              >Paycheck</button>
              <button
                type="button"
                className={incomeMode === 'reimbursement' ? 'active' : ''}
                onClick={() => setIncomeMode('reimbursement')}
              >Reimbursement</button>
            </div>
            <span className="small muted" style={{ alignSelf: 'center' }}>
              {incomeMode === 'paycheck'
                ? 'Tracked as actual income — already covered by your plan'
                : 'Credits a specific fund (e.g. roommate split, refund)'}
            </span>
          </div>
        )}

        {suggestedFund && (!isIncome || incomeMode === 'reimbursement') && (
          <div className="suggestion-box">
            <div>
              <div className="label">Suggested</div>
              <div className="value">{suggestedFund.name}</div>
            </div>
            <div className="ai-tag">AI</div>
          </div>
        )}

        {(!isIncome || incomeMode === 'reimbursement') && (
          <>
            <div className="eyebrow" style={{ marginBottom: 8 }}>
              {isIncome ? 'Credit which fund?' : 'Assign to fund'}
            </div>
            <div className="fund-picker">
              {funds.map(f => (
                <button
                  key={f.id}
                  type="button"
                  className={`fund-pill ${String(f.id) === chosenId ? 'selected' : ''}`}
                  onClick={() => setOverride(String(f.id))}
                >
                  {f.name}
                </button>
              ))}
            </div>
          </>
        )}

        {err && <div className="bad small" style={{ marginBottom: 8 }}>{err}</div>}

        <div className="tx-actions">
          <button className="btn reject-btn" onClick={reject} disabled={busy}>
            <Icon name="x" /> Reject
          </button>
          <button
            className="btn approve-btn"
            onClick={approve}
            disabled={busy || (!(isIncome && incomeMode === 'paycheck') && !chosenId)}
          >
            <Icon name="check" /> Approve
          </button>
        </div>
      </div>
    </div>
  )
}
