import { useState } from 'react'
import { api, fmt } from '../api'
import { keys, useInvalidate, useResource, writes } from '../resource'
import ErrorCard from '../components/ErrorCard'
import { relativeTime } from '../format'
import { Icon } from '../components/Icons'
import PlaidConnect, { LinkedItems } from '../components/PlaidConnect'

export default function Settings() {
  const accountsRes = useResource(keys.accounts())
  const fundsRes = useResource(keys.funds())
  const invalidate = useInvalidate()
  const [showAdd, setShowAdd] = useState(false)

  const accounts = accountsRes.data || []
  // The fund list only decorates the account cards with the goals they back,
  // so losing it costs the reconciliation panel, not the page.
  const funds = fundsRes.data || []

  async function updateBalance(id, v) {
    await api.accounts.update(id, { current_balance: Number(v) })
    invalidate(writes.balances)
  }

  async function updateType(id, type) {
    await api.accounts.update(id, { type })
    invalidate(writes.balances)
  }

  async function deleteAccount(id, name) {
    if (!confirm(`Delete account "${name}"?`)) return
    await api.accounts.delete(id)
    invalidate(writes.balances)
  }

  if (accountsRes.error) return <ErrorCard error={accountsRes.error} />

  return (
    <div>
      <div className="sec-head" style={{ marginTop: 0 }}>
        <h2>Accounts</h2>
        <span className="sub">checking, savings, credit</span>
        <div className="spacer" />
        <button className="btn primary sm" onClick={() => setShowAdd(true)}>
          <Icon name="plus" /> Add account
        </button>
      </div>

      {accounts.length === 0 && <div className="card muted">No accounts yet.</div>}

      <div className="acct-grid">
        {accounts.map(a => {
          const tracked = funds
            .filter(f => f.backed_by_account_id === a.id && f.kind === 'goal')
            .map(f => ({
              id: f.id, name: f.name,
              amount: Number(f.balance),
              type: f.goal_type,
            }))
          return (
            <AccountCard key={a.id} acct={a} tracked={tracked}
              onUpdate={updateBalance} onDelete={deleteAccount} onChangeType={updateType} />
          )
        })}
      </div>

      <div className="sec-head">
        <h2>Bank connections</h2>
        <span className="sub">Plaid</span>
      </div>
      <PlaidSection />
      <div style={{ height: 24 }} />

      <div className="sec-head">
        <h2>Danger zone</h2>
        <span className="sub">irreversible</span>
      </div>
      <div className="card">
        <ResetSection />
      </div>

      {showAdd && (
        <AddAccountModal onClose={() => setShowAdd(false)} onAdded={() => setShowAdd(false)} />
      )}
    </div>
  )
}

function AccountCard({ acct, tracked = [], onUpdate, onDelete, onChangeType }) {
  const [editing, setEditing] = useState(false)
  const [val, setVal] = useState(String(acct.current_balance))
  const isCredit = acct.type === 'credit'
  const isInvestment = acct.type === 'investment'
  const acctBal = Number(acct.current_balance)
  const trackedSum = tracked.reduce((s, g) => s + g.amount, 0)
  const drift = acctBal - trackedSum
  const hasGoals = tracked.length > 0
  const reconciled = Math.abs(drift) < 0.01

  function startEdit() {
    setVal(String(acct.current_balance))
    setEditing(true)
  }
  async function commit() {
    setEditing(false)
    if (Number(val) !== Number(acct.current_balance)) {
      await onUpdate(acct.id, val)
    }
  }

  return (
    <div className={`acct-card ${isCredit ? 'credit' : ''}`}>
      <div className="row" style={{ alignItems: 'flex-start' }}>
        <div className="col" style={{ flex: 1 }}>
          <select
            className="acct-type-select"
            value={acct.type}
            onChange={(e) => onChangeType?.(acct.id, e.target.value)}
            title="Change account type"
          >
            <option value="checking">checking</option>
            <option value="savings">savings</option>
            <option value="emergency_fund">emergency fund</option>
            <option value="credit">credit</option>
            <option value="investment">investment</option>
          </select>
          <div className="name">{acct.name}</div>
        </div>
        <button className="btn ghost sm" title="Delete" onClick={() => onDelete(acct.id, acct.name)}>
          <Icon name="trash" size={14} />
        </button>
      </div>
      {editing ? (
        <input
          autoFocus
          inputMode="decimal"
          value={val}
          onChange={e => setVal(e.target.value)}
          onBlur={commit}
          onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(false) }}
          style={{ marginTop: 10 }}
        />
      ) : (
        <button className="bal" onClick={startEdit} title="Click to edit balance"
          style={{ background: 'transparent', textAlign: 'left', cursor: 'pointer', display: 'block', width: '100%' }}>
          {fmt(acct.current_balance)}
        </button>
      )}
      <FreshnessLine acct={acct} onUpdate={startEdit} />
      {hasGoals && !isCredit && (
        <div className="acct-recon">
          <div className="acct-recon-head">
            <span className="eyebrow">Goals tracked</span>
            <span className={`recon-badge ${reconciled ? 'ok' : drift > 0 ? 'unallocated' : 'over'}`}>
              {reconciled ? '✓ reconciled' :
               drift > 0
                 ? (isInvestment ? `+${fmt(drift)} growth / extra` : `+${fmt(drift)} unallocated`)
                 : `${fmt(Math.abs(drift))} over-allocated`}
            </span>
          </div>
          <div className="acct-recon-list">
            {tracked.map(g => (
              <div key={g.id} className="acct-recon-row">
                <span>{g.name}</span>
                {g.type === 'contribution' && <span className="goal-badge contribution" style={{ fontSize: 9 }}>contribution</span>}
                <div className="spacer" />
                <span className="num">{fmt(g.amount)}</span>
              </div>
            ))}
            <div className="acct-recon-row total">
              <span>Sum of goals</span>
              <div className="spacer" />
              <span className="num">{fmt(trackedSum)}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function FreshnessLine({ acct, onUpdate }) {
  const sync = acct.last_synced_at ? new Date(acct.last_synced_at) : null
  const ageMs = sync ? Date.now() - sync.getTime() : Infinity
  const ageDays = ageMs / (1000 * 60 * 60 * 24)
  const stale = ageDays > 7
  const veryStale = ageDays > 30
  const tone = veryStale ? 'bad' : stale ? 'warn' : 'muted'
  const linked = !!acct.plaid_account_id
  const label = !sync
    ? 'never synced — click balance to set'
    : `${linked ? 'Plaid sync' : 'manual'} · ${relativeTime(sync)}`

  return (
    <div className="row" style={{ marginTop: 6, gap: 8 }}>
      <span className={`sync small ${tone}`}>{label}</span>
      <div className="spacer" />
      {!linked && (
        <button className="btn ghost sm" onClick={onUpdate}>
          <Icon name="sync" size={12} /> Update
        </button>
      )}
    </div>
  )
}

function AddAccountModal({ onClose, onAdded }) {
  const invalidate = useInvalidate()
  const [name, setName] = useState('')
  const [type, setType] = useState('checking')
  const [balance, setBalance] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setErr('')
    if (!name.trim()) { setErr('Name required'); return }
    setBusy(true)
    try {
      const bal = Number(balance)
      await api.accounts.create({
        name: name.trim(),
        type,
        current_balance: Number.isFinite(bal) ? bal : 0,
      })
      invalidate(writes.balances)
      onAdded()
    } catch (e) { setErr(String(e)); setBusy(false) }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="modal" onClick={e => e.stopPropagation()} onSubmit={submit}>
        <h2>Add account</h2>
        <div className="field">
          <label>Name</label>
          <input autoFocus value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Chase Checking" />
        </div>
        <div className="field">
          <label>Type</label>
          <select value={type} onChange={e => setType(e.target.value)}>
            <option value="checking">Checking</option>
            <option value="savings">Savings</option>
            <option value="emergency_fund">Emergency fund</option>
            <option value="credit">Credit card</option>
            <option value="investment">Investment (IRA / brokerage / 401k)</option>
          </select>
        </div>
        <div className="field">
          <label>Current balance</label>
          <input inputMode="decimal" value={balance} onChange={e => setBalance(e.target.value)} placeholder="0.00" />
        </div>
        {err && <div className="bad small">{err}</div>}
        <div className="actions">
          <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy}>{busy ? 'Adding…' : 'Add account'}</button>
        </div>
      </form>
    </div>
  )
}

function PlaidSection() {
  const { data, error } = useResource(keys.plaidItems())
  const invalidate = useInvalidate()
  const [status, setStatus] = useState('')
  const [syncing, setSyncing] = useState(false)

  const items = data || []
  // A 400 saying the credentials are missing is a setup step to explain, not a
  // failure to report — PlaidConnect renders the instructions instead.
  const hasCreds = !(error?.status === 400 && String(error.detail).includes('Plaid credentials not configured'))

  async function sync() {
    setSyncing(true); setStatus('')
    try {
      const r = await api.plaid.sync()
      setStatus(`Added ${r.added} transaction${r.added === 1 ? '' : 's'} to inbox`)
      invalidate(writes.plaid)
    } catch (e) { setStatus(String(e)) }
    finally { setSyncing(false) }
  }

  async function unlink(id, name) {
    const lines = [
      `Unlink ${name || 'this institution'}?`,
      '',
      'IMPORTANT: Plaid\'s Trial plan caps you at 10 Items lifetime — unlinking does NOT free the slot. You can re-link the same institution without burning another slot, but linking a different one will.',
      '',
      'Accounts stay; new transactions stop syncing.',
    ]
    if (!confirm(lines.join('\n'))) return
    await api.plaid.unlinkItem(id)
    invalidate(writes.plaid)
  }

  const atCap = items.length >= 10

  return (
    <div className="stack">
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <PlaidConnect hasCreds={hasCreds} onLinked={() => invalidate(writes.plaid)} disabled={atCap} />
        {items.length > 0 && (
          <button className="btn" onClick={sync} disabled={syncing}>
            <Icon name="sync" /> {syncing ? 'Syncing…' : 'Sync now'}
          </button>
        )}
        <div className="spacer" />
        <span className={`small ${atCap ? 'bad' : 'muted'}`}>
          {items.length} / 10 trial Items used
        </span>
      </div>
      {status && <div className="small muted">{status}</div>}
      <LinkedItems items={items} onUnlink={unlink} />
    </div>
  )
}

function ResetSection() {
  const invalidate = useInvalidate()
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  async function reset() {
    if (!confirm('Wipe all data and re-seed to the May 2026 snapshot?')) return
    setBusy(true); setStatus('Resetting…')
    try {
      await api.admin.resetToSeed()
      setStatus('Done.')
      // The one write that really does make everything on screen stale.
      invalidate(writes.everything)
    } catch (e) { setStatus(String(e)) }
    finally { setBusy(false) }
  }
  return (
    <div className="stack">
      <div className="muted small">
        Wipes all accounts, funds, transactions, and templates, then re-runs the seed script.
      </div>
      <div className="row" style={{ gap: 8 }}>
        <button className="btn danger" onClick={reset} disabled={busy}>Reset to seed</button>
        {status && <span className="small muted">{status}</span>}
      </div>
    </div>
  )
}
