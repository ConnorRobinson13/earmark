import { NavLink, Route, Routes, Navigate } from 'react-router-dom'
import Dashboard from './views/Dashboard'
import QuickAdd from './views/QuickAdd'
import Inbox from './views/Inbox'
import Goals from './views/Goals'
import Planner from './views/Planner'
import FundDetail from './views/FundDetail'
import Settings from './views/Settings'

export default function App() {
  return (
    <>
      <div className="app">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/funds/:id" element={<FundDetail />} />
          <Route path="/quick-add" element={<QuickAdd />} />
          <Route path="/inbox" element={<Inbox />} />
          <Route path="/goals" element={<Goals />} />
          <Route path="/planner" element={<Planner />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
      <Nav />
    </>
  )
}

function Nav() {
  const item = (to, icon, label) => (
    <NavLink to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'active' : '')}>
      <span className="icon">{icon}</span>
      {label}
    </NavLink>
  )
  return (
    <nav className="nav">
      {item('/', '◉', 'Home')}
      {item('/quick-add', '+', 'Add')}
      {item('/inbox', '⌧', 'Inbox')}
      {item('/goals', '◆', 'Goals')}
      {item('/planner', '▤', 'Plan')}
      {item('/settings', '⚙', 'More')}
    </nav>
  )
}
