import { useState } from 'react'
import { Link, useOutletContext, useNavigate } from 'react-router-dom'
import { api, fmt } from '../api'
import { keys, useInvalidate, useResource, writes } from '../resource'
import ErrorCard from '../components/ErrorCard'
import GoalSummary, { goalProgress } from '../components/GoalSummary'
import InlineAssigned from '../components/InlineAssigned'
import { thisMonth, shiftMonth } from '../components/MonthSelector'
import { monthLabel, monthShort } from '../format'
import { isGoal, isOperational } from '../funds'
import { Icon } from '../components/Icons'
import ToMovePanel from '../components/ToMovePanel'

export default function Dashboard() {
  const { month } = useOutletContext()
  const dashboardRes = useResource(keys.dashboard(month))
  const inboxRes = useResource(keys.inbox())
  const accountsRes = useResource(keys.accounts())
  const [showNew, setShowNew] = useState(false)
  const nav = useNavigate()

  const data = dashboardRes.data
  // The badges are nice-to-have: a failed inbox or accounts read leaves the
  // rest of the dashboard standing, as it did before.
  const inbox = inboxRes.data || []
  const accounts = accountsRes.data || []

  const isPast = month < thisMonth()

  if (dashboardRes.error) return <ErrorCard error={dashboardRes.error} />
  if (!data) return <div className="muted">Loading…</div>

  const ops = data.funds.filter(isOperational)
  const goals = data.funds.filter(isGoal)

  const u = data.unassigned
  const uTone = Math.abs(u) < 0.01 ? 'good' : u > 0 ? 'warn' : 'bad'
  const uMessage = uTone === 'good'
    ? 'Every dollar has a job'
    : u > 0 ? 'Money to assign' : 'Overbudget — pull from a fund'

  const grouped = groupByCategory(ops)

  const goalsTargetTotal = goals.reduce((s, g) => s + (g.target ?? 0), 0)
  const goalsBalanceTotal = goals.reduce((s, g) => s + Math.min(g.balance, g.target ?? 0), 0)
  const goalsPct = goalsTargetTotal > 0 ? Math.round((goalsBalanceTotal / goalsTargetTotal) * 100) : 0

  return (
    <div>
      {/* ─── HERO ─── */}
      <div className="hero">
        <div className="hero-unassigned">
          <div className="label-row">
            <span className="pulse" />
            <span className="eyebrow">Unassigned · {monthLabel(month)}</span>
          </div>
          <div className={`big-num ${uTone}`}>{fmt(u)}</div>
          <div className="sub">{uMessage}. Zero-based means every dollar should land in a fund before the month is out.</div>
          <div className="pill-row">
            <Link to="/planner" className="btn primary sm">Open planner →</Link>
            <Link to="/quick-add" className="btn sm">+ Record income</Link>
            <CopyPrevMonthButton currentMonth={month} />
          </div>
        </div>

        <div className="hero-side">
          <div className="hero-tile">
            <div>
              <div className="eyebrow">Net cash · spendable after cards</div>
              <div className={`num-big ${data.net_cash < 0 ? 'bad' : 'good'}`}>{fmt(data.net_cash)}</div>
            </div>
            <div className="sub">
              {fmt(data.liquid_total)} liquid
              {data.credit_owed > 0 && ` − ${fmt(data.credit_owed)} owed on cards`}
            </div>
          </div>
          <div className="hero-tile">
            <div className="split-tile">
              <div>
                <div className="eyebrow">Spent</div>
                <div className="num-big">{fmt(data.spent_this_month)}</div>
                <div className="sub">of {fmt(data.income_this_month)} income</div>
              </div>
              <div className="divider" />
              <div>
                <div className="eyebrow">Saved</div>
                <div className="num-big" style={{ color: 'var(--accent)' }}>{fmt(data.saved_this_month)}</div>
                <div className="sub">into goals this month</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <ToMovePanel month={month} accounts={accounts} />

      {/* ─── SECONDARY METRICS ─── */}
      <div className="metric-row" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
        <div className="cell">
          <div className="lbl">Income · plan vs actual</div>
          <PlannedIncomeCell
            month={month}
            planned={data.planned_income}
            actual={data.income_this_month}
            readOnly={isPast}
          />
        </div>
        <div className="cell">
          <div className="lbl">Pending review</div>
          <div className="val">
            {inbox.length}
            <span style={{ fontSize: 12, color: 'var(--text-dim)', fontWeight: 400, marginLeft: 6 }}>
              transaction{inbox.length === 1 ? '' : 's'}
            </span>
          </div>
        </div>
        <div className="cell">
          <div className="lbl">Goals progress</div>
          <div className="val">{goalsTargetTotal > 0 ? `${goalsPct}%` : '—'}</div>
        </div>
      </div>

      {/* ─── FUNDS BY CATEGORY ─── */}
      <div className="sec-head">
        <h2>Funds</h2>
        <span className="sub">grouped by category · click to drill in</span>
        <div className="spacer" />
        {isPast && <span style={{ fontSize: 12, color: 'var(--warn)' }}>read-only archive</span>}
        <button className="btn sm" onClick={() => setShowNew(true)}>
          <Icon name="plus" /> Add fund
        </button>
      </div>

      {grouped.length === 0 && <div className="card muted">No funds yet.</div>}

      {grouped.map(([cat, items]) => {
        const catSpent = items.reduce((s, f) => s + f.net_spent_this_month, 0)
        const catAssigned = items.reduce((s, f) => s + f.assigned_this_month, 0)
        return (
          <div key={cat} className="cat-group">
            <div className="cat-head">
              <span className="name">{cat}</span>
              <span className="totals">
                <b>{fmt(catSpent)}</b> of <b>{fmt(catAssigned)}</b>
              </span>
            </div>
            <div className="fund-list">
              {items.map(f => (
                <FundRow key={f.id} fund={f} month={month} readOnly={isPast}
                  onClick={() => nav(`/funds/${f.id}`)} />
              ))}
            </div>
          </div>
        )
      })}

      {/* ─── SPENDING TRENDS ─── */}
      <SpendingTrends />

      {/* ─── GOALS ─── */}
      {goals.length > 0 && (
        <>
          <div className="sec-head">
            <h2>Goals</h2>
            <span className="sub">
              {goals.length} active · {fmt(goals.reduce((s, g) => s + g.balance, 0))} saved
            </span>
            <div className="spacer" />
            <Link to="/goals" className="btn sm">Manage all →</Link>
          </div>
          <div className="goal-grid">
            {goals.map(g => (
              <GoalMiniCard key={g.id} goal={g} month={month} readOnly={isPast} />
            ))}
          </div>
        </>
      )}

      {showNew && (
        <NewFundModal
          onClose={() => setShowNew(false)}
          onCreated={() => setShowNew(false)}
          existingCategories={[...new Set(ops.map(f => f.category).filter(Boolean))]}
        />
      )}
    </div>
  )
}

const TREND_COLORS = ['#6c8cff', '#39c0a0', '#f0a35e', '#e06c9f', '#9b8cff', '#c0c84a', '#888']

function SpendingTrends() {
  // Decorative: if the read fails there is simply no trend section.
  const { data } = useResource(keys.dashboardTrends(6))
  if (!data || !data.months.length) return null

  const categories = data.categories
  const colorOf = (c) => TREND_COLORS[categories.indexOf(c) % TREND_COLORS.length]
  // Only positive net spend stacks; max month total sets the scale.
  const monthTotal = (m) => categories.reduce((s, c) => s + Math.max(0, m.categories[c] ?? 0), 0)
  const max = Math.max(...data.months.map(monthTotal), 1)

  return (
    <>
      <div className="sec-head">
        <h2>Spending trends</h2>
        <span className="sub">net spend by category · last {data.months.length} months</span>
      </div>
      <div className="card">
        <div className="trend-bars">
          {data.months.map(m => {
            const total = monthTotal(m)
            return (
              <div key={m.month} className="trend-col">
                <div className="trend-stack" title={`${fmt(total)} total`}>
                  {categories.map(c => {
                    const v = Math.max(0, m.categories[c] ?? 0)
                    if (v === 0) return null
                    return (
                      <div key={c} className="trend-seg"
                        style={{ height: `${(v / max) * 100}%`, background: colorOf(c) }}
                        title={`${c}: ${fmt(v)}`} />
                    )
                  })}
                </div>
                <div className="trend-total">{total > 0 ? fmt(total) : '—'}</div>
                <div className="trend-label">{monthShort(m.month)}</div>
              </div>
            )
          })}
        </div>
        <div className="trend-legend">
          {categories.map(c => (
            <span key={c} className="trend-key">
              <span className="trend-dot" style={{ background: colorOf(c) }} />{c}
            </span>
          ))}
        </div>
      </div>
    </>
  )
}

function FundRow({ fund, month, readOnly, onClick }) {
  const invalidate = useInvalidate()
  const spent = fund.net_spent_this_month
  const available = fund.available_this_month
  const balance = fund.balance
  const pct = available > 0 ? Math.min(100, (spent / available) * 100) : (spent > 0 ? 100 : 0)
  const tone = balance < 0 ? 'over' : pct > 90 ? 'warn' : 'ok'

  return (
    <div className="fund-row" onClick={onClick}>
      <div>
        <div className="name">{fund.name}</div>
        {fund.target && <div className="meta">target {fmt(fund.target)}</div>}
      </div>

      <div className="right" onClick={(e) => e.stopPropagation()}>
        <div className="col-lbl">assigned</div>
        <InlineAssigned fund={fund} month={month} readOnly={readOnly} />
      </div>

      <div className="right col-balance-meta">
        <div className="col-lbl">spent</div>
        <div className="assigned" style={{ color: 'var(--text-dim)' }}>{fmt(spent)}</div>
      </div>

      <div className="right">
        <div className="col-lbl">balance</div>
        <div className={`balance ${balance < 0 ? 'bad' : (available > 0 && balance < available * 0.1 ? 'warn' : '')}`}>
          {fmt(balance)}
        </div>
      </div>

      <button
        className="row-del"
        title="Delete fund this month forward"
        onClick={async (e) => {
          e.stopPropagation()
          const lines = [
            `End "${fund.name}" from ${monthLabel(month)} forward?`,
            'Prior months stay intact. Any transactions dated in this month or later are deleted, and any rollover balance is swept back to Unassigned.',
          ]
          if (!confirm(lines.join('\n\n'))) return
          await api.funds.archive(fund.id, month)
          invalidate(writes.ledger)
        }}
      >
        <Icon name="x" size={14} />
      </button>

      <div className="progress-track">
        <div className={`progress-fill ${tone === 'over' ? 'over' : tone === 'warn' ? 'warn' : ''}`}
          style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
    </div>
  )
}

function GoalMiniCard({ goal, month, readOnly }) {
  const progress = goalProgress(goal, month)
  const { isDebt, remaining, fixedPayment, minMonthly } = progress
  const assigned = goal.assigned_this_month

  return (
    <div className="goal-card">
      <GoalSummary goal={goal} progress={progress} linkTo="/goals" />
      <div className="goal-assign-row" onClick={(e) => e.stopPropagation()}>
        <div className="col">
          <span className="col-lbl">Assigned this month</span>
          {minMonthly != null && remaining > 0 && (
            <span className="goal-min small muted">
              min <span className="num">{fmt(minMonthly)}</span>/mo{fixedPayment != null ? '' : isDebt ? ' to pay off on time' : ' to hit target'}
            </span>
          )}
        </div>
        <div className={`assign-wrap ${assigned > 0 ? 'filled' : 'empty'} ${minMonthly != null && assigned < minMonthly ? 'short' : ''}`}>
          <InlineAssigned fund={goal} month={month} readOnly={readOnly} />
        </div>
      </div>
    </div>
  )
}

function PlannedIncomeCell({ month, planned, actual, readOnly }) {
  const invalidate = useInvalidate()
  const [editing, setEditing] = useState(false)
  const [val, setVal] = useState('')
  const p = planned ?? 0
  const a = actual ?? 0
  const pct = p > 0 ? Math.min(100, (a / p) * 100) : 0
  const delta = a - p
  const onTrack = Math.abs(delta) < 1
  const ahead = delta > 0

  async function commit() {
    setEditing(false)
    const n = Number(val)
    if (!Number.isFinite(n) || n < 0) return
    if (Math.abs(n - p) < 0.005) return
    await api.monthlyMeta.set(month, n)
    invalidate(writes.plannedIncome)
  }

  if (editing) {
    return (
      <input
        autoFocus
        inputMode="decimal"
        defaultValue={p.toFixed(2)}
        onChange={(e) => setVal(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(false) }}
        className="val"
        style={{ width: '100%', height: 'auto', background: 'transparent', border: 'none', padding: 0, color: 'var(--accent)' }}
      />
    )
  }

  return (
    <>
      <button
        className="val"
        onClick={() => !readOnly && (setVal(p.toFixed(2)), setEditing(true))}
        title={readOnly ? 'Past month — read only' : 'Click to edit planned income'}
        style={{ background: 'transparent', border: 'none', padding: 0, textAlign: 'left', cursor: readOnly ? 'default' : 'pointer' }}
      >
        {fmt(a)} <span style={{ color: 'var(--text-dim)', fontSize: 13, fontWeight: 400 }}> of {fmt(p)}</span>
      </button>
      <div className="inc-progress">
        <div className={`fill ${onTrack ? 'ok' : ahead ? 'ahead' : ''}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="small muted" style={{ marginTop: 4 }}>
        {p === 0 ? 'Set a target — click the amount above' :
          onTrack ? 'on plan' :
          ahead ? `+${fmt(delta)} ahead of plan` : `${fmt(Math.abs(delta))} short of plan`}
      </div>
    </>
  )
}

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

function CopyPrevMonthButton({ currentMonth }) {
  const invalidate = useInvalidate()
  const prev = shiftMonth(currentMonth, -1)
  async function go() {
    if (!confirm(`Copy assignments from ${monthLabel(prev)} into ${monthLabel(currentMonth)}? This makes each fund's assigned amount this month match last month.`)) return
    try {
      const r = await api.bulk.copyAssignments(prev, currentMonth)
      invalidate(writes.ledger)
      const parts = [`Updated ${r.funds_updated} fund(s)`]
      if (r.funds_resurrected) parts.push(`resurrected ${r.funds_resurrected}`)
      if (Number(r.income_delta)) parts.push(`income adjusted by ${r.income_delta}`)
      alert(parts.join(', ') + '.')
    } catch (e) { alert(String(e)) }
  }
  return <button className="btn ghost sm" onClick={go}>↻ Copy from {monthLabel(prev)}</button>
}

function NewFundModal({ onClose, onCreated, existingCategories }) {
  const invalidate = useInvalidate()
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
      invalidate(writes.ledger)
      onCreated()
    } catch (e) { setErr(String(e)); setBusy(false) }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="modal" onClick={e => e.stopPropagation()} onSubmit={submit}>
        <h2>New fund</h2>
        <div className="field">
          <label>Name</label>
          <input autoFocus placeholder="e.g. Groceries" value={name} onChange={e => setName(e.target.value)} />
        </div>
        <div className="field">
          <label>Target (optional)</label>
          <input inputMode="decimal" value={target} onChange={e => setTarget(e.target.value)} />
        </div>
        <div className="field">
          <label>Category</label>
          <input
            list="category-list"
            placeholder="e.g. Housing"
            value={category}
            onChange={e => setCategory(e.target.value)}
          />
          <datalist id="category-list">
            {existingCategories.map(c => <option key={c} value={c} />)}
          </datalist>
        </div>
        {err && <div className="bad small">{err}</div>}
        <div className="actions">
          <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy}>{busy ? 'Adding…' : 'Add fund'}</button>
        </div>
      </form>
    </div>
  )
}
