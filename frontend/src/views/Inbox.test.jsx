import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderApp, fund, shellRoutes, SHELL_KEYS } from '../test/renderApp'
import { ApiError, keys } from '../resource'
import { api } from '../api'

const FUNDS = [
  fund({ id: 1, name: 'Groceries', category: 'Food' }),
  fund({ id: 2, name: 'Eating out', category: 'Food' }),
]

function item(overrides) {
  return {
    id: 11,
    merchant: 'Trader Joes',
    amount: '43.10',
    date: '2026-08-01',
    suggested_fund_id: 1,
    status: 'pending',
    created_at: '2026-08-01T10:00:00',
    ...overrides,
  }
}

const ITEMS = [item({ id: 11, merchant: 'Trader Joes' }), item({ id: 12, merchant: 'Shell' })]

function routes(overrides = {}) {
  return {
    ...shellRoutes(),
    [keys.inbox()]: ITEMS,
    [keys.funds()]: FUNDS,
    ...overrides,
  }
}

/** The nav dock's inbox badge, or null when there is nothing to review. */
function badge() {
  return document.querySelector('.dock .badge')?.textContent ?? null
}

afterEach(() => vi.restoreAllMocks())

describe('Inbox', () => {
  it('renders the first pending item against a stub adapter', async () => {
    renderApp(routes(), { route: '/inbox' })

    expect(await screen.findByText('Trader Joes')).toBeTruthy()
    expect(screen.getByText('1 / 2')).toBeTruthy()
    // The suggested fund is named, and every fund is offered as an override.
    expect(screen.getAllByText('Groceries').length).toBe(2)
    expect(screen.getByText('Eating out')).toBeTruthy()
  })

  it('shares the shell’s inbox read instead of issuing its own', async () => {
    const { adapter } = renderApp(routes(), { route: '/inbox' })

    await screen.findByText('Trader Joes')
    // Two readers of `/inbox` — the nav badge and this view — one round trip,
    // because both spell the key the same way.
    expect(adapter.requested.filter(k => k === keys.inbox()).length).toBe(1)
    const own = adapter.requested.filter(k => !SHELL_KEYS.includes(k))
    expect([...new Set(own)]).toEqual([keys.funds()])
  })

  it('drops the nav badge when an item is approved, with no dashboard mounted', async () => {
    // The list the stub serves shrinks once the approval goes through, the way
    // the backend's would.
    let pending = ITEMS
    vi.spyOn(api.inbox, 'approve').mockImplementation(async () => {
      pending = [ITEMS[1]]
      return {}
    })
    renderApp(routes({ [keys.inbox()]: () => pending }), { route: '/inbox' })

    await screen.findByText('Trader Joes')
    await waitFor(() => expect(badge()).toBe('2'))

    fireEvent.click(screen.getByRole('button', { name: /Approve/ }))

    // The badge is the inbox's own read — nothing pushed it here, and the
    // dashboard never mounted.
    await waitFor(() => expect(badge()).toBe('1'))
    expect(api.inbox.approve).toHaveBeenCalledWith(11, 1, false)
    expect(await screen.findByText('Shell')).toBeTruthy()
  })

  it('does not fetch the inbox twice for one approval', async () => {
    vi.spyOn(api.inbox, 'approve').mockResolvedValue({})
    const { adapter } = renderApp(routes(), { route: '/inbox' })

    await screen.findByText('Trader Joes')
    const before = adapter.requested.filter(k => k === keys.inbox()).length

    fireEvent.click(screen.getByRole('button', { name: /Approve/ }))

    await waitFor(() => expect(api.inbox.approve).toHaveBeenCalled())
    await waitFor(() => {
      expect(adapter.requested.filter(k => k === keys.inbox()).length).toBe(before + 1)
    })
  })

  it('says so when the inbox read fails', async () => {
    renderApp(routes({
      [keys.inbox()]: new ApiError(503, { detail: 'Database is asleep' }, keys.inbox()),
    }), { route: '/inbox' })

    expect(await screen.findByText('Database is asleep')).toBeTruthy()
  })

  it('shows the caught-up card when nothing is pending', async () => {
    renderApp(routes({ [keys.inbox()]: [] }), { route: '/inbox' })

    expect(await screen.findByText('All caught up')).toBeTruthy()
    expect(badge()).toBe(null)
  })
})
