import { useEffect, useMemo, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { api, fmt, todayISO } from '../api'
import { Icon } from '../components/Icons'

export default function Planner() {
  const { refresh, refreshTick } = useOutletContext()
  const [dash, setDash] = useState(null)
  const [funds, setFunds] = useState([])
  const [template, setTemplate] = useState([])
  const [assigns, setAssigns] = useState({})
  const [income, setIncome] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function load() {
    try {
      const [d, f, t] = await Promise.all([api.dashboard(), api.funds.list(), api.templates.list()])
      setDash(d); setFunds(f); setTemplate(t)
    } catch (e) { setErr(String(e)) }
  }
  useEffect(() => { load() }, [refreshTick])

  const templatedFundIds = useMemo(() => new Set(template.map(t => t.fund_id)), [template])
  const flexFunds = funds.filter(f => !templatedFundIds.has(f.id))
  const assignedByFund = useMemo(() => {
    const m = new Map()
    for (const f of funds) m.set(f.id, Number(f.assigned_this_month || 0))
    return m
  }, [funds])

  const plannedTotal = template.reduce((s, t) => s + Number(t.planned_amount || 0), 0)
  const remainingTemplate = template.reduce((s, t) => {
    const planned = Number(t.planned_amount || 0)
    const already = assignedByFund.get(t.fund_id) || 0
    return s + Math.max(0, planned - already)
  }, 0)
  const flexTotal = Object.values(assigns).reduce((s, v) => s + (Number(v) || 0), 0)
  const projUnassigned = Number(dash?.unassigned || 0) + (Number(income) || 0) - remainingTemplate - flexTotal

  async function postIncome() {
    const n = Number(income)
    if (!n) return
    setBusy(true); setErr('')
    try {
      await api.transactions.quickAdd({
        fund_id: null, amount: n, date: todayISO(),
        merchant: 'Income', type: 'income',
      })
      setIncome('')
      await load(); refresh()
    } catch (e) { setErr(String(e)) }
    finally { setBusy(false) }
  }

  async function applyTemplate() {
    setBusy(true); setErr('')
    try {
      await api.templates.apply(todayISO())
      await load(); refresh()
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
      await load(); refresh()
    } catch (e) { setErr(String(e)) }
    finally { setBusy(false) }
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

  function updateTemplateLine(i, k, v) {
    setTemplate(t => t.map((row, idx) => idx === i ? { ...row, [k]: v } : row))
  }

  if (err) return <div className="card"><span className="bad">{err}</span></div>
  if (!dash) return <div className="muted">Loading…</div>

  const projTone = Math.abs(projUnassigned) < 0.01 ? 'good' : projUnassigned > 0 ? 'warn' : 'bad'
  const projMessage = projTone === 'good'
    ? 'Zero-based — every dollar has a home'
    : projUnassigned > 0 ? `${fmt(projUnassigned)} still to assign` : `Overplanned by ${fmt(Math.abs(projUnassigned))}`

  return (
    <div>
      <div className="sec-head" style={{ marginTop: 0 }}>
        <h2>Monthly planner</h2>
        <span className="sub">income → fixed → flex → review</span>
      </div>

      <div className="plan-grid">
        <div>
          <div className="plan-step done">
            <div className="step-head">
              <div className="step-num">1</div>
              <h3>Record income</h3>
            </div>
            <div className="card stack">
              <input placeholder="Paycheck / income amount" inputMode="decimal"
                value={income} onChange={e => setIncome(e.target.value)} />
              <div className="row">
                <div className="spacer" />
                <button className="btn primary sm" onClick={postIncome} disabled={busy || !Number(income)}>
                  Record → Unassigned
                </button>
              </div>
            </div>
          </div>

          <div className="plan-step">
            <div className="step-head">
              <div className="step-num">2</div>
              <h3>Fixed expenses (template)</h3>
            </div>
            <div className="card">
              {template.length === 0 && <div className="muted small" style={{ marginBottom: 8 }}>No template yet — add lines below.</div>}
              {template.map((row, i) => (
                <div key={i} className="template-row">
                  <select value={row.fund_id || ''} onChange={e => updateTemplateLine(i, 'fund_id', Number(e.target.value))}>
                    <option value="">Fund…</option>
                    {funds.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
                  </select>
                  <input className="amt-input" inputMode="decimal" value={row.planned_amount || ''}
                    onChange={e => updateTemplateLine(i, 'planned_amount', e.target.value)} placeholder="0" />
                  <button className="btn ghost sm" onClick={() => setTemplate(t => t.filter((_, idx) => idx !== i))}>
                    <Icon name="x" size={12} />
                  </button>
                </div>
              ))}
              <div className="row" style={{ marginTop: 12, gap: 8 }}>
                <button className="btn sm" onClick={() => setTemplate(t => [...t, { fund_id: '', planned_amount: '' }])}>
                  <Icon name="plus" size={12} /> Add line
                </button>
                <button className="btn sm" onClick={saveTemplate} disabled={busy}>Save template</button>
                <div className="spacer" />
                <button className="btn primary sm" onClick={applyTemplate} disabled={busy || template.length === 0}>
                  Apply template
                </button>
              </div>
              <div className="muted small" style={{ marginTop: 8 }}>
                Planned total: <b style={{ color: 'var(--text-2)' }}>{fmt(plannedTotal)}</b>
              </div>
            </div>
          </div>

          <div className="plan-step">
            <div className="step-head">
              <div className="step-num">3</div>
              <h3>Flex assignments</h3>
            </div>
            <div className="card">
              {flexFunds.length === 0 && <div className="muted small">All funds are templated.</div>}
              {flexFunds.map(f => (
                <div key={f.id} className="template-row">
                  <div>
                    <div style={{ fontWeight: 500 }}>{f.name}</div>
                    <div className="muted small">balance {fmt(f.balance)}</div>
                  </div>
                  <input className="amt-input" inputMode="decimal" placeholder="0"
                    value={assigns[f.id] || ''}
                    onChange={e => setAssigns(a => ({ ...a, [f.id]: e.target.value }))} />
                  <div />
                </div>
              ))}
              <div className="row" style={{ marginTop: 12 }}>
                <div className="spacer" />
                <button className="btn primary sm" onClick={commitAssigns} disabled={busy || flexTotal === 0}>
                  Commit assignments ({fmt(flexTotal)})
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="plan-sticky">
          <div className="lbl">Projected unassigned</div>
          <div className={`big ${projTone}`}>{fmt(projUnassigned)}</div>
          <div className="helper">{projMessage}</div>
          <div style={{ height: 14 }} />
          <div className="lbl">Current state</div>
          <div className="small" style={{ marginTop: 6, lineHeight: 1.6 }}>
            <div className="row"><span className="muted">Unassigned now</span><div className="spacer" /><span className="num">{fmt(dash.unassigned)}</span></div>
            <div className="row"><span className="muted">+ Income to record</span><div className="spacer" /><span className="num">{fmt(Number(income) || 0)}</span></div>
            <div className="row" title="Template lines minus what's already assigned this month">
              <span className="muted">− Template remaining</span>
              <div className="spacer" />
              <span className="num">{fmt(remainingTemplate)}</span>
            </div>
            <div className="row"><span className="muted">− Flex assigns</span><div className="spacer" /><span className="num">{fmt(flexTotal)}</span></div>
          </div>
          <div className="small muted" style={{ marginTop: 8 }}>
            Full template plan: {fmt(plannedTotal)} · already done: {fmt(plannedTotal - remainingTemplate)}
          </div>
        </div>
      </div>
    </div>
  )
}
