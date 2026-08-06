import { describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderApp, emptyDashboard, shellRoutes } from './test/renderApp'
import { keys } from './resource'
import { thisMonth, shiftMonth } from './components/MonthSelector'

const MONTH = thisMonth()

const INBOX = [
  { id: 11, merchant: 'Trader Joes', amount: '43.10', date: '2026-08-01', suggested_fund_id: null, status: 'pending', created_at: '2026-08-01T10:00:00' },
  { id: 12, merchant: 'Shell', amount: '52.00', date: '2026-08-02', suggested_fund_id: null, status: 'pending', created_at: '2026-08-02T10:00:00' },
]

function routes(overrides = {}) {
  return {
    ...shellRoutes({ inbox: INBOX, dashboard: emptyDashboard({ unassigned: '120.50' }) }),
    [keys.accounts()]: [],
    [keys.funds()]: [],
    ...overrides,
  }
}

const chip = () => document.querySelector('.uchip .amt')?.textContent ?? null

describe('Shell', () => {
  it('shows the unassigned chip on a route that is not the dashboard', async () => {
    renderApp(routes(), { route: '/goals' })

    // It used to be hidden everywhere but the dashboard, because only the
    // dashboard fed it.
    await waitFor(() => expect(chip()).toBe('$120.50'))
  })

  it('fills the nav badge before any view has mounted that reads the inbox', async () => {
    renderApp(routes(), { route: '/settings' })

    await waitFor(() => expect(document.querySelector('.dock .badge').textContent).toBe('2'))
  })

  it('moves the chip to the newly selected month', async () => {
    const previous = shiftMonth(MONTH, -1)
    renderApp(routes({
      [keys.dashboard(previous)]: emptyDashboard({ month: previous, unassigned: '99.00' }),
    }), { route: '/goals' })

    await waitFor(() => expect(chip()).toBe('$120.50'))
    fireEvent.click(screen.getByLabelText('Previous month'))

    await waitFor(() => expect(chip()).toBe('$99.00'))
  })

  it('leaves the chip off when the dashboard read fails, without breaking the page', async () => {
    const withoutDashboard = routes()
    delete withoutDashboard[keys.dashboard(MONTH)]
    renderApp(withoutDashboard, { route: '/settings' })

    expect(await screen.findByText('Accounts')).toBeTruthy()
    expect(chip()).toBe(null)
  })
})
