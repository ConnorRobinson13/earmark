import { useState } from 'react'
import { api, fmt } from '../api'
import { keys, useResource } from '../resource'
import ErrorCard from './ErrorCard'
import { Icon } from './Icons'

/**
 * "Move money you've earmarked" — end-of-month settlement panel.
 *
 * Lists goals where (assignments_this_month - settlements_this_month) > 0,
 * i.e. money you've budgeted toward the goal but haven't physically moved
 * out of checking yet. Clicking "Mark moved" records a settlement, bumps
 * the source account down and the goal's backing account up.
 */
export default function ToMovePanel({ month, accounts, onMoved }) {
  const { data, error, reload } = useResource(keys.pendingSettlements(month))
  const [settleErr, setSettleErr] = useState('')
  const [busyId, setBusyId] = useState(null)

  if (error) return <ErrorCard error={error} />
  if (settleErr) return <div className="card"><span className="bad">{settleErr}</span></div>

  const items = data || []
  if (items.length === 0) return null

  const total = items.reduce((s, it) => s + it.pending_amount, 0)

  async function settle(item, fromAccountId) {
    setBusyId(item.goal_id)
    try {
      await api.settlements.settle(item.goal_id, {
        amount: item.pending_amount,
        from_account_id: fromAccountId || null,
        settled_at: lastDayOf(month),
      })
      reload()
      onMoved?.()
    } catch (e) {
      setSettleErr(String(e))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="tomove-panel">
      <div className="tomove-head">
        <span className="eyebrow">To move this month</span>
        <span className="amt">{fmt(total)}</span>
      </div>
      <div className="tomove-list">
        {items.map(it => (
          <ToMoveRow
            key={it.goal_id}
            item={it}
            accounts={accounts}
            busy={busyId === it.goal_id}
            onSettle={(fromId) => settle(it, fromId)}
          />
        ))}
      </div>
    </div>
  )
}

function ToMoveRow({ item, accounts, busy, onSettle }) {
  const [fromId, setFromId] = useState(item.suggested_from_account_id || '')
  const toName = item.to_account_name || <span className="muted">— unlinked</span>

  return (
    <div className="tomove-row">
      <div className="goal">{item.goal_name}</div>
      <div className="arrow muted">→</div>
      <div className="dest">{toName}</div>
      <div className="amt num">{fmt(item.pending_amount)}</div>
      <select className="from-pick" value={fromId} onChange={e => setFromId(Number(e.target.value) || '')}>
        <option value="">From…</option>
        {accounts.filter(a => a.type === 'checking' || a.type === 'savings').map(a => (
          <option key={a.id} value={a.id}>{a.name}</option>
        ))}
      </select>
      <button className="btn primary sm" disabled={busy || !fromId} onClick={() => onSettle(fromId)}>
        {busy ? '…' : <><Icon name="check" size={12} /> Mark moved</>}
      </button>
    </div>
  )
}

function lastDayOf(monthStr) {
  // monthStr is YYYY-MM-01. Return YYYY-MM-LL where LL is last day of that month.
  const [y, m] = monthStr.split('-').map(Number)
  const d = new Date(Date.UTC(y, m, 0))  // day 0 of next month = last of this
  return d.toISOString().slice(0, 10)
}
