import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderApp, fund, shellRoutes, SHELL_KEYS } from '../test/renderApp'
import { ApiError, keys } from '../resource'
import { api } from '../api'

const ACCOUNTS = [
  { id: 1, name: 'Everyday checking', type: 'checking', current_balance: '2200.00', last_synced_at: null, plaid_account_id: null },
  { id: 2, name: 'Ally savings', type: 'savings', current_balance: '2000.00', last_synced_at: null, plaid_account_id: null },
]

const FUNDS = [
  fund({ id: 4, name: 'Emergency fund', kind: 'goal', goal_type: 'savings', balance: '2000.00', backed_by_account_id: 2 }),
]

const ITEMS = [
  { id: 1, item_id: 'wv6zx9abcdef0123', institution_name: 'Chase', accounts: [] },
]

function routes(overrides = {}) {
  return {
    ...shellRoutes(),
    [keys.accounts()]: ACCOUNTS,
    [keys.funds()]: FUNDS,
    [keys.plaidItems()]: ITEMS,
    ...overrides,
  }
}

afterEach(() => vi.restoreAllMocks())

describe('Settings', () => {
  it('renders accounts, their goals, and the linked institutions', async () => {
    renderApp(routes(), { route: '/settings' })

    expect(await screen.findByText('Everyday checking')).toBeTruthy()
    expect(screen.getByText('Ally savings')).toBeTruthy()
    // Ally backs the emergency fund exactly, so it reconciles.
    expect(screen.getByText('✓ reconciled')).toBeTruthy()
    expect(await screen.findByText('Chase')).toBeTruthy()
    expect(screen.getByText('1 / 10 trial Items used')).toBeTruthy()
  })

  it('keeps the Plaid item id as text rather than coercing it to a number', async () => {
    renderApp(routes({
      [keys.plaidItems()]: [{ ...ITEMS[0], item_id: '90210111213141516' }],
    }), { route: '/settings' })

    // A digits-only opaque token must survive the decimal coercion intact.
    expect(await screen.findByText('item 902101112131…')).toBeTruthy()
  })

  it('reads accounts, funds and Plaid items, on top of the shell’s', async () => {
    const { adapter } = renderApp(routes(), { route: '/settings' })

    await screen.findByText('Chase')
    const own = adapter.requested.filter(k => !SHELL_KEYS.includes(k))
    expect([...new Set(own)].sort()).toEqual([keys.accounts(), keys.funds(), keys.plaidItems()].sort())
  })

  it('refetches the accounts once when a balance is edited', async () => {
    vi.spyOn(api.accounts, 'update').mockResolvedValue({})
    const { adapter } = renderApp(routes(), { route: '/settings' })

    await screen.findByText('Everyday checking')
    const before = adapter.requested.filter(k => k === keys.accounts()).length

    fireEvent.click(screen.getByText('$2,200.00'))
    const input = screen.getByDisplayValue('2200')
    fireEvent.change(input, { target: { value: '2500' } })
    fireEvent.blur(input)

    await waitFor(() => expect(api.accounts.update).toHaveBeenCalledWith(1, { current_balance: 2500 }))
    await waitFor(() => {
      expect(adapter.requested.filter(k => k === keys.accounts()).length).toBe(before + 1)
    })
  })

  it('explains the missing credentials rather than reporting a failure', async () => {
    renderApp(routes({
      [keys.plaidItems()]: new ApiError(400, { detail: 'Plaid credentials not configured' }, keys.plaidItems()),
    }), { route: '/settings' })

    expect(await screen.findByText(/Plaid credentials not configured\. Add/)).toBeTruthy()
  })

  it('shows the server message when the accounts read fails', async () => {
    renderApp(routes({
      [keys.accounts()]: new ApiError(503, { detail: 'Database is asleep' }, keys.accounts()),
    }), { route: '/settings' })

    expect(await screen.findByText('Database is asleep')).toBeTruthy()
  })
})
