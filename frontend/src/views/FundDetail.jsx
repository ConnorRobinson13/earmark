import { Link, useParams } from 'react-router-dom'
import { api, fmt } from '../api'
import { keys, useInvalidate, useResource, writes } from '../resource'
import ErrorCard from '../components/ErrorCard'
import { Icon } from '../components/Icons'
import { isGoal } from '../funds'

export default function FundDetail() {
  const { id } = useParams()
  const invalidate = useInvalidate()
  const fundRes = useResource(keys.fund(id))
  const txnsRes = useResource(keys.fundTransactions(id))

  const fund = fundRes.data
  const txns = txnsRes.data

  async function del(txId) {
    if (!confirm('Delete this transaction?')) return
    await api.transactions.delete(txId)
    invalidate(writes.ledger)
  }

  const error = fundRes.error || txnsRes.error
  if (error) return <ErrorCard error={error} />
  if (!fund || !txns) return <div className="muted">Loading…</div>

  const balance = fund.balance
  const spent = fund.net_spent_this_month
  const assigned = fund.assigned_this_month
  const available = fund.available_this_month

  return (
    <div>
      <div className="fd-hero">
        <div className="crumbs">
          <Link to="/" style={{ color: 'var(--text-dim)' }}>Dashboard</Link>
          <span> / </span>
          <span>{fund.category || 'Uncategorized'}</span>
        </div>
        <h1>{fund.name}</h1>

        <div className="stats">
          <div className="stat">
            <div className="lbl">Balance</div>
            <div className={`val ${balance < 0 ? 'bad' : ''}`}>{fmt(balance)}</div>
          </div>
          <div className="stat">
            <div className="lbl">Assigned this month</div>
            <div className="val">{fmt(assigned)}</div>
          </div>
          <div className="stat">
            <div className="lbl">Spent this month</div>
            <div className="val">{fmt(spent)}</div>
          </div>
          <div className="stat">
            <div className="lbl">{isGoal(fund) ? 'Target' : 'Available'}</div>
            <div className="val">{fmt(isGoal(fund) ? (fund.target ?? 0) : available)}</div>
          </div>
        </div>

        <div className="row" style={{ marginTop: 18, gap: 10 }}>
          <span className="eyebrow">Category</span>
          <input
            defaultValue={fund.category || ''}
            placeholder="Uncategorized"
            onBlur={async (e) => {
              const v = e.target.value.trim()
              if (v === (fund.category || '')) return
              await api.funds.update(fund.id, { category: v || null })
              invalidate(writes.ledger)
            }}
            style={{ maxWidth: 240 }}
          />
        </div>
      </div>

      <div className="sec-head" style={{ marginTop: 8 }}>
        <h2>History</h2>
        <span className="sub">{txns.length} transaction{txns.length === 1 ? '' : 's'}</span>
      </div>

      {txns.length === 0 ? (
        <div className="card muted">No transactions yet.</div>
      ) : (
        <div className="tx-list">
          {txns.map(t => {
            const n = t.amount
            const isIncome = n >= 0 && (t.type === 'income' || t.type === 'assignment')
            return (
              <div key={t.id} className="tx-row">
                <div className="date">{t.date}</div>
                <div className="merchant">
                  {t.merchant || <span className="muted">({t.type})</span>}
                  {t.notes && <div className="notes">{t.notes}</div>}
                </div>
                <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}>
                  <div className={`amount ${isIncome ? 'income' : 'outflow'}`}>
                    {n >= 0 ? '+' : ''}{fmt(n)}
                  </div>
                  <button className="btn ghost sm" title="Delete" onClick={() => del(t.id)}>
                    <Icon name="trash" size={12} />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
