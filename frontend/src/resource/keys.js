/**
 * Canonical keys for the reads the resource module serves.
 *
 * Deduplication and invalidation both compare keys as strings, so two callers
 * asking for the same thing have to spell it the same way. Building keys here
 * rather than in views is what makes that true — the shell's unassigned chip
 * and the dashboard share one round trip only because both spell the key
 * `keys.dashboard(month)`.
 *
 * Keys are grouped by path prefix so `writes.js` can name a family of them:
 * everything under `/funds` is one prefix, and that reaches the fund list and
 * `/funds/3` alike.
 */
export const keys = {
  dashboard: (month) => `/dashboard${month ? `?month=${month}` : ''}`,
  dashboardTrends: (months = 6) => `/dashboard/trends?months=${months}`,
  accounts: () => '/accounts',
  inbox: () => '/inbox',
  funds: () => '/funds?include_archived=false',
  fund: (id) => `/funds/${id}`,
  fundTransactions: (id) => `/transactions?fund_id=${id}&limit=200`,
  pendingSettlements: (month) => `/settlements/pending${month ? `?month=${month}` : ''}`,
  templates: () => '/templates',
  networth: () => '/networth',
  networthHistory: () => '/networth/history',
  plaidItems: () => '/plaid/items',
}
