import { BASE } from '../api'
import { ApiError } from './ApiError'

/**
 * The browser adapter: the one place that knows about `fetch`.
 *
 * An adapter is `(path, { signal }) => Promise<parsedJson>` that throws an
 * `ApiError` when the server says no, and lets `AbortError` through untouched
 * so the caller can tell "you cancelled this" from "this failed". Swapping in
 * a stub adapter is what lets a view render with no backend running.
 */
export function createHttpAdapter({ base = BASE, fetchImpl = fetch } = {}) {
  return async function httpAdapter(path, { signal } = {}) {
    let res
    try {
      res = await fetchImpl(`${base}${path}`, {
        headers: { 'Content-Type': 'application/json' },
        signal,
      })
    } catch (e) {
      if (e.name === 'AbortError') throw e
      // DNS failure, offline, CORS — there is no status to report.
      throw new ApiError(0, e.message, path)
    }

    if (!res.ok) throw new ApiError(res.status, await readBody(res), path)
    if (res.status === 204) return null
    return res.json()
  }
}

async function readBody(res) {
  const text = await res.text()
  if (!res.headers.get('Content-Type')?.includes('application/json')) return text
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}
