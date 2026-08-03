import { describe, expect, it, vi } from 'vitest'
import { createResourceStore } from './store'
import { ApiError } from './ApiError'

/** An adapter whose responses the test resolves by hand. */
function deferredAdapter() {
  const calls = []
  const adapter = vi.fn((path, { signal } = {}) => new Promise((resolve, reject) => {
    calls.push({ path, signal, resolve, reject })
    signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  }))
  return { adapter, calls }
}

describe('createResourceStore', () => {
  it('coerces decimal strings to numbers once, at the edge', async () => {
    const store = createResourceStore(async () => ({ unassigned: '120.50' }))
    await expect(store.read('/dashboard')).resolves.toEqual({ unassigned: 120.5 })
  })

  it('deduplicates concurrent requests for the same key', async () => {
    const { adapter, calls } = deferredAdapter()
    const store = createResourceStore(adapter)

    const a = store.read('/dashboard')
    const b = store.read('/dashboard')
    expect(adapter).toHaveBeenCalledTimes(1)

    calls[0].resolve({ unassigned: '1' })
    expect(await a).toEqual(await b)
  })

  it('does not deduplicate different keys', () => {
    const { adapter } = deferredAdapter()
    const store = createResourceStore(adapter)

    store.read('/dashboard?month=2026-08-01')
    store.read('/dashboard?month=2026-07-01')
    expect(adapter).toHaveBeenCalledTimes(2)
  })

  it('starts a fresh request once the previous one has settled', async () => {
    // Dedupe is for concurrency, not caching — a later read must hit the server.
    const adapter = vi.fn(async () => ({ n: '1' }))
    const store = createResourceStore(adapter)

    await store.read('/dashboard')
    await store.read('/dashboard')
    expect(adapter).toHaveBeenCalledTimes(2)
  })

  it('aborts the underlying request when the only caller gives up', async () => {
    const { adapter, calls } = deferredAdapter()
    const store = createResourceStore(adapter)
    const controller = new AbortController()

    const promise = store.read('/dashboard', { signal: controller.signal })
    controller.abort()

    await expect(promise).rejects.toHaveProperty('name', 'AbortError')
    expect(calls[0].signal.aborted).toBe(true)
  })

  it('keeps the shared request alive while another caller still wants it', async () => {
    const { adapter, calls } = deferredAdapter()
    const store = createResourceStore(adapter)
    const leaving = new AbortController()

    const abandoned = store.read('/dashboard', { signal: leaving.signal })
    const kept = store.read('/dashboard')
    leaving.abort()

    await expect(abandoned).rejects.toHaveProperty('name', 'AbortError')
    expect(calls[0].signal.aborted).toBe(false)

    calls[0].resolve({ unassigned: '9' })
    await expect(kept).resolves.toEqual({ unassigned: 9 })
  })

  it('surfaces the adapter error unchanged', async () => {
    const store = createResourceStore(async () => { throw new ApiError(404, { detail: 'nope' }, '/funds/9') })

    const err = await store.read('/funds/9').catch(e => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(404)
  })

  it('notifies subscribers whose key matches the invalidated prefix', () => {
    const store = createResourceStore(vi.fn())
    const dashboard = vi.fn()
    const other = vi.fn()
    store.subscribe('/dashboard?month=2026-08-01', dashboard)
    store.subscribe('/accounts', other)

    store.invalidate('/dashboard')

    expect(dashboard).toHaveBeenCalledTimes(1)
    expect(other).not.toHaveBeenCalled()
  })

  it('invalidates everything when given no prefix', () => {
    const store = createResourceStore(vi.fn())
    const dashboard = vi.fn()
    const other = vi.fn()
    store.subscribe('/dashboard', dashboard)
    store.subscribe('/accounts', other)

    store.invalidate()

    expect(dashboard).toHaveBeenCalledTimes(1)
    expect(other).toHaveBeenCalledTimes(1)
  })

  it('retires an in-flight request so a later reader cannot dedupe onto stale data', async () => {
    const { adapter, calls } = deferredAdapter()
    const store = createResourceStore(adapter)

    const before = store.read('/dashboard')
    store.invalidate('/dashboard')
    const after = store.read('/dashboard')

    expect(adapter).toHaveBeenCalledTimes(2)
    calls[0].resolve({ unassigned: '1' })
    calls[1].resolve({ unassigned: '2' })
    await expect(before).resolves.toEqual({ unassigned: 1 })
    await expect(after).resolves.toEqual({ unassigned: 2 })
  })

  it('stops notifying after unsubscribe', () => {
    const store = createResourceStore(vi.fn())
    const listener = vi.fn()
    const unsubscribe = store.subscribe('/accounts', listener)

    unsubscribe()
    store.invalidate()

    expect(listener).not.toHaveBeenCalled()
  })
})
