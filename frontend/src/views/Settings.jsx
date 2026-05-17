import { useEffect, useState } from 'react'
import { api, fmt } from '../api'

export default function Settings() {
  const [accounts, setAccounts] = useState([])
  const [err, setErr] = useState('')
  const [name, setName] = useState('')
  const [type, setType] = useState('checking')
  const [balance, setBalance] = useState('')

  async function load() {
    try { setAccounts(await api.accounts.list()) }
    catch (e) { setErr(String(e)) }
  }
  useEffect(() => { load() }, [])

  const [addErr, setAddErr] = useState('')
  const [addStatus, setAddStatus] = useState('')
  const [busy, setBusy] = useState(false)

  async function addAccount(e) {
    e.preventDefault()
    setAddErr(''); setAddStatus('')
    if (!name.trim()) { setAddErr('Name required'); return }
    setBusy(true)
    try {
      const bal = Number(balance)
      const a = await api.accounts.create({
        name: name.trim(),
        type,
        current_balance: Number.isFinite(bal) ? bal : 0,
      })
      setName(''); setBalance('')
      setAddStatus(`Added "${a.name}"`)
      load()
    } catch (err) {
      setAddErr(String(err))
    } finally {
      setBusy(false)
    }
  }

  async function updateBalance(id, v) {
    await api.accounts.update(id, { current_balance: Number(v) })
    load()
  }

  async function deleteAccount(id, name) {
    if (!confirm(`Delete account "${name}"?`)) return
    await api.accounts.delete(id)
    load()
  }

  return (
    <div>
      <h1>Settings</h1>
      {err && <div className="card bad">{err}</div>}

      <h2>Accounts</h2>
      <div className="card">
        {accounts.length === 0 && <div className="muted small">No accounts yet.</div>}
        {accounts.map(a => (
          <div key={a.id} className="fund-row">
            <div className="col" style={{ flex: 1 }}>
              <div className="name">{a.name}</div>
              <div className="meta">{a.type}</div>
            </div>
            <input
              style={{ maxWidth: 120 }}
              inputMode="decimal"
              defaultValue={a.current_balance}
              onBlur={e => updateBalance(a.id, e.target.value)}
            />
            <button className="ghost" title="Delete" onClick={() => deleteAccount(a.id, a.name)}>×</button>
          </div>
        ))}
      </div>

      <h2>Add account</h2>
      <form className="card stack" onSubmit={addAccount}>
        <input placeholder="Name" value={name} onChange={e => setName(e.target.value)} />
        <select value={type} onChange={e => setType(e.target.value)}>
          <option value="checking">Checking</option>
          <option value="savings">Savings</option>
          <option value="credit">Credit card</option>
        </select>
        <input placeholder="Current balance" inputMode="decimal" value={balance} onChange={e => setBalance(e.target.value)} />
        {addErr && <div className="bad small">{addErr}</div>}
        {addStatus && <div className="good small">{addStatus}</div>}
        <button type="submit" className="primary" disabled={busy}>
          {busy ? 'Adding…' : 'Add account'}
        </button>
      </form>

      <h2>Plaid</h2>
      <div className="card">
        <PlaidSection />
      </div>

      <h2>Danger zone</h2>
      <div className="card">
        <ResetSection />
      </div>
    </div>
  )
}

function ResetSection() {
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  async function reset() {
    if (!confirm('Wipe all data and re-seed to the May 2026 snapshot?')) return
    setBusy(true); setStatus('Resetting…')
    try {
      await api.admin.resetToSeed()
      setStatus('Done. Reload to see fresh data.')
    } catch (e) { setStatus(String(e)) }
    finally { setBusy(false) }
  }
  return (
    <div className="stack">
      <div className="muted small">
        Wipes all accounts, funds, transactions, and templates, then re-runs the seed script.
      </div>
      <button className="danger" onClick={reset} disabled={busy}>Reset to seed</button>
      {status && <div className="small muted">{status}</div>}
    </div>
  )
}

function PlaidSection() {
  const [status, setStatus] = useState('')
  async function sync() {
    setStatus('Syncing…')
    try {
      const r = await api.plaid.sync()
      setStatus(`Added ${r.added} to inbox`)
    } catch (e) { setStatus(String(e)) }
  }
  return (
    <div className="stack">
      <div className="muted small">
        Plaid Link UI not implemented in v1 — link your first item via the API.
      </div>
      <button onClick={sync}>Sync transactions</button>
      {status && <div className="small muted">{status}</div>}
    </div>
  )
}
