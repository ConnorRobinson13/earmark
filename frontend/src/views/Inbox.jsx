import { useState } from 'react'
import { api, fmt } from '../api'
import { keys, useInvalidate, useResource, writes } from '../resource'
import ErrorCard from '../components/ErrorCard'
import { Icon } from '../components/Icons'

export default function Inbox() {
  const inboxRes = useResource(keys.inbox())
  const fundsRes = useResource(keys.funds())
  const invalidate = useInvalidate()
  // Items this session has already ruled on. The refetch that follows a
  // decision removes them for real; until it lands this is what stops the item
  // just approved from sitting there a second time.
  const [decided, setDecided] = useState(() => new Set())
  const [override, setOverride] = useState('')
  const [actionErr, setActionErr] = useState(null)
  const [busy, setBusy] = useState(false)
  // For income items: user picks "Paycheck" (untagged, doesn't bump Unassigned —
  // already covered by planned income) OR a fund (= reimbursement, credits that fund).
  const [incomeMode, setIncomeMode] = useState('paycheck')

  const error = inboxRes.error || fundsRes.error
  if (error) return <ErrorCard error={error} />
  if (!inboxRes.data || !fundsRes.data) return <div className="muted">Loading…</div>

  const pending = inboxRes.data
  const funds = fundsRes.data
  const items = pending.filter(it => !decided.has(it.id))
  const done = pending.length - items.length
  const item = items[0]

  async function syncPlaid() {
    setBusy(true); setActionErr(null)
    try { await api.plaid.sync(); invalidate(writes.plaid) }
    catch (e) { setActionErr(e) }
    finally { setBusy(false) }
  }

  if (!item) {
    return (
      <div className="inbox-wrap">
        <div className="inbox-empty">
          <div className="icon"><Icon name="check" size={28} /></div>
          <h2>All caught up</h2>
          <p>No pending transactions to categorize.</p>
          <button className="btn primary" onClick={syncPlaid} disabled={busy}>
            <Icon name="sync" /> {busy ? 'Syncing…' : 'Sync Plaid'}
          </button>
          {actionErr && <ErrorCard error={actionErr} />}
        </div>
      </div>
    )
  }

  const suggestedFund = funds.find(f => f.id === item.suggested_fund_id)
  const chosenId = override || (item.suggested_fund_id ? String(item.suggested_fund_id) : '')
  const amount = item.amount
  const isIncome = amount < 0
  const initials = (item.merchant || '?').trim().slice(0, 2).toUpperCase()

  /** Hide the item we just ruled on, and pull the fresh list in behind it. */
  function settled() {
    setDecided(d => new Set(d).add(item.id))
    setOverride('')
    setIncomeMode('paycheck')
    invalidate(writes.inboxDecision)
  }

  async function approve() {
    setBusy(true); setActionErr(null)
    try {
      if (isIncome && incomeMode === 'paycheck') {
        await api.inbox.approve(item.id, null, true)
      } else {
        if (!chosenId) { setBusy(false); return }
        await api.inbox.approve(item.id, Number(chosenId), false)
      }
      settled()
    } catch (e) { setActionErr(e) }
    finally { setBusy(false) }
  }

  async function reject() {
    setBusy(true); setActionErr(null)
    try {
      await api.inbox.reject(item.id)
      settled()
    } catch (e) { setActionErr(e) }
    finally { setBusy(false) }
  }

  const progressPct = (done / pending.length) * 100

  return (
    <div className="inbox-wrap">
      <div className="inbox-progress">
        <div className="bar"><div style={{ width: `${progressPct}%` }} /></div>
        <div className="count">{done + 1} / {pending.length}</div>
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

        {actionErr && <ErrorCard error={actionErr} />}

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
