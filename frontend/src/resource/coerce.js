/**
 * Decimal-to-number coercion for API responses.
 *
 * The backend models money as `Decimal`, which pydantic serialises as a JSON
 * string ("1234.56") to avoid float drift on the wire. Every consumer then had
 * to remember `Number(...)` before doing arithmetic — and mostly did, 85 times.
 * Coercing once here means views can treat money as numbers.
 *
 * Shape alone can't tell money from text: a fund called "529" or a merchant
 * called "76" is a string that looks like a number, and turning it into one
 * breaks `localeCompare` and equality checks downstream. So text fields are
 * named here and left alone, and everything else decimal-shaped is money.
 * A field the backend adds is money by default, which is the safe way round —
 * a missed text field renders the same, a missed money field breaks sums.
 */

// Field names whose values are text: typed by the user, or an opaque token.
const TEXT_FIELDS = new Set([
  // user-typed
  'name', 'goal_name', 'fund_name', 'to_account_name', 'account_name',
  'merchant', 'notes', 'category', 'categories', 'institution_name',
  // a cash-flow event's label is a fund's name (or "Paycheck"), so it is
  // user-typed too — listed ahead of that view migrating, because a fund
  // called "529" would otherwise become a number in the timeline.
  'label',
  // enums
  'type', 'kind', 'goal_type', 'status', 'source',
  // dates — these don't match the pattern below either, but say so out loud
  'month', 'date', 'target_date', 'settled_at', 'created_at', 'archived_at',
  'last_synced_at',
  // opaque identifiers
  'mask', 'plaid_transaction_id', 'plaid_item_id',
])

// Plain base-10 integers and decimals only. Deliberately does NOT match:
// dates ("2026-08-01"), datetimes, exponent notation, leading zeros (account
// masks), or anything with surrounding whitespace.
const DECIMAL = /^-?(0|[1-9]\d*)(\.\d+)?$/

// Longer than this and a round trip through a double can lose digits, so the
// string is more faithful than the number would be.
const MAX_DIGITS = 15

function coerceString(s) {
  if (!DECIMAL.test(s)) return s
  if (s.replace(/[-.]/g, '').length > MAX_DIGITS) return s
  return Number(s)
}

/**
 * Deep-copy `value`, replacing every decimal-looking string with its number.
 *
 * `key` is the field the value arrived under; nested arrays keep their parent's
 * key, so `categories: ["Housing", "529"]` stays text while the values of
 * `categories: { Housing: "1200.00" }` — keyed by category name — do not.
 */
export function coerceNumbers(value, key) {
  if (typeof value === 'string') return TEXT_FIELDS.has(key) ? value : coerceString(value)
  if (Array.isArray(value)) return value.map(v => coerceNumbers(v, key))
  if (value && typeof value === 'object') {
    const out = {}
    for (const [k, v] of Object.entries(value)) out[k] = coerceNumbers(v, k)
    return out
  }
  return value
}
