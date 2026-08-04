import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from '../App'
import { keys, ResourceProvider, createResourceStore, createStubAdapter } from '../resource'
import { thisMonth } from '../components/MonthSelector'

/**
 * Mount the real app at `route` with a stub adapter in place of the network.
 * No backend, no `fetch` — if a view asks for a key the test did not stub, the
 * stub answers 404 and the view says so.
 */
export function renderApp(routes, { route = '/' } = {}) {
  const adapter = createStubAdapter(routes)
  const store = createResourceStore(adapter)
  const result = render(
    <ResourceProvider store={store}>
      <MemoryRouter initialEntries={[route]}>
        <App />
      </MemoryRouter>
    </ResourceProvider>,
  )
  return { ...result, store, adapter }
}

/** The keys the shell reads on every route: nav badge, then topbar chip. */
export const SHELL_KEYS = [keys.inbox(), keys.dashboard(thisMonth())]

/**
 * Stubs for those two. A view test that cares about neither still has to
 * provide them — an unstubbed key 404s, and the shell would render a missing
 * badge and no chip on a page where the real app shows both.
 */
export function shellRoutes({ inbox = [], dashboard = emptyDashboard(), month = thisMonth() } = {}) {
  return {
    [keys.inbox()]: inbox,
    [keys.dashboard(month)]: dashboard,
  }
}

/** A dashboard with nothing in it, as the backend serialises it. */
export function emptyDashboard(overrides) {
  return {
    liquid_total: '0.00',
    credit_owed: '0.00',
    net_cash: '0.00',
    unassigned: '0.00',
    funds_total: '0.00',
    spent_this_month: '0.00',
    saved_this_month: '0.00',
    income_this_month: '0.00',
    planned_income: '0.00',
    month: thisMonth(),
    funds: [],
    ...overrides,
  }
}

/** A fund as the backend serialises it: every money field a decimal string. */
export function fund(overrides) {
  return {
    id: 1,
    name: 'Groceries',
    kind: 'operational',
    goal_type: null,
    category: 'Food',
    due_day: 1,
    sort_order: 0,
    target: null,
    target_date: null,
    backed_by_account_id: null,
    min_payment: null,
    balance: '0.00',
    net_spent_this_month: '0.00',
    assigned_this_month: '0.00',
    available_this_month: '0.00',
    contribution_ytd: null,
    contribution_year: null,
    archived_at: null,
    ...overrides,
  }
}
