import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, fmt } from '../api'
import { keys, useInvalidate, useResource, writes } from '../resource'
import ErrorCard from '../components/ErrorCard'
import CategoryPicker from '../components/CategoryPicker'
import { Icon } from '../components/Icons'
import { isGoal } from '../funds'

export default function FundDetail() {
  const { id } = useParams()
  const invalidate = useInvalidate()
  const fundRes = useResource(keys.fund(id))
  const txnsRes = useResource(keys.fundTransactions(id))
  const fundsRes = useResource(keys.funds())
  const [actionErr, setActionErr] = useState(null)

  const fund = fundRes.data
  const txns = txnsRes.data
  const funds = fundsRes.data

  async function del(txId) {
    if (!confirm('Delete this transaction?')) return
    await api.transactions.delete(txId)
    invalidate(writes.ledger)
  }

  // Re-tag a transaction to another fund. The amount leaves this fund and lands
  // on the destination; both balances re-derive on the refetch `writes.ledger`
  // triggers. A rejected destination surfaces rather than silently no-op'ing.
  async function move(txId, fundId) {
    setActionErr(null)
    try {
      await api.transactions.move(txId, Number(fundId))
      invalidate(writes.ledger)
    } catch (e) {
      setActionErr(e)
    }
  }

  const error = fundRes.error || txnsRes.error || fundsRes.error
  if (error) return <ErrorCard error={error} />
  if (!fund || !txns || !funds) return <div className="muted">Loading…</div>

  // Only ordinary expense/income rows move between funds; assignment and
  // transfer legs are double-entry and must stay balanced. Destinations are the
  // other active funds (archived funds are already filtered out of the list).
  const canMove = (t) =>
    (t.type === 'expense' || t.type === 'income') && !t.linked_transaction_id
  const destFunds = funds.filter(f => f.id !== fund.id)

  const balance = fund.balance
  const spent = fund.net_spent_this_month
  const assigned = fund.assigned_this_month
  const available = fund.available_this_month

  return (
    <div>
      <div className="fd-hero">
        <div className="fd-back-row">
          <Link to="/" className="btn sm fd-back">
            <Icon name="chev_l" /> Back to dashboard
          </Link>
          <span className="crumbs">{fund.category || 'Uncategorized'}</span>
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
          <CategoryPicker
            value={fund.category_id ?? null}
            onChange={async (categoryId) => {
              if (categoryId === (fund.category_id ?? null)) return
              await api.funds.update(fund.id, { category_id: categoryId })
              invalidate(writes.ledger)
            }}
          />
        </div>
      </div>

      <div className="sec-head" style={{ marginTop: 8 }}>
        <h2>History</h2>
        <span className="sub">{txns.length} transaction{txns.length === 1 ? '' : 's'}</span>
      </div>

      {actionErr && <ErrorCard error={actionErr} />}

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
                  {canMove(t) && destFunds.length > 0 && (
                    <select className="fd-move-select"
                      aria-label={`Move transaction ${t.merchant || t.type} ${t.date} to another fund`}
                      value=""
                      onChange={(e) => { if (e.target.value) move(t.id, e.target.value) }}>
                      <option value="">Move to…</option>
                      {destFunds.map(f => (
                        <option key={f.id} value={f.id}>{f.name}</option>
                      ))}
                    </select>
                  )}
                  <button className="btn ghost sm" title="Delete"
                    aria-label={`Delete transaction ${t.merchant || t.type} ${t.date}`}
                    onClick={() => del(t.id)}>
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
