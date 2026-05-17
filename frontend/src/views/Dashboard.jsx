import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmt } from '../api'
import InlineAssigned from '../components/InlineAssigned'
import InlineIncome from '../components/InlineIncome'
import MetricCard from '../components/MetricCard'
import MonthSelector, { thisMonth, monthLabel } from '../components/MonthSelector'

function prevMonth(monthStr) {
  const [y, m] = monthStr.split('-').map(Number)
  const d = new Date(Date.UTC(y, m - 2, 1))
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-01`
}

export default function Dashboard() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [showNew, setShowNew] = useState(false)
  const [month, setMonth] = useState(thisMonth())
  const isCurrent = month === thisMonth()
  const isPast = month < thisMonth()  // YYYY-MM-DD strings compare lexicographically

  async function load() {
    try { setData(await api.dashboard(month)) }
    catch (e) { setErr(String(e)) }
  }
  useEffect(() => { load() }, [month])

  if (err) return <div className="card bad">{err}</div>
  if (!data) return <div className="muted">Loading…</div>

  const goals = data.funds.filter(f => f.kind === 'goal')
  const ops = data.funds.filter(f => f.kind === 'operational')

  return (
    <div>
      <StickyUnassigned value={data.unassigned} />
      <MonthSelector value={month} onChange={setMonth} />

      <div className="metric-grid">
        <MetricCard
          label="Income"
          value={<InlineIncome value={data.income_this_month} month={month} onChange={load} />}
          info="Sum of income that landed in Unassigned this month (paychecks, untagged inflows). Click the number to edit — posts an adjusting income transaction to match."
        />
        <MetricCard
          label="Unassigned"
          value={fmt(data.unassigned)}
          tone={Number(data.unassigned) === 0 ? 'muted' : Number(data.unassigned) > 0 ? 'warn' : 'bad'}
          info="Money that's landed in your accounts but hasn't been budgeted to a fund yet. Target: $0 (zero-based budgeting)."
          action={<Link to="/planner"><button className="primary">Plan</button></Link>}
        />
        <MetricCard
          label="Net cash"
          value={fmt(data.net_cash)}
          subtext={
            <>
              {fmt(data.liquid_total)} liquid
              {Number(data.credit_owed) > 0 && ` · ${fmt(data.credit_owed)} owed`}
            </>
          }
          tone={Number(data.net_cash) < 0 ? 'bad' : ''}
          info="What you actually have: checking + savings minus credit card balances owed. Add accounts in Settings."
        />
        <MetricCard
          label="Spent this month"
          value={fmt(data.spent_this_month)}
          info="Net outflows across every fund this month — expenses + transfers minus tagged income (reimbursements offset spending)."
        />
        <MetricCard
          label="Left to spend"
          value={fmt(data.funds_total)}
          tone={Number(data.funds_total) < 0 ? 'bad' : ''}
          info="Sum of all fund balances — money allocated to specific purposes that hasn't been spent yet, including rollover from prior months."
        />
      </div>


      <div className="row" style={{ marginTop: 8, gap: 8 }}>
        <h2 style={{ margin: 0, flex: 1 }}>Funds</h2>
        <CopyPrevMonthButton currentMonth={month} onDone={load} />
        <button
          className="primary"
          onClick={() => setShowNew(true)}
          title="New fund"
          style={{ padding: '4px 12px', fontSize: 18, lineHeight: 1 }}
        >+</button>
      </div>
      {ops.length === 0 && <div className="card muted">No funds yet.</div>}
      {groupByCategory(ops).map(([cat, items]) => {
        const catSpent = items.reduce((s, f) => s + Number(f.net_spent_this_month || 0), 0)
        return (
        <div key={cat} style={{ marginBottom: 16 }}>
          <div className="category-row">
            <h3 className="category-header">{cat}</h3>
            <div className="category-totals small muted">
              spent <span className="num">{fmt(catSpent)}</span>
            </div>
          </div>
          <div className="card">
            {items.map(f => {
          const spent = Number(f.net_spent_this_month || 0)
          const available = Number(f.available_this_month || 0)
          const pct = available > 0 ? (spent / available) * 100 : 0
          const tone = Number(f.balance) < 0 ? 'over' : 'ok'
          return (
            <div key={f.id} className="fund-row" style={{ display: 'block' }}>
              <div className="row">
                <Link to={`/funds/${f.id}`} className="col" style={{ color: 'inherit', flex: 1, minWidth: 0 }}>
                  <div className="name">{f.name}</div>
                  <div className="meta">
                    spent {fmt(spent)} of {fmt(available)} available
                    {f.target ? ` · target ${fmt(f.target)}` : ''}
                  </div>
                </Link>
                <InlineAssigned fund={f} month={month} readOnly={isPast} onChange={load} />
                <div className="col" style={{ alignItems: 'flex-end', minWidth: 90 }}>
                  <div className="muted small">balance</div>
                  <div className={`balance-num ${Number(f.balance) < 0 ? 'bad' : ''}`}>{fmt(f.balance)}</div>
                </div>
                <button
                  className="ghost"
                  title="Delete fund"
                  onClick={async (e) => {
                    e.preventDefault()
                    const lines = [
                      `End "${f.name}" from ${monthLabel(month)} forward?`,
                      'Prior months stay intact. Any transactions dated in this month or later are deleted, and any rollover balance is swept back to Unassigned.',
                    ]
                    if (!confirm(lines.join('\n\n'))) return
                    await api.funds.archive(f.id, month)
                    load()
                  }}
                  style={{ alignSelf: 'center', padding: '4px 8px' }}
                >×</button>
              </div>
              {available > 0 && (
                <div className="spend-bar">
                  <div className={tone} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
                </div>
              )}
            </div>
          )
        })}
          </div>
        </div>
        )
      })}

      {showNew && (
        <NewFundModal
          onClose={() => setShowNew(false)}
          onCreated={() => { setShowNew(false); load() }}
          existingCategories={[...new Set(ops.map(f => f.category).filter(Boolean))]}
        />
      )}

      {goals.length > 0 && (
        <>
          <h2 style={{ marginTop: 16 }}>Goals</h2>
          <div className="card">
            {goals.map(g => {
              const bal = Number(g.balance)
              const target = Number(g.target || 0)
              const pct = target > 0 ? Math.min(100, Math.max(0, (bal / target) * 100)) : 0
              const remaining = Math.max(0, target - bal)
              const minMonthly = minMonthlyNeeded(bal, target, g.target_date, month)
              return (
                <div key={g.id} className="fund-row" style={{ display: 'block' }}>
                  <div className="row">
                    <Link to="/goals" className="col" style={{ flex: 1, color: 'inherit', minWidth: 0 }}>
                      <div className="name">{g.name}</div>
                      <div className="meta">
                        {fmt(remaining)} left
                        {g.target_date ? ` · by ${g.target_date}` : ''}
                        {minMonthly != null && ` · min ${fmt(minMonthly)}/mo`}
                      </div>
                    </Link>
                    <InlineAssigned fund={g} month={month} readOnly={isPast} onChange={load} />
                    <div className="col" style={{ alignItems: 'flex-end', minWidth: 90 }}>
                      <div className="muted small">balance</div>
                      <div className={`balance-num ${bal < 0 ? 'bad' : ''}`}>{fmt(bal)}</div>
                    </div>
                  </div>
                  <div className="progress" style={{ marginTop: 8 }}>
                    <div style={{ width: `${pct}%` }} />
                  </div>
                </div>
              )
            })}
            <Link to="/goals" className="small" style={{ display: 'inline-block', marginTop: 8 }}>
              Manage goals →
            </Link>
          </div>
        </>
      )}

    </div>
  )
}

function StickyUnassigned({ value }) {
  const n = Number(value)
  const tone = n === 0 ? 'ok' : n > 0 ? 'warn' : 'bad'
  return (
    <div className={`sticky-unassigned ${tone}`} title="Unassigned">
      <span className="muted small">U</span>
      <span className="amt">{fmt(n)}</span>
    </div>
  )
}

/**
 * Months between `from` (YYYY-MM-01 string) and a target date (YYYY-MM-DD).
 * Returns null if no target date. Floors at 1 so we don't say "min $0/mo"
 * for a goal due this month with money still owed.
 */
function monthsBetween(fromMonth, targetDate) {
  if (!targetDate) return null
  const [fy, fm] = fromMonth.split('-').map(Number)
  const [ty, tm] = targetDate.split('-').map(Number)
  return Math.max(1, (ty - fy) * 12 + (tm - fm) + 1)
}

function minMonthlyNeeded(balance, target, targetDate, viewMonth) {
  if (!target || !targetDate) return null
  const remaining = Number(target) - Number(balance)
  if (remaining <= 0) return 0
  const months = monthsBetween(viewMonth, targetDate)
  if (months == null) return null
  return remaining / months
}

// Stable ordering: categories appear in the order their first fund appears in `ops`.
const CATEGORY_ORDER = ['Housing', 'Food', 'Transportation', 'Subscriptions', 'Discretionary']

function groupByCategory(funds) {
  const groups = new Map()
  for (const f of funds) {
    const cat = f.category || 'Uncategorized'
    if (!groups.has(cat)) groups.set(cat, [])
    groups.get(cat).push(f)
  }
  return [...groups.entries()].sort(([a], [b]) => {
    const ia = CATEGORY_ORDER.indexOf(a)
    const ib = CATEGORY_ORDER.indexOf(b)
    if (ia !== -1 && ib !== -1) return ia - ib
    if (ia !== -1) return -1
    if (ib !== -1) return 1
    return a.localeCompare(b)
  })
}

function CopyPrevMonthButton({ currentMonth, onDone }) {
  const prev = prevMonth(currentMonth)
  async function go() {
    if (!confirm(`Copy assignments from ${monthLabel(prev)} into ${monthLabel(currentMonth)}? This makes each fund's assigned amount this month match last month.`)) return
    try {
      const r = await api.bulk.copyAssignments(prev, currentMonth)
      onDone()
      const parts = [`Updated ${r.funds_updated} fund(s)`]
      if (r.funds_resurrected) parts.push(`resurrected ${r.funds_resurrected}`)
      if (Number(r.income_delta)) parts.push(`income adjusted by ${r.income_delta}`)
      alert(parts.join(', ') + '.')
    } catch (e) { alert(String(e)) }
  }
  return <button className="ghost small" onClick={go}>↻ Copy from {monthLabel(prev)}</button>
}

function NewFundModal({ onClose, onCreated, existingCategories }) {
  const [name, setName] = useState('')
  const [target, setTarget] = useState('')
  const [category, setCategory] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function submit(e) {
    e.preventDefault()
    setErr('')
    if (!name.trim()) { setErr('Name required'); return }
    setBusy(true)
    try {
      await api.funds.create({
        name: name.trim(),
        kind: 'operational',
        target: target ? Number(target) : null,
        category: category.trim() || null,
      })
      onCreated()
    } catch (e) { setErr(String(e)); setBusy(false) }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="modal stack" onClick={e => e.stopPropagation()} onSubmit={submit}>
        <h2 style={{ margin: 0 }}>New fund</h2>
        <input autoFocus placeholder="Name (e.g. Groceries)" value={name} onChange={e => setName(e.target.value)} />
        <input placeholder="Target (optional)" inputMode="decimal" value={target} onChange={e => setTarget(e.target.value)} />
        <input
          list="category-list"
          placeholder="Category (e.g. Housing)"
          value={category}
          onChange={e => setCategory(e.target.value)}
        />
        <datalist id="category-list">
          {existingCategories.map(c => <option key={c} value={c} />)}
        </datalist>
        {err && <div className="bad small">{err}</div>}
        <div className="row">
          <button type="button" className="ghost" onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy}>{busy ? 'Adding…' : 'Add fund'}</button>
        </div>
      </form>
    </div>
  )
}
