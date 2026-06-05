import { useEffect, useRef, useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { api, todayISO, fmt } from '../api'
import { Icon } from '../components/Icons'

export default function QuickAdd() {
  const { refresh } = useOutletContext()
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
    setTimeout(() => amountRef.current?.focus(), 50)
  }, [])

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
      refresh()
      nav('/')
    } catch (e) { setErr(String(e)); setBusy(false) }
  }

  function close() { nav('/') }

  return (
    <div className="modal-backdrop" onClick={close}>
      <form className="modal" onClick={e => e.stopPropagation()} onSubmit={submit}>
        <div className="row" style={{ marginBottom: 12 }}>
          <h2 style={{ flex: 1, margin: 0 }}>Quick add</h2>
          <div className="type-toggle">
            <button type="button" className={type === 'expense' ? 'active' : ''} onClick={() => setType('expense')}>− Expense</button>
            <button type="button" className={type === 'income' ? 'active' : ''} onClick={() => setType('income')}>+ Income</button>
          </div>
        </div>

        <div className="field">
          <label>Amount</label>
          <input
            ref={amountRef}
            className="amount-input"
            inputMode="decimal"
            placeholder="0.00"
            value={amount}
            onChange={e => setAmount(e.target.value)}
          />
        </div>

        <div className="field">
          <label>Merchant / source</label>
          <input value={merchant} onChange={e => setMerchant(e.target.value)} placeholder="e.g. Trader Joe's" />
        </div>

        <div className="field">
          <label>Fund</label>
          <div className="fund-picker" style={{ maxHeight: 120 }}>
            {funds.map(f => (
              <button
                key={f.id}
                type="button"
                className={`fund-pill ${String(f.id) === fundId ? 'selected' : ''}`}
                onClick={() => { setFundId(String(f.id)); setSuggestSrc('') }}
              >
                {f.name}
              </button>
            ))}
          </div>
          {suggestSrc && (
            <div className="small muted">Auto-picked via {suggestSrc}</div>
          )}
        </div>

        <div className="field">
          <label>Date</label>
          <input type="date" value={date} onChange={e => setDate(e.target.value)} />
        </div>

        {err && <div className="bad small">{err}</div>}

        <div className="actions">
          <button type="button" className="btn ghost" onClick={close}>Cancel</button>
          <button className="btn primary" disabled={busy || !fundId || !Number(amount)}>
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </div>
  )
}
