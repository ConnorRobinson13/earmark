import { useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { api, fmt, todayISO } from '../api'
import { keys, useInvalidate, useResource, writes } from '../resource'
import ErrorCard from '../components/ErrorCard'
import GoalSummary, { goalProgress } from '../components/GoalSummary'
import { dateInMonth, thisMonth } from '../components/MonthSelector'
import { isGoal } from '../funds'
import { Icon } from '../components/Icons'

export default function Goals() {
  const { month } = useOutletContext()
  // The dashboard read already carries every fund enriched for the selected
  // month, so this page follows the top bar without a second fund list.
  const dashRes = useResource(keys.dashboard(month))
  const accountsRes = useResource(keys.accounts())
  const [showAdd, setShowAdd] = useState(false)
  const [contributingId, setContributingId] = useState(null)

  if (dashRes.error) return <ErrorCard error={dashRes.error} />
  if (!dashRes.data) return <div className="muted">Loading…</div>

  const isPast = month < thisMonth()
  const goals = dashRes.data.funds.filter(isGoal)
  const unassigned = dashRes.data.unassigned
  // A failed accounts read costs the backing-account picker, not the page.
  const accounts = accountsRes.data || []

  return (
    <div>
      <div className="sec-head" style={{ marginTop: 0 }}>
        <h2>Goals</h2>
        <span className="sub">long-term savings buckets</span>
        <div className="spacer" />
        {isPast ? (
          // A goal created today did not exist in a month that has already
          // ended, so it would not come back in this month's read. Say the
          // month is an archive rather than let one vanish on creation.
          <span style={{ fontSize: 12, color: 'var(--warn)' }}>read-only archive</span>
        ) : (
          <button className="btn primary sm" onClick={() => setShowAdd(true)}>
            <Icon name="plus" /> New goal
          </button>
        )}
      </div>

      {goals.length === 0 && <div className="card muted">No goals yet.</div>}

      <div className="goal-grid">
        {goals.map(g => (
          <GoalCard
            key={g.id}
            goal={g}
            month={month}
            accounts={accounts}
            unassigned={unassigned}
            expanded={contributingId === g.id}
            onToggleContribute={() => setContributingId(id => id === g.id ? null : g.id)}
          />
        ))}
      </div>

      {showAdd && (
        <NewGoalModal
          accounts={accounts}
          onClose={() => setShowAdd(false)}
          onCreated={() => setShowAdd(false)}
        />
      )}
    </div>
  )
}

function GoalCard({ goal, month, accounts, unassigned, expanded, onToggleContribute }) {
  const invalidate = useInvalidate()
  const progress = goalProgress(goal, month)
  const { isDebt, remaining, fixedPayment, minMonthly } = progress
  const backingAcct = accounts.find(a => a.id === goal.backed_by_account_id)

  async function del() {
    const msg = goal.balance !== 0
      ? `Delete "${goal.name}"? Balance of ${fmt(goal.balance)} will be swept back to Unassigned.`
      : `Delete "${goal.name}"?`
    if (!confirm(msg)) return
    await api.funds.archive(goal.id)
    invalidate(writes.ledger)
  }

  async function setAccount(accountIdStr) {
    const id = accountIdStr ? Number(accountIdStr) : null
    await api.funds.update(goal.id, { backed_by_account_id: id })
    invalidate(writes.ledger)
  }

  return (
    <div className="goal-card" style={{ cursor: 'default' }}>
      <GoalSummary goal={goal} progress={progress} />

      {isDebt && remaining > 0 && (
        <div className="goal-min small muted" style={{ marginTop: 6 }}>
          {minMonthly != null
            ? <>minimum <span className="num">{fmt(minMonthly)}</span>/mo{fixedPayment != null ? '' : ' to pay off on time'}</>
            : <>set a payoff date to see the minimum payment</>}
        </div>
      )}

      {!isDebt && (
        <>
          <div className="row" style={{ marginTop: 10, gap: 8 }}>
            <span className="eyebrow">Backed by</span>
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
            <div className="small muted">
              {backingAcct.name} balance: {fmt(backingAcct.current_balance)}
            </div>
          )}
        </>
      )}

      <div className="row" style={{ gap: 6, marginTop: 4 }}>
        <button className="btn sm" onClick={onToggleContribute}>
          {expanded ? 'Cancel' : <><Icon name="plus" size={12} /> {isDebt ? 'Pay down' : 'Contribute'}</>}
        </button>
        <div className="spacer" />
        <button className="btn ghost sm" onClick={del} title="Delete goal">
          <Icon name="trash" size={14} />
        </button>
      </div>

      {expanded && (
        <ContributeForm
          goal={goal}
          month={month}
          accounts={accounts}
          unassigned={unassigned}
          onDone={onToggleContribute}
        />
      )}
    </div>
  )
}

function ContributeForm({ goal, month, accounts, unassigned, onDone }) {
  const invalidate = useInvalidate()
  const isContribution = goal.goal_type === 'contribution'
  const isDebt = goal.goal_type === 'debt'
  const [amount, setAmount] = useState('')
  const [source, setSource] = useState(isContribution ? 'already' : 'unassigned')
  // Backfill default: Jan 1 of the target year, so historical contributions
  // count toward contribution_ytd but NOT toward this-month "Saved" tile.
  // Live moves: default to today.
  const backfillDate = (() => {
    if (!isContribution) return todayISO()
    const year = goal.target_date
      ? new Date(goal.target_date + 'T00:00:00').getUTCFullYear()
      : new Date().getUTCFullYear()
    return `${year}-01-01`
  })()
  const [contribDate, setContribDate] = useState(backfillDate)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function submit(e) {
    e.preventDefault()
    setErr('')
    const n = Number(amount)
    if (!Number.isFinite(n) || n <= 0) { setErr('Amount must be > 0'); return }
    setBusy(true)
    try {
      if (isContribution) {
        // For contribution goals, "Contribute" means "record money physically
        // moved into the destination account" — i.e. a GoalSettlement. This is
        // what contribution_ytd reads from. Source picker chooses whether to
        // also debit a checking account (real this-month move) or just log it
        // historically (backfill of prior contributions).
        const fromAccountId = source && source !== 'already' ? Number(source) : null
        await api.settlements.settle(goal.id, {
          amount: n,
          from_account_id: fromAccountId,
          settled_at: contribDate,
        })
        invalidate(writes.balances)
      } else if (source === 'unassigned') {
        await api.transactions.assign({
          fund_id: goal.id, amount: n, date: dateInMonth(month),
          notes: 'Goal contribution',
        })
        invalidate(writes.ledger)
      } else {
        await api.transactions.quickAdd({
          fund_id: goal.id, amount: n, date: dateInMonth(month),
          merchant: 'Direct deposit', type: 'income',
        })
        invalidate(writes.ledger)
      }
      onDone()
    } catch (e) { setErr(String(e)) }
    finally { setBusy(false) }
  }

  return (
    <form onSubmit={submit} style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--hairline)', display: 'flex', flexDirection: 'column', gap: 8 }}>
      <input
        autoFocus
        inputMode="decimal"
        placeholder="Amount"
        value={amount}
        onChange={e => setAmount(e.target.value.replace(/-/g, ''))}
      />
      {isContribution ? (
        <>
          <select value={source} onChange={e => {
            const v = e.target.value
            setSource(v)
            // Flip the default date: backfill → Jan 1 of target year; live move → today
            if (v === 'already') {
              const year = goal.target_date
                ? new Date(goal.target_date + 'T00:00:00').getUTCFullYear()
                : new Date().getUTCFullYear()
              setContribDate(`${year}-01-01`)
            } else {
              setContribDate(todayISO())
            }
          }}>
            <option value="already">Already contributed (backfill — no cash movement)</option>
            {(accounts || []).filter(a => a.type === 'checking' || a.type === 'savings').map(a => (
              <option key={a.id} value={a.id}>Move now from {a.name}</option>
            ))}
          </select>
          <input
            type="date"
            value={contribDate}
            onChange={e => setContribDate(e.target.value)}
            title="Date of the contribution (counts toward that year's contribution_ytd)"
          />
          <div className="small muted">
            Records a settlement dated {contribDate} for {fmt(Number(amount) || 0)} → counts toward this year's contribution total.
          </div>
        </>
      ) : (
        <select value={source} onChange={e => setSource(e.target.value)}>
          <option value="unassigned">From Unassigned ({fmt(unassigned)} available)</option>
          <option value="external">Direct deposit (external)</option>
        </select>
      )}
      {err && <div className="bad small">{err}</div>}
      <button className="btn primary sm" disabled={busy}>
        {busy ? 'Saving…' : isDebt ? 'Add payment' : 'Add contribution'}
      </button>
    </form>
  )
}

function NewGoalModal({ accounts, onClose, onCreated }) {
  const invalidate = useInvalidate()
  const [name, setName] = useState('')
  const [goalType, setGoalType] = useState('savings')  // 'savings' | 'contribution'
  const [target, setTarget] = useState('')
  const [targetDate, setTargetDate] = useState('')
  const [minPayment, setMinPayment] = useState('')
  const [startingBalance, setStartingBalance] = useState('')
  const [accountId, setAccountId] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const isContribution = goalType === 'contribution'
  const isDebt = goalType === 'debt'

  async function submit(e) {
    e.preventDefault()
    setErr('')
    if (!name.trim() || !target) { setErr('Name and target required'); return }
    setBusy(true)
    try {
      const fund = await api.funds.create({
        name: name.trim(),
        kind: 'goal',
        goal_type: goalType,
        target: Number(target),
        target_date: targetDate || null,
        min_payment: isDebt && minPayment ? Number(minPayment) : null,
        backed_by_account_id: accountId ? Number(accountId) : null,
      })
      // Starting balance only makes sense for savings goals. Contribution goals
      // derive progress from settlements; debt funds start at 0 paid (the full
      // target is owed) and count down as payments are added.
      const start = Number(startingBalance)
      if (!isContribution && !isDebt && Number.isFinite(start) && start > 0) {
        await api.transactions.quickAdd({
          fund_id: fund.id,
          amount: start,
          date: todayISO(),
          merchant: 'Starting balance',
          type: 'income',
        })
      }
      invalidate(writes.ledger)
      onCreated()
    } catch (e) { setErr(String(e)); setBusy(false) }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="modal" onClick={e => e.stopPropagation()} onSubmit={submit}>
        <h2>New goal</h2>
        <div className="field">
          <label>Goal type</label>
          <div className="type-toggle" style={{ display: 'flex' }}>
            <button type="button" className={goalType === 'savings' ? 'active' : ''} onClick={() => setGoalType('savings')}>
              Savings
            </button>
            <button type="button" className={isContribution ? 'active' : ''} onClick={() => setGoalType('contribution')}>
              Contribution
            </button>
            <button type="button" className={isDebt ? 'active' : ''} onClick={() => setGoalType('debt')}>
              Debt
            </button>
          </div>
          <div className="small muted">
            {isContribution
              ? 'Tracks total contributed in the target year (Roth, HSA, 401k). Progress = sum of settlements within that calendar year.'
              : isDebt
              ? 'Tracks a balance you owe (car loan, student loan). Starts at the amount owed and counts DOWN as you add payments.'
              : 'Tracks a balance you want to hit (emergency fund, down payment, trip). Progress = current balance.'}
          </div>
        </div>
        <div className="field">
          <label>Name</label>
          <input autoFocus placeholder={isContribution ? 'e.g. Roth IRA 2026' : isDebt ? 'e.g. Car loan' : 'e.g. Emergency fund'} value={name} onChange={e => setName(e.target.value)} />
        </div>
        <div className="field">
          <label>{isContribution ? 'Annual contribution target' : isDebt ? 'Amount owed' : 'Target amount'}</label>
          <input inputMode="decimal" placeholder={isContribution ? 'e.g. 7000' : isDebt ? 'e.g. 22000' : ''} value={target} onChange={e => setTarget(e.target.value.replace(/-/g, ''))} />
        </div>
        <div className="field">
          <label>{isContribution ? 'Deadline (e.g. Dec 31 of tax year)' : isDebt ? 'Payoff target date (optional)' : 'Target date (optional)'}</label>
          <input type="date" value={targetDate} onChange={e => setTargetDate(e.target.value)} />
        </div>
        {isDebt && (
          <div className="field">
            <label>Monthly payment (optional)</label>
            <input inputMode="decimal" placeholder="e.g. 531" value={minPayment}
              onChange={e => setMinPayment(e.target.value.replace(/-/g, ''))} />
            <div className="small muted">The lender's fixed payment (incl. interest). If blank, we estimate it from the payoff date.</div>
          </div>
        )}
        {!isContribution && !isDebt && (
          <div className="field">
            <label>Starting balance (optional)</label>
            <input inputMode="decimal" value={startingBalance}
              onChange={e => setStartingBalance(e.target.value.replace(/-/g, ''))} />
          </div>
        )}
        {!isDebt && (
          <div className="field">
            <label>Backed by account (optional)</label>
            <select value={accountId} onChange={e => setAccountId(e.target.value)}>
              <option value="">None</option>
              {accounts.map(a => <option key={a.id} value={a.id}>{a.name} ({a.type})</option>)}
            </select>
          </div>
        )}
        {err && <div className="bad small">{err}</div>}
        <div className="actions">
          <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy}>{busy ? 'Creating…' : 'Create goal'}</button>
        </div>
      </form>
    </div>
  )
}
