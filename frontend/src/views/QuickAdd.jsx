import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, todayISO } from '../api'

export default function QuickAdd() {
  const [funds, setFunds] = useState([])
  const [amount, setAmount] = useState('')
  const [merchant, setMerchant] = useState('')
  const [fundId, setFundId] = useState('')
  const [type, setType] = useState('expense')
  const [date, setDate] = useState(todayISO())
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [suggestSrc, setSuggestSrc] = useState('')
  const nav = useNavigate()
  const amountRef = useRef(null)
  const suggestTimer = useRef(null)

  useEffect(() => {
    api.funds.list().then(setFunds).catch(e => setErr(String(e)))
    setTimeout(() => amountRef.current?.focus(), 100)
  }, [])

  // debounce suggest on merchant typing
  useEffect(() => {
    clearTimeout(suggestTimer.current)
    if (!merchant.trim() || fundId) return
    suggestTimer.current = setTimeout(async () => {
      try {
        const r = await api.suggest(merchant, amount ? Number(amount) : null)
        if (r.fund_id) {
          setFundId(String(r.fund_id))
          setSuggestSrc(r.source)
        }
      } catch {}
    }, 400)
    return () => clearTimeout(suggestTimer.current)
  }, [merchant])

  async function submit(e) {
    e.preventDefault()
    if (!fundId || !Number(amount)) return
    setBusy(true); setErr('')
    try {
      await api.transactions.quickAdd({
        fund_id: Number(fundId),
        amount: Number(amount),
        date,
        merchant,
        type,
      })
      nav('/')
    } catch (e) { setErr(String(e)); setBusy(false) }
  }

  return (
    <div>
      <h1>Quick add</h1>
      <form className="card stack" onSubmit={submit}>
        <div className="row" style={{ gap: 8 }}>
          <button
            type="button"
            className={type === 'expense' ? 'primary' : ''}
            onClick={() => setType('expense')}
            style={{ flex: 1 }}
          >− Expense</button>
          <button
            type="button"
            className={type === 'income' ? 'primary' : ''}
            onClick={() => setType('income')}
            style={{ flex: 1 }}
          >+ Income</button>
        </div>

        <input
          ref={amountRef}
          inputMode="decimal"
          placeholder="Amount"
          value={amount}
          onChange={e => setAmount(e.target.value)}
          style={{ fontSize: 22, fontWeight: 600 }}
        />

        <input
          placeholder="Merchant / source"
          value={merchant}
          onChange={e => setMerchant(e.target.value)}
        />

        <select value={fundId} onChange={e => { setFundId(e.target.value); setSuggestSrc('') }}>
          <option value="">Choose fund…</option>
          {funds.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
        </select>
        {suggestSrc && (
          <div className="small muted">Suggested via {suggestSrc}. Change above if wrong.</div>
        )}

        <input type="date" value={date} onChange={e => setDate(e.target.value)} />

        {err && <div className="bad small">{err}</div>}
        <button className="primary" disabled={busy || !fundId || !Number(amount)}>
          Save
        </button>
      </form>
    </div>
  )
}
