import { describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { useResource } from './useResource'
import { ResourceProvider } from './context'
import { createResourceStore } from './store'
import { ApiError } from './ApiError'

/** An adapter the test resolves by hand, one deferred per call. */
function deferredAdapter({ honourAbort = true } = {}) {
  const calls = []
  const adapter = vi.fn((path, { signal } = {}) => new Promise((resolve, reject) => {
    calls.push({ path, signal, resolve, reject })
    if (honourAbort) {
      signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    }
  }))
  return { adapter, calls, callFor: (path) => calls.find(c => c.path === path) }
}

function renderResource(adapter, initialKey) {
  const store = createResourceStore(adapter)
  const wrapper = ({ children }) => <ResourceProvider store={store}>{children}</ResourceProvider>
  const view = renderHook(({ key }) => useResource(key), {
    wrapper,
    initialProps: { key: initialKey },
  })
  return { ...view, store }
}

describe('useResource', () => {
  it('exposes data for a keyed request', async () => {
    const { result } = renderResource(async () => ({ unassigned: '12.50' }), '/dashboard')

    expect(result.current.data).toBe(null)
    await waitFor(() => expect(result.current.data).toEqual({ unassigned: 12.5 }))
    expect(result.current.error).toBe(null)
  })

  it('exposes the structured error, not a formatted string', async () => {
    const failure = new ApiError(500, { detail: 'boom' }, '/dashboard')
    const { result } = renderResource(async () => { throw failure }, '/dashboard')

    await waitFor(() => expect(result.current.error).toBe(failure))
    expect(result.current.error.status).toBe(500)
    expect(result.current.error.body).toEqual({ detail: 'boom' })
    expect(result.current.data).toBe(null)
  })

  it('refetches on reload', async () => {
    const adapter = vi.fn()
      .mockResolvedValueOnce({ unassigned: '1' })
      .mockResolvedValueOnce({ unassigned: '2' })
    const { result } = renderResource(adapter, '/dashboard')

    await waitFor(() => expect(result.current.data).toEqual({ unassigned: 1 }))
    act(() => result.current.reload())
    await waitFor(() => expect(result.current.data).toEqual({ unassigned: 2 }))
  })

  it('refetches when its key is invalidated', async () => {
    const adapter = vi.fn()
      .mockResolvedValueOnce({ unassigned: '1' })
      .mockResolvedValueOnce({ unassigned: '2' })
    const { result, store } = renderResource(adapter, '/dashboard?month=2026-08-01')

    await waitFor(() => expect(result.current.data).toEqual({ unassigned: 1 }))
    await act(async () => { store.invalidate('/dashboard') })
    await waitFor(() => expect(result.current.data).toEqual({ unassigned: 2 }))
  })

  it('aborts the in-flight request on unmount', async () => {
    const { adapter, calls } = deferredAdapter()
    const { unmount } = renderResource(adapter, '/dashboard')

    expect(calls[0].signal.aborted).toBe(false)
    unmount()
    expect(calls[0].signal.aborted).toBe(true)
  })

  it('aborts the in-flight request when the key changes', async () => {
    const { adapter, calls } = deferredAdapter()
    const { rerender } = renderResource(adapter, '/dashboard?month=2026-08-01')

    rerender({ key: '/dashboard?month=2026-07-01' })

    expect(calls[0].signal.aborted).toBe(true)
    expect(calls[1].signal.aborted).toBe(false)
  })

  it('drops the previous key’s data instead of showing it under the new key', async () => {
    const { adapter, callFor } = deferredAdapter()
    const { result, rerender } = renderResource(adapter, '/dashboard?month=2026-08-01')

    await act(async () => { callFor('/dashboard?month=2026-08-01').resolve({ month: 'august' }) })
    await waitFor(() => expect(result.current.data).toEqual({ month: 'august' }))

    rerender({ key: '/dashboard?month=2026-07-01' })
    expect(result.current.data).toBe(null)
  })

  it('drops the previous key’s error too', async () => {
    const adapter = vi.fn()
      .mockRejectedValueOnce(new ApiError(500, { detail: 'boom' }, '/dashboard?month=2026-08-01'))
      .mockImplementation(() => new Promise(() => {}))
    const { result, rerender } = renderResource(adapter, '/dashboard?month=2026-08-01')

    await waitFor(() => expect(result.current.error).toBeTruthy())
    rerender({ key: '/dashboard?month=2026-07-01' })
    expect(result.current.error).toBe(null)
  })

  it('keeps what is on screen while a reload of the same key is in flight', async () => {
    const { adapter, calls } = deferredAdapter()
    const { result } = renderResource(adapter, '/dashboard')

    await act(async () => { calls[0].resolve({ unassigned: '1' }) })
    await waitFor(() => expect(result.current.data).toEqual({ unassigned: 1 }))

    act(() => result.current.reload())
    expect(result.current.data).toEqual({ unassigned: 1 })
  })

  it('cannot let a stale response overwrite newer state', async () => {
    // A stub that ignores abort is the worst case: the old month's response
    // still arrives, and arrives *after* the new month's.
    const { adapter, callFor } = deferredAdapter({ honourAbort: false })
    const { result, rerender } = renderResource(adapter, '/dashboard?month=2026-08-01')

    rerender({ key: '/dashboard?month=2026-07-01' })

    await act(async () => {
      callFor('/dashboard?month=2026-07-01').resolve({ month: 'july' })
    })
    await waitFor(() => expect(result.current.data).toEqual({ month: 'july' }))

    // August was requested first but answers last — it must be ignored.
    await act(async () => {
      callFor('/dashboard?month=2026-08-01').resolve({ month: 'august' })
    })
    expect(result.current.data).toEqual({ month: 'july' })
  })
})
