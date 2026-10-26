import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { renderApp, fund, shellRoutes, SHELL_KEYS } from '../test/renderApp'
import { ApiError, keys } from '../resource'
import { api } from '../api'

const plaidLinkMock = vi.hoisted(() => ({ openCalls: 0, lastOptions: null }))
vi.mock('react-plaid-link', () => ({
  usePlaidLink: (options) => ({
    open: () => {
      plaidLinkMock.openCalls += 1
      plaidLinkMock.lastOptions = options
    },
    ready: true,
  }),
}))

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

afterEach(() => {
  vi.restoreAllMocks()
  plaidLinkMock.openCalls = 0
  plaidLinkMock.lastOptions = null
})

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

  it('shows reconnect from the live Plaid Item status on page load', async () => {
    renderApp(routes({
      [keys.plaidItems()]: [{
        ...ITEMS[0],
        error_code: 'ITEM_LOGIN_REQUIRED',
        needs_reauthentication: true,
      }],
    }), { route: '/settings' })

    expect(await screen.findByRole('button', { name: 'Reconnect Chase' })).toBeTruthy()
  })

  it('distinguishes an unavailable status probe from a healthy Item', async () => {
    renderApp(routes({
      [keys.plaidItems()]: [{ ...ITEMS[0], status_available: false }],
    }), { route: '/settings' })

    expect(await screen.findByText('Plaid connection status is temporarily unavailable. Try syncing again.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Reconnect Chase' })).toBeNull()
  })

  it('does not recommend retrying a permanently invalid Plaid item', async () => {
    renderApp(routes({
      [keys.plaidItems()]: [{
        ...ITEMS[0],
        error_code: 'INVALID_ACCESS_TOKEN',
        needs_reauthentication: false,
        status_available: true,
      }],
    }), { route: '/settings' })

    expect(await screen.findByText(
      'Plaid says this link is invalid (INVALID_ACCESS_TOKEN). Review it before unlinking or reconnecting.',
    )).toBeTruthy()
    expect(screen.queryByText(/Try again later/)).toBeNull()
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
    expect([...new Set(own)].sort()).toEqual(
      [keys.accounts(), keys.funds(), keys.categories(), keys.plaidItems()].sort(),
    )
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

  it('explains missing credentials reported by the link-token endpoint', async () => {
    vi.spyOn(api.plaid, 'linkToken').mockRejectedValue(
      new ApiError(400, {
        detail: {
          code: 'PLAID_CREDENTIALS_NOT_CONFIGURED',
          message: 'Plaid credentials not configured',
        },
      }, '/plaid/link-token'),
    )
    renderApp(routes(), { route: '/settings' })

    expect(await screen.findByText(/Plaid credentials not configured\. Add/)).toBeTruthy()
  })

  it('shows the server message when the accounts read fails', async () => {
    renderApp(routes({
      [keys.accounts()]: new ApiError(503, { detail: 'Database is asleep' }, keys.accounts()),
    }), { route: '/settings' })

    expect(await screen.findByText('Database is asleep')).toBeTruthy()
  })

  it('offers Plaid update mode for an item that requires login', async () => {
    vi.spyOn(api.plaid, 'sync')
      .mockResolvedValueOnce({
        added: 0,
        issues: [{
          id: 1,
          institution_name: 'Chase',
          error_code: 'ITEM_LOGIN_REQUIRED',
          needs_reauthentication: true,
        }],
      })
      .mockResolvedValueOnce({ added: 2, issues: [] })
    vi.spyOn(api.plaid, 'updateLinkToken').mockResolvedValue({ link_token: 'update-token' })

    renderApp(routes(), { route: '/settings' })
    await screen.findByText('Chase')

    fireEvent.click(screen.getByRole('button', { name: 'Sync now' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Reconnect Chase' }))

    await waitFor(() => {
      expect(api.plaid.updateLinkToken).toHaveBeenCalledWith(1)
      expect(plaidLinkMock.openCalls).toBe(1)
    })
    await act(async () => {
      await plaidLinkMock.lastOptions.onSuccess?.(null, {})
    })
    await waitFor(() => expect(api.plaid.sync).toHaveBeenCalledTimes(2))
    expect(await screen.findByText(/Reconnected\. Added 2 transactions to inbox/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Reconnect Chase' })).toBeNull()
  })

  it('shows a reconnect error without retrying sync when Link token creation fails', async () => {
    vi.spyOn(api.plaid, 'sync').mockResolvedValue({
      added: 0,
      issues: [{
        id: 1,
        institution_name: 'Chase',
        error_code: 'ITEM_LOGIN_REQUIRED',
        needs_reauthentication: true,
      }],
    })
    vi.spyOn(api.plaid, 'updateLinkToken').mockRejectedValue(new Error('Plaid Link unavailable'))

    renderApp(routes(), { route: '/settings' })
    fireEvent.click(await screen.findByRole('button', { name: 'Sync now' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Reconnect Chase' }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Plaid Link unavailable')
    expect(api.plaid.sync).toHaveBeenCalledTimes(1)
    expect(plaidLinkMock.openCalls).toBe(0)
  })

  it('stops offering update mode when Plaid says the Item is invalid', async () => {
    vi.spyOn(api.plaid, 'sync').mockResolvedValue({
      added: 0,
      issues: [{ id: 1, institution_name: 'Chase', error_code: 'ITEM_LOGIN_REQUIRED', needs_reauthentication: true }],
    })
    vi.spyOn(api.plaid, 'updateLinkToken').mockRejectedValue(new ApiError(502, {
      detail: {
        code: 'PLAID_UPDATE_LINK_FAILED',
        error_code: 'INVALID_ACCESS_TOKEN',
        message: 'Plaid no longer recognizes this linked Item; update mode cannot repair it.',
      },
    }, '/plaid/items/1/update-link-token'))

    renderApp(routes(), { route: '/settings' })
    fireEvent.click(await screen.findByRole('button', { name: 'Sync now' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Reconnect Chase' }))

    expect(await screen.findByText('Plaid cannot repair this Item in update mode. Review it before unlinking or reconnecting.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Reconnect Chase' })).toBeNull()
    expect(api.plaid.sync).toHaveBeenCalledTimes(1)
  })

  it('shows non-login Plaid issues without offering reconnect', async () => {
    vi.spyOn(api.plaid, 'sync').mockResolvedValue({
      added: 0,
      issues: [{
        id: 1,
        institution_name: 'Chase',
        error_code: 'RATE_LIMIT_EXCEEDED',
        needs_reauthentication: false,
      }],
    })

    renderApp(routes(), { route: '/settings' })
    fireEvent.click(await screen.findByRole('button', { name: 'Sync now' }))

    expect(await screen.findByText('Sync issue from Plaid: RATE_LIMIT_EXCEEDED. Try again later.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Reconnect Chase' })).toBeNull()
  })

  it('labels a database sync failure as an application issue, not a Plaid issue', async () => {
    vi.spyOn(api.plaid, 'sync').mockResolvedValue({
      added: 0,
      issues: [{ id: 1, institution_name: 'Chase', error_code: 'DATABASE_ERROR', needs_reauthentication: false }],
    })

    renderApp(routes(), { route: '/settings' })
    fireEvent.click(await screen.findByRole('button', { name: 'Sync now' }))

    expect(await screen.findByText('The app could not save this Item’s sync results. Check the backend logs.')).toBeTruthy()
  })

  it('shows the Plaid Link exit message if reauthentication is cancelled', async () => {
    vi.spyOn(api.plaid, 'sync').mockResolvedValue({
      added: 0,
      issues: [{
        id: 1,
        institution_name: 'Chase',
        error_code: 'ITEM_LOGIN_REQUIRED',
        needs_reauthentication: true,
      }],
    })
    vi.spyOn(api.plaid, 'updateLinkToken').mockResolvedValue({ link_token: 'update-token' })

    renderApp(routes(), { route: '/settings' })
    fireEvent.click(await screen.findByRole('button', { name: 'Sync now' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Reconnect Chase' }))
    await waitFor(() => expect(plaidLinkMock.openCalls).toBe(1))
    await act(async () => {
      plaidLinkMock.lastOptions.onExit({ display_message: 'Sign-in cancelled' })
    })

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Sign-in cancelled')
    expect(api.plaid.sync).toHaveBeenCalledTimes(1)
  })
})
