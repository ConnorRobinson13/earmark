import { ApiError } from '../resource'

/**
 * The failed-request card the views used to each spell out by hand around a
 * `String(e)`. Reads the structured fields off an `ApiError` so what lands on
 * screen is the server's message, not "Error: 500: {"detail":"..."}".
 */
export default function ErrorCard({ error }) {
  return <div className="card"><span className="bad">{errorText(error)}</span></div>
}

function errorText(error) {
  if (!error) return ''
  if (!(error instanceof ApiError)) return String(error.message || error)
  if (error.status === 0) return `Can't reach the server — ${error.body}`
  const { detail } = error
  if (typeof detail === 'string' && detail) return detail
  return detail == null ? `Request failed (${error.status})` : JSON.stringify(detail)
}
