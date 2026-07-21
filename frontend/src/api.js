const BASE = import.meta.env.VITE_API_URL || '/api'

async function req(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`${res.status}: ${body}`)
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  dashboard: (month) => req(`/dashboard${month ? `?month=${month}` : ''}`),
  dashboardTrends: (months = 6) => req(`/dashboard/trends?months=${months}`),

  funds: {
    list: (includeArchived = false) => req(`/funds?include_archived=${includeArchived}`),
    get: (id) => req(`/funds/${id}`),
    create: (body) => req('/funds', { method: 'POST', body: JSON.stringify(body) }),
    update: (id, body) => req(`/funds/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
    archive: (id, month) => req(`/funds/${id}${month ? `?month=${month}` : ''}`, { method: 'DELETE' }),
  },

  transactions: {
    list: (params = {}) => {
      const qs = new URLSearchParams(params).toString()
      return req(`/transactions${qs ? '?' + qs : ''}`)
    },
    quickAdd: (body) => req('/transactions/quick-add', { method: 'POST', body: JSON.stringify(body) }),
    transfer: (body) => req('/transactions/transfer', { method: 'POST', body: JSON.stringify(body) }),
    assign: (body) => req('/transactions/assign', { method: 'POST', body: JSON.stringify(body) }),
    delete: (id) => req(`/transactions/${id}`, { method: 'DELETE' }),
    update: (id, body) => req(`/transactions/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  },

  accounts: {
    list: () => req('/accounts'),
    create: (body) => req('/accounts', { method: 'POST', body: JSON.stringify(body) }),
    update: (id, body) => req(`/accounts/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
    delete: (id) => req(`/accounts/${id}`, { method: 'DELETE' }),
  },

  templates: {
    list: () => req('/templates'),
    replace: (items) => req('/templates', { method: 'PUT', body: JSON.stringify(items) }),
    apply: (month) => req('/templates/apply', { method: 'POST', body: JSON.stringify({ month }) }),
  },

  suggest: (merchant, amount) =>
    req('/suggest', { method: 'POST', body: JSON.stringify({ merchant, amount }) }),

  inbox: {
    list: () => req('/inbox'),
    approve: (id, fundId, asPaycheck = false) => req(`/inbox/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify({ fund_id: fundId, as_paycheck: asPaycheck }),
    }),
    reject: (id) => req(`/inbox/${id}/reject`, { method: 'POST' }),
    resuggest: (id) => req(`/inbox/${id}/resuggest`, { method: 'POST' }),
  },

  plaid: {
    linkToken: () => req('/plaid/link-token', { method: 'POST' }),
    exchange: (publicToken, institutionName) =>
      req('/plaid/exchange', {
        method: 'POST',
        body: JSON.stringify({ public_token: publicToken, institution_name: institutionName || null }),
      }),
    sync: () => req('/plaid/sync', { method: 'POST' }),
    items: () => req('/plaid/items'),
    unlinkItem: (id) => req(`/plaid/items/${id}`, { method: 'DELETE' }),
  },

  admin: {
    resetToSeed: () => req('/admin/reset-to-seed', { method: 'POST' }),
  },

  networth: () => req('/networth'),
  networthHistory: () => req('/networth/history'),

  paydays: {
    list: () => req('/paydays'),
    create: (body) => req('/paydays', { method: 'POST', body: JSON.stringify(body) }),
    delete: (id) => req(`/paydays/${id}`, { method: 'DELETE' }),
  },

  monthlyMeta: {
    get: (month) => req(`/monthly-meta/${month}`),
    set: (month, plannedIncome) => req(`/monthly-meta/${month}`, {
      method: 'PUT', body: JSON.stringify({ planned_income: plannedIncome }),
    }),
  },

  settlements: {
    pending: (month) => req(`/settlements/pending${month ? `?month=${month}` : ''}`),
    settle: (goalId, body) => req(`/settlements/goal/${goalId}`, {
      method: 'POST', body: JSON.stringify(body),
    }),
    undo: (id) => req(`/settlements/${id}`, { method: 'DELETE' }),
  },

  bulk: {
    copyAssignments: (fromMonth, toMonth) =>
      req('/bulk/copy-assignments', {
        method: 'POST',
        body: JSON.stringify({ from_month: fromMonth, to_month: toMonth }),
      }),
    setMonthlyIncome: (month, amount) =>
      req('/bulk/set-monthly-income', {
        method: 'POST',
        body: JSON.stringify({ month, amount }),
      }),
  },
}

export function fmt(n) {
  const v = Number(n || 0)
  return v.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

export function todayISO() {
  return new Date().toISOString().slice(0, 10)
}
