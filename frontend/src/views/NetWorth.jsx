import { useEffect, useMemo, useRef, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { api, fmt } from '../api'
import { keys, useInvalidate, useResource, writes } from '../resource'
import ErrorCard from '../components/ErrorCard'
import { monthShortYear } from '../format'
import { isOperational } from '../funds'

const STORAGE_KEY = 'budget-app:networth-projection'

const DEFAULT_PROJECTION = {
  currentAge: 28,
  retireAge: 65,
  annualReturnPct: 8,     // S&P historical ~10% nominal, 7% real — pick a middle
  monthlyContribution: 583, // Roth max / 12 as a sensible default — this is year 1
  contributionGrowthPct: 3, // raises flow into higher savings each year
  inflationPct: 2.5,        // long-run CPI-ish, used for today's-dollars view
  showRealDollars: true,    // headline in today's dollars vs raw nominal
}

function loadProjection() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return { ...DEFAULT_PROJECTION, ...JSON.parse(raw) }
  } catch {}
  return DEFAULT_PROJECTION
}

function saveProjection(p) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(p)) } catch {}
}

// Long enough that a slider dragged at any human speed asks once, short enough
// that letting go and reading the answer feels like one motion.
const SETTLE_MS = 250

/**
 * `value`, but only once it has held still for `SETTLE_MS`.
 *
 * The projection is a server read keyed on every dial it was drawn under, so
 * without this a slider dragged across seventeen positions would ask seventeen
 * questions on its way to the one being asked. The first value is taken as-is:
 * the page has to ask for something on mount.
 */
function useSettled(value) {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), SETTLE_MS)
    return () => clearTimeout(timer)
  }, [value])
  return settled
}

/**
 * Record this month's net worth on open; report when that attempt has finished.
 *
 * Reading `/networth` used to upsert a snapshot on the way past, so every page
 * load wrote to the database. The write lives behind its own POST now — and
 * nothing was calling it, so the trend simply stopped gaining points. Opening
 * this page still captures the month; it is just asked for out loud.
 *
 * The view rather than the daily scheduler, because the two are not equivalent
 * here: a snapshot is only worth having if someone looks at the chart, and this
 * is the only page that draws it. Putting it on the scheduler would mean the
 * backend writing a row a day whether or not anyone ever reads one, and would
 * leave a first visit to a fresh database with nothing to show until tomorrow.
 *
 * The history is read only once this has settled, which is what puts this
 * month's point on the line the first time it is drawn. A failed capture gets
 * no message: whatever history already exists is still worth showing.
 */
function useCapturedSnapshot() {
  const invalidate = useInvalidate()
  const [captured, setCaptured] = useState(false)
  useEffect(() => {
    let alive = true
    // Capturing twice in one month replaces that month's row rather than adding
    // a second, so a remount — or StrictMode running this effect twice in dev —
    // cannot put two points on the chart for the same month.
    api.networthSnapshot()
      .then(() => invalidate(writes.snapshot))
      .catch(() => {})
      .finally(() => { if (alive) setCaptured(true) })
    return () => { alive = false }
  }, [invalidate])
  return captured
}

export default function NetWorth() {
  const { month } = useOutletContext()
  const netWorthRes = useResource(keys.networth())
  const dashRes = useResource(keys.dashboard(month))
  const [proj, setProj] = useState(loadProjection)
  const captured = useCapturedSnapshot()

  // The dials the projection is *asked* under, which lag the dials on screen by
  // a beat: each one is part of the key, so without this a slider dragged from
  // 28 to 45 would ask the backend seventeen questions on the way.
  const asked = useSettled(proj)
  const projRes = useResource(keys.retirementProjection(asked))
  // A new key drops the previous answer, so hold the last projection on screen
  // while the next lands rather than blanking the panel every time a dial moves.
  // A failed read is not covered by that: an error takes precedence below, so a
  // projection that could not be fetched never shows as the current one.
  const lastProjection = useRef(null)
  if (projRes.data) lastProjection.current = projRes.data
  const projection = projRes.data || lastProjection.current

  const data = netWorthRes.data
  // The runway is a nice-to-have on top of the position: a failed dashboard
  // read costs that panel, not the page.
  const dash = dashRes.data

  // Monthly NEEDS = bare-bones survival budget for the runway: housing + any
  // scheduled bill (non-default due day, e.g. insurance) + a groceries
  // allowance. Subscriptions, discretionary (eating out, buffer, gifts) and
  // one-offs are all excluded — in a real emergency you'd cut every one.
  const monthlyNeeds = useMemo(() => {
    if (!dash) return 0
    return dash.funds
      .filter(f => {
        // The car loan is a debt you can't walk away from in an emergency, so
        // count it even though it's modeled as a goal, not an operational fund.
        const carPayment = /car loan|car payment/i.test(f.name)
        if (!isOperational(f) && !carPayment) return false
        const scheduledBill = (f.category === 'Housing' || f.due_day !== 1) && f.category !== 'Subscriptions'
        const groceries = /grocer/i.test(f.name)
        return scheduledBill || groceries || carPayment
      })
      .reduce((s, f) => s + (f.assigned_this_month || 0), 0)
  }, [dash])

  function patch(k, v) {
    setProj(p => {
      const next = { ...p, [k]: v }
      saveProjection(next)
      return next
    })
  }

  if (netWorthRes.error) return <ErrorCard error={netWorthRes.error} />
  if (!data) return <div className="muted">Loading…</div>

  const total = data.total
  const liquid = data.liquid
  const investment = data.investment
  const emergency = data.emergency_fund || 0
  const debt = data.credit_debt
  const loan = data.loan_debt || 0

  return (
    <div>
      <div className="sec-head" style={{ marginTop: 0 }}>
        <h2>Net worth</h2>
        <span className="sub">current position + retirement projection</span>
      </div>

      {/* Hero */}
      <div className="hero" style={{ gridTemplateColumns: '1.4fr 1fr' }}>
        <div className="hero-unassigned">
          <div className="label-row">
            <span className="eyebrow">Total net worth · today</span>
          </div>
          <div className={`big-num ${total < 0 ? 'bad' : 'good'}`}>{fmt(total)}</div>
          <div className="sub">
            {fmt(liquid + investment + emergency)} in assets
            {debt > 0 && ` · ${fmt(debt)} in card debt`}
            {loan > 0 && ` · ${fmt(loan)} in loans`}
          </div>
        </div>

        <div className="hero-side">
          <div className="hero-tile">
            <div className="split-tile">
              <div>
                <div className="eyebrow">Liquid</div>
                <div className="num-big">{fmt(liquid)}</div>
                <div className="sub">spendable</div>
              </div>
              <div className="divider" />
              <div>
                <div className="eyebrow">Emergency</div>
                <div className="num-big">{fmt(emergency)}</div>
                <div className="sub">earmarked</div>
              </div>
            </div>
          </div>
          <div className="hero-tile">
            <div>
              <div className="eyebrow">Investments</div>
              <div className="num-big">{fmt(investment)}</div>
            </div>
            <div className="sub">retirement / brokerage</div>
          </div>
        </div>
      </div>

      {/* Net worth over time */}
      <div className="sec-head">
        <h2>Over time</h2>
        <span className="sub">monthly snapshots</span>
      </div>
      <div className="card">
        {captured ? <NetWorthOverTime /> : <div className="muted small">Loading…</div>}
      </div>

      {/* Emergency-fund runway */}
      {monthlyNeeds > 0 && emergency > 0 && (
        <div className="card runway-card">
          <div>
            <div className="eyebrow">Emergency runway</div>
            <div className="sub">{fmt(emergency)} ÷ {fmt(monthlyNeeds)}/mo needs (fixed bills + groceries + car payment)</div>
          </div>
          <div className="runway-num">
            <span className={`big ${emergency / monthlyNeeds < 3 ? 'warn' : 'good'}`}>
              {(emergency / monthlyNeeds).toFixed(1)}
            </span>
            <span className="muted"> months covered</span>
          </div>
        </div>
      )}

      {/* Account breakdown */}
      <div className="sec-head">
        <h2>By account</h2>
      </div>
      <div className="card" style={{ padding: 0 }}>
        {data.accounts.map(a => (
          <div key={a.id} className="row" style={{ padding: '12px 16px', borderBottom: '1px solid var(--hairline)' }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 500 }}>{a.name}</div>
              <div className="small muted">{a.type}</div>
            </div>
            <div className={`num ${a.type === 'credit' ? 'warn' : ''}`} style={{ fontSize: 16, fontWeight: 500 }}>
              {a.type === 'credit' ? '−' : ''}{fmt(a.balance)}
            </div>
          </div>
        ))}
        {data.accounts.length === 0 && (
          <div style={{ padding: 16 }} className="muted">No accounts yet.</div>
        )}
      </div>

      {/* Projection */}
      <div className="sec-head">
        <h2>Retirement projection</h2>
        <span className="sub">simple compounding — invest current investment balance + monthly contribution at chosen return</span>
      </div>

      <div className="plan-grid">
        <div>
          <div className="card stack" style={{ gap: 14 }}>
            <ProjInput
              label="Current age"
              value={proj.currentAge}
              min={18} max={80} step={1} suffix="years"
              onChange={(v) => patch('currentAge', v)}
            />
            <ProjInput
              label="Retirement age"
              value={proj.retireAge}
              min={Math.max(proj.currentAge + 1, 30)} max={90} step={1} suffix="years"
              onChange={(v) => patch('retireAge', v)}
            />
            <ProjInput
              label="Annual return"
              value={proj.annualReturnPct}
              min={0} max={15} step={0.5} suffix="%"
              onChange={(v) => patch('annualReturnPct', v)}
            />
            <ProjInput
              label="Monthly contribution"
              value={proj.monthlyContribution}
              min={0} max={5000} step={50} suffix="/mo · yr 1"
              onChange={(v) => patch('monthlyContribution', v)}
              formatValue={fmt}
            />
            <ProjInput
              label="Grow contribution"
              value={proj.contributionGrowthPct}
              min={0} max={10} step={0.5} suffix="%/yr"
              onChange={(v) => patch('contributionGrowthPct', v)}
            />
            <ProjToggle
              label="Show in today's dollars"
              checked={proj.showRealDollars}
              onChange={(v) => patch('showRealDollars', v)}
            />
            {proj.showRealDollars && (
              <ProjInput
                label="Inflation"
                value={proj.inflationPct}
                min={0} max={6} step={0.5} suffix="%/yr"
                onChange={(v) => patch('inflationPct', v)}
              />
            )}
          </div>
        </div>

        {projRes.error ? (
          <ErrorCard error={projRes.error} />
        ) : projection ? (
          <ProjectionPanel projection={projection} showReal={proj.showRealDollars} />
        ) : (
          <div className="plan-sticky muted">Loading…</div>
        )}
      </div>
    </div>
  )
}

function ProjInput({ label, value, min, max, step, suffix, onChange, formatValue }) {
  return (
    <div>
      <div className="row" style={{ alignItems: 'baseline', marginBottom: 4 }}>
        <span className="eyebrow">{label}</span>
        <div className="spacer" />
        <span className="num" style={{ fontSize: 16, fontWeight: 500 }}>
          {formatValue ? formatValue(value) : value}
          {suffix && <span className="muted small" style={{ marginLeft: 4 }}>{suffix}</span>}
        </span>
      </div>
      <input
        type="range"
        min={min} max={max} step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="proj-slider"
      />
    </div>
  )
}

function ProjToggle({ label, checked, onChange }) {
  return (
    <label className="row" style={{ alignItems: 'center', cursor: 'pointer', gap: 8 }}>
      <span className="eyebrow">{label}</span>
      <div className="spacer" />
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
    </label>
  )
}

/**
 * Mounted only once this month's snapshot has been captured, so the history it
 * reads already includes today's point. Asking first would draw a line one
 * point short of the number in the hero above it.
 *
 * That ordering holds on mount, which is the path that matters: the capture is
 * this page's only write. A write made elsewhere invalidates the `/networth`
 * prefix, which reaches this key too — the line refreshes, without a new
 * snapshot being taken for it.
 */
function NetWorthOverTime() {
  const { data } = useResource(keys.networthHistory())
  const history = data || []
  if (history.length < 2) {
    return (
      <div className="muted small">
        Tracking starts now — opening this page records one point per month.
        Come back next month to see the trend line.
      </div>
    )
  }
  return <NetWorthTrend history={history} />
}

function NetWorthTrend({ history }) {
  const pts = history.map(h => ({ month: h.month, value: h.total }))
  const first = pts[0].value
  const last = pts[pts.length - 1].value
  const change = last - first
  const w = 640, h = 140, pad = 10
  const vals = pts.map(p => p.value)
  const max = Math.max(...vals)
  const min = Math.min(...vals)
  const span = max - min || 1
  const stepX = (w - pad * 2) / Math.max(pts.length - 1, 1)
  const coords = pts.map((p, i) => {
    const x = pad + i * stepX
    const y = h - pad - ((p.value - min) / span) * (h - pad * 2)
    return [x, y]
  })
  const line = 'M ' + coords.map(([x, y]) => `${x},${y}`).join(' L ')
  const area = `${line} L ${coords[coords.length - 1][0]},${h - pad} L ${pad},${h - pad} Z`
  return (
    <div>
      <div className="row" style={{ alignItems: 'baseline', marginBottom: 8 }}>
        <span className="num-big">{fmt(last)}</span>
        <span className={`sub ${change >= 0 ? 'good' : 'bad'}`} style={{ marginLeft: 10 }}>
          {change >= 0 ? '▲' : '▼'} {fmt(Math.abs(change))} since {monthShortYear(pts[0].month)}
        </span>
      </div>
      <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
        <path d={area} fill="var(--accent)" opacity="0.12" />
        <path d={line} fill="none" stroke="var(--accent)" strokeWidth="2" />
      </svg>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <span className="muted small">{monthShortYear(pts[0].month)}</span>
        <span className="muted small">{monthShortYear(pts[pts.length - 1].month)}</span>
      </div>
    </div>
  )
}

/**
 * The projection, as the backend drew it.
 *
 * This used to compound its own series here, and the MCP tool compounded a
 * different one — same question, two answers. Nothing is worked out in this
 * component now beyond which of the two currencies to show: the response
 * carries every point in both nominal and today's dollars, so the toggle above
 * costs no round trip.
 */
function ProjectionPanel({ projection, showReal }) {
  const {
    years,
    current_age: currentAge,
    retire_age: retireAge,
    annual_return_pct: rPct,
    contribution_growth_pct: gPct,
    inflation_pct: inflationPct,
    starting_balance: startBalance,
    total_contributed: totalContrib,
    compounded_growth: growth,
    final_nominal: finalNominal,
    final_real: finalReal,
    series,
  } = projection

  const displaySeries = useMemo(
    () => series.map(p => ({ year: p.year, value: showReal ? p.real : p.nominal })),
    [series, showReal]
  )

  const headline = showReal ? finalReal : finalNominal
  const counterpart = showReal ? finalNominal : finalReal

  return (
    <div className="plan-sticky">
      <div className="lbl">Projected at age {retireAge}</div>
      <div className="big good">{fmt(headline)}</div>
      <div className="helper">
        in {years} years at {rPct}% return, contributions growing {gPct}%/yr
      </div>
      <div className="helper">
        {showReal
          ? `≈ ${fmt(counterpart)} nominal · shown in today's dollars after ${inflationPct}% inflation`
          : `≈ ${fmt(counterpart)} in today's dollars`}
      </div>

      <ProjChart series={displaySeries} startAge={currentAge} />

      <div className="stack small" style={{ marginTop: 14, gap: 6 }}>
        <div className="row"><span className="muted">Starting balance</span><div className="spacer" /><span className="num">{fmt(startBalance)}</span></div>
        <div className="row"><span className="muted">+ Contributions ({years} yrs)</span><div className="spacer" /><span className="num">{fmt(totalContrib)}</span></div>
        <div className="row"><span className="muted">+ Compounded growth</span><div className="spacer" /><span className="num good">{fmt(growth)}</span></div>
        <div className="row" style={{ paddingTop: 6, borderTop: '1px dashed var(--hairline)', fontWeight: 600 }}>
          <span>Total at retirement{showReal ? ' (nominal)' : ''}</span><div className="spacer" /><span className="num">{fmt(finalNominal)}</span>
        </div>
        {showReal && (
          <div className="row" style={{ fontWeight: 600 }}>
            <span>In today's dollars</span><div className="spacer" /><span className="num good">{fmt(finalReal)}</span>
          </div>
        )}
      </div>
    </div>
  )
}

function ProjChart({ series, startAge }) {
  const w = 320, h = 140, pad = 8
  if (!series.length) return null
  const max = Math.max(...series.map(p => p.value), 1)
  const min = 0
  const stepX = (w - pad * 2) / Math.max(series.length - 1, 1)
  const points = series.map((p, i) => {
    const x = pad + i * stepX
    const y = h - pad - ((p.value - min) / (max - min)) * (h - pad * 2)
    return [x, y]
  })
  const linePath = 'M ' + points.map(([x, y]) => `${x},${y}`).join(' L ')
  const areaPath = `${linePath} L ${points[points.length - 1][0]},${h - pad} L ${pad},${h - pad} Z`

  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} style={{ marginTop: 12 }}>
      <path d={areaPath} fill="var(--accent)" opacity="0.12" />
      <path d={linePath} fill="none" stroke="var(--accent)" strokeWidth="2" />
      <text x={pad} y={h - 2} fontSize="9" fill="var(--text-mute)">
        age {startAge}
      </text>
      <text x={w - pad} y={h - 2} fontSize="9" fill="var(--text-mute)" textAnchor="end">
        age {startAge + series.length - 1}
      </text>
    </svg>
  )
}
