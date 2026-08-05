import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { renderApp, fund, emptyDashboard, shellRoutes, SHELL_KEYS } from '../test/renderApp'
import { ApiError, keys } from '../resource'
import { thisMonth } from '../components/MonthSelector'

const MONTH = thisMonth()

const NETWORTH = {
  total: '48250.00',
  liquid: '4200.00',
  investment: '42000.00',
  emergency_fund: '6000.00',
  credit_debt: '350.00',
  loan_debt: '3600.00',
  accounts: [
    { id: 1, name: 'Everyday checking', type: 'checking', balance: '2200.00' },
    { id: 3, name: 'Vanguard', type: 'investment', balance: '42000.00' },
  ],
}

const HISTORY = [
  { month: '2026-06-01', total: '45000.00' },
  { month: '2026-07-01', total: '46500.00' },
  { month: '2026-08-01', total: '48250.00' },
]

// Rent and groceries count toward the runway; the streaming subscription does not.
const DASH_FUNDS = [
  fund({ id: 1, name: 'Rent', category: 'Housing', assigned_this_month: '1800.00' }),
  fund({ id: 2, name: 'Groceries', category: 'Food', assigned_this_month: '600.00' }),
  fund({ id: 3, name: 'Netflix', category: 'Subscriptions', assigned_this_month: '20.00' }),
]

function routes(overrides = {}) {
  return {
    ...shellRoutes({ dashboard: emptyDashboard({ funds: DASH_FUNDS }) }),
    [keys.networth()]: NETWORTH,
    [keys.networthHistory()]: HISTORY,
    ...overrides,
  }
}

describe('NetWorth', () => {
  it('renders the current position against a stub adapter', async () => {
    renderApp(routes(), { route: '/networth' })

    expect(await screen.findByText('$48,250.00')).toBeTruthy()
    expect(screen.getByText('$6,000.00')).toBeTruthy()   // emergency
    expect(screen.getByText('Vanguard')).toBeTruthy()
    expect(screen.getByText(/\$350\.00 in card debt/)).toBeTruthy()
  })

  it('computes the emergency runway from the month in the top bar', async () => {
    renderApp(routes(), { route: '/networth' })

    // 6000 ÷ (1800 rent + 600 groceries) = 2.5 months. Netflix is excluded.
    expect(await screen.findByText(/\$2,400\.00\/mo needs/)).toBeTruthy()
    expect(document.querySelector('.runway-num .big').textContent).toBe('2.5')
  })

  it('asks for the history only after the net-worth read has landed', async () => {
    // Reading /networth is what writes this month's snapshot, so the history
    // has to be asked for second or it comes back a point short.
    let netWorthSettled = false
    let historyAskedBefore = null
    const { adapter } = renderApp(routes({
      [keys.networth()]: () => Promise.resolve().then(() => { netWorthSettled = true; return NETWORTH }),
      [keys.networthHistory()]: () => {
        if (historyAskedBefore === null) historyAskedBefore = !netWorthSettled
        return HISTORY
      },
    }), { route: '/networth' })

    await screen.findByText('$48,250.00')
    await waitFor(() => expect(adapter.requested).toContain(keys.networthHistory()))
    expect(historyAskedBefore).toBe(false)
  })

  it('draws the trend once there are two snapshots', async () => {
    renderApp(routes(), { route: '/networth' })

    expect(await screen.findByText(/since Jun 26/)).toBeTruthy()
    expect(screen.queryByText(/Tracking starts now/)).toBe(null)
  })

  it('explains the empty trend when there is only one snapshot', async () => {
    renderApp(routes({ [keys.networthHistory()]: [HISTORY[0]] }), { route: '/networth' })

    expect(await screen.findByText(/Tracking starts now/)).toBeTruthy()
  })

  it('shows the server message when the net-worth read fails', async () => {
    renderApp(routes({
      [keys.networth()]: new ApiError(503, { detail: 'Database is asleep' }, keys.networth()),
    }), { route: '/networth' })

    expect(await screen.findByText('Database is asleep')).toBeTruthy()
  })

  it('keeps the position standing when only the runway read fails', async () => {
    renderApp(routes({
      [keys.dashboard(MONTH)]: new ApiError(500, { detail: 'dashboard down' }, keys.dashboard(MONTH)),
    }), { route: '/networth' })

    await screen.findByText('$48,250.00')
    expect(screen.queryByText(/months covered/)).toBe(null)
  })

  it('reads three keys, one of them shared with the shell', async () => {
    const { adapter } = renderApp(routes(), { route: '/networth' })

    await screen.findByText(/since Jun 26/)
    const own = adapter.requested.filter(k => !SHELL_KEYS.includes(k))
    expect([...new Set(own)].sort()).toEqual([keys.networth(), keys.networthHistory()].sort())
  })
})
