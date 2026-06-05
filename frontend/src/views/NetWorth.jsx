import { useEffect, useMemo, useState } from 'react'
import { api, fmt } from '../api'
import { thisMonth } from '../components/MonthSelector'

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

export default function NetWorth() {
  const [data, setData] = useState(null)
  const [dash, setDash] = useState(null)
  const [history, setHistory] = useState([])
  const [err, setErr] = useState('')
  const [proj, setProj] = useState(loadProjection)

  useEffect(() => {
    // networth() also captures this month's snapshot, so fetch history after it
    // resolves to include the latest point.
    api.networth()
      .then(d => { setData(d); return api.networthHistory() })
      .then(setHistory)
      .catch(e => setErr(String(e)))
    api.dashboard(thisMonth()).then(setDash).catch(() => {})
  }, [])

  // Monthly NEEDS = bare-bones survival budget for the runway: housing + any
  // scheduled bill (non-default due day, e.g. insurance) + a groceries
  // allowance. Subscriptions, discretionary (eating out, buffer, gifts) and
  // one-offs are all excluded — in a real emergency you'd cut every one.
  const monthlyNeeds = useMemo(() => {
    if (!dash) return 0
    return dash.funds
      .filter(f => f.kind === 'operational')
      .filter(f => {
        const scheduledBill = (f.category === 'Housing' || f.due_day !== 1) && f.category !== 'Subscriptions'
        const groceries = /grocer/i.test(f.name)
        return scheduledBill || groceries
      })
      .reduce((s, f) => s + Number(f.assigned_this_month || 0), 0)
  }, [dash])

  function patch(k, v) {
    setProj(p => {
      const next = { ...p, [k]: v }
      saveProjection(next)
      return next
    })
  }

  if (err) return <div className="card"><span className="bad">{err}</span></div>
  if (!data) return <div className="muted">Loading…</div>

  const total = Number(data.total)
  const liquid = Number(data.liquid)
  const investment = Number(data.investment)
  const emergency = Number(data.emergency_fund || 0)
  const debt = Number(data.credit_debt)
  const loan = Number(data.loan_debt || 0)

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
        {history.length < 2 ? (
          <div className="muted small">
            Tracking starts now — a snapshot is saved each month you open this page.
            Come back next month to see the trend line.
          </div>
        ) : (
          <NetWorthTrend history={history} />
        )}
      </div>

      {/* Emergency-fund runway */}
      {monthlyNeeds > 0 && emergency > 0 && (
        <div className="card runway-card">
          <div>
            <div className="eyebrow">Emergency runway</div>
            <div className="sub">{fmt(emergency)} ÷ {fmt(monthlyNeeds)}/mo needs (fixed bills + groceries)</div>
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

        <ProjectionPanel
          startBalance={investment}
          monthly={proj.monthlyContribution}
          rPct={proj.annualReturnPct}
          gPct={proj.contributionGrowthPct}
          years={Math.max(0, proj.retireAge - proj.currentAge)}
          retireAge={proj.retireAge}
          currentAge={proj.currentAge}
          showReal={proj.showRealDollars}
          inflationPct={proj.inflationPct}
        />
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

function NetWorthTrend({ history }) {
  const pts = history.map(h => ({ month: h.month, value: Number(h.total) }))
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
  const fmtMonth = (iso) => {
    const [y, m] = iso.split('-').map(Number)
    return new Date(y, m - 1, 1).toLocaleDateString('en-US', { month: 'short', year: '2-digit' })
  }
  return (
    <div>
      <div className="row" style={{ alignItems: 'baseline', marginBottom: 8 }}>
        <span className="num-big">{fmt(last)}</span>
        <span className={`sub ${change >= 0 ? 'good' : 'bad'}`} style={{ marginLeft: 10 }}>
          {change >= 0 ? '▲' : '▼'} {fmt(Math.abs(change))} since {fmtMonth(pts[0].month)}
        </span>
      </div>
      <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
        <path d={area} fill="var(--accent)" opacity="0.12" />
        <path d={line} fill="none" stroke="var(--accent)" strokeWidth="2" />
      </svg>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <span className="muted small">{fmtMonth(pts[0].month)}</span>
        <span className="muted small">{fmtMonth(pts[pts.length - 1].month)}</span>
      </div>
    </div>
  )
}

function projectSeries(startBalance, monthly, rPct, years, gPct) {
  // Year-by-year compound with monthly contributions, compounded annually for
  // simplicity (close enough at this granularity). Contributions escalate by
  // gPct each year to mirror raises — year 1 uses the base monthly amount.
  const r = rPct / 100
  const g = gPct / 100
  const points = []
  let bal = startBalance
  let annualContrib = monthly * 12
  let contribCumulative = 0
  points.push({ year: 0, value: bal, contribCumulative: 0 })
  for (let y = 1; y <= years; y++) {
    bal = bal * (1 + r) + annualContrib
    contribCumulative += annualContrib
    points.push({ year: y, value: bal, contribCumulative })
    annualContrib *= (1 + g) // next year's contribution grows with raises
  }
  return points
}

function ProjectionPanel({ startBalance, monthly, rPct, gPct, years, retireAge, currentAge, showReal, inflationPct }) {
  const series = useMemo(
    () => projectSeries(startBalance, monthly, rPct, years, gPct),
    [startBalance, monthly, rPct, years, gPct]
  )
  // Deflate a future nominal value at `year` into today's dollars.
  const deflate = (v, year) => v / Math.pow(1 + inflationPct / 100, year)

  const displaySeries = useMemo(
    () => series.map(p => ({ year: p.year, value: showReal ? deflate(p.value, p.year) : p.value })),
    [series, showReal, inflationPct]
  )

  const finalNominal = series[series.length - 1]?.value ?? startBalance
  const finalReal = deflate(finalNominal, years)
  const headline = showReal ? finalReal : finalNominal
  const counterpart = showReal ? finalNominal : finalReal

  const totalContrib = series[series.length - 1]?.contribCumulative ?? 0
  const growth = finalNominal - startBalance - totalContrib

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
