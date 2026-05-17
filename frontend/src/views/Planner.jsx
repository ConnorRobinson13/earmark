import { useEffect, useMemo, useState } from 'react'
import { api, fmt, todayISO } from '../api'

export default function Planner() {
  const [dash, setDash] = useState(null)
  const [funds, setFunds] = useState([])
  const [template, setTemplate] = useState([])  // [{fund_id, planned_amount}]
  const [assigns, setAssigns] = useState({})    // {fund_id: amount string} - flex/goal additions
  const [income, setIncome] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function load() {
    try {
      const [d, f, t] = await Promise.all([api.dashboard(), api.funds.list(), api.templates.list()])
      setDash(d); setFunds(f); setTemplate(t)
    } catch (e) { setErr(String(e)) }
  }
  useEffect(() => { load() }, [])

  const templatedFundIds = useMemo(() => new Set(template.map(t => t.fund_id)), [template])
  const flexFunds = funds.filter(f => !templatedFundIds.has(f.id))

  const plannedTotal = template.reduce((s, t) => s + Number(t.planned_amount), 0)
  const flexTotal = Object.values(assigns).reduce((s, v) => s + (Number(v) || 0), 0)
  const projUnassigned = Number(dash?.unassigned || 0) + (Number(income) || 0) - plannedTotal - flexTotal

  async function postUntaggedIncome() {
    const n = Number(income)
    if (!n) return
    setBusy(true); setErr('')
    try {
      await api.transactions.quickAdd({
        fund_id: null,
        amount: n,
        date: todayISO(),
        merchant: 'Income',
        type: 'income',
      })
      setIncome('')
      await load()
    } catch (e) { setErr(String(e)) }
    finally { setBusy(false) }
  }

  async function applyTemplate() {
    setBusy(true); setErr('')
    try {
      await api.templates.apply(todayISO())
      await load()
    } catch (e) { setErr(String(e)) }
    finally { setBusy(false) }
  }

  async function commitAssigns() {
    setBusy(true); setErr('')
    try {
      for (const [fid, v] of Object.entries(assigns)) {
        const n = Number(v)
        if (!n) continue
        await api.transactions.assign({ fund_id: Number(fid), amount: n, date: todayISO() })
      }
      setAssigns({})
      await load()
    } catch (e) { setErr(String(e)) }
    finally { setBusy(false) }
  }

  function updateTemplateLine(i, k, v) {
    setTemplate(t => t.map((row, idx) => idx === i ? { ...row, [k]: v } : row))
  }

  async function saveTemplate() {
    setBusy(true); setErr('')
    try {
      await api.templates.replace(
        template
          .filter(t => t.fund_id && Number(t.planned_amount))
          .map(t => ({ fund_id: Number(t.fund_id), planned_amount: Number(t.planned_amount) }))
      )
      await load()
    } catch (e) { setErr(String(e)) }
    finally { setBusy(false) }
  }

  if (err) return <div className="card bad">{err}</div>
  if (!dash) return <div className="muted">Loading…</div>

  return (
    <div>
      <h1>Monthly planner</h1>

      <div className="card">
        <div className="muted small">Projected unassigned after plan</div>
        <div className={`xlarge ${Math.abs(projUnassigned) < 0.01 ? 'good' : projUnassigned > 0 ? 'warn' : 'bad'}`}>
          {fmt(projUnassigned)}
        </div>
        <div className="muted small">target: $0.00 (zero-based)</div>
      </div>

      <h2>1. Income</h2>
      <div className="card stack">
        <input placeholder="Paycheck / income amount" inputMode="decimal" value={income} onChange={e => setIncome(e.target.value)} />
        <button className="primary" onClick={postUntaggedIncome} disabled={busy || !Number(income)}>
          Record income → Unassigned
        </button>
      </div>

      <h2>2. Fixed expenses (template)</h2>
      <div className="card">
        {template.length === 0 && <div className="muted small">No template yet. Add lines below.</div>}
        {template.map((row, i) => (
          <div key={i} className="row" style={{ marginBottom: 8 }}>
            <select value={row.fund_id} onChange={e => updateTemplateLine(i, 'fund_id', Number(e.target.value))}>
              <option value="">Fund…</option>
              {funds.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
            <input style={{ maxWidth: 120 }} inputMode="decimal" value={row.planned_amount}
              onChange={e => updateTemplateLine(i, 'planned_amount', e.target.value)} />
            <button className="ghost" onClick={() => setTemplate(t => t.filter((_, idx) => idx !== i))}>×</button>
          </div>
        ))}
        <div className="row" style={{ marginTop: 8 }}>
          <button onClick={() => setTemplate(t => [...t, { fund_id: '', planned_amount: '' }])}>Add line</button>
          <button onClick={saveTemplate} disabled={busy}>Save template</button>
          <button className="primary" onClick={applyTemplate} disabled={busy || template.length === 0}>
            Apply template
          </button>
        </div>
        <div className="muted small" style={{ marginTop: 8 }}>
          Planned total: {fmt(plannedTotal)}
        </div>
      </div>

      <h2>3. Flex assignments</h2>
      <div className="card">
        {flexFunds.length === 0 && <div className="muted small">All funds are templated.</div>}
        {flexFunds.map(f => (
          <div key={f.id} className="row" style={{ padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
            <div className="col" style={{ flex: 1 }}>
              <div>{f.name}</div>
              <div className="meta">balance {fmt(f.balance)}</div>
            </div>
            <input
              style={{ maxWidth: 120 }}
              inputMode="decimal"
              placeholder="0"
              value={assigns[f.id] || ''}
              onChange={e => setAssigns(a => ({ ...a, [f.id]: e.target.value }))}
            />
          </div>
        ))}
        <button className="primary" style={{ marginTop: 12 }} onClick={commitAssigns} disabled={busy || flexTotal === 0}>
          Commit assignments ({fmt(flexTotal)})
        </button>
      </div>
    </div>
  )
}
