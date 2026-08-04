/**
 * A failed request, as structured fields rather than a formatted string.
 *
 * The old `throw new Error(\`${status}: ${body}\`)` forced every caller to
 * `String(e)` and render whatever fell out, so nothing could branch on a 404
 * or read `detail` out of the body. Callers now get `status` and `body`;
 * `message` exists for devtools and is not the contract.
 */
export class ApiError extends Error {
  /**
   * @param {number} status HTTP status, or 0 when the request never landed
   * @param {*} body parsed JSON body when the server sent JSON, else the raw text
   * @param {string} path request path, for context
   */
  constructor(status, body, path) {
    super(`${status || 'network'} ${path}`)
    this.name = 'ApiError'
    this.status = status
    this.body = body
    this.path = path
  }

  /** FastAPI errors are `{"detail": ...}`; fall back to the raw body. */
  get detail() {
    if (this.body && typeof this.body === 'object' && 'detail' in this.body) return this.body.detail
    return this.body
  }
}
