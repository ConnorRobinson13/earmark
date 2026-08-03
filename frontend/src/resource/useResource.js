import { useCallback, useEffect, useState } from 'react'
import { useResourceStore } from './context'

const NOTHING_YET = { data: null, error: null }

/**
 * Read one keyed request.
 *
 * Replaces the hand-rolled loader every view used to carry: a `useEffect`, a
 * `data` state, an `err` state set from `String(e)`, and a tick to force a
 * refetch. Returns `{ data, error, reload }`, where `error` is an `ApiError`
 * with `status` and `body`. Until the first response lands both are null.
 *
 * The request is abandoned on unmount and whenever `key` changes, so a slow
 * response for last month's key can never land on top of this month's data.
 */
export function useResource(key) {
  const store = useResourceStore()
  const [state, setState] = useState(NOTHING_YET)
  const [attempt, setAttempt] = useState(0)
  const [readKey, setReadKey] = useState(key)

  // A new key is a different question: drop the previous answer rather than
  // render it under the new key's heading. A reload asks the same question,
  // so that keeps what's on screen until the fresh answer arrives.
  if (key !== readKey) {
    setReadKey(key)
    setState(NOTHING_YET)
  }

  const reload = useCallback(() => setAttempt(n => n + 1), [])

  useEffect(() => {
    const controller = new AbortController()
    store.read(key, { signal: controller.signal }).then(
      (data) => {
        if (!controller.signal.aborted) setState({ data, error: null })
      },
      (error) => {
        // An abort is this component losing interest, not a failure to report.
        if (!controller.signal.aborted) setState({ data: null, error })
      },
    )
    return () => controller.abort()
  }, [store, key, attempt])

  // Someone else's mutation can invalidate this key; refetch when it does.
  useEffect(() => store.subscribe(key, reload), [store, key, reload])

  return { data: state.data, error: state.error, reload }
}
