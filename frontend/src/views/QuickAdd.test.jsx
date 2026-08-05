import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderApp, fund, emptyDashboard, shellRoutes, SHELL_KEYS } from '../test/renderApp'
import { keys } from '../resource'
import { thisMonth, shiftMonth } from '../components/MonthSelector'
import { api, todayISO } from '../api'

const MONTH = thisMonth()

const FUNDS = [
  fund({ id: 1, name: 'Groceries', category: 'Food' }),
  fund({ id: 2, name: 'Eating out', category: 'Food' }),
]

function routes(overrides = {}) {
  return {
    ...shellRoutes(),
    [keys.funds()]: FUNDS,
    ...overrides,
  }
}

afterEach(() => vi.restoreAllMocks())

describe('QuickAdd', () => {
  it('offers the funds from the resource module', async () => {
    const { adapter } = renderApp(routes(), { route: '/quick-add' })

    expect(await screen.findByText('Groceries')).toBeTruthy()
    expect(screen.getByText('Eating out')).toBeTruthy()
    const own = adapter.requested.filter(k => !SHELL_KEYS.includes(k))
    expect([...new Set(own)]).toEqual([keys.funds()])
  })

  it('dates the transaction today while the current month is selected', async () => {
    vi.spyOn(api.transactions, 'quickAdd').mockResolvedValue({})
    renderApp(routes(), { route: '/quick-add' })

    fireEvent.click(await screen.findByText('Groceries'))
    fireEvent.change(screen.getByPlaceholderText('0.00'), { target: { value: '43.10' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.transactions.quickAdd).toHaveBeenCalledWith(
      expect.objectContaining({ fund_id: 1, amount: 43.1, date: todayISO() }),
    ))
  })

  it('dates it into the month in the top bar when that is an archived one', async () => {
    const previous = shiftMonth(MONTH, -1)
    vi.spyOn(api.transactions, 'quickAdd').mockResolvedValue({})
    // Step back a month on the dashboard first, then open quick add from the
    // top bar — the way you would reach it while looking at an old month.
    renderApp(routes({
      [keys.dashboard(previous)]: emptyDashboard({ month: previous }),
      [keys.accounts()]: [],
      [keys.pendingSettlements(previous)]: [],
      [keys.pendingSettlements(MONTH)]: [],
      [keys.dashboardTrends(6)]: { months: [], categories: [] },
    }), { route: '/' })

    fireEvent.click(await screen.findByLabelText('Previous month'))
    fireEvent.click(screen.getByRole('button', { name: /Quick add/ }))

    fireEvent.click(await screen.findByText('Groceries'))
    fireEvent.change(screen.getByPlaceholderText('0.00'), { target: { value: '20' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.transactions.quickAdd).toHaveBeenCalledWith(
      expect.objectContaining({ date: previous }),
    ))
  })

  it('says so when the fund list fails to load', async () => {
    const withoutFunds = routes()
    delete withoutFunds[keys.funds()]
    renderApp(withoutFunds, { route: '/quick-add' })

    // No stub route at all, so the adapter answers 404 the way a missing
    // endpoint would.
    expect(await screen.findByText(/no stub route/)).toBeTruthy()
  })
})
