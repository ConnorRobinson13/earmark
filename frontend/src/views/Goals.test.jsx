import { describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderApp, fund, emptyDashboard, shellRoutes, SHELL_KEYS } from '../test/renderApp'
import { ApiError, keys } from '../resource'
import { thisMonth, shiftMonth } from '../components/MonthSelector'

const MONTH = thisMonth()

const GOALS = [
  fund({
    id: 4, name: 'Emergency fund', kind: 'goal', goal_type: 'savings', category: null,
    target: '10000.00', balance: '2000.00', assigned_this_month: '250.00',
    backed_by_account_id: 1,
  }),
  fund({
    id: 5, name: 'Car loan', kind: 'goal', goal_type: 'debt', category: null,
    target: '22000.00', balance: '4000.00', min_payment: '531.00', target_date: '2029-06-30',
  }),
]

const OPERATIONAL = fund({ id: 1, name: 'Groceries', category: 'Food', balance: '87.65' })

const ACCOUNTS = [
  { id: 1, name: 'Ally savings', type: 'savings', current_balance: '2000.00', last_synced_at: null },
]

function routes(overrides = {}) {
  return {
    ...shellRoutes({
      dashboard: emptyDashboard({ unassigned: '120.50', funds: [OPERATIONAL, ...GOALS] }),
    }),
    [keys.accounts()]: ACCOUNTS,
    ...overrides,
  }
}

describe('Goals', () => {
  it('renders the goals from the dashboard read, skipping operational funds', async () => {
    renderApp(routes(), { route: '/goals' })

    expect(await screen.findByText('Emergency fund')).toBeTruthy()
    expect(screen.getByText('Car loan')).toBeTruthy()
    expect(screen.queryByText('Groceries')).toBe(null)
    // 2000 of 10000 saved, 4000 of 22000 paid off.
    expect(screen.getByText('20% complete')).toBeTruthy()
    expect(screen.getByText('18% paid off')).toBeTruthy()
  })

  it('shows the debt’s own monthly payment rather than estimating one', async () => {
    renderApp(routes(), { route: '/goals' })

    await screen.findByText('Car loan')
    expect(screen.getByText('$531.00')).toBeTruthy()
    expect(screen.queryByText(/to pay off on time/)).toBe(null)
  })

  it('needs no fund list of its own — the dashboard read carries the funds', async () => {
    const { adapter } = renderApp(routes(), { route: '/goals' })

    await screen.findByText('Emergency fund')
    const own = adapter.requested.filter(k => !SHELL_KEYS.includes(k))
    expect([...new Set(own)]).toEqual([keys.accounts()])
  })

  it('follows the top-bar month', async () => {
    const previous = shiftMonth(MONTH, -1)
    const { adapter } = renderApp(routes({
      [keys.dashboard(previous)]: emptyDashboard({
        month: previous,
        funds: [fund({ id: 4, name: 'Emergency fund', kind: 'goal', goal_type: 'savings', target: '10000.00', balance: '1000.00' })],
      }),
    }), { route: '/goals' })

    await screen.findByText('20% complete')
    fireEvent.click(screen.getByLabelText('Previous month'))

    await screen.findByText('10% complete')
    expect(adapter.requested).toContain(keys.dashboard(previous))
  })

  it('shows the server message when the read fails', async () => {
    renderApp(routes({
      [keys.dashboard(MONTH)]: new ApiError(503, { detail: 'Database is asleep' }, keys.dashboard(MONTH)),
    }), { route: '/goals' })

    expect(await screen.findByText('Database is asleep')).toBeTruthy()
  })

  it('keeps rendering when only the accounts read fails', async () => {
    renderApp(routes({
      [keys.accounts()]: new ApiError(500, { detail: 'accounts down' }, keys.accounts()),
    }), { route: '/goals' })

    await screen.findByText('Emergency fund')
    await waitFor(() => expect(screen.getByText('No specific account')).toBeTruthy())
  })
})
