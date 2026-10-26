import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderApp, fund, shellRoutes, SHELL_KEYS } from '../test/renderApp'
import { ApiError, keys } from '../resource'
import { api } from '../api'

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

const DINING = fund({ id: 8, name: 'Dining', category: 'Food' })

function routes(overrides = {}) {
  return {
    ...shellRoutes(),
    [keys.fund('7')]: GROCERIES,
    [keys.fundTransactions('7')]: TXNS,
    [keys.funds()]: [GROCERIES, DINING],
    ...overrides,
  }
}

afterEach(() => vi.restoreAllMocks())

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

  it('reads exactly the keys it needs, on top of the shell’s', async () => {
    const { adapter } = renderApp(routes(), { route: '/funds/7' })

    await screen.findByRole('heading', { name: 'Groceries' })
    const own = adapter.requested.filter(k => !SHELL_KEYS.includes(k))
    // The fund, its history, the fund list that feeds the "move to" picker, and
    // the category list behind the category picker.
    expect([...new Set(own)].sort()).toEqual(
      [keys.fund('7'), keys.fundTransactions('7'), keys.funds(), keys.categories()].sort(),
    )
  })

  it('moves a transaction to another fund via the picker', async () => {
    vi.spyOn(api.transactions, 'move').mockResolvedValue({})
    renderApp(routes(), { route: '/funds/7' })

    // The expense is movable; its picker offers the other fund but not this one.
    const select = await screen.findByRole('combobox', {
      name: /Move transaction Trader Joes/,
    })
    const options = [...select.options].map(o => o.textContent)
    expect(options).toEqual(['Move to…', 'Dining'])

    fireEvent.change(select, { target: { value: '8' } })

    await waitFor(() => expect(api.transactions.move).toHaveBeenCalledWith(102, 8))
  })

  it('does not offer a move picker on an assignment row', async () => {
    renderApp(routes(), { route: '/funds/7' })

    await screen.findByRole('heading', { name: 'Groceries' })
    // The +500 assignment leg is double-entry — no move picker on it, so the only
    // move picker on the page is the expense's. The category picker is labelled
    // "Category" and is not a move picker, so it is not counted.
    const movePickers = screen
      .getAllByRole('combobox')
      .filter(el => el.getAttribute('aria-label') !== 'Category')
    expect(movePickers.length).toBe(1)
  })

  it('surfaces the server message when a move is rejected', async () => {
    vi.spyOn(api.transactions, 'move').mockRejectedValue(
      new ApiError(400, { detail: 'destination fund does not exist or is archived' }, 'move'),
    )
    renderApp(routes(), { route: '/funds/7' })

    const select = await screen.findByRole('combobox', {
      name: /Move transaction Trader Joes/,
    })
    fireEvent.change(select, { target: { value: '8' } })

    expect(
      await screen.findByText('destination fund does not exist or is archived'),
    ).toBeTruthy()
  })

  it('shows the server message when the fund is missing', async () => {
    renderApp(routes({
      [keys.fund('7')]: new ApiError(404, { detail: 'Fund not found' }, keys.fund('7')),
    }), { route: '/funds/7' })

    expect(await screen.findByText('Fund not found')).toBeTruthy()
  })
})
