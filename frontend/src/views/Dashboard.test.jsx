import { describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderApp, fund } from '../test/renderApp'
import { ApiError, keys } from '../resource'
import { thisMonth, shiftMonth } from '../components/MonthSelector'

const MONTH = thisMonth()

const FUNDS = [
  fund({ id: 1, name: 'Groceries', category: 'Food', balance: '87.65', net_spent_this_month: '412.35', assigned_this_month: '500.00', available_this_month: '500.00' }),
  fund({ id: 2, name: 'Eating out', category: 'Food', balance: '20.00', net_spent_this_month: '100.00', assigned_this_month: '120.00', available_this_month: '120.00' }),
  fund({ id: 3, name: 'Rent', category: 'Housing', balance: '0.00', net_spent_this_month: '1800.00', assigned_this_month: '1800.00', available_this_month: '1800.00' }),
  // A fund and category whose names are all digits: the dashboard sorts
  // categories with localeCompare, which a number does not have.
  fund({ id: 6, name: '529', category: '529', balance: '75.00', net_spent_this_month: '0.00', assigned_this_month: '50.00', available_this_month: '50.00' }),
  fund({ id: 4, name: 'Emergency fund', kind: 'goal', goal_type: 'savings', category: null, target: '10000.00', balance: '2000.00', assigned_this_month: '250.00' }),
  fund({ id: 5, name: 'New laptop', kind: 'goal', goal_type: 'savings', category: null, target: '2000.00', balance: '500.00', assigned_this_month: '100.00' }),
]

const DASHBOARD = {
  liquid_total: '4200.00',
  credit_owed: '350.00',
  net_cash: '3850.00',
  unassigned: '120.50',
  funds_total: '2607.65',
  spent_this_month: '2312.35',
  saved_this_month: '350.00',
  income_this_month: '3000.00',
  planned_income: '3200.00',
  month: MONTH,
  funds: FUNDS,
}

const INBOX = [
  { id: 11, merchant: 'Trader Joes', amount: '43.10', date: '2026-08-01', suggested_fund_id: 1, status: 'pending', created_at: '2026-08-01T10:00:00' },
]

const ACCOUNTS = [
  { id: 1, name: 'Everyday checking', type: 'checking', current_balance: '2200.00', last_synced_at: null },
]

const PENDING = [
  { goal_id: 4, goal_name: 'Emergency fund', pending_amount: '250.00', to_account_id: null, to_account_name: 'Ally savings', suggested_from_account_id: 1 },
]

function routes(overrides = {}) {
  return {
    [keys.dashboard(MONTH)]: DASHBOARD,
    [keys.inbox()]: INBOX,
    [keys.accounts()]: ACCOUNTS,
    [keys.pendingSettlements(MONTH)]: PENDING,
    [keys.dashboardTrends(6)]: { months: [], categories: [] },
    ...overrides,
  }
}

describe('Dashboard', () => {
  it('renders against a stub adapter with no backend running', async () => {
    renderApp(routes())

    await screen.findAllByText('$120.50')
    expect(screen.getByText('Money to assign. Zero-based means every dollar should land in a fund before the month is out.')).toBeTruthy()
    expect(screen.getByText('Groceries')).toBeTruthy()
    expect(screen.getByText('Rent')).toBeTruthy()
    // Fund name and category heading, both still text rather than numbers.
    expect(screen.getAllByText('529').length).toBe(2)
    expect(screen.getAllByText('Emergency fund').length).toBeGreaterThan(0)
    // The to-move panel is fed by its own key and renders alongside.
    expect(await screen.findByText('Ally savings')).toBeTruthy()
  })

  it('does the arithmetic on numbers, not on decimal strings', async () => {
    renderApp(routes())

    // Food spent = 412.35 + 100.00. Summing the raw strings would concatenate
    // them into nonsense, so this only passes if coercion happened at the edge.
    expect(await screen.findByText('$512.35')).toBeTruthy()
    expect(screen.getByText('$620.00')).toBeTruthy()   // Food assigned
    // Goals progress: min-capped 2000 + 500 over targets 10000 + 2000 = 21%.
    expect(screen.getByText('21%')).toBeTruthy()
    expect(screen.getByText(/2 active · \$2,500\.00 saved/)).toBeTruthy()
  })

  it('reads every key through the resource module', async () => {
    const { adapter } = renderApp(routes())

    // The panels below the fold only mount once the dashboard read lands, so
    // wait for the whole tree rather than the hero alone.
    await screen.findByText('Ally savings')
    await waitFor(() => expect(adapter.requested).toEqual(expect.arrayContaining([
      keys.dashboard(MONTH),
      keys.inbox(),
      keys.accounts(),
      keys.pendingSettlements(MONTH),
      keys.dashboardTrends(6),
    ])))
  })

  it('feeds the shell topbar chip and the inbox count', async () => {
    renderApp(routes())

    // The unassigned figure shows twice: hero and topbar chip.
    await waitFor(() => expect(screen.getAllByText('$120.50').length).toBe(2))
    expect(screen.getByText('transaction')).toBeTruthy()
  })

  it('refetches on the new key when the month changes', async () => {
    const previous = shiftMonth(MONTH, -1)
    const { adapter } = renderApp(routes({
      [keys.dashboard(previous)]: { ...DASHBOARD, unassigned: '99.00', month: previous, funds: [] },
      [keys.pendingSettlements(previous)]: [],
    }))

    await screen.findAllByText('$120.50')
    fireEvent.click(screen.getByLabelText('Previous month'))

    await waitFor(() => expect(screen.getAllByText('$99.00').length).toBe(2))
    expect(adapter.requested).toContain(keys.dashboard(previous))
  })

  it('shows the server message when the dashboard read fails', async () => {
    renderApp(routes({
      [keys.dashboard(MONTH)]: new ApiError(503, { detail: 'Database is asleep' }, keys.dashboard(MONTH)),
    }))

    expect(await screen.findByText('Database is asleep')).toBeTruthy()
  })

  it('keeps rendering when only the optional reads fail', async () => {
    renderApp(routes({
      [keys.inbox()]: new ApiError(500, { detail: 'inbox down' }, keys.inbox()),
      [keys.accounts()]: new ApiError(500, { detail: 'accounts down' }, keys.accounts()),
    }))

    await screen.findAllByText('$120.50')
    expect(screen.getByText('transactions')).toBeTruthy()
  })
})
