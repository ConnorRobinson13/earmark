/**
 * The frontend's one way to read from the API.
 *
 * Views call `useResource(keys.something(...))` and get `{ data, error,
 * reload }` — both null until the first response lands, which is what a view
 * renders its loading state from. Behind that: one round trip per key no matter how many
 * callers, numbers instead of decimal strings, `ApiError` instead of a
 * stringified exception, requests dropped on unmount and on key change, and
 * `invalidate(prefix)` to push fresh data to whoever is reading it.
 *
 * Writes still go through `api` — this module owns reads.
 */
export { useResource } from './useResource'
export { keys } from './keys'
export { ApiError } from './ApiError'
export { ResourceProvider, useResourceStore } from './context'
export { createResourceStore } from './store'
export { createStubAdapter } from './stubAdapter'
