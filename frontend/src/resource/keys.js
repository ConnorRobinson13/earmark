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
  /**
   * The retirement projection, which the backend computes.
   *
   * Every assumption is in the key, because every assumption changes the
   * answer — a moved slider is a different question and gets its own round
   * trip. The field order is fixed here rather than left to the caller so the
   * same assumptions always spell the same key.
   *
   * The starting balance is deliberately absent: it is the current investment
   * total, and the endpoint reads it. Passing it would let this client and the
   * MCP tool project from two different numbers.
   */
  retirementProjection: (p) =>
    '/retirement/projection'
    + `?current_age=${p.currentAge}`
    + `&retire_age=${p.retireAge}`
    + `&annual_return_pct=${p.annualReturnPct}`
    + `&monthly_contribution=${p.monthlyContribution}`
    + `&contribution_growth_pct=${p.contributionGrowthPct}`
    + `&inflation_pct=${p.inflationPct}`,
  plaidItems: () => '/plaid/items',
}
