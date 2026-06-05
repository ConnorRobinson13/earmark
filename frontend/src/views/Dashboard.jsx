import { useEffect, useState } from 'react'
import { Link, useOutletContext, useNavigate } from 'react-router-dom'
import { api, fmt } from '../api'
import InlineAssigned from '../components/InlineAssigned'
import { thisMonth, monthLabel, shiftMonth } from '../components/MonthSelector'
import { Icon } from '../components/Icons'
import ToMovePanel from '../components/ToMovePanel'

export default function Dashboard() {
  const ctx = useOutletContext()
  const { month, setUnassigned, setInboxCount, refreshTick, refresh } = ctx
  const [data, setData] = useState(null)
  const [inbox, setInbox] = useState([])
  const [accounts, setAccounts] = useState([])
  const [err, setErr] = useState('')
  const [showNew, setShowNew] = useState(false)
  const nav = useNavigate()

  const isCurrent = month === thisMonth()
  const isPast = month < thisMonth()

  async function load() {
    try {
      const [d, ib, ac] = await Promise.all([
        api.dashboard(month),
        api.inbox.list().catch(() => []),
        api.accounts.list().catch(() => []),
      ])
      setData(d)
      setInbox(ib || [])
      setAccounts(ac || [])
      setUnassigned(Number(d.unassigned))
      setInboxCount((ib || []).length)
    } catch (e) {
      setErr(String(e))
    }
  }
  useEffect(() => { load() }, [month, refreshTick])

  if (err) return <div className="card"><span className="bad">{err}</span></div>
  if (!data) return <div className="muted">Loading…</div>

  const ops = data.funds.filter(f => f.kind === 'operational')
  const goals = data.funds.filter(f => f.kind === 'goal')

  const u = Number(data.unassigned)
  const uTone = Math.abs(u) < 0.01 ? 'good' : u > 0 ? 'warn' : 'bad'
  const uMessage = uTone === 'good'
    ? 'Every dollar has a job'
    : u > 0 ? 'Money to assign' : 'Overbudget — pull from a fund'

  const grouped = groupByCategory(ops)

  const goalsTargetTotal = goals.reduce((s, g) => s + Number(g.target || 0), 0)
  const goalsBalanceTotal = goals.reduce((s, g) => s + Math.min(Number(g.balance), Number(g.target || 0)), 0)
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
            <CopyPrevMonthButton currentMonth={month} onDone={refresh} />
          </div>
        </div>

        <div className="hero-side">
          <div className="hero-tile">
            <div>
              <div className="eyebrow">Net cash · spendable after cards</div>
              <div className={`num-big ${Number(data.net_cash) < 0 ? 'bad' : 'good'}`}>{fmt(data.net_cash)}</div>
            </div>
            <div className="sub">
              {fmt(data.liquid_total)} liquid
              {Number(data.credit_owed) > 0 && ` − ${fmt(data.credit_owed)} owed on cards`}
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

      <ToMovePanel month={month} accounts={accounts} onMoved={refresh} />

      {/* ─── SECONDARY METRICS ─── */}
      <div className="metric-row" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
        <div className="cell">
          <div className="lbl">Income · plan vs actual</div>
          <PlannedIncomeCell
            month={month}
            planned={data.planned_income}
            actual={data.income_this_month}
            readOnly={isPast}
            onChange={refresh}
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
        const catSpent = items.reduce((s, f) => s + Number(f.net_spent_this_month || 0), 0)
        const catAssigned = items.reduce((s, f) => s + Number(f.assigned_this_month || 0), 0)
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
                <FundRow key={f.id} fund={f} month={month} readOnly={isPast} onChange={refresh}
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
              {goals.length} active · {fmt(goals.reduce((s, g) => s + Number(g.balance), 0))} saved
            </span>
            <div className="spacer" />
            <Link to="/goals" className="btn sm">Manage all →</Link>
          </div>
          <div className="goal-grid">
            {goals.map(g => (
              <GoalMiniCard key={g.id} goal={g} month={month} readOnly={isPast} onChange={refresh} />
            ))}
          </div>
        </>
      )}

      {showNew && (
        <NewFundModal
          onClose={() => setShowNew(false)}
          onCreated={() => { setShowNew(false); refresh() }}
          existingCategories={[...new Set(ops.map(f => f.category).filter(Boolean))]}
        />
      )}
    </div>
  )
}

const TREND_COLORS = ['#6c8cff', '#39c0a0', '#f0a35e', '#e06c9f', '#9b8cff', '#c0c84a', '#888']

function SpendingTrends() {
  const [data, setData] = useState(null)
  useEffect(() => { api.dashboardTrends(6).then(setData).catch(() => {}) }, [])
  if (!data || !data.months.length) return null

  const categories = data.categories
  const colorOf = (c) => TREND_COLORS[categories.indexOf(c) % TREND_COLORS.length]
  // Only positive net spend stacks; max month total sets the scale.
  const monthTotal = (m) => categories.reduce((s, c) => s + Math.max(0, Number(m.categories[c] || 0)), 0)
  const max = Math.max(...data.months.map(monthTotal), 1)
  const fmtMonth = (iso) => {
    const [y, mo] = iso.split('-').map(Number)
    return new Date(y, mo - 1, 1).toLocaleDateString('en-US', { month: 'short' })
  }

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
                    const v = Math.max(0, Number(m.categories[c] || 0))
                    if (v === 0) return null
                    return (
                      <div key={c} className="trend-seg"
                        style={{ height: `${(v / max) * 100}%`, background: colorOf(c) }}
                        title={`${c}: ${fmt(v)}`} />
                    )
                  })}
                </div>
                <div className="trend-total">{total > 0 ? fmt(total) : '—'}</div>
                <div className="trend-label">{fmtMonth(m.month)}</div>
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

function FundRow({ fund, month, readOnly, onClick, onChange }) {
  const spent = Number(fund.net_spent_this_month || 0)
  const available = Number(fund.available_this_month || 0)
  const balance = Number(fund.balance)
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
        <InlineAssigned fund={fund} month={month} readOnly={readOnly} onChange={onChange} />
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
          onChange?.()
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

function GoalMiniCard({ goal, month, readOnly, onChange }) {
  const isContribution = goal.goal_type === 'contribution'
  const isDebt = goal.goal_type === 'debt'
  const target = Number(goal.target || 0)
  const progressValue = isContribution
    ? Number(goal.contribution_ytd || 0)
    : Number(goal.balance)
  const pct = target > 0 ? Math.min(100, Math.max(0, (progressValue / target) * 100)) : 0
  const remaining = Math.max(0, target - progressValue)
  const assigned = Number(goal.assigned_this_month || 0)
  const actualMin = isDebt && goal.min_payment != null ? Number(goal.min_payment) : null
  const minMonthly = actualMin != null ? actualMin : minMonthlyNeeded(progressValue, target, goal.target_date, month)

  return (
    <div className="goal-card">
      <Link to="/goals" style={{ color: 'inherit', display: 'block' }}>
        <div className="row" style={{ gap: 6, alignItems: 'center' }}>
          <div className="name">{goal.name}</div>
          <span className={`goal-badge ${isContribution ? 'contribution' : isDebt ? 'debt' : 'savings'}`}>
            {isContribution ? 'contribution' : isDebt ? 'debt' : 'savings'}
          </span>
        </div>
        <div className="deadline">
          {goal.target_date
            ? `${isDebt ? 'payoff by' : 'by'} ${new Date(goal.target_date + 'T00:00:00').toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`
            : 'no deadline'}
        </div>
      </Link>
      <div className="amount-row">
        <div className="big">{fmt(isDebt ? remaining : progressValue)}</div>
        <div className="target">
          {isContribution ? `of ${fmt(target)} ${goal.contribution_year ?? ''}` : isDebt ? `of ${fmt(target)} owed` : `of ${fmt(target)}`}
        </div>
      </div>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="footer-row">
        <span>{pct.toFixed(0)}% {isContribution ? 'contributed' : isDebt ? 'paid off' : 'complete'}</span>
        <span>{isDebt ? (remaining > 0 ? `${fmt(remaining)} left` : 'paid off 🎉') : `${fmt(remaining)} to go`}</span>
      </div>
      <div className="goal-assign-row" onClick={(e) => e.stopPropagation()}>
        <div className="col">
          <span className="col-lbl">Assigned this month</span>
          {minMonthly != null && remaining > 0 && (
            <span className="goal-min small muted">
              min <span className="num">{fmt(minMonthly)}</span>/mo{actualMin != null ? '' : isDebt ? ' to pay off on time' : ' to hit target'}
            </span>
          )}
        </div>
        <div className={`assign-wrap ${assigned > 0 ? 'filled' : 'empty'} ${minMonthly != null && assigned < minMonthly ? 'short' : ''}`}>
          <InlineAssigned fund={goal} month={month} readOnly={readOnly} onChange={onChange} />
        </div>
      </div>
    </div>
  )
}

/** Months from `fromMonth` (YYYY-MM-01) through `targetDate` (YYYY-MM-DD), floor 1. */
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

function PlannedIncomeCell({ month, planned, actual, readOnly, onChange }) {
  const [editing, setEditing] = useState(false)
  const [val, setVal] = useState('')
  const p = Number(planned || 0)
  const a = Number(actual || 0)
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
    onChange?.()
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

function CopyPrevMonthButton({ currentMonth, onDone }) {
  const prev = shiftMonth(currentMonth, -1)
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
  return <button className="btn ghost sm" onClick={go}>↻ Copy from {monthLabel(prev)}</button>
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
