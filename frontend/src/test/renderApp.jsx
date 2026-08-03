import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from '../App'
import { ResourceProvider, createResourceStore, createStubAdapter } from '../resource'

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
