import { coerceNumbers } from './coerce'

/**
 * Owns every read from the API.
 *
 * A *key* is the request path — `/dashboard?month=2026-08-01`. It identifies
 * the request for three purposes at once: deduplication (two callers asking
 * for the same key share one round trip), invalidation (a mutation says
 * `invalidate('/dashboard')` and everyone reading a dashboard refetches), and
 * cancellation (a caller that loses interest drops its share).
 *
 * There is no cache. Dedupe covers concurrent readers; once a request settles
 * the next read goes to the server, so nothing here can serve stale data.
 */
export function createResourceStore(adapter) {
  /** key -> { controller, promise, refs } for requests currently in flight */
  const inflight = new Map()
  /** key -> Set<listener> for mounted readers wanting invalidation news */
  const listeners = new Map()

  function start(key) {
    const controller = new AbortController()
    const entry = { controller, refs: 0, settled: false }
    // The async wrapper starts the adapter synchronously (so a second caller
    // in the same tick dedupes onto it) while turning a sync throw into a
    // rejection.
    entry.promise = (async () => adapter(key, { signal: controller.signal }))()
      .then(coerceNumbers)
      .finally(() => {
        entry.settled = true
        // Only clear our own entry: a later request for the same key may have
        // replaced it while this one was settling.
        if (inflight.get(key) === entry) inflight.delete(key)
      })
    inflight.set(key, entry)
    return entry
  }

  /**
   * Read `key`. Rejects with `ApiError` on failure, or `AbortError` if the
   * caller's `signal` fires first.
   *
   * Aborting drops this caller's share of the request. The underlying request
   * is only cancelled once every caller has dropped out — otherwise one
   * component unmounting would cancel another's data.
   */
  function read(key, { signal } = {}) {
    const entry = inflight.get(key) || start(key)
    entry.refs++

    let released = false
    const release = () => {
      if (released) return
      released = true
      entry.refs--
      if (entry.refs > 0 || entry.settled) return
      if (inflight.get(key) === entry) inflight.delete(key)
      entry.controller.abort()
    }

    if (!signal) return entry.promise.finally(release)
    if (signal.aborted) {
      release()
      return Promise.reject(abortError())
    }

    return new Promise((resolve, reject) => {
      const onAbort = () => {
        release()
        reject(abortError())
      }
      signal.addEventListener('abort', onAbort, { once: true })
      entry.promise.then(resolve, reject).finally(() => {
        signal.removeEventListener('abort', onAbort)
        release()
      })
    })
  }

  /**
   * Tell every reader whose key starts with `prefix` to refetch. No prefix
   * means every reader. Pass a path prefix to scope it: `invalidate('/funds')`
   * reaches `/funds/3` and `/funds?include_archived=false`.
   */
  function invalidate(prefix = '') {
    // Retire matching in-flight requests first: they were issued before
    // whatever prompted this, so a reader must not be allowed to dedupe onto
    // one and get the pre-mutation answer. Readers already waiting on them
    // still get their response, and are told to reload just below.
    for (const key of [...inflight.keys()]) {
      if (key.startsWith(prefix)) inflight.delete(key)
    }
    for (const [key, set] of listeners) {
      if (!key.startsWith(prefix)) continue
      for (const listener of [...set]) listener()
    }
  }

  /** Register interest in `key`. Returns an unsubscribe function. */
  function subscribe(key, listener) {
    let set = listeners.get(key)
    if (!set) listeners.set(key, (set = new Set()))
    set.add(listener)
    return () => {
      set.delete(listener)
      if (set.size === 0) listeners.delete(key)
    }
  }

  return { read, invalidate, subscribe }
}

function abortError() {
  return new DOMException('Aborted', 'AbortError')
}
