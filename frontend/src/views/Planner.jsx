import { useMemo, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { api, fmt } from '../api'
import { keys, useInvalidate, useResource, writes } from '../resource'
import ErrorCard from '../components/ErrorCard'
import { dateInMonth } from '../components/MonthSelector'
import { Icon } from '../components/Icons'

export default function Planner() {
  const { month } = useOutletContext()
  // One read, not two: the dashboard carries the funds enriched for the
  // selected month, which is exactly what the planner is planning against.
  const dashRes = useResource(keys.dashboard(month))
  const templateRes = useResource(keys.templates())
  const invalidate = useInvalidate()
  const [assigns, setAssigns] = useState({})
  const [income, setIncome] = useState('')
  const [saveErr, setSaveErr] = useState(null)
  const [busy, setBusy] = useState(false)

  // The template rows are edited in place before they are saved, so they live
  // in local state. A fresh read — after a save, or after anything else
  // invalidates `/templates` — replaces the draft wholesale.
  const [draft, setDraft] = useState([])
  const [drafted, setDrafted] = useState(null)
  if (templateRes.data && templateRes.data !== drafted) {
    setDrafted(templateRes.data)
    setDraft(templateRes.data)
  }

  const dash = dashRes.data
  const funds = dash?.funds ?? []
  const template = draft

  const templatedFundIds = useMemo(() => new Set(template.map(t => t.fund_id)), [template])
  const flexFunds = funds.filter(f => !templatedFundIds.has(f.id))
  const assignedByFund = useMemo(() => {
    const m = new Map()
    for (const f of funds) m.set(f.id, f.assigned_this_month || 0)
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
    setBusy(true); setSaveErr(null)
    try {
      await api.transactions.quickAdd({
        fund_id: null, amount: n, date: dateInMonth(month),
        merchant: 'Income', type: 'income',
      })
      setIncome('')
      invalidate(writes.ledger)
    } catch (e) { setSaveErr(e) }
    finally { setBusy(false) }
  }

  async function applyTemplate() {
    setBusy(true); setSaveErr(null)
    try {
      // Applied to the month in the top bar, not to whatever month today is in.
      await api.templates.apply(month)
      invalidate(writes.ledger)
    } catch (e) { setSaveErr(e) }
    finally { setBusy(false) }
  }

  async function commitAssigns() {
    setBusy(true); setSaveErr(null)
    try {
      for (const [fid, v] of Object.entries(assigns)) {
        const n = Number(v)
        if (!n) continue
        await api.transactions.assign({ fund_id: Number(fid), amount: n, date: dateInMonth(month) })
      }
      setAssigns({})
      invalidate(writes.ledger)
    } catch (e) { setSaveErr(e) }
    finally { setBusy(false) }
  }

  async function saveTemplate() {
    setBusy(true); setSaveErr(null)
    try {
      await api.templates.replace(
        template
          .filter(t => t.fund_id && Number(t.planned_amount))
          .map(t => ({ fund_id: Number(t.fund_id), planned_amount: Number(t.planned_amount) }))
      )
      invalidate(writes.template)
    } catch (e) { setSaveErr(e) }
    finally { setBusy(false) }
  }

  function updateTemplateLine(i, k, v) {
    setDraft(t => t.map((row, idx) => idx === i ? { ...row, [k]: v } : row))
  }

  const error = dashRes.error || templateRes.error
  if (error) return <ErrorCard error={error} />
  if (!dash || !templateRes.data) return <div className="muted">Loading…</div>

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

      {saveErr && <ErrorCard error={saveErr} />}

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
                  <button className="btn ghost sm" onClick={() => setDraft(t => t.filter((_, idx) => idx !== i))}>
                    <Icon name="x" size={12} />
                  </button>
                </div>
              ))}
              <div className="row" style={{ marginTop: 12, gap: 8 }}>
                <button className="btn sm" onClick={() => setDraft(t => [...t, { fund_id: '', planned_amount: '' }])}>
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
