import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderApp, fund, shellRoutes } from '../test/renderApp'
import { keys } from '../resource'
import { api } from '../api'

const FUNDS = [
  fund({ id: 1, name: 'Groceries', category: 'Food' }),
  fund({ id: 2, name: 'Transport', category: 'Car' }),
]

// An inbox item so the view renders its active card; auto-sort works on pending
// purchases, independent of whichever inbox item is showing.
const ITEMS = [
  { id: 11, merchant: 'Trader Joes', amount: '43.10', date: '2026-08-01', suggested_fund_id: 1, status: 'pending', created_at: '2026-08-01T10:00:00' },
]

const SUGGESTIONS = [
  { inbox_id: 101, merchant: 'Whole Foods', amount: '55.00', date: '2026-07-01', suggested_fund_id: 1, suggested_fund_name: 'Groceries' },
  { inbox_id: 102, merchant: 'Shell', amount: '40.00', date: '2026-07-02', suggested_fund_id: 2, suggested_fund_name: 'Transport' },
]

function routes(overrides = {}) {
  return {
    ...shellRoutes({ inbox: ITEMS }),
    [keys.inbox()]: ITEMS,
    [keys.funds()]: FUNDS,
    [keys.autosortStatus()]: { enabled: true, model: 'test/model' },
    ...overrides,
  }
}

afterEach(() => vi.restoreAllMocks())

describe('Auto-sort review', () => {
  it('disables the action when the server reports the feature off', async () => {
    renderApp(
      routes({ [keys.autosortStatus()]: { enabled: false, model: '' } }),
      { route: '/inbox' },
    )

    // The off-message appears once status lands; its presence is what proves
    // the disabled state is the server's "not configured", not just the
    // pre-status initial render.
    expect(await screen.findByText(/not configured on the server/)).toBeTruthy()
    const btn = screen.getByRole('button', { name: /Auto-sort/ })
    expect(btn.disabled).toBe(true)
  })

  it('fetches suggestions on demand without applying anything', async () => {
    const suggest = vi.spyOn(api.autosort, 'suggestions').mockResolvedValue({ suggestions: SUGGESTIONS })
    const confirm = vi.spyOn(api.autosort, 'confirm').mockResolvedValue({ updated: [] })
    renderApp(routes(), { route: '/inbox' })

    const btn = await screen.findByRole('button', { name: /Auto-sort/ })
    await waitFor(() => expect(btn.disabled).toBe(false))
    fireEvent.click(btn)

    // The proposal is shown for review; nothing is written to get here.
    expect(await screen.findByText('Whole Foods')).toBeTruthy()
    expect(screen.getByText('Shell')).toBeTruthy()
    expect(suggest).toHaveBeenCalledTimes(1)
    expect(confirm).not.toHaveBeenCalled()
  })

  it('applies only the checked rows on confirm', async () => {
    vi.spyOn(api.autosort, 'suggestions').mockResolvedValue({ suggestions: SUGGESTIONS })
    const confirm = vi.spyOn(api.autosort, 'confirm').mockResolvedValue({ updated: [{ id: 101 }] })
    renderApp(routes(), { route: '/inbox' })

    fireEvent.click(await screen.findByRole('button', { name: /Auto-sort/ }))
    await screen.findByText('Whole Foods')

    // Both rows start checked; deselect Shell so only Whole Foods is applied.
    const boxes = screen.getAllByRole('checkbox')
    expect(boxes.every(b => b.checked)).toBe(true)
    fireEvent.click(boxes[1])

    fireEvent.click(screen.getByRole('button', { name: /^Confirm/ }))

    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1))
    expect(confirm).toHaveBeenCalledWith([{ inbox_id: 101, fund_id: 1 }])
    // The modal closes and a result line is shown.
    await waitFor(() => expect(screen.queryByText('Whole Foods')).toBeNull())
    expect(screen.getByText(/Assigned 1 transaction\./)).toBeTruthy()
  })

  it('writes nothing when the review is cancelled', async () => {
    vi.spyOn(api.autosort, 'suggestions').mockResolvedValue({ suggestions: SUGGESTIONS })
    const confirm = vi.spyOn(api.autosort, 'confirm').mockResolvedValue({ updated: [] })
    renderApp(routes(), { route: '/inbox' })

    fireEvent.click(await screen.findByRole('button', { name: /Auto-sort/ }))
    await screen.findByText('Whole Foods')

    fireEvent.click(screen.getByRole('button', { name: /Cancel/ }))

    await waitFor(() => expect(screen.queryByText('Whole Foods')).toBeNull())
    expect(confirm).not.toHaveBeenCalled()
  })

  it('cannot confirm with every row unchecked', async () => {
    vi.spyOn(api.autosort, 'suggestions').mockResolvedValue({ suggestions: SUGGESTIONS })
    const confirm = vi.spyOn(api.autosort, 'confirm').mockResolvedValue({ updated: [] })
    renderApp(routes(), { route: '/inbox' })

    fireEvent.click(await screen.findByRole('button', { name: /Auto-sort/ }))
    await screen.findByText('Whole Foods')

    for (const box of screen.getAllByRole('checkbox')) fireEvent.click(box)

    const confirmBtn = screen.getByRole('button', { name: /^Confirm/ })
    expect(confirmBtn.disabled).toBe(true)
    fireEvent.click(confirmBtn)
    expect(confirm).not.toHaveBeenCalled()
  })
})
