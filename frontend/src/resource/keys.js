/**
 * Canonical keys for the reads the resource module serves.
 *
 * Deduplication and invalidation both compare keys as strings, so two callers
 * asking for the same thing have to spell it the same way. Building keys here
 * rather than in views is what makes that true. Only the reads that have been
 * migrated live here — the list grows as views move over.
 */
export const keys = {
  dashboard: (month) => `/dashboard${month ? `?month=${month}` : ''}`,
  dashboardTrends: (months = 6) => `/dashboard/trends?months=${months}`,
  accounts: () => '/accounts',
  inbox: () => '/inbox',
  fund: (id) => `/funds/${id}`,
  fundTransactions: (id, limit = 200) => `/transactions?fund_id=${id}&limit=${limit}`,
  pendingSettlements: (month) => `/settlements/pending${month ? `?month=${month}` : ''}`,
}
