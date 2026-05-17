import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, fmt } from '../api'

export default function FundDetail() {
  const { id } = useParams()
  const [fund, setFund] = useState(null)
  const [txns, setTxns] = useState([])
  const [err, setErr] = useState('')

  async function load() {
    try {
      const [f, t] = await Promise.all([api.funds.get(id), api.transactions.list({ fund_id: id, limit: 200 })])
      setFund(f); setTxns(t)
    } catch (e) { setErr(String(e)) }
  }
  useEffect(() => { load() }, [id])

  async function del(txId) {
    if (!confirm('Delete this transaction?')) return
    await api.transactions.delete(txId)
    await load()
  }

  if (err) return <div className="card bad">{err}</div>
  if (!fund) return <div className="muted">Loading…</div>

  return (
    <div>
      <Link to="/" className="small muted">← Home</Link>
      <h1>{fund.name}</h1>
      <div className="card">
        <div className="muted small">Balance</div>
        <div className={`xlarge ${Number(fund.balance) < 0 ? 'bad' : ''}`}>{fmt(fund.balance)}</div>
        <div className="muted small">Spent this month: {fmt(fund.net_spent_this_month)}</div>
        {fund.target && <div className="muted small">Target: {fmt(fund.target)}</div>}
        <div style={{ marginTop: 10 }}>
          <div className="muted small">Category</div>
          <input
            placeholder="Uncategorized"
            defaultValue={fund.category || ''}
            onBlur={async (e) => {
              const v = e.target.value.trim()
              if (v === (fund.category || '')) return
              await api.funds.update(fund.id, { category: v || null })
              load()
            }}
            style={{ maxWidth: 240 }}
          />
        </div>
      </div>

      <h2>History</h2>
      <div className="card">
        {txns.length === 0 && <div className="muted small">No transactions yet.</div>}
        {txns.map(t => (
          <div key={t.id} className="fund-row">
            <div className="col" style={{ flex: 1 }}>
              <div className="name">{t.merchant || `(${t.type})`}</div>
              <div className="meta">{t.date} · {t.type}</div>
            </div>
            <div className="col" style={{ alignItems: 'flex-end' }}>
              <div className={Number(t.amount) >= 0 ? 'good' : 'bad'}>
                {Number(t.amount) >= 0 ? '+' : ''}{fmt(t.amount)}
              </div>
              <button className="ghost small" onClick={() => del(t.id)}>delete</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
