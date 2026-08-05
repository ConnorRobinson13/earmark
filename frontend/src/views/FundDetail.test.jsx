import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { renderApp, fund, shellRoutes, SHELL_KEYS } from '../test/renderApp'
import { ApiError, keys } from '../resource'

const GROCERIES = fund({
  id: 7,
  name: 'Groceries',
  category: 'Food',
  balance: '87.65',
  net_spent_this_month: '412.35',
  assigned_this_month: '500.00',
  available_this_month: '500.00',
})

const TXNS = [
  { id: 101, type: 'assignment', amount: '500.00', date: '2026-08-01', merchant: '', notes: null, fund_id: 7, linked_transaction_id: null, plaid_transaction_id: null, created_at: '2026-08-01T09:00:00' },
  { id: 102, type: 'expense', amount: '-412.35', date: '2026-08-03', merchant: 'Trader Joes', notes: 'weekly shop', fund_id: 7, linked_transaction_id: null, plaid_transaction_id: null, created_at: '2026-08-03T18:00:00' },
]

function routes(overrides = {}) {
  return {
    ...shellRoutes(),
    [keys.fund('7')]: GROCERIES,
    [keys.fundTransactions('7')]: TXNS,
    ...overrides,
  }
}

describe('FundDetail', () => {
  it('renders against a stub adapter with no backend running', async () => {
    renderApp(routes(), { route: '/funds/7' })

    expect(await screen.findByRole('heading', { name: 'Groceries' })).toBeTruthy()
    expect(screen.getByText('$87.65')).toBeTruthy()    // balance
    expect(screen.getAllByText('$500.00').length).toBe(2)  // assigned + available
    expect(screen.getByText('$412.35')).toBeTruthy()   // spent this month
    expect(screen.getByText('Trader Joes')).toBeTruthy()
    expect(screen.getByText('weekly shop')).toBeTruthy()
    expect(screen.getByText('2 transactions')).toBeTruthy()
  })

  it('renders inflows and outflows with the right sign', async () => {
    renderApp(routes(), { route: '/funds/7' })

    expect(await screen.findByText('+$500.00')).toBeTruthy()
    expect(screen.getByText('-$412.35')).toBeTruthy()
  })

  it('reads exactly the two keys it needs, on top of the shell’s', async () => {
    const { adapter } = renderApp(routes(), { route: '/funds/7' })

    await screen.findByRole('heading', { name: 'Groceries' })
    const own = adapter.requested.filter(k => !SHELL_KEYS.includes(k))
    expect(own.sort()).toEqual([keys.fund('7'), keys.fundTransactions('7')].sort())
  })

  it('shows the server message when the fund is missing', async () => {
    renderApp(routes({
      [keys.fund('7')]: new ApiError(404, { detail: 'Fund not found' }, keys.fund('7')),
    }), { route: '/funds/7' })

    expect(await screen.findByText('Fund not found')).toBeTruthy()
  })
})
