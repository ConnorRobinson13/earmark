import { useState, useCallback } from 'react'
import { NavLink, Route, Routes, Navigate, Outlet, useNavigate, useLocation } from 'react-router-dom'
import Dashboard from './views/Dashboard'
import QuickAdd from './views/QuickAdd'
import Inbox from './views/Inbox'
import Goals from './views/Goals'
import Planner from './views/Planner'
import FundDetail from './views/FundDetail'
import Settings from './views/Settings'
import NetWorth from './views/NetWorth'
import { thisMonth, monthLabel, shiftMonth } from './components/MonthSelector'
import { Icon } from './components/Icons'
import { fmt } from './api'
import { useResourceStore } from './resource'

export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/funds/:id" element={<FundDetail />} />
        <Route path="/quick-add" element={<QuickAdd />} />
        <Route path="/inbox" element={<Inbox />} />
        <Route path="/goals" element={<Goals />} />
        <Route path="/planner" element={<Planner />} />
        <Route path="/networth" element={<NetWorth />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

function Shell() {
  const [month, setMonth] = useState(thisMonth())
  const [unassigned, setUnassigned] = useState(null)
  const [inboxCount, setInboxCount] = useState(0)
  const [refreshTick, setRefreshTick] = useState(0)
  const store = useResourceStore()
  // Migrated views refetch from the invalidation; the rest still watch the tick.
  const refresh = useCallback(() => {
    store.invalidate()
    setRefreshTick(t => t + 1)
  }, [store])

  const ctx = { month, setMonth, unassigned, setUnassigned, inboxCount, setInboxCount, refreshTick, refresh }

  return (
    <div className="app">
      <NavDock inboxCount={inboxCount} />
      <main className="main">
        <Topbar month={month} setMonth={setMonth} unassigned={unassigned} />
        <div className="main-inner">
          <Outlet context={ctx} />
        </div>
      </main>
    </div>
  )
}

function NavDock({ inboxCount }) {
  const items = [
    { to: '/',         label: 'Dashboard', icon: 'home'  },
    { to: '/inbox',    label: 'Inbox',     icon: 'inbox', badge: inboxCount || null },
    { to: '/goals',    label: 'Goals',     icon: 'flag'  },
    { to: '/planner',  label: 'Planner',   icon: 'plan'  },
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

function Topbar({ month, setMonth, unassigned }) {
  const nav = useNavigate()
  const isCurrent = month === thisMonth()

  const onDashboard = useLocation().pathname === '/'
  const u = Number(unassigned)
  const showChip = onDashboard && unassigned != null && Number.isFinite(u)
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
