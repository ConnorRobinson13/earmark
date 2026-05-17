import { useEffect, useState } from 'react'
import { api, fmt, todayISO } from '../api'

export default function Goals() {
  const [funds, setFunds] = useState([])
  const [accounts, setAccounts] = useState([])
  const [unassigned, setUnassigned] = useState(0)
  const [err, setErr] = useState('')
  const [showAdd, setShowAdd] = useState(false)

  async function load() {
    try {
      const [all, dash, accts] = await Promise.all([
        api.funds.list(), api.dashboard(), api.accounts.list(),
      ])
      setFunds(all.filter(f => f.kind === 'goal'))
      setUnassigned(Number(dash.unassigned))
      setAccounts(accts)
    } catch (e) { setErr(String(e)) }
  }
  useEffect(() => { load() }, [])

  if (err) return <div className="card bad">{err}</div>

  return (
    <div>
      <h1>Goals</h1>
      {funds.length === 0 && <div className="card muted">No goals yet.</div>}
      {funds.map(g => (
        <GoalCard key={g.id} goal={g} unassigned={unassigned} accounts={accounts} onChange={load} />
      ))}

      <button className="primary" onClick={() => setShowAdd(s => !s)}>
        {showAdd ? 'Cancel' : 'New goal'}
      </button>
      {showAdd && <NewGoal accounts={accounts} onCreated={() => { setShowAdd(false); load() }} />}
    </div>
  )
}

function GoalCard({ goal, unassigned, accounts, onChange }) {
  const [contributing, setContributing] = useState(false)
  const balance = Number(goal.balance)
  const target = Number(goal.target || 0)
  const pct = target > 0 ? Math.min(100, Math.max(0, (balance / target) * 100)) : 0
  const remaining = Math.max(0, target - balance)
  const backingAcct = accounts.find(a => a.id === goal.backed_by_account_id)

  async function del() {
    const msg = balance !== 0
      ? `Delete "${goal.name}"? Balance of ${balance.toLocaleString('en-US',{style:'currency',currency:'USD'})} will be swept back to Unassigned.`
      : `Delete "${goal.name}"?`
    if (!confirm(msg)) return
    await api.funds.archive(goal.id)
    onChange()
  }

  async function setAccount(accountIdStr) {
    const id = accountIdStr ? Number(accountIdStr) : null
    await api.funds.update(goal.id, { backed_by_account_id: id })
    onChange()
  }

  return (
    <div className="card">
      <div className="row">
        <div className="col" style={{ flex: 1 }}>
          <div className="name" style={{ fontSize: 16 }}>{goal.name}</div>
          <div className="muted small">{goal.target_date || 'no deadline'}</div>
        </div>
        <button className="ghost" onClick={() => setContributing(c => !c)}>
          {contributing ? 'Cancel' : '+ Contribute'}
        </button>
        <button className="ghost" onClick={del} title="Delete">×</button>
      </div>
      <div className="large" style={{ margin: '8px 0' }}>{fmt(balance)}</div>
      <div className="progress"><div style={{ width: `${pct}%` }} /></div>
      <div className="muted small" style={{ marginTop: 6 }}>
        {fmt(remaining)} to {fmt(target)} · {pct.toFixed(0)}%
      </div>

      <div className="row" style={{ marginTop: 10, gap: 8 }}>
        <span className="muted small">Backed by</span>
        <select
          value={goal.backed_by_account_id || ''}
          onChange={(e) => setAccount(e.target.value)}
          style={{ flex: 1 }}
        >
          <option value="">No specific account</option>
          {accounts.map(a => <option key={a.id} value={a.id}>{a.name} ({a.type})</option>)}
        </select>
      </div>
      {backingAcct && (
        <div className="muted small" style={{ marginTop: 4 }}>
          {backingAcct.name} balance: {fmt(backingAcct.current_balance)}
        </div>
      )}

      {contributing && (
        <ContributeForm
          goal={goal}
          unassigned={unassigned}
          onDone={() => { setContributing(false); onChange() }}
        />
      )}
    </div>
  )
}

function ContributeForm({ goal, unassigned, onDone }) {
  const [amount, setAmount] = useState('')
  const [source, setSource] = useState('unassigned')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function submit(e) {
    e.preventDefault()
    setErr('')
    const n = Number(amount)
    if (!Number.isFinite(n) || n <= 0) { setErr('Amount must be > 0'); return }
    setBusy(true)
    try {
      if (source === 'unassigned') {
        await api.transactions.assign({
          fund_id: goal.id, amount: n, date: todayISO(),
          notes: 'Goal contribution',
        })
      } else {
        // direct deposit — money entering the goal from outside (e.g. paycheck deduction
        // straight to Roth, gift, transfer-in). Doesn't touch Unassigned.
        await api.transactions.quickAdd({
          fund_id: goal.id, amount: n, date: todayISO(),
          merchant: 'Direct deposit', type: 'income',
        })
      }
      onDone()
    } catch (e) { setErr(String(e)) }
    finally { setBusy(false) }
  }

  return (
    <form onSubmit={submit} className="stack" style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
      <input
        autoFocus
        inputMode="decimal"
        placeholder="Amount"
        value={amount}
        onChange={e => setAmount(e.target.value.replace(/-/g, ''))}
      />
      <select value={source} onChange={e => setSource(e.target.value)}>
        <option value="unassigned">From Unassigned ({fmt(unassigned)} available)</option>
        <option value="external">Direct deposit (external money)</option>
      </select>
      {err && <div className="bad small">{err}</div>}
      <button className="primary" disabled={busy}>
        {busy ? 'Saving…' : 'Add contribution'}
      </button>
    </form>
  )
}

function NewGoal({ accounts, onCreated }) {
  const [name, setName] = useState('')
  const [target, setTarget] = useState('')
  const [targetDate, setTargetDate] = useState('')
  const [startingBalance, setStartingBalance] = useState('')
  const [accountId, setAccountId] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function submit(e) {
    e.preventDefault()
    setErr('')
    if (!name.trim() || !target) { setErr('Name and target required'); return }
    setBusy(true)
    try {
      const fund = await api.funds.create({
        name: name.trim(),
        kind: 'goal',
        target: Number(target),
        target_date: targetDate || null,
        backed_by_account_id: accountId ? Number(accountId) : null,
      })
      const start = Number(startingBalance)
      if (Number.isFinite(start) && start > 0) {
        await api.transactions.quickAdd({
          fund_id: fund.id,
          amount: start,
          date: todayISO(),
          merchant: 'Starting balance',
          type: 'income',
        })
      }
      onCreated()
    } catch (e) { setErr(String(e)); setBusy(false) }
  }

  return (
    <form className="card stack" onSubmit={submit} style={{ marginTop: 12 }}>
      <input placeholder="Goal name (e.g. Roth IRA 2026)" value={name} onChange={e => setName(e.target.value)} />
      <input placeholder="Target amount" inputMode="decimal" value={target}
        onChange={e => setTarget(e.target.value.replace(/-/g, ''))} />
      <input type="date" value={targetDate} onChange={e => setTargetDate(e.target.value)} />
      <input
        placeholder="Starting balance (optional — money already in this account)"
        inputMode="decimal"
        value={startingBalance}
        onChange={e => setStartingBalance(e.target.value.replace(/-/g, ''))}
      />
      <select value={accountId} onChange={e => setAccountId(e.target.value)}>
        <option value="">Backed by account (optional)</option>
        {accounts.map(a => <option key={a.id} value={a.id}>{a.name} ({a.type})</option>)}
      </select>
      {err && <div className="bad small">{err}</div>}
      <button className="primary" disabled={busy}>
        {busy ? 'Creating…' : 'Create goal'}
      </button>
    </form>
  )
}
