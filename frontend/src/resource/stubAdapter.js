import { ApiError } from './ApiError'

/**
 * The other adapter: canned responses instead of a network.
 *
 * `routes` maps a key to what that read returns. A value may be the response
 * itself, an `ApiError` to reject with, or a function `(path) => response`
 * (return a promise from it to control when the read settles). Responses are
 * written the way the backend writes them — money as decimal strings — so
 * tests exercise the coercion at the edge rather than side-stepping it.
 *
 * An unlisted key rejects with a 404, so a view that grew a new read fails
 * loudly instead of silently rendering half a page.
 */
export function createStubAdapter(routes = {}) {
  const requested = []

  function stubAdapter(path) {
    requested.push(path)
    if (!(path in routes)) {
      return Promise.reject(new ApiError(404, { detail: `no stub route for ${path}` }, path))
    }
    const route = routes[path]
    const value = typeof route === 'function' ? route(path) : route
    return value instanceof ApiError ? Promise.reject(value) : Promise.resolve(value)
  }

  stubAdapter.requested = requested
  return stubAdapter
}
