import { useState } from 'react'
import { NavLink, Route, Routes, Navigate, Outlet, useNavigate } from 'react-router-dom'
import Dashboard from './views/Dashboard'
import QuickAdd from './views/QuickAdd'
import Inbox from './views/Inbox'
import Goals from './views/Goals'
import FundDetail from './views/FundDetail'
import Settings from './views/Settings'
import NetWorth from './views/NetWorth'
import { thisMonth, shiftMonth } from './components/MonthSelector'
import { monthLabel } from './format'
import { Icon } from './components/Icons'
import { fmt } from './api'
import { keys, useResource } from './resource'

export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/funds/:id" element={<FundDetail />} />
        <Route path="/quick-add" element={<QuickAdd />} />
        <Route path="/inbox" element={<Inbox />} />
        <Route path="/goals" element={<Goals />} />
        <Route path="/networth" element={<NetWorth />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

/**
 * The month is the only thing the shell owns and hands down. The nav badge and
 * the unassigned chip used to live here too, pushed up from the dashboard's
 * loader through setter props, which meant they were blank until the dashboard
 * had mounted and wrong the moment anything else changed them. Both now read
 * their own key.
 */
function Shell() {
  const [month, setMonth] = useState(thisMonth())

  return (
    <div className="app">
      <NavDock />
      <main className="main">
        <Topbar month={month} setMonth={setMonth} />
        <div className="main-inner">
          <Outlet context={{ month, setMonth }} />
        </div>
      </main>
    </div>
  )
}

function NavDock() {
  // Its own read of the inbox, so the badge is right on first paint and drops
  // the moment an item is approved — from any route, dashboard or not.
  const { data } = useResource(keys.inbox())
  const inboxCount = data?.length ?? 0

  const items = [
    { to: '/',         label: 'Dashboard', icon: 'home'  },
    { to: '/inbox',    label: 'Inbox',     icon: 'inbox', badge: inboxCount || null },
    { to: '/goals',    label: 'Goals',     icon: 'flag'  },
    { to: '/networth', label: 'Net worth', icon: 'spark' },
  ]
  return (
    <nav className="dock">
      <img className="dock-mark" src="/assets/ronin-logomark-light.png" alt="Ronin Systems" />
      <span className="dock-div" />
      {items.map(it => (
        <NavLink key={it.to} to={it.to} end={it.to === '/'}
          className={({ isActive }) => `dockitem ${isActive ? 'active' : ''}`}
        >
          <Icon name={it.icon} />
          <span>{it.label}</span>
          {it.badge ? <span className="badge">{it.badge}</span> : null}
        </NavLink>
      ))}
      <span className="dock-div" />
      <NavLink to="/settings" aria-label="Settings"
        className={({ isActive }) => `dockitem icon-only ${isActive ? 'active' : ''}`}
      >
        <Icon name="cog" />
      </NavLink>
    </nav>
  )
}

function Topbar({ month, setMonth }) {
  const nav = useNavigate()
  const isCurrent = month === thisMonth()

  // The same key the dashboard reads, so the two share one round trip and
  // cannot disagree. The chip used to be hidden off the dashboard route to
  // conceal that it was showing whatever month the dashboard last loaded.
  const { data } = useResource(keys.dashboard(month))
  const u = data?.unassigned
  const showChip = Number.isFinite(u)
  const tone = Math.abs(u) < 0.01 ? 'zero' : u > 0 ? 'pos' : 'neg'

  return (
    <div className="topbar">
      {showChip ? (
        <div className={`uchip ${tone}`} title="Money left to assign this month">
          <span className="dot" />
          <span className="eyebrow">Unassigned</span>
          <span className="amt">{fmt(u)}</span>
        </div>
      ) : null}
      <div className="spacer" />
      <div className="monthsw">
        <button onClick={() => setMonth(shiftMonth(month, -1))} aria-label="Previous month">
          <Icon name="chev_l" />
        </button>
        <div className="label" onClick={() => setMonth(thisMonth())} title="Jump to current month">
          {monthLabel(month)}
          {!isCurrent && <span className="archived">archived</span>}
        </div>
        <button onClick={() => setMonth(shiftMonth(month, 1))} aria-label="Next month">
          <Icon name="chev_r" />
        </button>
      </div>
      <button className="btn sm primary" title="Quick add (n)" onClick={() => nav('/quick-add')}>
        <Icon name="plus" /> Quick add
      </button>
    </div>
  )
}
