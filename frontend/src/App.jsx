import { useState, useCallback } from 'react'
import { NavLink, Route, Routes, Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom'
import Dashboard from './views/Dashboard'
import QuickAdd from './views/QuickAdd'
import Inbox from './views/Inbox'
import Goals from './views/Goals'
import Planner from './views/Planner'
import FundDetail from './views/FundDetail'
import Settings from './views/Settings'
import NetWorth from './views/NetWorth'
import CashFlow from './views/CashFlow'
import { fmt } from './api'
import { thisMonth, monthLabel, shiftMonth } from './components/MonthSelector'
import { Icon } from './components/Icons'

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
        <Route path="/cashflow" element={<CashFlow />} />
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
  const refresh = useCallback(() => setRefreshTick(t => t + 1), [])

  const ctx = { month, setMonth, unassigned, setUnassigned, inboxCount, setInboxCount, refreshTick, refresh }

  return (
    <div className="app">
      <Sidebar inboxCount={inboxCount} />
      <main className="main">
        <Topbar month={month} setMonth={setMonth} unassigned={unassigned} />
        <div className="main-inner">
          <Outlet context={ctx} />
        </div>
      </main>
    </div>
  )
}

function Sidebar({ inboxCount }) {
  const items = [
    { to: '/',         label: 'Dashboard', icon: 'home'  },
    { to: '/inbox',    label: 'Inbox',     icon: 'inbox', badge: inboxCount || null },
    { to: '/goals',    label: 'Goals',     icon: 'flag'  },
    { to: '/planner',  label: 'Planner',   icon: 'plan'  },
    { to: '/cashflow', label: 'Cash flow', icon: 'wave'  },
    { to: '/networth', label: 'Net worth', icon: 'spark' },
    { to: '/settings', label: 'Settings',  icon: 'cog'   },
  ]
  return (
    <aside className="sidebar">
      <nav>
        {items.map(it => (
          <NavLink key={it.to} to={it.to} end={it.to === '/'}
            className={({ isActive }) => `navitem ${isActive ? 'active' : ''}`}
          >
            <Icon name={it.icon} />
            <span>{it.label}</span>
            {it.badge ? <span className="badge">{it.badge}</span> : null}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}

const ROUTE_TITLES = {
  '/':         'Dashboard',
  '/inbox':    'Inbox',
  '/goals':    'Goals',
  '/planner':  'Planner',
  '/cashflow': 'Cash flow',
  '/networth': 'Net worth',
  '/settings': 'Settings',
  '/quick-add':'Quick add',
}

function Topbar({ month, setMonth, unassigned }) {
  const { pathname } = useLocation()
  const nav = useNavigate()
  const title = ROUTE_TITLES[pathname] || (pathname.startsWith('/funds/') ? 'Fund' : 'Ledger')
  const isCurrent = month === thisMonth()

  return (
    <div className="topbar">
      <div className="crumb">{title}</div>
      <div className="spacer" />
      {unassigned !== null && <UnassignedChip value={unassigned} />}
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
      <button className="iconbtn primary" title="Quick add (n)" onClick={() => nav('/quick-add')}>
        <Icon name="plus" />
      </button>
    </div>
  )
}

function UnassignedChip({ value }) {
  const n = Number(value)
  const tone = Math.abs(n) < 0.01 ? 'zero' : n > 0 ? 'pos' : 'neg'
  const label = tone === 'zero' ? 'Fully assigned' : tone === 'pos' ? 'Unassigned' : 'Overbudget'
  return (
    <div className={`uchip ${tone}`}>
      <span className="dot" />
      <span style={{ color: 'var(--text-dim)' }}>{label}</span>
      <span className="amt">{fmt(n)}</span>
    </div>
  )
}
