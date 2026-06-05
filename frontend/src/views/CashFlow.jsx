import { useEffect, useMemo, useRef, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { api, fmt } from '../api'
import { monthLabel } from '../components/MonthSelector'

// Categories we treat as fixed bills. A fund is also fixed if it carries a
// non-default due day (an explicitly scheduled bill like insurance).
const FIXED_CATEGORIES = new Set(['Housing', 'Subscriptions'])
const TRAY = 'tray'

function isFixedFund(f) {
  return FIXED_CATEGORIES.has(f.category) || f.due_day !== 1
}

function parseMonth(monthStr) {
  const [y, m] = monthStr.split('-').map(Number)
  return { y, m } // m is 1-12
}
function daysInMonthOf(y, m) {
  return new Date(y, m, 0).getDate()
}
function clampDay(day, dim) {
  return Math.min(Math.max(day, 1), dim)
}
function weekdayShort(y, m, day) {
  return new Date(y, m - 1, day).toLocaleDateString('en-US', { weekday: 'short' })
}

export default function CashFlow() {
  const { month, refreshTick } = useOutletContext()
  const [dash, setDash] = useState(null)
  const [paydays, setPaydays] = useState([])
  const [err, setErr] = useState('')

  // placement: cardId -> day number | 'tray'. Custom cards: list of card defs.
  const [placement, setPlacement] = useState({})
  const [customCards, setCustomCards] = useState([])
  const [draggingId, setDraggingId] = useState(null)
  const [dropTarget, setDropTarget] = useState(null)

  const { y, m } = parseMonth(month)
  const dim = daysInMonthOf(y, m)

  const today = new Date()
  const isCurrentMonth = y === today.getFullYear() && m === today.getMonth() + 1
  const isPast = y < today.getFullYear() || (y === today.getFullYear() && m < today.getMonth() + 1)
  const todayDay = today.getDate()
  // Day through which events are "already consumed" when anchoring to net cash.
  const anchorDay = isCurrentMonth ? todayDay : (isPast ? dim : 0)

  useEffect(() => {
    setDash(null); setErr('')
    Promise.all([api.dashboard(month), api.paydays.list()])
      .then(([d, pd]) => { setDash(d); setPaydays(pd) })
      .catch(e => setErr(String(e)))
  }, [month, refreshTick])

  // Expense cards from operational funds (goals excluded — those are timed by hand).
  const fundCards = useMemo(() => {
    if (!dash) return []
    return dash.funds
      .filter(f => f.kind === 'operational' && Number(f.assigned_this_month) !== 0)
      .map(f => ({
        id: `fund-${f.id}`,
        label: f.name,
        amount: -Math.abs(Number(f.assigned_this_month)),
        fixed: isFixedFund(f),
        defaultDay: clampDay(f.due_day, dim),
      }))
  }, [dash, dim])

  const allCards = useMemo(() => [...fundCards, ...customCards], [fundCards, customCards])

  // Reset placement whenever the source data changes: fixed pinned to their day,
  // variable parked in the tray. Custom cards keep whatever the user set.
  useEffect(() => {
    setPlacement(prev => {
      const next = {}
      for (const c of fundCards) next[c.id] = c.fixed ? c.defaultDay : TRAY
      for (const c of customCards) next[c.id] = prev[c.id] ?? TRAY
      return next
    })
  }, [fundCards]) // eslint-disable-line react-hooks/exhaustive-deps

  // Paydays as fixed income events on their day (not draggable).
  const paydayEvents = useMemo(() => {
    if (!dash) return []
    const planned = Number(dash.planned_income || 0)
    const fixedPaid = paydays.filter(p => p.amount != null).reduce((s, p) => s + Number(p.amount), 0)
    const splitCount = paydays.filter(p => p.amount == null).length
    const splitEach = splitCount ? (planned - fixedPaid) / splitCount : 0
    return paydays
      .map(p => ({
        day: clampDay(p.day_of_month, dim),
        amount: p.amount != null ? Number(p.amount) : splitEach,
        label: 'Paycheck',
      }))
      .filter(e => e.amount !== 0)
  }, [dash, paydays, dim])

  // Day-by-day net-cash balance, anchored so balance(today) === net_cash.
  const model = useMemo(() => {
    const netCash = dash ? Number(dash.net_cash) : 0
    const perDay = Array.from({ length: dim + 1 }, () => [])
    for (const e of paydayEvents) perDay[e.day].push({ ...e, kind: 'income' })
    for (const c of allCards) {
      const pl = placement[c.id]
      if (typeof pl === 'number') {
        perDay[pl].push({ label: c.label, amount: c.amount, kind: c.amount < 0 ? 'expense' : 'income', cardId: c.id })
      }
    }
    // Only events STRICTLY before today are "already happened" and baked into
    // net cash (we reconstruct the past from them). Net cash is the balance
    // entering today, so anything placed on today-or-later draws the line down
    // from here forward — exactly what dragging a planned expense should do.
    let consumed = 0
    for (let d = 1; d < anchorDay && d <= dim; d++)
      for (const e of perDay[d]) consumed += e.amount
    const start = netCash - consumed

    let running = start
    const days = []
    let minBal = Infinity
    let minDay = 1
    const lowFrom = isCurrentMonth ? todayDay : 1
    for (let d = 1; d <= dim; d++) {
      for (const e of perDay[d]) running += e.amount
      days.push({ day: d, balance: running, events: perDay[d] })
      if (d >= lowFrom && running < minBal) { minBal = running; minDay = d }
    }
    return { days, start, end: running, minBal: minBal === Infinity ? start : minBal, minDay }
  }, [dash, allCards, placement, paydayEvents, anchorDay, dim, isCurrentMonth, todayDay])

  function move(cardId, target) {
    setPlacement(p => ({ ...p, [cardId]: target }))
  }
  // Native HTML5 DnD: setData is required to actually start a drag (Firefox
  // won't drag without it). We also stash the id in dataTransfer as a fallback
  // so onDrop works even if the draggingId state read is stale.
  function handleDragStart(e, id) {
    setDraggingId(id)
    if (e.dataTransfer) {
      e.dataTransfer.setData('text/plain', id)
      e.dataTransfer.effectAllowed = 'move'
    }
  }
  function handleDrop(e, target) {
    e.preventDefault()
    const id = draggingId || (e.dataTransfer && e.dataTransfer.getData('text/plain'))
    if (id) move(id, target)
    setDropTarget(null)
    setDraggingId(null)
  }
  function addCustom(card) {
    setCustomCards(list => [...list, card])
    setPlacement(p => ({ ...p, [card.id]: TRAY }))
  }
  function removeCustom(cardId) {
    setCustomCards(list => list.filter(c => c.id !== cardId))
    setPlacement(p => { const n = { ...p }; delete n[cardId]; return n })
  }

  if (err) return <div className="card"><span className="bad">{err}</span></div>

  return (
    <div>
      <div className="sec-head" style={{ marginTop: 0 }}>
        <h2>Cash flow</h2>
        <span className="sub">{monthLabel(month)} · net cash, day by day · drag to plan</span>
      </div>

      {!dash ? (
        <div className="muted">Loading…</div>
      ) : isPast ? (
        <div className="card muted">Daily balances can only be planned for the current or a future month.</div>
      ) : (
        <>
          <CashChart days={model.days} todayDay={isCurrentMonth ? todayDay : null} />

          <div className={`card cf-banner ${model.minBal < 0 ? 'cf-warn' : 'cf-ok'}`}>
            {model.minBal < 0 ? (
              <><b>⚠ Dips below $0</b> on {monthLabel(month).split(' ')[0]} {model.minDay} (down to <b>{fmt(model.minBal)}</b>). Move an expense later or drop one off.</>
            ) : (
              <><b>✓ Stays positive.</b> Lowest point is {monthLabel(month).split(' ')[0]} {model.minDay} at <b>{fmt(model.minBal)}</b>.</>
            )}
          </div>

          <div className="cf-layout">
            <Tray
              cards={allCards.filter(c => placement[c.id] === TRAY)}
              onDragStart={handleDragStart}
              onDragEnd={() => { setDraggingId(null); setDropTarget(null) }}
              onDrop={e => handleDrop(e, TRAY)}
              over={dropTarget === TRAY}
              setOver={v => setDropTarget(v ? TRAY : null)}
              onAddCustom={addCustom}
              onRemoveCustom={removeCustom}
            />

            <div className="cf-days">
              {model.days.map(d => {
                const editable = !isCurrentMonth || d.day >= todayDay
                const isToday = isCurrentMonth && d.day === todayDay
                const neg = d.balance < 0
                return (
                  <div
                    key={d.day}
                    className={`cf-day ${isToday ? 'today' : ''} ${neg ? 'neg' : ''} ${dropTarget === d.day ? 'cf-drop' : ''} ${editable ? '' : 'cf-locked'}`}
                    onDragOver={editable ? (e => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; setDropTarget(d.day) }) : undefined}
                    onDragLeave={() => setDropTarget(t => (t === d.day ? null : t))}
                    onDrop={editable ? (e => handleDrop(e, d.day)) : undefined}
                  >
                    <div className="cf-date">
                      <span className="cf-wd">{weekdayShort(y, m, d.day)}</span>
                      <span className="cf-dn">{d.day}</span>
                      {isToday && <span className="cf-today-tag">today</span>}
                    </div>
                    <div className="cf-events">
                      {d.events.length === 0
                        ? <span className="muted small">{editable ? 'drop here' : '—'}</span>
                        : d.events.map((e, i) => (
                            e.cardId ? (
                              <DayCard key={e.cardId} card={e} onDragStart={handleDragStart} onDragEnd={() => { setDraggingId(null); setDropTarget(null) }} onRemove={() => move(e.cardId, TRAY)} />
                            ) : (
                              <div key={i} className="cf-evt">
                                <span>💵 {e.label}</span>
                                <span className="good">+{fmt(e.amount)}</span>
                              </div>
                            )
                          ))}
                    </div>
                    <div className={`cf-bal ${neg ? 'bad' : ''}`}>{fmt(d.balance)}</div>
                  </div>
                )
              })}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function Tray({ cards, onDragStart, onDragEnd, onDrop, over, setOver, onAddCustom, onRemoveCustom }) {
  return (
    <div
      className={`cf-tray ${over ? 'cf-drop' : ''}`}
      onDragOver={e => { e.preventDefault(); setOver(true) }}
      onDragLeave={() => setOver(false)}
      onDrop={e => { onDrop(e); setOver(false) }}
    >
      <div className="cf-tray-head">To place</div>
      {cards.length === 0 && <div className="muted small" style={{ padding: '4px 2px' }}>Everything's placed.</div>}
      {cards.map(c => (
        <TrayCard key={c.id} card={c} onDragStart={onDragStart} onDragEnd={onDragEnd}
          onRemove={c.id.startsWith('custom-') ? () => onRemoveCustom(c.id) : null} />
      ))}
      <CustomCardForm onAdd={onAddCustom} />
    </div>
  )
}

function TrayCard({ card, onDragStart, onDragEnd, onRemove }) {
  const income = card.amount > 0
  return (
    <div className="cf-card" draggable
      onDragStart={e => onDragStart(e, card.id)} onDragEnd={onDragEnd}>
      <span className="cf-card-label">{card.label}</span>
      <span className={`cf-card-amt ${income ? 'good' : ''}`}>{income ? '+' : ''}{fmt(card.amount)}</span>
      {onRemove && <button className="cf-card-x" onClick={onRemove} title="Delete card">×</button>}
    </div>
  )
}

function DayCard({ card, onDragStart, onDragEnd, onRemove }) {
  const income = card.amount > 0
  return (
    <div className="cf-evt cf-evt-card" draggable
      onDragStart={e => onDragStart(e, card.cardId)} onDragEnd={onDragEnd}>
      <span>{card.label}</span>
      <span className={income ? 'good' : 'bad'}>
        {income ? '+' : ''}{fmt(card.amount)}
        <button className="cf-card-x" onClick={onRemove} title="Back to tray">×</button>
      </span>
    </div>
  )
}

function CustomCardForm({ onAdd }) {
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [amount, setAmount] = useState('')
  const [income, setIncome] = useState(false)
  const idRef = useRef(0)

  if (!open) return <button className="cf-add" onClick={() => setOpen(true)}>+ custom</button>

  function submit(e) {
    e.preventDefault()
    const val = Math.abs(Number(amount))
    if (!label.trim() || !val) return
    onAdd({
      id: `custom-${Date.now()}-${idRef.current++}`,
      label: label.trim(),
      amount: income ? val : -val,
    })
    setLabel(''); setAmount(''); setIncome(false); setOpen(false)
  }

  return (
    <form className="cf-add-form" onSubmit={submit}>
      <input autoFocus placeholder="Label (e.g. Car downpayment)" value={label} onChange={e => setLabel(e.target.value)} />
      <div className="row" style={{ gap: 6 }}>
        <input type="number" placeholder="Amount" value={amount} onChange={e => setAmount(e.target.value)} style={{ width: 90 }} />
        <button type="button" className={`cf-toggle ${income ? 'on' : ''}`} onClick={() => setIncome(v => !v)}>
          {income ? '+ income' : '− expense'}
        </button>
      </div>
      <div className="row" style={{ gap: 6 }}>
        <button type="submit" className="iconbtn primary" style={{ flex: 1 }}>Add</button>
        <button type="button" className="iconbtn" onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </form>
  )
}

function CashChart({ days, todayDay }) {
  const w = 640, h = 120, pad = 8
  if (!days.length) return null
  const vals = days.map(d => d.balance)
  const max = Math.max(...vals, 0)
  const min = Math.min(...vals, 0)
  const span = max - min || 1
  const stepX = (w - pad * 2) / Math.max(days.length - 1, 1)
  const pts = days.map((d, i) => {
    const x = pad + i * stepX
    const yy = h - pad - ((d.balance - min) / span) * (h - pad * 2)
    return [x, yy]
  })
  const line = 'M ' + pts.map(([x, yy]) => `${x},${yy}`).join(' L ')
  const area = `${line} L ${pts[pts.length - 1][0]},${h - pad} L ${pad},${h - pad} Z`
  // zero baseline (only meaningful when the line crosses it)
  const zeroY = h - pad - ((0 - min) / span) * (h - pad * 2)
  const todayX = todayDay ? pad + (todayDay - 1) * stepX : null

  return (
    <svg className="cf-chart" width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <path d={area} fill="var(--accent)" opacity="0.12" />
      {min < 0 && <line x1={pad} y1={zeroY} x2={w - pad} y2={zeroY} stroke="var(--bad)" strokeWidth="1" strokeDasharray="3 3" opacity="0.6" />}
      <path d={line} fill="none" stroke="var(--accent)" strokeWidth="2" />
      {todayX != null && <line x1={todayX} y1={pad} x2={todayX} y2={h - pad} stroke="var(--text-mute)" strokeWidth="1" strokeDasharray="2 2" />}
    </svg>
  )
}
