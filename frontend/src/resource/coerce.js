/**
 * Decimal-to-number coercion for API responses.
 *
 * The backend models money as `Decimal`, which pydantic serialises as a JSON
 * string ("1234.56") to avoid float drift on the wire. Every consumer then had
 * to remember `Number(...)` before doing arithmetic — and mostly did, 85 times.
 * Coercing once here means views can treat money as numbers.
 */

// Plain base-10 integers and decimals only. Deliberately does NOT match:
// dates ("2026-08-01"), datetimes, exponent notation, or anything with
// surrounding whitespace.
const DECIMAL = /^-?(0|[1-9]\d*)(\.\d+)?$/

// Longer than this and a round trip through a double can lose digits, so the
// string is more faithful than the number would be.
const MAX_DIGITS = 15

function coerceString(s) {
  if (!DECIMAL.test(s)) return s
  if (s.replace(/[-.]/g, '').length > MAX_DIGITS) return s
  return Number(s)
}

/** Deep-copy `value`, replacing every decimal-looking string with its number. */
export function coerceNumbers(value) {
  if (typeof value === 'string') return coerceString(value)
  if (Array.isArray(value)) return value.map(coerceNumbers)
  if (value && typeof value === 'object') {
    const out = {}
    for (const [k, v] of Object.entries(value)) out[k] = coerceNumbers(v)
    return out
  }
  return value
}
