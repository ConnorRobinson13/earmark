import { describe, expect, it, vi } from 'vitest'
import { createHttpAdapter } from './httpAdapter'
import { ApiError } from './ApiError'

function jsonResponse(body, { status = 200 } = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('createHttpAdapter', () => {
  it('prefixes the base and returns the parsed body', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ unassigned: '12.00' }))
    const adapter = createHttpAdapter({ base: '/api', fetchImpl })

    await expect(adapter('/dashboard')).resolves.toEqual({ unassigned: '12.00' })
    expect(fetchImpl).toHaveBeenCalledWith('/api/dashboard', expect.anything())
  })

  it('returns null for 204', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    const adapter = createHttpAdapter({ base: '/api', fetchImpl })

    await expect(adapter('/nothing')).resolves.toBe(null)
  })

  it('throws an ApiError carrying status and parsed body', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ detail: 'Fund not found' }, { status: 404 }))
    const adapter = createHttpAdapter({ base: '/api', fetchImpl })

    const err = await adapter('/funds/9').catch(e => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(404)
    expect(err.body).toEqual({ detail: 'Fund not found' })
    expect(err.detail).toBe('Fund not found')
    expect(err.path).toBe('/funds/9')
  })

  it('keeps a non-JSON error body as text', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response('upstream exploded', { status: 502 }))
    const adapter = createHttpAdapter({ base: '/api', fetchImpl })

    const err = await adapter('/dashboard').catch(e => e)
    expect(err.status).toBe(502)
    expect(err.body).toBe('upstream exploded')
  })

  it('reports a transport failure as status 0 rather than a raw TypeError', async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    const adapter = createHttpAdapter({ base: '/api', fetchImpl })

    const err = await adapter('/dashboard').catch(e => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(0)
    expect(err.body).toBe('Failed to fetch')
  })

  it('passes the abort signal through and lets AbortError escape unwrapped', async () => {
    const controller = new AbortController()
    const fetchImpl = vi.fn((_path, opts) => new Promise((_resolve, reject) => {
      opts.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    }))
    const adapter = createHttpAdapter({ base: '/api', fetchImpl })

    const promise = adapter('/dashboard', { signal: controller.signal })
    controller.abort()

    const err = await promise.catch(e => e)
    expect(err.name).toBe('AbortError')
    expect(err).not.toBeInstanceOf(ApiError)
  })
})
