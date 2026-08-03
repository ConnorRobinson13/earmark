import { useCallback, useEffect, useState } from 'react'
import { useResourceStore } from './context'

const IDLE = { data: null, error: null, loading: true }

/**
 * Read one keyed request.
 *
 * Replaces the hand-rolled loader every view used to carry: a `useEffect`, a
 * `data` state, an `err` state set from `String(e)`, and a tick to force a
 * refetch. Returns `{ data, error, loading, reload }`, where `error` is an
 * `ApiError` with `status` and `body`.
 *
 * The request is abandoned on unmount and whenever `key` changes, so a slow
 * response for last month's key can never land on top of this month's data.
 */
export function useResource(key) {
  const store = useResourceStore()
  const [state, setState] = useState(IDLE)
  const [attempt, setAttempt] = useState(0)

  const reload = useCallback(() => setAttempt(n => n + 1), [])

  useEffect(() => {
    const controller = new AbortController()
    setState(s => (s.loading ? s : { ...s, loading: true }))
    store.fetch(key, { signal: controller.signal }).then(
      (data) => {
        if (!controller.signal.aborted) setState({ data, error: null, loading: false })
      },
      (error) => {
        // An abort is this component losing interest, not a failure to report.
        if (!controller.signal.aborted) setState({ data: null, error, loading: false })
      },
    )
    return () => controller.abort()
  }, [store, key, attempt])

  // Someone else's mutation can invalidate this key; refetch when it does.
  useEffect(() => store.subscribe(key, reload), [store, key, reload])

  return { data: state.data, error: state.error, loading: state.loading, reload }
}
