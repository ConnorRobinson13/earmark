import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderApp, fund, emptyDashboard, shellRoutes, SHELL_KEYS } from '../test/renderApp'
import { ApiError, keys } from '../resource'
import { thisMonth, shiftMonth } from '../components/MonthSelector'
import { api } from '../api'

const MONTH = thisMonth()

const FUNDS = [
  fund({ id: 1, name: 'Rent', category: 'Housing', assigned_this_month: '1800.00', balance: '0.00' }),
  fund({ id: 2, name: 'Groceries', category: 'Food', assigned_this_month: '200.00', balance: '87.65' }),
]

const TEMPLATE = [{ fund_id: 1, planned_amount: '1800.00' }]

function routes(overrides = {}) {
  return {
    ...shellRoutes({ dashboard: emptyDashboard({ unassigned: '500.00', funds: FUNDS }) }),
    [keys.templates()]: TEMPLATE,
    ...overrides,
  }
}

afterEach(() => vi.restoreAllMocks())

describe('Planner', () => {
  it('projects against the dashboard and the saved template', async () => {
    renderApp(routes(), { route: '/planner' })

    // Rent's 1800 is already assigned, so the template has nothing left to
    // take: 500 unassigned stays 500.
    expect(await screen.findByText('$500.00 still to assign')).toBeTruthy()
    expect(screen.getAllByText('Groceries').length).toBeGreaterThan(0)  // untemplated → flex
    expect(screen.getByText(/Planned total/)).toBeTruthy()
  })

  it('reads the dashboard and the template, and nothing else', async () => {
    const { adapter } = renderApp(routes(), { route: '/planner' })

    await screen.findByText(/Planned total/)
    const own = adapter.requested.filter(k => !SHELL_KEYS.includes(k))
    expect([...new Set(own)]).toEqual([keys.templates()])
  })

  it('applies the template to the month in the top bar, not to today', async () => {
    const previous = shiftMonth(MONTH, -1)
    vi.spyOn(api.templates, 'apply').mockResolvedValue({})
    renderApp(routes({
      [keys.dashboard(previous)]: emptyDashboard({ month: previous, unassigned: '10.00', funds: FUNDS }),
    }), { route: '/planner' })

    await screen.findByText('$500.00 still to assign')
    fireEvent.click(screen.getByLabelText('Previous month'))
    await screen.findByText('$10.00 still to assign')

    fireEvent.click(screen.getByRole('button', { name: 'Apply template' }))
    await waitFor(() => expect(api.templates.apply).toHaveBeenCalledWith(previous))
  })

  it('refetches on the new key when the month changes', async () => {
    const previous = shiftMonth(MONTH, -1)
    const { adapter } = renderApp(routes({
      [keys.dashboard(previous)]: emptyDashboard({ month: previous, unassigned: '10.00', funds: FUNDS }),
    }), { route: '/planner' })

    await screen.findByText('$500.00 still to assign')
    fireEvent.click(screen.getByLabelText('Previous month'))

    await screen.findByText('$10.00 still to assign')
    expect(adapter.requested).toContain(keys.dashboard(previous))
  })

  it('shows the server message when the template read fails', async () => {
    renderApp(routes({
      [keys.templates()]: new ApiError(500, { detail: 'templates unavailable' }, keys.templates()),
    }), { route: '/planner' })

    expect(await screen.findByText('templates unavailable')).toBeTruthy()
  })
})
